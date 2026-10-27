"""Pipeline de video, etapas 2 y 3: duración → audio → transcripción → `Analisis` del contrato.

`analizar_video` deja en `trabajo_dir` el audio (`audio.mp3`) y el TXT de la transcripción, que
se escribe mientras avanza (RF-10), y devuelve el `Analisis` ya validado, con la transcripción
re-cortada por frases y pausas (`resegmentar`). Los fotogramas (RF-11) llegan en S5; por
ahora la lista va vacía.

El transcriptor se inyecta (RNF-14): este módulo no crea modelos. `al_avanzar(etapa, porcentaje)`
recibe el avance global, de 0 a 100 y sin retrocesos, para guardarlo después en la tabla
`videos`. Los logs solo llevan tiempos y conteos, nunca texto transcrito.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sopvid.contrato import Analisis, Segmento
from sopvid.percepcion.medios import duracion, extraer_audio
from sopvid.percepcion.transcripcion import (
    DECIMALES,
    Transcriptor,
    escritor_txt,
    resegmentar,
)

logger = logging.getLogger(__name__)

ARCHIVO_AUDIO = "audio.mp3"
ARCHIVO_TXT = "transcripcion.txt"

# Etapa en curso y porcentaje global con el que empieza. La transcripción avanza de 15 a 95
# según el fin del último segmento escrito; "listo" (100) solo llega con el `Analisis` validado.
INICIO_ETAPA = {"duracion": 0, "audio": 5, "transcripcion": 15, "listo": 100}
FIN_TRANSCRIPCION = 95

AlAvanzar = Callable[[str, int], None]


def analizar_video(
    video: Path,
    video_id: int,
    idioma: str | None,
    transcriptor: Transcriptor,
    trabajo_dir: Path,
    al_avanzar: AlAvanzar | None = None,
) -> Analisis:
    """Analiza `video` y devuelve su `Analisis` (sin fotogramas), validado contra el contrato.

    Con `idioma` (ISO 639-1) la transcripción lo fuerza y queda fijado a mano. `duracion_s` va
    en milisegundos, y los tiempos que Whisper deja más allá del final del video se recortan a
    ella antes de validar.
    Errores: `MedioInvalido` y demás de `ErrorMedios`, los del transcriptor, y
    `pydantic.ValidationError` si la transcripción no cumple el contrato.
    """
    avance = _Avance(al_avanzar)
    inicio = time.perf_counter()

    avance.etapa("duracion")
    # En milisegundos, como los tiempos de la transcripción; el recorte usa este valor.
    duracion_s = round(duracion(video), DECIMALES)

    avance.etapa("audio")
    audio = extraer_audio(video, trabajo_dir / ARCHIVO_AUDIO)

    avance.etapa("transcripcion")
    rango = FIN_TRANSCRIPCION - INICIO_ETAPA["transcripcion"]
    with escritor_txt(trabajo_dir / ARCHIVO_TXT) as escribir:

        def al_segmento(segmento: Segmento) -> None:
            escribir(segmento)
            fraccion = min(segmento.t_fin / duracion_s, 1.0)
            avance.informar("transcripcion", INICIO_ETAPA["transcripcion"] + int(rango * fraccion))

        transcripcion = transcriptor.transcribir(audio, idioma, al_segmento=al_segmento)

    # Frases y pausas en vez de las ventanas de Whisper (ver `resegmentar`); el TXT en vivo
    # conserva los segmentos tal como salieron.
    segmentos = [s.model_dump() for s in resegmentar(transcripcion.segmentos)]
    recortados = _recortar_a_duracion(segmentos, duracion_s)
    analisis = Analisis.model_validate(
        {
            "video_id": video_id,
            "duracion_s": duracion_s,
            "idioma": transcripcion.idioma.model_dump(),
            "transcripcion": segmentos,
            "fotogramas": [],
        }
    )
    logger.info(
        "Análisis del video %d: %.1f s de video, %d segmentos (%d recortados a la duración) "
        "en %.1f s",
        video_id,
        duracion_s,
        len(segmentos),
        recortados,
        time.perf_counter() - inicio,
    )
    avance.etapa("listo")
    return analisis


def _recortar_a_duracion(segmentos: list[dict[str, Any]], duracion_s: float) -> int:
    """Recorta a `duracion_s` los tiempos de segmentos y palabras; devuelve cuántos segmentos tocó.

    El mismo tope para todos conserva el orden y la ausencia de solapes. También se recorta el
    inicio del segmento: si empezara después del final, recortar solo el fin dejaría fin < inicio.
    """
    recortados = 0
    for segmento in segmentos:
        tocado = segmento["t_fin"] > duracion_s
        segmento["t_inicio"] = min(segmento["t_inicio"], duracion_s)
        segmento["t_fin"] = min(segmento["t_fin"], duracion_s)
        for palabra in segmento["palabras"]:
            tocado = tocado or palabra["t_fin"] > duracion_s
            palabra["t"] = min(palabra["t"], duracion_s)
            palabra["t_fin"] = min(palabra["t_fin"], duracion_s)
        recortados += tocado
    return recortados


class _Avance:
    """Informa `(etapa, porcentaje)` solo cuando cambia y sin retroceder."""

    def __init__(self, al_avanzar: AlAvanzar | None):
        self._al_avanzar = al_avanzar
        self._ultimo: tuple[str, int] | None = None

    def etapa(self, nombre: str) -> None:
        self.informar(nombre, INICIO_ETAPA[nombre])

    def informar(self, etapa: str, porcentaje: int) -> None:
        if self._ultimo is not None:
            porcentaje = max(porcentaje, self._ultimo[1])
        if (etapa, porcentaje) == self._ultimo:
            return
        self._ultimo = (etapa, porcentaje)
        logger.debug("Avance: %s %d %%", etapa, porcentaje)
        if self._al_avanzar is not None:
            self._al_avanzar(etapa, porcentaje)
