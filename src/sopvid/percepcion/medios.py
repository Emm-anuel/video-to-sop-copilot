"""Etapa 2 del pipeline: duración del video y audio mp3 mono a 16 kHz con ffmpeg.

ffmpeg y ffprobe se llaman con `subprocess` y lista de argumentos, nunca con `shell=True`, y
con un tope de tiempo (`FFMPEG_TIMEOUT_S`). Los errores de `subprocess` no salen de este
módulo: se traducen a `MedioInvalido`, `FfmpegNoDisponible` o `FfmpegTiempoAgotado`, que
heredan de `ErrorMedios`. Con `-v error`, ffmpeg no imprime los metadatos del archivo; los
mensajes solo llevan el nombre del archivo y la última línea de error de ffmpeg.
"""

import json
import logging
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from sopvid.plataforma.config import get_settings

logger = logging.getLogger(__name__)

FRECUENCIA_AUDIO_HZ = 16_000
CANALES_AUDIO = 1
BITRATE_AUDIO = "64k"


class ErrorMedios(Exception):  # noqa: N818 (nombres de dominio acordados)
    """Base de los errores al procesar medios con ffmpeg."""


class MedioInvalido(ErrorMedios):  # noqa: N818
    """El archivo no existe, ffmpeg no lo puede leer o no tiene lo que se pide (p. ej. audio)."""


class FfmpegNoDisponible(ErrorMedios):  # noqa: N818
    """`ffmpeg` o `ffprobe` no están instalados o no están en el PATH."""


class FfmpegTiempoAgotado(ErrorMedios):  # noqa: N818
    """ffmpeg o ffprobe no terminaron dentro del tope de tiempo."""


def duracion(video: Path, timeout_s: float | None = None) -> float:
    """Duración del video en segundos, según el contenedor (ffprobe)."""
    info = _sondear(video, timeout_s)
    valor = info.get("format", {}).get("duration")
    try:
        segundos = float(valor)
    except (TypeError, ValueError):
        raise MedioInvalido(f"{video.name}: ffprobe no reporta la duración") from None
    if not math.isfinite(segundos) or segundos <= 0:
        raise MedioInvalido(f"{video.name}: duración no válida ({segundos})")
    return segundos


def extraer_audio(video: Path, destino: Path, timeout_s: float | None = None) -> Path:
    """Extrae el audio de `video` a `destino` en mp3 mono a 16 kHz y devuelve `destino`.

    Crea la carpeta de `destino` si no existe y sobrescribe un archivo previo. ffmpeg escribe
    primero en un temporal junto a `destino` que se renombra al terminar, así que nunca queda
    un mp3 a medias.
    """
    info = _sondear(video, timeout_s)
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise MedioInvalido(f"{video.name}: el video no tiene pista de audio")

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".part")
    args = [
        _binario("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        str(CANALES_AUDIO),
        "-ar",
        str(FRECUENCIA_AUDIO_HZ),
        "-c:a",
        "libmp3lame",
        "-b:a",
        BITRATE_AUDIO,
        # El temporal termina en .part: sin -f, ffmpeg no puede inferir el formato de salida.
        "-f",
        "mp3",
        str(temporal),
    ]
    inicio = time.perf_counter()
    try:
        resultado = _ejecutar(args, timeout_s)
        if resultado.returncode != 0:
            raise MedioInvalido(
                f"{video.name}: ffmpeg no pudo extraer el audio ({_ultima_linea(resultado)})"
            )
        temporal.replace(destino)
    finally:
        temporal.unlink(missing_ok=True)
    logger.info("Audio extraído de %s en %.1f s", video.name, time.perf_counter() - inicio)
    return destino


def _sondear(video: Path, timeout_s: float | None) -> dict[str, Any]:
    """Formato y pistas del archivo según ffprobe (JSON)."""
    if not video.is_file():
        raise MedioInvalido(f"{video.name}: el archivo no existe")
    args = [
        _binario("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(video),
    ]
    resultado = _ejecutar(args, timeout_s)
    if resultado.returncode != 0:
        raise MedioInvalido(f"{video.name}: ffprobe no lo pudo leer ({_ultima_linea(resultado)})")
    try:
        return json.loads(resultado.stdout)
    except json.JSONDecodeError:
        raise MedioInvalido(f"{video.name}: ffprobe devolvió una salida ilegible") from None


def _binario(nombre: str) -> str:
    ruta = shutil.which(nombre)
    if ruta is None:
        raise FfmpegNoDisponible(f"no se encontró '{nombre}' en el PATH; instala ffmpeg")
    return ruta


def _ejecutar(args: list[str], timeout_s: float | None) -> subprocess.CompletedProcess[bytes]:
    tope = timeout_s if timeout_s is not None else get_settings().ffmpeg_timeout_s
    nombre = Path(args[0]).stem
    try:
        return subprocess.run(args, capture_output=True, timeout=tope, check=False)
    except FileNotFoundError:
        raise FfmpegNoDisponible(f"no se pudo ejecutar '{nombre}'; instala ffmpeg") from None
    except subprocess.TimeoutExpired:
        raise FfmpegTiempoAgotado(f"{nombre} no terminó en {tope:g} s") from None


def _ultima_linea(resultado: subprocess.CompletedProcess[bytes]) -> str:
    lineas = resultado.stderr.decode("utf-8", errors="replace").strip().splitlines()
    return lineas[-1] if lineas else f"código {resultado.returncode}"
