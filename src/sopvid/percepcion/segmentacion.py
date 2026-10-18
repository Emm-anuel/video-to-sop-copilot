"""Segmentación de la narración en pasos (ADR-010) y extracción de los pasos del video (RF-13).

El LLM recibe los segmentos de habla numerados y las etiquetas del video (nunca el SOP), y
responde SOLO una lista de `PropuestaPaso` (`segmento_id`, `nombre`, `descripcion`,
`responsable`, `cita`) restringida con un JSON Schema generado desde Pydantic. Los tiempos de
cada paso se toman del segmento elegido, **nunca del LLM** (regla 4 de CLAUDE.md): el prompt no
lleva tiempos y el esquema no los admite.

Si el LLM no está disponible, falla o su propuesta no pasa la validación (esquema, ids
existentes, orden creciente, sin duplicados, nombres no vacíos), se usa la heurística de
respaldo: palabras de transición al inicio del segmento ("primero", "ahora", "después", "luego",
"siguiente", "finalmente"…) y pausas largas. El camino usado queda en `Segmentacion.metodo` y en
el log.

Este módulo es Python puro (sin pandas) porque corre en la API.
"""

import logging
import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, field_validator

from sopvid.contrato import Analisis, PasoVideo
from sopvid.lenguaje.llm import ClienteLLM, LLMError

logger = logging.getLogger(__name__)

NO_IDENTIFICADO = "No identificado"  # responsable cuando nadie lo dice en el audio (ADR-008)


class Segmento(TypedDict):
    """Segmento de habla del índice. `t_fin` es opcional; sin él no se usan pausas."""

    id: int
    t_inicio: float
    texto: str
    t_fin: NotRequired[float]


@dataclass(frozen=True)
class Paso:
    segmento_id: int
    t_inicio: float  # siempre el del segmento, nunca uno escrito por el LLM
    nombre: str
    descripcion: str = ""
    responsable: str = NO_IDENTIFICADO
    cita: str = ""  # la heurística no tiene evidencia que citar


@dataclass(frozen=True)
class Segmentacion:
    pasos: list[Paso]
    metodo: Literal["llm", "heuristica"]
    motivo_respaldo: str | None  # por qué se usó la heurística; None si fue el LLM
    modelo: str | None


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
    def _responsable_por_defecto(cls, v: str) -> str:
        return v or NO_IDENTIFICADO


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
    segmentos: Sequence[Segmento],
    etiquetas: Mapping[str, str],
    *,
    regla_aclaraciones: bool = False,
) -> list[dict[str, str]]:
    """Mensajes para el LLM. Solo números de segmento y texto: ningún tiempo y nunca el SOP.

    La regla de cortes es la del prompt v1 (benchmark de ADR-006), ampliada para RF-13 con
    descripción, responsable y cita. `regla_aclaraciones=True` agrega la regla de aclaraciones
    (prompt v2, descartado en la Fase 4).
    """
    numerados = "\n".join(f"[{s['id']}] {s['texto']}" for s in segmentos)
    texto_etiquetas = "; ".join(f"{k}={v}" for k, v in etiquetas.items())
    usuario = (
        f"Etiquetas del video: {texto_etiquetas}.\n\n"
        f"Segmentos de la transcripción, numerados y en orden:\n{numerados}\n\n"
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


def validar_propuesta(datos: Any, segmentos: Sequence[Segmento]) -> list[Paso]:
    """Convierte la respuesta del LLM en pasos (solo inicio) o lanza `PropuestaInvalida`."""
    por_id = {s["id"]: s for s in segmentos}
    return [
        Paso(
            p.segmento_id,
            float(por_id[p.segmento_id]["t_inicio"]),
            p.nombre,
            p.descripcion,
            p.responsable,
            p.cita,
        )
        for p in _validar_propuestas(datos, por_id)
    ]


@dataclass(frozen=True)
class _PasoConRango:
    """Paso del video más los segmentos que abarca (inclusive), para verificar la cita."""

    paso: PasoVideo
    primer_segmento: int
    ultimo_segmento: int


def _construir_con_rangos(propuestas: Any, analisis: Analisis) -> list[_PasoConRango]:
    segmentos = analisis.transcripcion
    posicion = {s.id: i for i, s in enumerate(segmentos)}
    validas = _validar_propuestas(propuestas, posicion)
    # Cada paso termina en el segmento anterior al inicio del siguiente; el último, al final.
    fines = [posicion[p.segmento_id] - 1 for p in validas[1:]] + [len(segmentos) - 1]

    resultado = []
    for numero, (p, i_fin) in enumerate(zip(validas, fines, strict=True), start=1):
        primero, ultimo = segmentos[posicion[p.segmento_id]], segmentos[i_fin]
        paso = PasoVideo(
            numero=numero,
            nombre=p.nombre,
            descripcion=p.descripcion,
            responsable=p.responsable,
            t_inicio=primero.t_inicio,
            t_fin=ultimo.t_fin,
            cita=p.cita,
            fuente="audio",  # provisional: se calcula al verificar la cita
            confianza="baja",  # provisional
        )
        resultado.append(_PasoConRango(paso, primero.id, ultimo.id))
    return resultado


def construir_pasos(propuestas: Any, analisis: Analisis) -> list[PasoVideo]:
    """Pasos del video a partir de la respuesta del LLM (JSON ya interpretado) y el análisis.

    Valida igual que `validar_propuesta` y lanza `PropuestaInvalida`. Los tiempos salen solo
    de la transcripción: `t_inicio` del segmento elegido y `t_fin` del último segmento antes del
    siguiente paso (o del último de la transcripción). `numero` es la posición desde 1.
    """
    return [r.paso for r in _construir_con_rangos(propuestas, analisis)]


def segmentar_con_llm(
    segmentos: Sequence[Segmento],
    etiquetas: Mapping[str, str],
    llm: ClienteLLM,
    *,
    regla_aclaraciones: bool = False,
) -> list[Paso]:
    """Pasos propuestos por el LLM. Lanza `LLMError` o `PropuestaInvalida`."""
    mensajes = construir_mensajes(segmentos, etiquetas, regla_aclaraciones=regla_aclaraciones)
    respuesta = llm.chat(mensajes, esquema=ESQUEMA_PASOS)
    return validar_propuesta(respuesta.datos, segmentos)


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


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())


def empieza_con_marcador(texto: str, palabras_iniciales: int = PALABRAS_INICIALES) -> bool:
    """True si un marcador de transición aparece entre las primeras palabras del texto."""
    inicio = " ".join(_normalizar(texto).split()[:palabras_iniciales])
    return any(re.search(rf"\b{m}\b", inicio) for m in MARCADORES)


def _pausa_previa(anterior: Segmento | None, actual: Segmento) -> float | None:
    if anterior is None or "t_fin" not in anterior:
        return None
    return float(actual["t_inicio"]) - float(anterior["t_fin"])


def _nombre_heuristico(texto: str) -> str:
    palabras = texto.split()
    nombre = " ".join(palabras[:_PALABRAS_NOMBRE])
    return nombre + ("…" if len(palabras) > _PALABRAS_NOMBRE else "")


def segmentar_heuristica(
    segmentos: Sequence[Segmento],
    *,
    pausa_min_s: float = PAUSA_MIN_S,
    separacion_min: int = SEPARACION_MIN,
) -> list[Paso]:
    """Inicio de paso donde el segmento empieza con un marcador o tras una pausa larga.

    Un candidato a menos de `separacion_min` segmentos del inicio anterior se descarta. Si no
    hay ningún candidato, todo el video es un solo paso desde el primer segmento.
    """
    pasos: list[Paso] = []
    ultimo_indice = None
    anterior = None
    for i, s in enumerate(segmentos):
        pausa = _pausa_previa(anterior, s)
        candidato = empieza_con_marcador(s["texto"]) or (pausa is not None and pausa >= pausa_min_s)
        if candidato and (ultimo_indice is None or i - ultimo_indice >= separacion_min):
            pasos.append(Paso(s["id"], float(s["t_inicio"]), _nombre_heuristico(s["texto"])))
            ultimo_indice = i
        anterior = s
    if not pasos and segmentos:
        s = segmentos[0]
        pasos.append(Paso(s["id"], float(s["t_inicio"]), _nombre_heuristico(s["texto"])))
    return pasos


# ── Orquestación ─────────────────────────────────────────────────────────────────────────────


def segmentar(
    segmentos: Sequence[Segmento],
    etiquetas: Mapping[str, str],
    llm: ClienteLLM | None = None,
    *,
    regla_aclaraciones: bool = False,
) -> Segmentacion:
    """Pasos del video: LLM si está y responde bien; si no, la heurística. Registra el camino."""
    if llm is None:
        motivo = "sin cliente LLM"
    else:
        try:
            pasos = segmentar_con_llm(
                segmentos, etiquetas, llm, regla_aclaraciones=regla_aclaraciones
            )
        except LLMError as exc:
            motivo = f"LLM no disponible o con error ({type(exc).__name__})"
        except PropuestaInvalida as exc:
            motivo = f"propuesta del LLM inválida: {exc}"
        else:
            logger.info("Segmentación por LLM (%s): %d pasos", llm.modelo, len(pasos))
            return Segmentacion(pasos, "llm", None, llm.modelo)

    pasos = segmentar_heuristica(segmentos)
    logger.info("Segmentación por heurística: %d pasos; motivo: %s", len(pasos), motivo)
    return Segmentacion(pasos, "heuristica", motivo, None)


# ── Evaluación ───────────────────────────────────────────────────────────────────────────────


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
