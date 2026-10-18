"""Segmentación de la narración en pasos (ADR-010) y extracción de los pasos del video (RF-13).

Entrada: el `Analisis` del pipeline de video (`sopvid.contrato`). Salida: `list[PasoVideo]`.

El LLM recibe los segmentos de habla numerados y, si las hay, las etiquetas del video (nunca el
SOP), y responde SOLO una lista de `PropuestaPaso` (`segmento_id`, `nombre`, `descripcion`,
`responsable`, `cita`) restringida con un JSON Schema generado desde Pydantic. Los tiempos de
cada paso se toman de los segmentos, **nunca del LLM** (regla 4 de CLAUDE.md): el prompt no
lleva tiempos y el esquema no los admite.

Si el LLM no está disponible, falla o su propuesta no pasa la validación (esquema, ids
existentes, orden creciente, sin duplicados, nombres no vacíos) tras los reintentos, se usa la
heurística de respaldo: palabras de transición al inicio del segmento ("primero", "ahora",
"después", "luego", "siguiente", "finalmente"…) y pausas largas. El camino usado queda en
`Segmentacion.metodo` y en el log.

Este módulo es Python puro (sin pandas) porque corre en la API.
"""

import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, field_validator

from sopvid.contrato import Analisis, Confianza, Fuente, PasoVideo, Segmento
from sopvid.lenguaje.llm import ClienteLLM, LLMError, LLMRespuestaInvalida

logger = logging.getLogger(__name__)

NO_IDENTIFICADO = "No identificado"  # responsable cuando nadie lo dice en el audio (ADR-008)


@dataclass(frozen=True)
class Segmentacion:
    pasos: list[PasoVideo]
    metodo: Literal["llm", "heuristica"]
    motivo_respaldo: str | None  # por qué se usó la heurística; None si fue el LLM
    modelo: str | None
    intentos: int = 0  # llamadas hechas al LLM (0 sin cliente; máximo MAX_INTENTOS)


class PropuestaInvalida(ValueError):  # noqa: N818 (nombre de dominio)
    """La lista del LLM no cumple las reglas de validación."""


# ── LLM ──────────────────────────────────────────────────────────────────────────────────────


class PropuestaPaso(BaseModel):
    """Un paso tal como lo propone el LLM: un número de segmento y texto, ningún tiempo."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,  # "2" o True no cuentan como segmento_id
        str_strip_whitespace=True,
        hide_input_in_errors=True,  # los errores no deben copiar texto de la transcripción
    )

    segmento_id: int
    nombre: str
    descripcion: str
    responsable: str
    cita: str

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, v: str) -> str:
        if not v:
            raise ValueError("nombre vacío")
        return v

    @field_validator("responsable")
    @classmethod
    def _responsable_normalizado(cls, v: str) -> str:
        return normalizar_responsable(v)


def _sin_refs(esquema: dict[str, Any]) -> dict[str, Any]:
    """Sustituye cada `$ref` local por su definición y quita `$defs`.

    Ollama convierte el esquema de `format` en una gramática; un esquema plano evita depender de
    que resuelva referencias. No admite modelos recursivos (no los hay en este contrato).
    """
    defs = esquema.get("$defs", {})

    def resolver(nodo: Any) -> Any:
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                definicion = defs[nodo["$ref"].removeprefix("#/$defs/")]
                resto = {k: v for k, v in nodo.items() if k != "$ref"}
                return resolver({**definicion, **resto})
            return {k: resolver(v) for k, v in nodo.items() if k != "$defs"}
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(esquema)


# Esquema para el parámetro `format` de Ollama, generado desde `PropuestaPaso` y sin `$ref`.
ESQUEMA_PASOS: dict[str, Any] = _sin_refs(TypeAdapter(list[PropuestaPaso]).json_schema())

SISTEMA = (
    "Eres un asistente técnico de una planta industrial. Respondes en español, con precisión y "
    "sin inventar datos."
)

# Prompt v2 (opcional): regla probada en la Fase 4 porque en el benchmark de ADR-006 todos los
# errores fueron pasos de más. Se descartó como valor por defecto: no redujo los falsos
# positivos de gemma4:e4b y empeoró a qwen3.5:9b (ver ADR-010).
REGLA_ACLARACIONES = (
    "No marques como paso nuevo las aclaraciones, advertencias, ejemplos, anécdotas ni comentarios "
    "que el técnico hace dentro de un paso: un paso nuevo empieza solo cuando pasa a una acción "
    "distinta del procedimiento. "
)


def construir_mensajes(
    analisis: Analisis,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> list[dict[str, str]]:
    """Mensajes para el LLM. Solo números de segmento y texto: ningún tiempo y nunca el SOP.

    La regla de cortes es la del prompt v1 (benchmark de ADR-006), ampliada para RF-13 con
    descripción, responsable y cita. Sin etiquetas (la ficha de contexto llega después), se
    omite esa línea. `regla_aclaraciones=True` agrega la regla de aclaraciones (prompt v2,
    descartado en la Fase 4).
    """
    numerados = "\n".join(f"[{s.id}] {s.texto}" for s in analisis.transcripcion)
    texto_etiquetas = "; ".join(f"{k}={v}" for k, v in (etiquetas or {}).items())
    usuario = (
        (f"Etiquetas del video: {texto_etiquetas}.\n\n" if texto_etiquetas else "")
        + f"Segmentos de la transcripción, numerados y en orden:\n{numerados}\n\n"
        "Identifica en qué segmento empieza cada paso del procedimiento. Un paso suele "
        "abarcar varios segmentos: no marques cada segmento como paso, y la introducción o "
        "los comentarios no inician pasos. "
        + (REGLA_ACLARACIONES if regla_aclaraciones else "")
        + "Para cada paso da:\n"
        "- segmento_id: número del segmento donde empieza el paso.\n"
        "- nombre: nombre corto del paso.\n"
        "- descripcion: qué se hace en el paso, en una o dos frases.\n"
        "- responsable: el rol de quien hace el paso según lo que se dice en el audio "
        f'(por ejemplo "Operador" o "Supervisor"); si nadie lo dice, "{NO_IDENTIFICADO}".\n'
        "- cita: una frase copiada textualmente de los segmentos del paso, de 4 a 15 "
        "palabras, sin parafrasear ni traducir.\n"
        "Redacta nombre, descripcion y responsable en español aunque la transcripción esté "
        "en otro idioma; la cita se deja en el idioma original. "
        "Responde SOLO con una lista JSON de esos objetos, en orden. Usa solo números de "
        "segmento de la lista; no escribas tiempos."
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


def _validar_propuestas(datos: Any, ids_existentes: Collection[int]) -> list[PropuestaPaso]:
    """Valida la respuesta del LLM o lanza `PropuestaInvalida`.

    Reglas: lista no vacía de objetos que cumplen `PropuestaPaso` (sin campos extra, como un
    tiempo inventado, y con nombre no vacío); ids que existen; orden estrictamente creciente (lo
    que también excluye duplicados). Los motivos nunca incluyen texto de la transcripción.
    """
    if not isinstance(datos, list) or not datos:
        raise PropuestaInvalida("la respuesta no es una lista con al menos un paso")
    propuestas: list[PropuestaPaso] = []
    for i, d in enumerate(datos):
        if not isinstance(d, dict):
            raise PropuestaInvalida(f"el elemento {i} no es un objeto")
        try:
            p = PropuestaPaso.model_validate(d)
        except ValidationError as exc:
            campos = ", ".join(
                f"{'.'.join(map(str, e['loc']))} ({e['type']})" for e in exc.errors()
            )
            raise PropuestaInvalida(f"el elemento {i} no cumple el esquema: {campos}") from None
        sid, anterior = p.segmento_id, propuestas[-1].segmento_id if propuestas else None
        if sid not in ids_existentes:
            raise PropuestaInvalida(f"el segmento {sid} no existe")
        if anterior is not None and sid == anterior:
            raise PropuestaInvalida(f"el segmento {sid} está duplicado")
        if anterior is not None and sid < anterior:
            raise PropuestaInvalida(f"orden no creciente: {anterior} → {sid}")
        propuestas.append(p)
    return propuestas


def _rangos(inicios: Sequence[int], n_segmentos: int) -> list[tuple[int, int]]:
    """(posición inicial, posición final) de cada paso, inclusive, a partir de las posiciones
    de inicio en orden creciente. Cada paso termina en el segmento anterior al inicio del
    siguiente; el último, en el último segmento de la transcripción."""
    if not inicios:
        return []
    fines = [i - 1 for i in inicios[1:]] + [n_segmentos - 1]
    return list(zip(inicios, fines, strict=True))


@dataclass(frozen=True)
class _PasoConRango:
    """Paso del video más los segmentos que abarca (inclusive), para verificar la cita."""

    paso: PasoVideo
    primer_segmento: int
    ultimo_segmento: int
    confianza_cita: Confianza  # antes de ajustar por el responsable
    rol_sin_mencion: bool  # el responsable no se dice en el paso ni en la introducción


def _construir_con_rangos(propuestas: Any, analisis: Analisis) -> list[_PasoConRango]:
    segmentos = analisis.transcripcion
    posicion = {s.id: i for i, s in enumerate(segmentos)}
    validas = _validar_propuestas(propuestas, posicion)
    rangos = _rangos([posicion[p.segmento_id] for p in validas], len(segmentos))
    # Introducción: lo que se dice antes del primer paso (ahí suele presentarse quien narra).
    introduccion = " ".join(s.texto for s in segmentos[: rangos[0][0]])

    resultado = []
    for numero, (p, (i_inicio, i_fin)) in enumerate(zip(validas, rangos, strict=True), start=1):
        primero, ultimo = segmentos[i_inicio], segmentos[i_fin]
        confianza_cita, fuente = verificar_cita(p.cita, analisis, (primero.id, ultimo.id))
        del_paso = " ".join(s.texto for s in segmentos[i_inicio : i_fin + 1])
        rol_sin_mencion = p.responsable != NO_IDENTIFICADO and not rol_mencionado(
            p.responsable, f"{introduccion} {del_paso}"
        )
        confianza = _BAJAR_CONFIANZA[confianza_cita] if rol_sin_mencion else confianza_cita
        paso = PasoVideo(
            numero=numero,
            nombre=p.nombre,
            descripcion=p.descripcion,
            responsable=p.responsable,
            t_inicio=primero.t_inicio,
            t_fin=ultimo.t_fin,
            cita=p.cita,
            fuente=fuente,
            confianza=confianza,
        )
        resultado.append(
            _PasoConRango(paso, primero.id, ultimo.id, confianza_cita, rol_sin_mencion)
        )
    return resultado


def construir_pasos(propuestas: Any, analisis: Analisis) -> list[PasoVideo]:
    """Pasos del video a partir de la respuesta del LLM (JSON ya interpretado) y el análisis.

    Si la propuesta no es válida lanza `PropuestaInvalida` (`_validar_propuestas`). Los tiempos
    salen solo de la transcripción: `t_inicio` del segmento elegido y `t_fin` del último
    segmento antes del siguiente paso (o del último de la transcripción). `numero` es la
    posición desde 1.
    `confianza` y `fuente` salen de verificar la cita (`verificar_cita`, RNF-06).

    Responsable (sin diarización, ADR-008: el rol solo sale de lo que se dice en el audio):

    - Se recorta y se capitaliza; vacío o un valor de relleno ("desconocido", "n/a",
      "ninguno"…) pasa a "No identificado" (`normalizar_responsable`).
    - Si el sustantivo del rol (p. ej. "operador" en "Operador de turno") no se menciona en los
      segmentos del paso ni en la introducción (lo que se dice antes del primer paso), el rol se
      conserva pero la confianza del paso baja un nivel: alta → media, media → baja (`baja` se
      queda en `baja`; la fuente no cambia). "No identificado" no baja nada.
    """
    construidos = _construir_con_rangos(propuestas, analisis)
    niveles = Counter(r.confianza_cita for r in construidos)
    logger.info(
        "Citas verificadas en %d pasos: alta=%d, media=%d, baja=%d; "
        "responsables no mencionados en el audio: %d",
        len(construidos),
        niveles["alta"],
        niveles["media"],
        niveles["baja"],
        sum(r.rol_sin_mencion for r in construidos),
    )
    return [r.paso for r in construidos]


# ── Verificación de citas (RNF-06) ───────────────────────────────────────────────────────────


def _texto_comparable(texto: str) -> str:
    """Minúsculas, sin acentos ni puntuación y con espacios colapsados (como la heurística)."""
    return " ".join(_normalizar(texto).split())


def verificar_cita(
    cita: str, analisis: Analisis, rango_ids: tuple[int, int]
) -> tuple[Confianza, Fuente]:
    """Confianza y fuente de un paso según dónde aparece su cita en la transcripción.

    La cita debe aparecer como secuencia contigua de palabras completas, tras normalizar ambos
    lados. Los segmentos del paso (`rango_ids`, ids inclusive) se unen, así que la cita puede
    cruzar de un segmento al siguiente.

    - dentro de los segmentos del paso → ("alta", "audio")
    - en otra parte de la transcripción → ("media", "audio")
    - en ninguna parte, o cita vacía → ("baja", "inferido")

    "visual" queda reservado para la evidencia de fotogramas.
    """
    buscada = _texto_comparable(cita)
    if not buscada:
        return "baja", "inferido"
    primer_id, ultimo_id = rango_ids
    del_paso = " ".join(s.texto for s in analisis.transcripcion if primer_id <= s.id <= ultimo_id)
    completa = " ".join(s.texto for s in analisis.transcripcion)
    if f" {buscada} " in f" {_texto_comparable(del_paso)} ":
        return "alta", "audio"
    if f" {buscada} " in f" {_texto_comparable(completa)} ":
        return "media", "audio"
    return "baja", "inferido"


# ── Responsable (ADR-008: sin diarización) ───────────────────────────────────────────────────

# Valores de relleno que equivalen a "nadie lo dice", ya normalizados ("n/a" → "n a").
_RESPONSABLE_VACIO = frozenset(
    {
        "desconocido",
        "desconocida",
        "n a",
        "na",
        "ninguno",
        "ninguna",
        "nadie",
        "no identificado",
        "no identificada",
        "sin identificar",
        "no especificado",
        "no especificada",
        "no se menciona",
        "no mencionado",
        "no aplica",
        "none",
        "null",
        "unknown",
    }
)
_ARTICULOS = frozenset({"el", "la", "los", "las", "un", "una"})
_BAJAR_CONFIANZA: dict[Confianza, Confianza] = {"alta": "media", "media": "baja", "baja": "baja"}


def normalizar_responsable(responsable: str) -> str:
    """Recorta y capitaliza el rol; vacío o un valor de relleno → "No identificado"."""
    limpio = " ".join(responsable.split())
    comparable = _texto_comparable(limpio)
    if not comparable or comparable in _RESPONSABLE_VACIO:
        return NO_IDENTIFICADO
    return limpio[0].upper() + limpio[1:]  # no `capitalize()`: conserva siglas como "CNC"


def _raiz(palabra: str) -> str:
    """Quita la terminación de género y número: operadora/operadores → operador."""
    raiz = re.sub(r"[aoe]?s?$", "", palabra)
    return raiz if len(raiz) >= 3 else palabra


def rol_mencionado(responsable: str, texto: str) -> bool:
    """True si el sustantivo del rol aparece en `texto`, sin importar acentos, género o número.

    El sustantivo es la primera palabra del rol que no es artículo ("El operador de turno" →
    "operador").
    """
    palabras = [p for p in _texto_comparable(responsable).split() if p not in _ARTICULOS]
    if not palabras:
        return False
    sustantivo = _raiz(palabras[0])
    return any(_raiz(p) == sustantivo for p in _texto_comparable(texto).split())


T = TypeVar("T")

MAX_INTENTOS = 3  # una llamada más dos reintentos si la propuesta no pasa la validación


def mensaje_de_correccion(motivo: PropuestaInvalida) -> str:
    """Mensaje "user" para pedir que corrija la propuesta. El motivo solo trae campos, tipos de
    error e ids, nunca texto de la transcripción."""
    return (
        f"Tu respuesta anterior no es válida: {motivo}. Corrígela y responde de nuevo SOLO con "
        "la lista JSON completa, con los mismos campos. Usa solo números de segmento de la "
        "lista, en orden creciente y sin repetir; no escribas tiempos."
    )


@dataclass(frozen=True)
class _Resultado(Generic[T]):
    """Lo que dejó el ciclo de reintentos: el valor o el error final, y las llamadas hechas."""

    valor: T | None
    intentos: int
    error: LLMError | PropuestaInvalida | None


def _pedir_con_reintentos(
    mensajes: list[dict[str, str]],
    llm: ClienteLLM,
    convertir: Callable[[Any], T],
) -> _Resultado[T]:
    """Llama al LLM y convierte su respuesta; si no es válida, reintenta.

    Se reintenta si `convertir` lanza `PropuestaInvalida` o si el modelo no devolvió JSON
    válido (`LLMRespuestaInvalida`). Cada reintento agrega la respuesta anterior como
    "assistant" (si se pudo leer; el cliente no expone el texto de un JSON roto) y un "user" con
    el motivo (`mensaje_de_correccion`). La temperatura y la semilla son las fijas del cliente.
    Los demás `LLMError` (Ollama caído, petición rechazada) no se reintentan.
    """
    historial = list(mensajes)
    error: PropuestaInvalida | None = None
    for intento in range(1, MAX_INTENTOS + 1):
        anterior: str | None = None
        try:
            respuesta = llm.chat(historial, esquema=ESQUEMA_PASOS)
        except LLMRespuestaInvalida as exc:
            error = PropuestaInvalida(str(exc))  # sin texto: solo longitud y done_reason
        except LLMError as exc:
            return _Resultado(None, intento, exc)
        else:
            try:
                return _Resultado(convertir(respuesta.datos), intento, None)
            except PropuestaInvalida as exc:
                error, anterior = exc, respuesta.texto
        logger.warning(
            "Propuesta del LLM inválida (intento %d de %d): %s", intento, MAX_INTENTOS, error
        )
        if anterior is not None:
            historial.append({"role": "assistant", "content": anterior})
        historial.append({"role": "user", "content": mensaje_de_correccion(error)})
    return _Resultado(
        None, MAX_INTENTOS, PropuestaInvalida(f"{error} (tras {MAX_INTENTOS} intentos)")
    )


def _segmentar_con_llm(
    analisis: Analisis,
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> _Resultado[list[PasoVideo]]:
    mensajes = construir_mensajes(analisis, etiquetas, regla_aclaraciones=regla_aclaraciones)
    return _pedir_con_reintentos(mensajes, llm, lambda datos: construir_pasos(datos, analisis))


def segmentar_con_llm(
    analisis: Analisis,
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> list[PasoVideo]:
    """Pasos propuestos por el LLM, con hasta `MAX_INTENTOS` llamadas si la propuesta (o su
    JSON) no es válida. Lanza `LLMError` si Ollama falla (sin reintentar) o
    `PropuestaInvalida` con el último motivo."""
    r = _segmentar_con_llm(analisis, llm, etiquetas, regla_aclaraciones=regla_aclaraciones)
    if r.error is not None:
        raise r.error
    assert r.valor is not None
    return r.valor


# ── Heurística de respaldo ───────────────────────────────────────────────────────────────────

# Marcadores de transición (sin acentos, minúsculas). Se buscan al inicio del segmento.
MARCADORES = (
    "primero",
    "lo primero",
    "ahora",
    "despues",
    "luego",
    "siguiente",
    "finalmente",
    "a continuacion",
    "por ultimo",
    "enseguida",
    "en seguida",
    "para terminar",
)
# Parámetros fijados de antemano, no ajustados con los fixtures de prueba.
PALABRAS_INICIALES = 3  # el marcador debe aparecer entre las primeras palabras
PAUSA_MIN_S = 3.0  # silencio previo que por sí solo sugiere un paso nuevo
SEPARACION_MIN = 2  # segmentos mínimos entre dos inicios de paso
_PALABRAS_NOMBRE = 8
_PALABRAS_CITA = 15  # máximo de la cita heurística, como la del LLM (4 a 15)
_CARACTERES_DESCRIPCION = 300


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())


def empieza_con_marcador(texto: str, palabras_iniciales: int = PALABRAS_INICIALES) -> bool:
    """True si un marcador de transición aparece entre las primeras palabras del texto."""
    inicio = " ".join(_normalizar(texto).split()[:palabras_iniciales])
    return any(re.search(rf"\b{m}\b", inicio) for m in MARCADORES)


def _nombre_heuristico(texto: str) -> str:
    palabras = texto.split()
    nombre = " ".join(palabras[:_PALABRAS_NOMBRE])
    return nombre + ("…" if len(palabras) > _PALABRAS_NOMBRE else "")


def _recortar(texto: str, limite: int = _CARACTERES_DESCRIPCION) -> str:
    """Recorta en la última palabra completa antes de `limite` caracteres y agrega "…"."""
    if len(texto) <= limite:
        return texto
    corte = texto[: limite + 1].rsplit(" ", 1)[0] or texto[:limite]
    return corte.rstrip(" ,;:.") + "…"


def inicios_heuristicos(
    segmentos: Sequence[Segmento],
    *,
    pausa_min_s: float = PAUSA_MIN_S,
    separacion_min: int = SEPARACION_MIN,
) -> list[int]:
    """Posiciones donde empieza un paso: segmento que empieza con un marcador o tras una pausa
    larga. Un candidato a menos de `separacion_min` segmentos del inicio anterior se descarta.
    Si no hay ningún candidato, todo el video es un solo paso desde el primer segmento."""
    inicios: list[int] = []
    for i, s in enumerate(segmentos):
        pausa = s.t_inicio - segmentos[i - 1].t_fin if i else None
        candidato = empieza_con_marcador(s.texto) or (pausa is not None and pausa >= pausa_min_s)
        if candidato and (not inicios or i - inicios[-1] >= separacion_min):
            inicios.append(i)
    return inicios or ([0] if segmentos else [])


def segmentar_heuristica(
    analisis: Analisis,
    *,
    pausa_min_s: float = PAUSA_MIN_S,
    separacion_min: int = SEPARACION_MIN,
) -> list[PasoVideo]:
    """Pasos del video sin LLM, con los inicios de `inicios_heuristicos`.

    Cada paso abarca hasta el segmento anterior al siguiente inicio (misma regla que
    `construir_pasos`). Nombre: primeras palabras del primer segmento; descripción: texto de
    los segmentos del paso recortado a ~300 caracteres; responsable "No identificado"; cita:
    primeras palabras (hasta 15) del primer segmento, así que siempre está en la transcripción.
    Fuente "audio" y confianza "baja" siempre: la heurística no entiende el contenido, y la
    confianza no sube aunque la cita aparezca.
    """
    segmentos = analisis.transcripcion
    inicios = inicios_heuristicos(segmentos, pausa_min_s=pausa_min_s, separacion_min=separacion_min)
    pasos = []
    for numero, (i_inicio, i_fin) in enumerate(_rangos(inicios, len(segmentos)), start=1):
        primero, ultimo = segmentos[i_inicio], segmentos[i_fin]
        texto = " ".join(" ".join(s.texto.split()) for s in segmentos[i_inicio : i_fin + 1])
        pasos.append(
            PasoVideo(
                numero=numero,
                nombre=_nombre_heuristico(primero.texto) or f"Paso {numero}",
                descripcion=_recortar(texto),
                responsable=NO_IDENTIFICADO,
                t_inicio=primero.t_inicio,
                t_fin=ultimo.t_fin,
                cita=" ".join(primero.texto.split()[:_PALABRAS_CITA]),
                fuente="audio",
                confianza="baja",
            )
        )
    return pasos


# ── Orquestación ─────────────────────────────────────────────────────────────────────────────


def segmentar(
    analisis: Analisis,
    llm: ClienteLLM | None,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> Segmentacion:
    """Pasos del video: LLM si está y responde bien; si no, la heurística. Registra el camino.

    Una propuesta inválida o con JSON roto se reintenta hasta completar `MAX_INTENTOS`
    llamadas; si el LLM no responde, se va directo a la heurística (RNF-07).
    `Segmentacion.intentos` cuenta las llamadas hechas al LLM. Las etiquetas son opcionales (la
    ficha de contexto llega en S5).
    """
    intentos = 0
    if not analisis.transcripcion:
        motivo = "transcripción vacía"
    elif llm is None:
        motivo = "sin cliente LLM"
    else:
        r = _segmentar_con_llm(analisis, llm, etiquetas, regla_aclaraciones=regla_aclaraciones)
        intentos = r.intentos
        if isinstance(r.error, LLMError):
            motivo = f"LLM no disponible o con error ({type(r.error).__name__})"
        elif isinstance(r.error, PropuestaInvalida):
            motivo = f"propuesta del LLM inválida: {r.error}"
        else:
            assert r.valor is not None
            logger.info(
                "Segmentación por LLM (%s): %d pasos en %d intento(s)",
                llm.modelo,
                len(r.valor),
                intentos,
            )
            return Segmentacion(r.valor, "llm", None, llm.modelo, intentos)

    pasos = segmentar_heuristica(analisis)
    logger.info("Segmentación por heurística: %d pasos; motivo: %s", len(pasos), motivo)
    return Segmentacion(pasos, "heuristica", motivo, None, intentos)


# ── Evaluación ───────────────────────────────────────────────────────────────────────────────


def cargar_transcripcion_prueba(path: Path | str, *, video_id: int = 0) -> Analisis:
    """`Analisis` a partir de una transcripción de prueba de tests/fixtures/transcripciones/.

    Esos archivos (inventados) solo traen segmentos con `id`, `t_inicio`, `t_fin` y `texto`,
    más `etiquetas` e `inicios_paso`, que se leen aparte. No se modifican: el idioma se fija a
    mano en español, la duración es el fin del último segmento y no hay palabras ni fotogramas.
    """
    datos = json.loads(Path(path).read_text(encoding="utf-8"))
    segmentos = datos["segmentos"]
    return Analisis(
        video_id=video_id,
        duracion_s=segmentos[-1]["t_fin"] if segmentos else 0.0,
        idioma={"codigo": "es", "confianza": 1.0, "fijado_a_mano": True},
        transcripcion=[{k: s[k] for k in ("id", "t_inicio", "t_fin", "texto")} for s in segmentos],
    )


def segmentos_de_inicio(pasos: Sequence[PasoVideo], analisis: Analisis) -> list[int]:
    """Id del segmento donde empieza cada paso. `t_inicio` siempre es el de un segmento."""
    id_por_inicio = {s.t_inicio: s.id for s in analisis.transcripcion}
    return [id_por_inicio[p.t_inicio] for p in pasos]


def f1_fronteras(
    predichos: Sequence[int], reales: Sequence[int], tolerancia: int = 1
) -> dict[str, Any]:
    """Precisión, recall y F1 de inicios de paso a ±`tolerancia` segmentos.

    Emparejamiento uno a uno de cardinalidad máxima (cada inicio real cuenta una sola vez). Entre
    los emparejamientos máximos se prefiere el que respeta las coincidencias exactas, para que
    las listas de falsos positivos y no detectados señalen el segmento que de verdad sobra o
    falta. Los ids se comparan por posición, así que deben ser consecutivos.
    """
    pred, real = sorted(set(predichos)), sorted(set(reales))
    maximo = _emparejar(pred, real, tolerancia, exactos_primero=False)
    preferido = _emparejar(pred, real, tolerancia, exactos_primero=True)
    aciertos = preferido if len(preferido) == len(maximo) else maximo
    n_pred, n_real, tp = len(pred), len(real), len(aciertos)
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_real if n_real else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    emparejados = {p for p, _ in aciertos}
    libres = sorted(set(real) - {r for _, r in aciertos})
    return {
        "tp": tp,
        "n_predichos": n_pred,
        "n_reales": n_real,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "falsos_positivos": [p for p in pred if p not in emparejados],
        "no_detectados": libres,
    }


def _emparejar(
    pred: list[int], real: list[int], tolerancia: int, *, exactos_primero: bool
) -> list[tuple[int, int]]:
    """Recorre los predichos de izquierda a derecha y toma el real libre más pequeño dentro de
    la ventana: con ventanas del mismo ancho eso da un emparejamiento de cardinalidad máxima.
    Con `exactos_primero`, antes fija las coincidencias exactas."""
    libres = set(real)
    aciertos: list[tuple[int, int]] = []
    if exactos_primero:
        for p in pred:
            if p in libres:
                libres.remove(p)
                aciertos.append((p, p))
    ya = {p for p, _ in aciertos}
    for p in pred:
        if p in ya:
            continue
        candidatos = [r for r in sorted(libres) if abs(r - p) <= tolerancia]
        if candidatos:
            libres.remove(candidatos[0])
            aciertos.append((p, candidatos[0]))
    return sorted(aciertos)
