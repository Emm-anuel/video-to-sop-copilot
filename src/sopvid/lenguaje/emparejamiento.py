"""Emparejamiento de los pasos del SOP con los pasos del video (ADR-012, plan §5.3).

Base de S2: `Embedder`, que vectoriza textos con MiniLM multilingüe
(`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensiones) siempre en CPU para no competir por
la VRAM con faster-whisper ni con Gemma 4, y `similitud`, la matriz de coseno entre dos grupos
de vectores. `texto_para_embeber` arma el mismo texto para un paso del SOP y uno del video.

S3: `fusionar` une los pasos consecutivos del video que caen en el mismo paso del SOP
(ADR-013). El algoritmo húngaro, la cascada con Gemma 4 y el orden llegan después.

`sentence_transformers` (y con él torch) se importa al cargar el modelo, no al importar este
módulo, para que la API arranque rápido y las pruebas puedan simular el modelo.
"""

import logging
import time
from collections.abc import Callable, Sequence
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from sopvid.contrato import Confianza, Fuente, Fusion, PasoSOP, PasoVideo
from sopvid.plataforma.config import get_settings

logger = logging.getLogger(__name__)

DIMENSION = 384  # tamaño del vector de paraphrase-multilingual-MiniLM-L12-v2
TAMANO_LOTE = 32


class Vectorizador(Protocol):
    """Lo que se usa de `SentenceTransformer`; las pruebas lo sustituyen por uno simulado."""

    def encode(self, sentences: list[str], **kwargs: Any) -> Any: ...


Cargador = Callable[[str, Path], Vectorizador]


def cargar_sentence_transformer(modelo: str, cache_dir: Path) -> Vectorizador:
    """`SentenceTransformer` en CPU, con los pesos en `cache_dir` (se descargan la primera vez)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(modelo, device="cpu", cache_folder=str(cache_dir))


class Embedder:
    """Vectoriza textos con MiniLM. El modelo se carga una sola vez, en la primera llamada a
    `embed` o con `cargar()`; crear el objeto no carga nada.

    Sin argumentos, el modelo y la carpeta de pesos salen de la configuración
    (`EMBEDDER_MODEL`, `EMBEDDER_CACHE_DIR`).
    """

    def __init__(
        self,
        modelo: str | None = None,
        cache_dir: Path | None = None,
        *,
        cargador: Cargador = cargar_sentence_transformer,
    ) -> None:
        settings = get_settings()
        self.modelo = modelo or settings.embedder_model
        self.cache_dir = cache_dir or settings.embedder_cache_path
        self._cargador = cargador
        self._vectorizador: Vectorizador | None = None
        self.segundos_carga: float | None = None  # lo que tardó la carga (None si no se cargó)

    @property
    def cargado(self) -> bool:
        return self._vectorizador is not None

    def cargar(self) -> None:
        """Carga el modelo si aún no está cargado (idempotente) y mide cuánto tardó."""
        if self._vectorizador is not None:
            return
        inicio = time.perf_counter()
        self._vectorizador = self._cargador(self.modelo, self.cache_dir)
        self.segundos_carga = time.perf_counter() - inicio
        logger.info("Modelo %s cargado en CPU en %.1f s", self.modelo, self.segundos_carga)

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        """Matriz `len(textos) × 384` en float32, con cada fila de norma 1 (un texto que da el
        vector cero queda en cero). Sin textos devuelve `0 × 384` sin cargar el modelo."""
        if not textos:
            return np.zeros((0, DIMENSION), dtype=np.float32)
        self.cargar()
        assert self._vectorizador is not None
        vectores = self._vectorizador.encode(
            list(textos),
            batch_size=TAMANO_LOTE,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return _normalizar_filas(np.asarray(vectores, dtype=np.float32))


@lru_cache
def get_embedder() -> Embedder:
    """El `Embedder` del proceso, con la configuración: un solo modelo en memoria."""
    return Embedder()


def _normalizar_filas(x: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(x, axis=1, keepdims=True)
    return np.divide(x, normas, out=np.zeros_like(x), where=normas > 0)


def similitud(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Coseno entre cada fila de `a` (m × d) y cada fila de `b` (n × d): matriz m × n en [-1, 1].

    Vuelve a normalizar las filas, así que acepta vectores sin normalizar; una fila de ceros da
    similitud 0 con todo. Un solo vector (1-D) cuenta como una fila.
    """
    a, b = np.atleast_2d(np.asarray(a, dtype=np.float32)), np.atleast_2d(np.asarray(b, np.float32))
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[1]:
        raise ValueError(f"dimensiones incompatibles: {a.shape} y {b.shape}")
    return np.clip(_normalizar_filas(a) @ _normalizar_filas(b).T, -1.0, 1.0)


def texto_para_embeber(paso: PasoSOP | PasoVideo) -> str:
    """Texto que se vectoriza de un paso: "nombre. descripción", o solo el nombre si no hay
    descripción, con los espacios colapsados. Si el nombre ya cierra con ".", "?" o "!", no se
    agrega otro punto. Igual para los pasos del SOP y los del video."""
    nombre = " ".join(paso.nombre.split())
    descripcion = " ".join(paso.descripcion.split())
    if not descripcion:
        return nombre
    separador = " " if nombre.endswith((".", "?", "!")) else ". "
    return f"{nombre}{separador}{descripcion}"


# ── Fusión de pasos del video (ADR-013) ──────────────────────────────────────────────────────

# De la evidencia más sólida a la más débil: el paso fusionado se queda con la más débil.
_ORDEN_CONFIANZA: dict[Confianza, int] = {"alta": 0, "media": 1, "baja": 2}
_ORDEN_FUENTE: dict[Fuente, int] = {"audio": 0, "visual": 1, "inferido": 2}


def fusionar(
    pasos_sop: Sequence[PasoSOP],
    pasos_video: Sequence[PasoVideo],
    embedder: Embedder,
    *,
    umbral: float | None = None,
) -> tuple[list[PasoVideo], list[Fusion]]:
    """Une los pasos consecutivos del video que caen en el mismo paso del SOP (ADR-013).

    El mejor paso del SOP de cada paso del video es el de mayor coseno (`texto_para_embeber`;
    en empate, el primero). Pasos seguidos en `pasos_video` con el mismo mejor paso del SOP y
    coseno ≥ `umbral` (por defecto `UMBRAL_FUSION`) forman un grupo, que queda en un paso:

    - `t_inicio` y `t_fin`: el menor inicio y el mayor fin de los originales (regla 4: ningún
      tiempo nuevo).
    - `nombre`, `cita` y `responsable`: los del original más parecido al paso del SOP (en
      empate, el primero). La cita es una de las originales, así que sigue apareciendo tal
      cual en la transcripción (regla 4); las demás quedan en el registro.
    - `descripcion`: las de los originales, unidas en orden.
    - `confianza` y `fuente`: la evidencia más débil del grupo.
    - `numero`: posición desde 1 tras la fusión. Un paso sin grupo solo cambia de número.

    Devuelve los pasos fusionados y un `Fusion` por cada uno, con todas las citas originales y,
    si los originales no coinciden en el responsable, la lista de los distintos. `pasos_video`
    debe venir en orden (números crecientes); sin pasos del video no carga el modelo.
    """
    if not pasos_video:
        return [], []
    if not pasos_sop:
        raise ValueError("fusionar necesita al menos un paso del SOP (ADR-013)")
    for a, b in pairwise(pasos_video):
        if b.numero <= a.numero:
            raise ValueError(f"pasos del video fuera de orden: {a.numero} → {b.numero}")
    if umbral is None:
        umbral = get_settings().umbral_fusion

    x = embedder.embed([texto_para_embeber(p) for p in (*pasos_sop, *pasos_video)])
    s = similitud(x[len(pasos_sop) :], x[: len(pasos_sop)])  # video × SOP
    mejor = s.argmax(axis=1)
    coseno = s[np.arange(len(pasos_video)), mejor]

    grupos: list[list[int]] = []
    for i in range(len(pasos_video)):
        anterior = grupos[-1][-1] if grupos else None
        if (
            anterior is not None
            and mejor[i] == mejor[anterior]
            and coseno[i] >= umbral
            and coseno[anterior] >= umbral
        ):
            grupos[-1].append(i)
        else:
            grupos.append([i])

    pasos: list[PasoVideo] = []
    registro: list[Fusion] = []
    for numero, grupo in enumerate(grupos, start=1):
        originales = [pasos_video[i] for i in grupo]
        representante = grupo[int(np.argmax(coseno[grupo]))]
        pasos.append(_unir(originales, pasos_video[representante], numero))
        registro.append(
            Fusion(
                numero=numero,
                originales=[p.numero for p in originales],
                paso_sop=pasos_sop[mejor[representante]].numero,
                citas=[p.cita for p in originales],
                similitudes=[float(coseno[i]) for i in grupo],
                responsables_distintos=_responsables_distintos(originales),
            )
        )
    logger.info(
        "Fusión (umbral %.2f): %d pasos del video → %d", umbral, len(pasos_video), len(pasos)
    )
    return pasos, registro


def _unir(originales: Sequence[PasoVideo], representante: PasoVideo, numero: int) -> PasoVideo:
    """Un paso con los datos de `originales` (ver `fusionar`); con uno solo, lo renumera."""
    if len(originales) == 1:
        return originales[0].model_copy(update={"numero": numero})
    return PasoVideo(
        numero=numero,
        nombre=representante.nombre,
        descripcion=" ".join(d for p in originales if (d := p.descripcion.strip())),
        responsable=representante.responsable,
        t_inicio=min(p.t_inicio for p in originales),
        t_fin=max(p.t_fin for p in originales),
        cita=representante.cita,
        fuente=max((p.fuente for p in originales), key=_ORDEN_FUENTE.__getitem__),
        confianza=max((p.confianza for p in originales), key=_ORDEN_CONFIANZA.__getitem__),
    )


def _responsables_distintos(originales: Sequence[PasoVideo]) -> list[str]:
    """Los responsables de `originales` sin repetir, en orden; vacía si todos coinciden."""
    distintos = list(dict.fromkeys(p.responsable for p in originales))
    return distintos if len(distintos) > 1 else []
