"""Segmentación de la narración en pasos (ADR-010).

El LLM recibe los segmentos de habla numerados y las etiquetas del video, y responde SOLO una
lista `[{"segmento_id": int, "titulo": str}]` restringida con JSON Schema. Los tiempos de cada
paso se toman del segmento elegido, **nunca del LLM** (regla 4 de CLAUDE.md): el prompt no lleva
tiempos y el esquema no los admite.

Si el LLM no está disponible, falla o su propuesta no pasa la validación (ids existentes, orden
creciente, sin duplicados, títulos no vacíos), se usa la heurística de respaldo: palabras de
transición al inicio del segmento ("primero", "ahora", "después", "luego", "siguiente",
"finalmente"…) y pausas largas. El camino usado queda en `Segmentacion.metodo` y en el log.

Este módulo es Python puro (sin pandas) porque corre en la API.
"""

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from sopvid.lenguaje.llm import ClienteLLM, LLMError

logger = logging.getLogger(__name__)


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
    titulo: str


@dataclass(frozen=True)
class Segmentacion:
    pasos: list[Paso]
    metodo: Literal["llm", "heuristica"]
    motivo_respaldo: str | None  # por qué se usó la heurística; None si fue el LLM
    modelo: str | None


class PropuestaInvalida(ValueError):  # noqa: N818 (nombre de dominio)
    """La lista del LLM no cumple las reglas de validación."""


# ── LLM ──────────────────────────────────────────────────────────────────────────────────────

ESQUEMA_PASOS: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"segmento_id": {"type": "integer"}, "titulo": {"type": "string"}},
        "required": ["segmento_id", "titulo"],
        "additionalProperties": False,
    },
}

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
    """Mensajes para el LLM. Solo números de segmento y texto: ningún tiempo.

    Por defecto, prompt v1 (el del benchmark de ADR-006); `regla_aclaraciones=True` agrega la
    regla de aclaraciones (prompt v2, descartado en la Fase 4).
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
        + "Responde SOLO con "
        'una lista JSON de objetos {"segmento_id": número del segmento donde empieza el '
        'paso, "titulo": nombre corto del paso en español}, en orden. Usa solo números de '
        "segmento de la lista; no escribas tiempos."
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


def validar_propuesta(datos: Any, segmentos: Sequence[Segmento]) -> list[Paso]:
    """Convierte la respuesta del LLM en pasos o lanza `PropuestaInvalida`.

    Reglas: lista no vacía de objetos con `segmento_id` entero y `titulo` no vacío; ids que
    existen; orden estrictamente creciente (lo que también excluye duplicados). Los motivos
    nunca incluyen texto de la transcripción.
    """
    if not isinstance(datos, list) or not datos:
        raise PropuestaInvalida("la respuesta no es una lista con al menos un paso")
    por_id = {s["id"]: s for s in segmentos}
    pasos: list[Paso] = []
    for i, d in enumerate(datos):
        if not isinstance(d, dict):
            raise PropuestaInvalida(f"el elemento {i} no es un objeto")
        sid, titulo = d.get("segmento_id"), d.get("titulo")
        if not isinstance(sid, int) or isinstance(sid, bool):
            raise PropuestaInvalida(f"el elemento {i} no trae un segmento_id entero")
        if not isinstance(titulo, str) or not titulo.strip():
            raise PropuestaInvalida(f"el elemento {i} no trae título")
        if sid not in por_id:
            raise PropuestaInvalida(f"el segmento {sid} no existe")
        if pasos and sid == pasos[-1].segmento_id:
            raise PropuestaInvalida(f"el segmento {sid} está duplicado")
        if pasos and sid < pasos[-1].segmento_id:
            raise PropuestaInvalida(f"orden no creciente: {pasos[-1].segmento_id} → {sid}")
        pasos.append(Paso(sid, float(por_id[sid]["t_inicio"]), titulo.strip()))
    return pasos


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
_PALABRAS_TITULO = 8


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


def _titulo_heuristico(texto: str) -> str:
    palabras = texto.split()
    titulo = " ".join(palabras[:_PALABRAS_TITULO])
    return titulo + ("…" if len(palabras) > _PALABRAS_TITULO else "")


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
            pasos.append(Paso(s["id"], float(s["t_inicio"]), _titulo_heuristico(s["texto"])))
            ultimo_indice = i
        anterior = s
    if not pasos and segmentos:
        s = segmentos[0]
        pasos.append(Paso(s["id"], float(s["t_inicio"]), _titulo_heuristico(s["texto"])))
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
