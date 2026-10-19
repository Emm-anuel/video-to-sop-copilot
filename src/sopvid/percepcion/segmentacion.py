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
    intentos: int = 0  # llamadas para las fronteras (o la única llamada); máximo MAX_INTENTOS
    intentos_redaccion: int = 0  # llamadas para redactar (opción A); 0 si no se llegó a pedir
    motivo_sin_redaccion: str | None = None  # por qué hay pasos sin redactar (sin texto)
    pasos_sin_redactar: int = 0  # pasos que quedaron con nombre = título y cita vacía


class PropuestaInvalida(ValueError):  # noqa: N818 (nombre de dominio)
    """La lista del LLM no cumple las reglas de validación."""


# ── LLM ──────────────────────────────────────────────────────────────────────────────────────

PALABRAS_CITA = (4, 15)  # largo exigido a la cita que redacta el LLM (opción A)


class _Respuesta(BaseModel):
    """Configuración común de lo que devuelve el LLM."""

    model_config = ConfigDict(
        extra="forbid",  # un campo de más, como un tiempo, invalida la respuesta
        strict=True,  # "2" o True no cuentan como número
        str_strip_whitespace=True,
        hide_input_in_errors=True,  # los errores no deben copiar texto de la transcripción
    )


class PropuestaFrontera(_Respuesta):
    """Llamada 1 de la opción A: dónde empieza cada paso y un título. Ningún tiempo."""

    segmento_id: int
    titulo: str

    @field_validator("titulo")
    @classmethod
    def _titulo_no_vacio(cls, v: str) -> str:
        if not v:
            raise ValueError("título vacío")
        return v


class RedaccionPaso(_Respuesta):
    """Llamada 2 de la opción A: redacción de un paso cuyas fronteras ya fijó el código."""

    numero: int
    descripcion: str
    responsable: str
    cita: str

    @field_validator("responsable")
    @classmethod
    def _responsable_normalizado(cls, v: str) -> str:
        return normalizar_responsable(v)

    @field_validator("cita")
    @classmethod
    def _cita_de_4_a_15_palabras(cls, v: str) -> str:
        """Menos de 4 palabras es inválida; más de 15 se recorta a sus primeras 15 (un recorte
        de una cita literal sigue siendo literal, así que se verifica igual)."""
        minimo, maximo = PALABRAS_CITA
        n = len(_texto_comparable(v).split())
        if n < minimo:
            raise ValueError(f"la cita tiene {n} palabras y debe tener de {minimo} a {maximo}")
        return recortar_cita(v, maximo) if n > maximo else v


class PropuestaPaso(_Respuesta):
    """Un paso completo en una sola llamada (opción descartada como valor por defecto, ver
    ADR-010): un número de segmento y texto, ningún tiempo."""

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


def _esquema_de_lista(modelo: type[BaseModel]) -> dict[str, Any]:
    """Esquema para el parámetro `format` de Ollama: lista de `modelo`, sin `$ref`."""
    return _sin_refs(TypeAdapter(list[modelo]).json_schema())


ESQUEMA_FRONTERAS = _esquema_de_lista(PropuestaFrontera)
ESQUEMA_REDACCION = _esquema_de_lista(RedaccionPaso)
ESQUEMA_PASOS = _esquema_de_lista(PropuestaPaso)

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


def _linea_etiquetas(etiquetas: Mapping[str, str] | None) -> str:
    texto = "; ".join(f"{k}={v}" for k, v in (etiquetas or {}).items())
    return f"Etiquetas del video: {texto}.\n\n" if texto else ""


def _numerados(segmentos: Sequence[Segmento]) -> str:
    return "\n".join(f"[{s.id}] {s.texto}" for s in segmentos)


# Regla de cortes del prompt v1 (benchmark de ADR-006); la usan la llamada de fronteras y la
# llamada única.
_REGLA_CORTES = (
    "Identifica en qué segmento empieza cada paso del procedimiento. Un paso suele "
    "abarcar varios segmentos: no marques cada segmento como paso, y la introducción o "
    "los comentarios no inician pasos. "
)


def construir_mensajes_fronteras(
    analisis: Analisis,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> list[dict[str, str]]:
    """Llamada 1 de la opción A: el prompt v1 de la Fase 4 (F1 0.74), sin cambios.

    Solo números de segmento y texto: ningún tiempo y nunca el SOP. Sin etiquetas se omite esa
    línea. `regla_aclaraciones=True` agrega la regla del prompt v2 (descartado en la Fase 4).
    """
    usuario = (
        _linea_etiquetas(etiquetas) + f"Segmentos de la transcripción, numerados y en orden:\n"
        f"{_numerados(analisis.transcripcion)}\n\n"
        + _REGLA_CORTES
        + (REGLA_ACLARACIONES if regla_aclaraciones else "")
        + "Responde SOLO con "
        'una lista JSON de objetos {"segmento_id": número del segmento donde empieza el '
        'paso, "titulo": nombre corto del paso en español}, en orden. Usa solo números de '
        "segmento de la lista; no escribas tiempos."
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


def construir_mensajes_redaccion(
    analisis: Analisis,
    fronteras: Sequence[PropuestaFrontera],
    etiquetas: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Llamada 2 de la opción A: redactar cada paso con las fronteras ya fijadas por el código.

    Muestra la introducción (lo anterior al primer paso, donde suele presentarse quien narra) y
    cada paso numerado con su título y su texto. Los segmentos van **sin número**: con `[n]` el
    modelo confundía el número de paso con el de segmento y citaba el segmento `[n]` en el paso
    n (medición del 18 oct, ADR-010). Sin tiempos, sin SOP y sin ejemplos de rol que el modelo
    pueda copiar; el responsable se pide como puesto, nunca como nombre de persona.
    """
    segmentos = analisis.transcripcion
    posicion = {s.id: i for i, s in enumerate(segmentos)}
    rangos = _rangos([posicion[f.segmento_id] for f in fronteras], len(segmentos))
    introduccion = _texto_de(segmentos[: rangos[0][0]]) if rangos else ""
    bloques = "\n\n".join(
        f"Paso {n} · {f.titulo}\n{_texto_de(segmentos[i : j + 1])}"
        for n, (f, (i, j)) in enumerate(zip(fronteras, rangos, strict=True), start=1)
    )
    usuario = (
        _linea_etiquetas(etiquetas)
        + "Transcripción de un procedimiento, ya dividida en pasos y en orden.\n\n"
        f"Introducción (antes del primer paso):\n{introduccion or '(sin introducción)'}\n\n"
        f"{bloques}\n\n"
        "Para cada paso da:\n"
        "- numero: el número del paso, tal como aparece arriba.\n"
        "- descripcion: qué se hace en el paso, en una o dos frases.\n"
        "- responsable: el puesto de quien hace el paso, nunca el nombre de una persona. Si "
        "quien narra dice su puesto (por lo general en la introducción) y describe los pasos "
        "en primera persona, ese puesto es el responsable de esos pasos. Si en la "
        f'transcripción no se dice ningún puesto, "{NO_IDENTIFICADO}". No supongas un puesto '
        "que no se dice.\n"
        f"- cita: una frase copiada textualmente del texto de ese mismo paso, de "
        f"{PALABRAS_CITA[0]} a {PALABRAS_CITA[1]} palabras, sin parafrasear ni traducir.\n"
        "Redacta descripcion y responsable en español aunque la transcripción esté en otro "
        "idioma; la cita se deja en el idioma original. "
        "Responde SOLO con una lista JSON con un objeto por paso, en el mismo orden. No "
        "cambies los pasos ni escribas tiempos."
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


def _texto_de(segmentos: Sequence[Segmento]) -> str:
    """Texto de los segmentos, uno por línea y sin número (para la llamada de redacción)."""
    return "\n".join(s.texto for s in segmentos)


def construir_mensajes(
    analisis: Analisis,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> list[dict[str, str]]:
    """Llamada única (descartada como valor por defecto): cortes y redacción a la vez.

    La regla de cortes es la del prompt v1, ampliada para RF-13 con descripción, responsable y
    cita. En la medición del 18 oct partió más los pasos que el prompt v1 solo (ADR-010).
    Solo números de segmento y texto: ningún tiempo y nunca el SOP.
    """
    usuario = (
        _linea_etiquetas(etiquetas) + f"Segmentos de la transcripción, numerados y en orden:\n"
        f"{_numerados(analisis.transcripcion)}\n\n"
        + _REGLA_CORTES
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


R = TypeVar("R", bound=_Respuesta)


def _validar_lista(datos: Any, modelo: type[R]) -> list[R]:
    """Lista no vacía de objetos que cumplen `modelo`, o `PropuestaInvalida`.

    El motivo nombra el elemento, el campo y el tipo de error (y el detalle de nuestras propias
    reglas, como el largo de la cita); nunca copia texto de la transcripción.
    """
    if not isinstance(datos, list) or not datos:
        raise PropuestaInvalida("la respuesta no es una lista con al menos un paso")
    validos: list[R] = []
    for i, d in enumerate(datos):
        if not isinstance(d, dict):
            raise PropuestaInvalida(f"el elemento {i} no es un objeto")
        try:
            validos.append(modelo.model_validate(d))
        except ValidationError as exc:
            raise PropuestaInvalida(
                f"el elemento {i} no cumple el esquema: {_resumen_errores(exc)}"
            ) from None
    return validos


def _resumen_errores(exc: ValidationError) -> str:
    """Campo y tipo de cada error, más el detalle de nuestras reglas; sin el valor recibido."""
    return ", ".join(
        f"{'.'.join(map(str, e['loc']))} ({e['type']})"
        + (f": {e['ctx']['error']}" if e["type"] == "value_error" else "")
        for e in exc.errors()
    )


def _validar_redaccion(
    datos: Any, esperados: Sequence[int]
) -> tuple[dict[int, RedaccionPaso], dict[int, str]]:
    """Valida la redacción paso por paso: (válidos por número, motivo de cada esperado que falla).

    Un paso inválido no invalida a los demás. Se ignoran los números que no se pidieron y las
    repeticiones (vale el primero). Los motivos nunca copian texto de la transcripción.
    """
    if not isinstance(datos, list) or not datos:
        return {}, dict.fromkeys(esperados, "la respuesta no es una lista con al menos un paso")
    validos: dict[int, RedaccionPaso] = {}
    fallos: dict[int, str] = {}
    for d in datos:
        numero = d.get("numero") if isinstance(d, dict) else None
        if not isinstance(numero, int) or isinstance(numero, bool) or numero not in esperados:
            continue  # sin un número de paso pedido no se puede atribuir
        if numero in validos:
            continue
        try:
            validos[numero] = RedaccionPaso.model_validate(d)
        except ValidationError as exc:
            fallos.setdefault(numero, _resumen_errores(exc))
        else:
            fallos.pop(numero, None)
    for n in esperados:
        if n not in validos:
            fallos.setdefault(n, "falta en la respuesta")
    return validos, fallos


P = TypeVar("P", PropuestaPaso, PropuestaFrontera)


def _validar_propuestas(
    datos: Any, ids_existentes: Collection[int], modelo: type[P] = PropuestaPaso
) -> list[P]:
    """Valida la respuesta del LLM o lanza `PropuestaInvalida`.

    Reglas: lista no vacía de objetos que cumplen `modelo` (sin campos extra, como un tiempo
    inventado, y con nombre o título no vacío); ids que existen; orden estrictamente creciente
    (lo que también excluye duplicados). Los motivos nunca incluyen texto de la transcripción.
    """
    propuestas: list[P] = []
    for p in _validar_lista(datos, modelo):
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
    posicion = {s.id: i for i, s in enumerate(analisis.transcripcion)}
    return _armar(_validar_propuestas(propuestas, posicion), analisis)


def _armar(validas: Sequence[PropuestaPaso], analisis: Analisis) -> list[_PasoConRango]:
    """`PasoVideo` con tiempos del índice, cita verificada y ajuste por responsable."""
    segmentos = analisis.transcripcion
    posicion = {s.id: i for i, s in enumerate(segmentos)}
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
    return _registrar(_construir_con_rangos(propuestas, analisis))


def _registrar(construidos: Sequence[_PasoConRango]) -> list[PasoVideo]:
    """Deja en el log cuántas citas cayeron en cada nivel (sin texto) y devuelve los pasos."""
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


def recortar_cita(cita: str, max_palabras: int = PALABRAS_CITA[1]) -> str:
    """Primeras `max_palabras` palabras de la cita, contadas como en la verificación (la
    puntuación sola no cuenta). Si la cita era literal, el recorte también lo es."""
    tomadas: list[str] = []
    n = 0
    for token in cita.split():
        cuenta = len(_texto_comparable(token).split())
        if n + cuenta > max_palabras:
            break
        tomadas.append(token)
        n += cuenta
    return " ".join(tomadas)


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

MAX_INTENTOS = 3  # una llamada más dos reintentos si la respuesta no pasa la validación

# Lo que se recuerda al pedir una corrección, según la llamada.
RECORDATORIO_SEGMENTOS = (
    "Usa solo números de segmento de la lista, en orden creciente y sin repetir; no escribas "
    "tiempos."
)
RECORDATORIO_REDACCION = (
    "La cita, de "
    f"{PALABRAS_CITA[0]} a {PALABRAS_CITA[1]} palabras copiadas de ese paso; no escribas tiempos."
)


def mensaje_de_correccion(
    motivo: PropuestaInvalida, recordatorio: str = RECORDATORIO_SEGMENTOS
) -> str:
    """Mensaje "user" para pedir que corrija la respuesta. El motivo solo trae campos, tipos de
    error, ids y números de paso, nunca texto de la transcripción."""
    return (
        f"Tu respuesta anterior no es válida: {motivo}. Corrígela y responde de nuevo SOLO con "
        f"la lista JSON completa, con los mismos campos. {recordatorio}"
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
    esquema: dict[str, Any],
    recordatorio: str = RECORDATORIO_SEGMENTOS,
) -> _Resultado[T]:
    """Llama al LLM con `esquema` y convierte su respuesta; si no es válida, reintenta.

    Se reintenta si `convertir` lanza `PropuestaInvalida` o si el modelo no devolvió JSON
    válido (`LLMRespuestaInvalida`). Cada reintento agrega la respuesta anterior como
    "assistant" (si se pudo leer; el cliente no expone el texto de un JSON roto) y un "user" con
    el motivo y `recordatorio` (`mensaje_de_correccion`). La temperatura y la semilla son las
    fijas del cliente. Los demás `LLMError` (Ollama caído, petición rechazada) no se reintentan.
    """
    historial = list(mensajes)
    error: PropuestaInvalida | None = None
    for intento in range(1, MAX_INTENTOS + 1):
        anterior: str | None = None
        try:
            respuesta = llm.chat(historial, esquema=esquema)
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
            "Respuesta del LLM inválida (intento %d de %d): %s", intento, MAX_INTENTOS, error
        )
        if anterior is not None:
            historial.append({"role": "assistant", "content": anterior})
        historial.append({"role": "user", "content": mensaje_de_correccion(error, recordatorio)})
    return _Resultado(
        None, MAX_INTENTOS, PropuestaInvalida(f"{error} (tras {MAX_INTENTOS} intentos)")
    )


@dataclass(frozen=True)
class _Extraccion:
    """Resultado del camino LLM: pasos o error final, y lo que pasó en cada llamada."""

    pasos: list[PasoVideo] | None
    error: LLMError | PropuestaInvalida | None
    intentos: int
    intentos_redaccion: int = 0
    motivo_sin_redaccion: str | None = None
    pasos_sin_redactar: int = 0


def _motivo(error: LLMError | PropuestaInvalida) -> str:
    if isinstance(error, PropuestaInvalida):
        return f"respuesta del LLM inválida: {error}"
    return f"LLM no disponible o con error ({type(error).__name__})"


def mensaje_de_pendientes(fallos: Mapping[int, str]) -> str:
    """Mensaje "user" del reintento de la redacción: solo los pasos que faltan o fallaron, con su
    motivo (sin texto de la transcripción). No se reenvía la respuesta anterior, así que el
    contexto no crece de un intento a otro."""
    detalle = "; ".join(f"paso {n}: {motivo}" for n, motivo in sorted(fallos.items()))
    numeros = ", ".join(str(n) for n in sorted(fallos))
    return (
        f"Faltan o no son válidos estos pasos: {detalle}. Responde SOLO con una lista JSON con "
        f"un objeto para cada uno de esos pasos (numero {numeros}), con los mismos campos. "
        f"{RECORDATORIO_REDACCION}"
    )


@dataclass(frozen=True)
class _Redaccion:
    """Lo que dejó la llamada 2: pasos redactados por número, llamadas y motivo de los que no."""

    validos: dict[int, RedaccionPaso]
    intentos: int
    motivo: str | None  # None si se redactaron todos


def _redactar(
    analisis: Analisis,
    fronteras: Sequence[PropuestaFrontera],
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None,
) -> _Redaccion:
    """Llamada 2 de la opción A, con hasta `MAX_INTENTOS` llamadas.

    Cada paso se valida por separado: los válidos se guardan y el reintento pide solo los que
    faltan o fallaron (`mensaje_de_pendientes`). Si Ollama no responde, se detiene ahí.
    """
    base = construir_mensajes_redaccion(analisis, fronteras, etiquetas)
    pendientes = list(range(1, len(fronteras) + 1))
    validos: dict[int, RedaccionPaso] = {}
    fallos: dict[int, str] = {}
    for intento in range(1, MAX_INTENTOS + 1):
        mensajes = base if intento == 1 else [*base, _usuario(mensaje_de_pendientes(fallos))]
        try:
            respuesta = llm.chat(mensajes, esquema=ESQUEMA_REDACCION)
        except LLMRespuestaInvalida as exc:  # sin texto: solo longitud y done_reason
            fallos = dict.fromkeys(pendientes, str(exc))
        except LLMError as exc:
            return _Redaccion(validos, intento, f"{_motivo(exc)}; {_sin_redactar(pendientes)}")
        else:
            nuevos, fallos = _validar_redaccion(respuesta.datos, pendientes)
            validos.update(nuevos)
        pendientes = [n for n in pendientes if n not in validos]
        if not pendientes:
            return _Redaccion(validos, intento, None)
        logger.warning(
            "Redacción: %d de %d pasos sin validar (intento %d de %d)",
            len(pendientes),
            len(fronteras),
            intento,
            MAX_INTENTOS,
        )
    detalle = "; ".join(f"paso {n}: {fallos[n]}" for n in pendientes)
    return _Redaccion(
        validos,
        MAX_INTENTOS,
        f"{_sin_redactar(pendientes)} tras {MAX_INTENTOS} intentos ({detalle})",
    )


def _usuario(contenido: str) -> dict[str, str]:
    return {"role": "user", "content": contenido}


def _sin_redactar(pendientes: Sequence[int]) -> str:
    return f"pasos sin redactar: {', '.join(str(n) for n in pendientes)}"


def _en_dos_llamadas(
    analisis: Analisis,
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None,
    regla_aclaraciones: bool,
) -> _Extraccion:
    """Opción A de ADR-010: fronteras con el prompt v1 y, aparte, la redacción de cada paso.

    Si las fronteras fallan, no hay pasos (`segmentar` usa la heurística). Cada paso que no se
    logra redactar conserva su frontera con nombre = título, cita vacía y confianza baja; los
    demás pasos se redactan normalmente.
    """
    posicion = {s.id: i for i, s in enumerate(analisis.transcripcion)}
    r1 = _pedir_con_reintentos(
        construir_mensajes_fronteras(analisis, etiquetas, regla_aclaraciones=regla_aclaraciones),
        llm,
        lambda datos: _validar_propuestas(datos, posicion, PropuestaFrontera),
        ESQUEMA_FRONTERAS,
    )
    if r1.error is not None:
        return _Extraccion(None, r1.error, r1.intentos)
    fronteras = r1.valor
    assert fronteras is not None

    r2 = _redactar(analisis, fronteras, llm, etiquetas)
    if r2.motivo is not None:
        logger.warning("Se conservan sin redactar algunas fronteras: %s", r2.motivo)
    propuestas = []
    for numero, f in enumerate(fronteras, start=1):
        r = r2.validos.get(numero)
        propuestas.append(
            PropuestaPaso(
                segmento_id=f.segmento_id,
                nombre=f.titulo,
                descripcion=r.descripcion if r else "",
                responsable=r.responsable if r else NO_IDENTIFICADO,
                cita=r.cita if r else "",
            )
        )
    return _Extraccion(
        _registrar(_armar(propuestas, analisis)),
        None,
        r1.intentos,
        r2.intentos,
        r2.motivo,
        len(fronteras) - len(r2.validos),
    )


def _en_una_llamada(
    analisis: Analisis,
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None,
    regla_aclaraciones: bool,
) -> _Extraccion:
    """Cortes y redacción en una sola llamada (prompt v1 ampliado, medido el 18 oct)."""
    r = _pedir_con_reintentos(
        construir_mensajes(analisis, etiquetas, regla_aclaraciones=regla_aclaraciones),
        llm,
        lambda datos: construir_pasos(datos, analisis),
        ESQUEMA_PASOS,
    )
    return _Extraccion(r.valor, r.error, r.intentos)


def _segmentar_con_llm(
    analisis: Analisis,
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
    dos_llamadas: bool = True,
) -> _Extraccion:
    extraer = _en_dos_llamadas if dos_llamadas else _en_una_llamada
    return extraer(analisis, llm, etiquetas, regla_aclaraciones)


def segmentar_con_llm(
    analisis: Analisis,
    llm: ClienteLLM,
    etiquetas: Mapping[str, str] | None = None,
    *,
    regla_aclaraciones: bool = False,
    dos_llamadas: bool = True,
) -> list[PasoVideo]:
    """Pasos propuestos por el LLM, con hasta `MAX_INTENTOS` llamadas por etapa si la respuesta
    (o su JSON) no es válida. Lanza `LLMError` si Ollama falla al buscar las fronteras (sin
    reintentar) o `PropuestaInvalida` con el último motivo. Con `dos_llamadas`, si solo falla la
    redacción, devuelve las fronteras sin redactar."""
    r = _segmentar_con_llm(
        analisis, llm, etiquetas, regla_aclaraciones=regla_aclaraciones, dos_llamadas=dos_llamadas
    )
    if r.error is not None:
        raise r.error
    assert r.pasos is not None
    return r.pasos


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
    dos_llamadas: bool = True,
) -> Segmentacion:
    """Pasos del video: LLM si está y responde bien; si no, la heurística. Registra el camino.

    Por defecto, opción A de ADR-010: una llamada para las fronteras (prompt v1) y otra para
    redactar descripción, responsable y cita; si falla solo la redacción, se conservan las
    fronteras sin redactar. Con `dos_llamadas=False`, todo en una llamada.

    Cada llamada reintenta una respuesta inválida o con JSON roto hasta completar `MAX_INTENTOS`;
    si el LLM no responde al buscar las fronteras, se va directo a la heurística (RNF-07).
    `Segmentacion.intentos` e `intentos_redaccion` cuentan las llamadas de cada etapa. Las
    etiquetas son opcionales (la ficha de contexto llega en S5).
    """
    intentos = 0
    if not analisis.transcripcion:
        motivo = "transcripción vacía"
    elif llm is None:
        motivo = "sin cliente LLM"
    else:
        r = _segmentar_con_llm(
            analisis,
            llm,
            etiquetas,
            regla_aclaraciones=regla_aclaraciones,
            dos_llamadas=dos_llamadas,
        )
        intentos = r.intentos
        if r.error is not None:
            motivo = _motivo(r.error)
        else:
            assert r.pasos is not None
            logger.info(
                "Segmentación por LLM (%s): %d pasos; %d intento(s) de fronteras, "
                "%d de redacción%s",
                llm.modelo,
                len(r.pasos),
                r.intentos,
                r.intentos_redaccion,
                f"; {r.pasos_sin_redactar} sin redactar" if r.pasos_sin_redactar else "",
            )
            return Segmentacion(
                r.pasos,
                "llm",
                None,
                llm.modelo,
                r.intentos,
                r.intentos_redaccion,
                r.motivo_sin_redaccion,
                r.pasos_sin_redactar,
            )

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
