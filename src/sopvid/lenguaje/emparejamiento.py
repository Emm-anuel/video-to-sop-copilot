"""Emparejamiento de los pasos del SOP con los pasos del video (ADR-012, plan §5.3).

Base de S2: `Embedder`, que vectoriza textos con MiniLM multilingüe
(`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensiones) siempre en CPU para no competir por
la VRAM con faster-whisper ni con Gemma 4, y `similitud`, la matriz de coseno entre dos grupos
de vectores. `texto_para_embeber` arma el mismo texto para un paso del SOP y uno del video. La
fusión (ADR-013), el algoritmo húngaro, los umbrales y el orden llegan en S3.

`sentence_transformers` (y con él torch) se importa al cargar el modelo, no al importar este
módulo, para que la API arranque rápido y las pruebas puedan simular el modelo.
"""

import logging
import time
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from sopvid.contrato import PasoSOP, PasoVideo
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
