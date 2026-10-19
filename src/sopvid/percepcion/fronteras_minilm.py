"""Experimento (19 oct): fronteras de paso con embeddings MiniLM, sin LLM y sin SOP.

No cambia `segmentacion.segmentar()`. Dos métodos que devuelven **ids de segmento** donde
empieza cada paso; los tiempos siguen saliendo del índice de la transcripción.

- **M1 · TextTiling con embeddings (Hearst, 1997).** Embedding de cada segmento. En cada hueco
  entre las posiciones i-1 e i, coseno entre la media de los `k` segmentos anteriores y la de los
  `k` siguientes (en los bordes, los que haya). Profundidad de Hearst: lo que sube la curva a la
  izquierda mientras crece más lo que sube a la derecha. Hay corte en los valles (mínimos locales)
  cuya profundidad supera media + `c`·desviación de las profundidades, elegidos de mayor a menor
  profundidad con al menos `separacion_min` segmentos entre inicios. El primer segmento siempre
  inicia un paso: no se fuerza una introducción.
- **M2 · Fusión de cortes de Gemma.** Recibe los inicios propuestos por el LLM. En cada vuelta
  calcula, para cada inicio salvo el primero, el coseno entre el embedding medio del paso
  anterior y el del paso siguiente, y quita el corte con el coseno más alto si supera `u` (los
  dos pasos se unen). Repite hasta que ninguno lo supere. Quitar el más alto primero hace que el
  resultado no dependa del orden del recorrido. El primer inicio no se toca: lo anterior es la
  introducción, no un paso. No usa el SOP: es distinto de la fusión de ADR-013.

Valores por defecto fijados **antes** de medir (ADR-010, experimento del 19 oct): k=2, c=0.5,
u=0.6. La separación mínima es la de la heurística (2).
"""

from collections.abc import Sequence
from typing import Protocol

import numpy as np

from sopvid.contrato import Analisis
from sopvid.percepcion.segmentacion import SEPARACION_MIN

K_VENTANA = 2
C_PROFUNDIDAD = 0.5
U_FUSION = 0.6


class Vectoriza(Protocol):
    """Lo que se usa de `sopvid.lenguaje.emparejamiento.Embedder`."""

    def embed(self, textos: Sequence[str]) -> np.ndarray: ...


def embeber_segmentos(analisis: Analisis, embedder: Vectoriza) -> np.ndarray:
    """Un vector por segmento de la transcripción, en orden (n × d)."""
    return embedder.embed([s.texto for s in analisis.transcripcion])


def _coseno(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(a @ b) / (na * nb) if na and nb else 0.0


# ── M1 · TextTiling ──────────────────────────────────────────────────────────────────────────


def puntajes_bloques(x: np.ndarray, k: int = K_VENTANA) -> np.ndarray:
    """Coseno en cada hueco: el elemento g compara x[g+1-k : g+1] con x[g+1 : g+1+k]
    (corte antes de la posición g+1). Largo n-1."""
    n = len(x)
    return np.array(
        [_coseno(x[max(0, i - k) : i].mean(axis=0), x[i : i + k].mean(axis=0)) for i in range(1, n)]
    )


def profundidades(s: np.ndarray) -> np.ndarray:
    """Profundidad de Hearst de cada hueco: (pico izquierdo - s) + (pico derecho - s), donde
    cada pico se alcanza subiendo mientras el puntaje no baja (como NLTK)."""
    d = np.zeros(len(s))
    for g, valor in enumerate(s):
        izq = valor
        for v in s[g::-1]:
            if v < izq:
                break
            izq = v
        der = valor
        for v in s[g:]:
            if v < der:
                break
            der = v
        d[g] = (izq - valor) + (der - valor)
    return d


def cortes_texttiling(
    x: np.ndarray,
    *,
    k: int = K_VENTANA,
    c: float = C_PROFUNDIDAD,
    separacion_min: int = SEPARACION_MIN,
) -> list[int]:
    """Posiciones (desde 0) donde empieza cada paso según M1; siempre incluye la 0."""
    n = len(x)
    if n == 0:
        return []
    if n == 1:
        return [0]
    s = puntajes_bloques(x, k)
    d = profundidades(s)
    umbral = d.mean() + c * d.std()
    valles = [
        g
        for g in range(len(s))
        if (g == 0 or s[g] <= s[g - 1]) and (g == len(s) - 1 or s[g] <= s[g + 1])
    ]
    candidatos = sorted((g for g in valles if d[g] > umbral), key=lambda g: (-d[g], g))
    inicios = [0]
    for g in candidatos:
        p = g + 1  # el hueco g está antes de la posición g+1
        if all(abs(p - q) >= separacion_min for q in inicios):
            inicios.append(p)
    return sorted(inicios)


def inicios_texttiling(
    analisis: Analisis,
    embedder: Vectoriza,
    *,
    k: int = K_VENTANA,
    c: float = C_PROFUNDIDAD,
    separacion_min: int = SEPARACION_MIN,
) -> list[int]:
    """M1 sobre un `Analisis`: ids de segmento donde empieza cada paso."""
    x = embeber_segmentos(analisis, embedder)
    posiciones = cortes_texttiling(x, k=k, c=c, separacion_min=separacion_min)
    return [analisis.transcripcion[p].id for p in posiciones]


# ── M2 · Fusión de cortes del LLM ────────────────────────────────────────────────────────────


def fusionar_cortes(x: np.ndarray, inicios: Sequence[int], *, u: float = U_FUSION) -> list[int]:
    """Posiciones de inicio tras unir pasos consecutivos parecidos (M2). `inicios` son
    posiciones (desde 0) en `x`; el resultado es un subconjunto ordenado que conserva el primero."""
    actuales = sorted(set(inicios))
    while len(actuales) > 1:
        limites = [*actuales, len(x)]
        medias = [x[a:b].mean(axis=0) for a, b in zip(limites, limites[1:], strict=False)]
        sims = [_coseno(medias[j - 1], medias[j]) for j in range(1, len(medias))]
        j = int(np.argmax(sims))  # el primero en caso de empate
        if sims[j] <= u:
            break
        del actuales[j + 1]
    return actuales


def fusionar_inicios(
    analisis: Analisis,
    inicios_ids: Sequence[int],
    embedder: Vectoriza,
    *,
    u: float = U_FUSION,
) -> list[int]:
    """M2 sobre un `Analisis`: ids de inicio del LLM → ids tras la fusión. Un id que no existe
    lanza `KeyError` (los del LLM ya pasaron la validación de `segmentacion`)."""
    posicion = {s.id: i for i, s in enumerate(analisis.transcripcion)}
    x = embeber_segmentos(analisis, embedder)
    fusion = fusionar_cortes(x, [posicion[i] for i in inicios_ids], u=u)
    return [analisis.transcripcion[p].id for p in fusion]
