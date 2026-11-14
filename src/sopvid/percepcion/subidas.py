"""Subida del video por partes (RF-06): el archivo se arma en disco parte por parte.

Cada subida vive en `media/subidas/<upload_id>/`, nunca en la base (no hay tabla: los bytes
recibidos son el estado):

- `meta.json`: extensión, tamaño declarado, tamaño de parte y fecha. Nunca el nombre original.
- `datos`: lo armado hasta ahora; `recibidos` es su tamaño.
- `parte-<uuid>.tmp`: el cuerpo de una petición que todavía llega; se anexa a `datos` solo si
  llegó entero, así que un corte a mitad de una parte no deja bytes sueltos.

Las partes se anexan en orden. Una parte en el offset siguiente se anexa; una que empieza en un
offset ya recibido no reescribe nada (si se extiende más allá, solo se anexa la cola), de modo que
repetir una parte no duplica ni corrompe. Un offset adelantado es `OffsetInesperado` con el offset
correcto. Un candado por subida serializa el armado y el consumo (la API es un solo proceso).

`reservada` entrega el archivo completo con el candado tomado para moverlo a `media/videos/<id>/`;
`descartar` borra la carpeta; `limpiar_caducadas` borra las que llevan `horas` sin actividad
(RNF-09).
"""

import json
import logging
import re
import shutil
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CARPETA = "subidas"
ARCHIVO_META = "meta.json"
ARCHIVO_DATOS = "datos"
SUFIJO_PARTE = ".tmp"
BLOQUE = 1024 * 1024
_ID = re.compile(r"^[0-9a-f]{32}$")

_candados: dict[str, threading.Lock] = {}
_candado_registro = threading.Lock()


class ErrorSubida(Exception):  # noqa: N818 (nombres de dominio)
    """Base de los errores de la subida por partes."""


class SubidaNoEncontrada(ErrorSubida):  # noqa: N818
    """El `upload_id` no existe, no es válido o ya se usó (o se canceló, o caducó)."""


class ParteGrande(ErrorSubida):  # noqa: N818
    """La parte pasa del tamaño de parte de la subida."""


class _ConPosicion(ErrorSubida):
    """Lleva lo recibido y el tamaño declarado, para que el cliente se reacomode."""

    def __init__(self, recibidos: int, tamano: int):
        super().__init__(recibidos, tamano)
        self.recibidos = recibidos
        self.tamano = tamano


class OffsetInesperado(_ConPosicion):  # noqa: N818
    """El offset no es el siguiente ni uno ya recibido: el cliente sigue en `recibidos`."""


class PasaDelTamano(_ConPosicion):  # noqa: N818
    """La parte llevaría el archivo más allá del tamaño declarado."""


class SubidaIncompleta(_ConPosicion):  # noqa: N818
    """Faltan bytes para el tamaño declarado."""


@dataclass(frozen=True)
class EstadoSubida:
    upload_id: str
    extension: str
    tamano: int
    tamano_parte: int
    recibidos: int

    @property
    def completo(self) -> bool:
        return self.recibidos == self.tamano


def carpeta_subidas(media: Path) -> Path:
    """`media/subidas/`, donde viven las subidas en curso."""
    return media / CARPETA


def candado(upload_id: str) -> threading.Lock:
    """El candado de la subida (uno por id, creado la primera vez)."""
    with _candado_registro:
        return _candados.setdefault(upload_id, threading.Lock())


def crear(media: Path, extension: str, tamano: int, tamano_parte: int) -> EstadoSubida:
    """Crea la carpeta de una subida nueva con `datos` vacío."""
    if tamano <= 0 or tamano_parte <= 0:
        raise ValueError("tamano y tamano_parte deben ser positivos")
    upload_id = uuid.uuid4().hex
    carpeta = carpeta_subidas(media) / upload_id
    carpeta.mkdir(parents=True)
    meta = {
        "extension": extension,
        "tamano": tamano,
        "tamano_parte": tamano_parte,
        "creado": datetime.now(UTC).isoformat(),
    }
    (carpeta / ARCHIVO_META).write_text(json.dumps(meta), encoding="utf-8")
    (carpeta / ARCHIVO_DATOS).touch()
    return EstadoSubida(upload_id, extension, tamano, tamano_parte, 0)


def estado(media: Path, upload_id: str) -> EstadoSubida:
    """Lo que se ha recibido de la subida; `SubidaNoEncontrada` si no existe."""
    carpeta = _carpeta(media, upload_id)
    try:
        meta = json.loads((carpeta / ARCHIVO_META).read_text(encoding="utf-8"))
        recibidos = (carpeta / ARCHIVO_DATOS).stat().st_size
    except (OSError, ValueError):
        raise SubidaNoEncontrada(upload_id) from None
    return EstadoSubida(
        upload_id, meta["extension"], int(meta["tamano"]), int(meta["tamano_parte"]), recibidos
    )


def temporal_parte(media: Path, upload_id: str) -> Path:
    """Ruta nueva para el cuerpo de una petición, dentro de la carpeta de la subida."""
    return _carpeta(media, upload_id) / f"parte-{uuid.uuid4().hex}{SUFIJO_PARTE}"


def guardar_parte(media: Path, upload_id: str, offset: int, temporal: Path) -> EstadoSubida:
    """Anexa la parte de `temporal` (ya completa) si empieza en `offset`, y devuelve el estado.

    Idempotente: si `offset` ya se había recibido no reescribe nada; si la parte se extiende más
    allá de lo recibido, solo anexa lo que falta. Errores: `SubidaNoEncontrada`, `ParteGrande`,
    `OffsetInesperado` (offset adelantado) y `PasaDelTamano`.
    """
    with candado(upload_id):
        actual = estado(media, upload_id)
        largo = temporal.stat().st_size
        if largo > actual.tamano_parte:
            raise ParteGrande(upload_id)
        if offset > actual.recibidos:
            raise OffsetInesperado(actual.recibidos, actual.tamano)
        if offset + largo > actual.tamano:
            raise PasaDelTamano(actual.recibidos, actual.tamano)
        if offset + largo > actual.recibidos:
            datos = _carpeta(media, upload_id) / ARCHIVO_DATOS
            with temporal.open("rb") as origen, datos.open("ab") as destino:
                origen.seek(actual.recibidos - offset)
                shutil.copyfileobj(origen, destino, BLOQUE)
        return estado(media, upload_id)


@contextmanager
def reservada(media: Path, upload_id: str) -> Iterator[tuple[EstadoSubida, Path]]:
    """El estado y el archivo armado de una subida completa, con su candado tomado.

    `SubidaNoEncontrada` si no existe y `SubidaIncompleta` si faltan bytes. Quien la recibe mueve
    el archivo y llama a `descartar` (con el candado todavía tomado no hay otra parte en vuelo).
    """
    _carpeta(media, upload_id)  # valida el id antes de crear su candado
    with candado(upload_id):
        actual = estado(media, upload_id)
        if not actual.completo:
            raise SubidaIncompleta(actual.recibidos, actual.tamano)
        yield actual, _carpeta(media, upload_id) / ARCHIVO_DATOS


def descartar(media: Path, upload_id: str) -> None:
    """Borra la carpeta de la subida; `SubidaNoEncontrada` si no existe."""
    carpeta = _carpeta(media, upload_id)
    shutil.rmtree(carpeta, ignore_errors=True)
    with _candado_registro:
        _candados.pop(upload_id, None)


def limpiar_caducadas(media: Path, horas: float, ahora: float | None = None) -> int:
    """Borra las subidas sin actividad (escritura en su carpeta) desde hace más de `horas`.

    Se salta una subida cuyo candado está tomado (una parte o un consumo en curso). Devuelve
    cuántas borró.
    """
    raiz = carpeta_subidas(media)
    if not raiz.is_dir():
        return 0
    limite = (time.time() if ahora is None else ahora) - horas * 3600
    borradas = 0
    for carpeta in raiz.iterdir():
        if not carpeta.is_dir() or not _ID.match(carpeta.name):
            continue
        if _ultima_actividad(carpeta) > limite:
            continue
        cerrojo = candado(carpeta.name)
        if not cerrojo.acquire(blocking=False):
            continue
        try:
            shutil.rmtree(carpeta, ignore_errors=True)
            borradas += 1
        finally:
            cerrojo.release()
            with _candado_registro:
                _candados.pop(carpeta.name, None)
    if borradas:
        logger.info("Subidas caducadas borradas: %d (más de %g h sin actividad)", borradas, horas)
    return borradas


def _ultima_actividad(carpeta: Path) -> float:
    marcas = [carpeta.stat().st_mtime]
    for archivo in carpeta.iterdir():
        try:
            marcas.append(archivo.stat().st_mtime)
        except OSError:
            continue
    return max(marcas)


def _carpeta(media: Path, upload_id: str) -> Path:
    if not _ID.match(upload_id):
        raise SubidaNoEncontrada(upload_id)
    carpeta = carpeta_subidas(media) / upload_id
    if not carpeta.is_dir():
        raise SubidaNoEncontrada(upload_id)
    return carpeta
