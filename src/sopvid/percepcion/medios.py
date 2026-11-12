"""Etapa 2 del pipeline: duración del video y audio mp3 mono a 16 kHz con ffmpeg; además, los
cuadros del video (miniaturas y fotogramas, RF-11, ADR-024) y si tiene imagen visible.

ffmpeg y ffprobe se llaman con `subprocess` y lista de argumentos, nunca con `shell=True`, y
con un tope de tiempo (`FFMPEG_TIMEOUT_S`). Los errores de `subprocess` no salen de este
módulo: se traducen a `MedioInvalido`, `FfmpegNoDisponible` o `FfmpegTiempoAgotado`, que
heredan de `ErrorMedios`. Con `-v error`, ffmpeg no imprime los metadatos del archivo; los
mensajes solo llevan el nombre del archivo y la última línea de error de ffmpeg.
"""

import json
import logging
import math
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sopvid.plataforma.config import get_settings

logger = logging.getLogger(__name__)

FRECUENCIA_AUDIO_HZ = 16_000
CANALES_AUDIO = 1
BITRATE_AUDIO = "64k"
# Calidad del JPEG de ffmpeg (-q:v, 2 = mejor, 31 = peor): legible y liviano.
CALIDAD_JPEG = 4
# Un cuadro es negro si su luma máxima (`signalstats` YMAX, 0–255) no pasa de aquí. El negro de
# rango limitado es 16; el margen cubre el ruido de compresión de una pantalla negra.
UMBRAL_NEGRO = 40
# Cuadros por llamada a ffmpeg en `extraer_cuadros` (mantiene la línea de comandos corta).
CUADROS_POR_LLAMADA = 20
# Cuadros repartidos en el video para decidir si tiene imagen visible.
MUESTRAS_IMAGEN = 5
_YMAX = re.compile(rb"lavfi\.signalstats\.YMAX=(\d+(?:\.\d+)?)")


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


def tiene_imagen(video: Path, timeout_s: float | None = None) -> bool:
    """True si el archivo tiene una pista de video que no es una portada (`attached_pic`)."""
    info = _sondear(video, timeout_s)
    return any(
        s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
        for s in info.get("streams", [])
    )


def extraer_cuadro(
    video: Path, t: float, destino: Path, lado_px: int, timeout_s: float | None = None
) -> Path:
    """Guarda en `destino` un JPEG del cuadro en el segundo `t`, con el lado mayor de `lado_px`
    (sin agrandar un video más chico), y devuelve `destino`.

    Escribe primero un temporal junto a `destino` que se renombra al terminar: nunca queda un
    JPEG a medias, aunque dos peticiones pidan el mismo cuadro a la vez.
    """
    hechos, resultado = _extraer_lote(video, [(t, destino)], lado_px, timeout_s)
    if not hechos:
        raise MedioInvalido(
            f"{video.name}: ffmpeg no pudo extraer el cuadro en {t:.1f} s "
            f"({_ultima_linea(resultado)})"
        )
    return destino


def extraer_cuadros(
    video: Path,
    pedidos: Sequence[tuple[float, Path]],
    lado_px: int,
    timeout_s: float | None = None,
) -> list[Path]:
    """Como `extraer_cuadro`, pero varios cuadros en una sola llamada a ffmpeg por tanda de
    `CUADROS_POR_LLAMADA`: una entrada con su `-ss` y una salida por cuadro (arrancar ffmpeg
    cuesta más que sacar el cuadro). Devuelve los destinos que sí se escribieron, en el orden
    pedido; uno que ffmpeg no pudo sacar (p. ej. un segundo después del final) simplemente falta.
    """
    hechos: list[Path] = []
    for inicio in range(0, len(pedidos), CUADROS_POR_LLAMADA):
        tanda, _ = _extraer_lote(
            video, pedidos[inicio : inicio + CUADROS_POR_LLAMADA], lado_px, timeout_s
        )
        hechos.extend(tanda)
    return hechos


def _extraer_lote(
    video: Path,
    pedidos: Sequence[tuple[float, Path]],
    lado_px: int,
    timeout_s: float | None,
) -> tuple[list[Path], subprocess.CompletedProcess[bytes]]:
    """Una llamada a ffmpeg para todos los `pedidos`; cada salida va a un temporal que se
    renombra solo si quedó completo (nunca un JPEG a medias, aunque dos peticiones pidan el mismo
    cuadro a la vez)."""
    escala = (
        f"scale='min({lado_px},iw)':'min({lado_px},ih)':force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )
    marca = time.monotonic_ns()
    args = [_binario("ffmpeg"), "-nostdin", "-v", "error", "-y"]
    for t, _ in pedidos:
        args += ["-ss", f"{max(t, 0.0):.3f}", "-i", str(video)]
    temporales = []
    for k, (_, destino) in enumerate(pedidos):
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f"{destino.stem}.{marca}.part")
        temporales.append(temporal)
        args += [
            "-map", f"{k}:v:0", "-frames:v", "1", "-vf", escala, "-q:v", str(CALIDAD_JPEG),
            # El temporal termina en .part: sin -f, ffmpeg no puede inferir el formato.
            "-f", "image2", "-c:v", "mjpeg", str(temporal),
        ]  # fmt: skip
    hechos = []
    try:
        resultado = _ejecutar(args, timeout_s)
        for temporal, (_, destino) in zip(temporales, pedidos, strict=True):
            if temporal.is_file() and temporal.stat().st_size > 0:
                temporal.replace(destino)
                hechos.append(destino)
    finally:
        for temporal in temporales:
            temporal.unlink(missing_ok=True)
    return hechos, resultado


def luma_maxima(video: Path, t: float, timeout_s: float | None = None) -> float | None:
    """Luma máxima (0–255) del cuadro en el segundo `t`, o None si ffmpeg no da ninguno."""
    args = [
        _binario("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-ss",
        f"{max(t, 0.0):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-an",
        "-vf",
        "scale=64:-2,signalstats,metadata=mode=print:key=lavfi.signalstats.YMAX:file=-",
        "-f",
        "null",
        "-",
    ]
    resultado = _ejecutar(args, timeout_s)
    valores = [float(v) for v in _YMAX.findall(resultado.stdout)]
    return max(valores) if valores else None


def imagen_visible(video: Path, duracion_s: float, timeout_s: float | None = None) -> bool:
    """True si el video tiene pista de imagen y al menos uno de `MUESTRAS_IMAGEN` cuadros
    repartidos de forma pareja no es negro. Sin pista o todo negro (p. ej. una grabación de solo
    voz con fondo negro): False."""
    if not tiene_imagen(video, timeout_s):
        return False
    for k in range(MUESTRAS_IMAGEN):
        t = (k + 0.5) * duracion_s / MUESTRAS_IMAGEN
        luma = luma_maxima(video, t, timeout_s)
        if luma is not None and luma > UMBRAL_NEGRO:
            return True
    return False


def _sondear(video: Path, timeout_s: float | None) -> dict[str, Any]:
    """Formato y pistas del archivo según ffprobe (JSON)."""
    if not video.is_file():
        raise MedioInvalido(f"{video.name}: el archivo no existe")
    args = [
        _binario("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type:stream_disposition=attached_pic",
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
