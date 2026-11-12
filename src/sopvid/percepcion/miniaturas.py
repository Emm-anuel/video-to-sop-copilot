"""Miniatura por paso (RF-11, ADR-024): un JPEG del video en un segundo, con ffmpeg y sin modelo.

Se sacan siempre, al terminar la validación (una por fila del reporte con segundo) o la generación
(una por paso del SOP generado, en su inicio), y la pantalla las pide por segundo con
`GET /videos/{id}/thumb?t=` (sin cambios de contrato: ni `FilaReporte` ni `PasoSOP` las nombran).

Viven en `media/videos/<id>/miniaturas/`, nunca en el repositorio, con el segundo en milisegundos
en el nombre (`t000012500.jpg` es 12.5 s). Una petición reusa la guardada más cercana si está a
`TOLERANCIA_S` o menos (RNF-03); si no, la genera y la deja en la carpeta como caché.

Un video sin pista de imagen o negro (p. ej. una grabación de solo voz) no tiene miniaturas: la
carpeta lleva la marca `SIN_IMAGEN`, el endpoint responde 404 sin volver a llamar a ffmpeg, y el
reporte (o el SOP generado) lleva el aviso informativo "sin_imagen", que no lo vuelve provisional.
"""

import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sopvid.contrato import Aviso
from sopvid.percepcion.medios import ErrorMedios, extraer_cuadro, extraer_cuadros, imagen_visible

logger = logging.getLogger(__name__)

CARPETA = "miniaturas"
MARCA_SIN_IMAGEN = "SIN_IMAGEN"
# Una miniatura guardada sirve para cualquier segundo a esta distancia o menos (RNF-03).
TOLERANCIA_S = 1.0
# Antes del final: con -ss en el último instante, ffmpeg puede no dar ningún cuadro.
MARGEN_FINAL_S = 0.1
_NOMBRE = re.compile(r"^t(\d{9})\.jpg$")


def carpeta_miniaturas(carpeta_video: Path) -> Path:
    """`media/videos/<id>/miniaturas/` a partir de la carpeta del video."""
    return carpeta_video / CARPETA


def nombre_miniatura(t: float) -> str:
    """El archivo de la miniatura del segundo `t`: el segundo en milisegundos, con ceros."""
    return f"t{round(max(t, 0.0) * 1000):09d}.jpg"


def sin_imagen_marcado(carpeta: Path) -> bool:
    return (carpeta / MARCA_SIN_IMAGEN).is_file()


def marcar_sin_imagen(carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / MARCA_SIN_IMAGEN).write_text("", encoding="utf-8")


def buscar(carpeta: Path, t: float, tolerancia_s: float = TOLERANCIA_S) -> Path | None:
    """La miniatura guardada más cercana a `t`, si está a `tolerancia_s` o menos; si no, None."""
    if not carpeta.is_dir():
        return None
    mejor: tuple[float, Path] | None = None
    for archivo in carpeta.iterdir():
        coincide = _NOMBRE.match(archivo.name)
        if coincide is None:
            continue
        distancia = abs(int(coincide.group(1)) / 1000 - t)
        if distancia <= tolerancia_s and (mejor is None or distancia < mejor[0]):
            mejor = (distancia, archivo)
    return None if mejor is None else mejor[1]


def asegurar(
    video: Path,
    carpeta: Path,
    t: float,
    duracion_s: float,
    lado_px: int,
    tolerancia_s: float = TOLERANCIA_S,
) -> Path:
    """La miniatura de `t`: la guardada a `tolerancia_s` o menos o una nueva, que queda en la
    carpeta. El endpoint usa la tolerancia de RNF-03; las del reporte, 0 (una por fila, en su `t`).

    Errores: los de `ErrorMedios` si ffmpeg no puede sacar el cuadro.
    """
    if (guardada := buscar(carpeta, t, tolerancia_s)) is not None:
        return guardada
    t_cuadro = min(max(t, 0.0), max(duracion_s - MARGEN_FINAL_S, 0.0))
    return extraer_cuadro(video, t_cuadro, carpeta / nombre_miniatura(t), lado_px)


@dataclass
class ResultadoMiniaturas:
    """Las miniaturas de un reporte o de un SOP generado. `fallidas` cuenta los segundos en que
    ffmpeg no pudo sacar el cuadro (el resultado se guarda igual)."""

    sin_imagen: bool = False
    archivos: list[Path] = field(default_factory=list)
    fallidas: int = 0
    segundos: float = 0.0


def generar_miniaturas(
    video: Path,
    carpeta: Path,
    tiempos: Iterable[float],
    duracion_s: float,
    lado_px: int,
) -> ResultadoMiniaturas:
    """Una miniatura por segundo de `tiempos`, cada una en su segundo exacto (se reusa solo la
    que ya está con el mismo nombre, p. ej. al repetir la validación).

    Sin imagen visible, marca la carpeta y no genera nada. Nunca lanza: un error de ffmpeg al
    revisar la imagen cuenta como sin imagen (se registra), y uno al sacar un cuadro solo suma a
    `fallidas`.
    """
    inicio = time.perf_counter()
    resultado = ResultadoMiniaturas()
    try:
        visible = imagen_visible(video, duracion_s)
    except ErrorMedios as exc:
        logger.warning("Miniaturas de %s: no se pudo revisar la imagen (%s)", video.name, exc)
        visible = False
    if not visible:
        marcar_sin_imagen(carpeta)
        resultado.sin_imagen = True
    else:
        faltan: list[tuple[float, Path]] = []
        for t in sorted(set(round(t, 3) for t in tiempos)):
            if (guardada := buscar(carpeta, t, 0.0)) is not None:
                resultado.archivos.append(guardada)
            else:
                t_cuadro = min(max(t, 0.0), max(duracion_s - MARGEN_FINAL_S, 0.0))
                faltan.append((t_cuadro, carpeta / nombre_miniatura(t)))
        if faltan:
            # Una sola llamada a ffmpeg para todas las que faltan (arrancarlo cuesta más que
            # sacar un cuadro).
            try:
                hechas = extraer_cuadros(video, faltan, lado_px)
            except ErrorMedios as exc:
                logger.warning("Miniaturas de %s: %s", video.name, exc)
                hechas = []
            resultado.archivos.extend(hechas)
            resultado.fallidas = len(faltan) - len(hechas)
    resultado.segundos = round(time.perf_counter() - inicio, 2)
    logger.info(
        "Miniaturas de %s: %s, %d archivos, %d fallidas, %.1f s",
        video.name,
        "sin imagen" if resultado.sin_imagen else "con imagen",
        len(resultado.archivos),
        resultado.fallidas,
        resultado.segundos,
    )
    return resultado


def aviso_sin_imagen() -> Aviso:
    """El aviso informativo: no es una falla y no vuelve provisional el reporte (ADR-024)."""
    return Aviso(
        tipo="sin_imagen",
        detalle="el video no tiene imagen visible (sin pista de video o negra): sin miniaturas",
    )
