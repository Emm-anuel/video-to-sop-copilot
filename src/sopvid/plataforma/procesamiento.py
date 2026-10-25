"""Cola de análisis de videos y paso del `Analisis` a la fila de `videos`.

Un solo trabajador (`ThreadPoolExecutor(max_workers=1)`): un modelo en GPU a la vez (ADR-014).
Cada trabajo corre `analizar_video` con su propia sesión y va actualizando `proceso`, `etapa` y
`progreso`; al terminar guarda el `Analisis` en las columnas (`guardar_analisis`).

Cómo se guarda el `Analisis` (sin migración): `duracion`, `idioma` (código) y `fotogramas` en
sus columnas, y en `transcripcion` (JSONB) un dict con la versión del contrato, el idioma
completo (código, confianza y si se fijó a mano) y los segmentos. `leer_analisis` lo rearma.

Un error deja `proceso="error"` y un mensaje sin texto del video: el de `ErrorMedios` (solo
nombra el archivo y la causa) o la etapa y el tipo de excepción. Nunca `str(exc)` de otros
errores: un `ValidationError` de pydantic incluye el texto transcrito.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from sopvid.contrato import Analisis
from sopvid.percepcion.medios import ErrorMedios
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.transcripcion import Transcriptor
from sopvid.plataforma.modelos import PROCESOS_VIDEO, Video

logger = logging.getLogger(__name__)

# Fábrica de sesiones: `sessionmaker` en producción; en pruebas, la sesión de la prueba.
FabricaSesiones = Callable[[], AbstractContextManager[Session]]

# Los cuatro valores de `videos.proceso` (CHECK de modelos.py), en su orden.
EN_COLA, PROCESANDO, LISTO, ERROR = PROCESOS_VIDEO
ERROR_REINICIO = "interrumpido por reinicio"


def guardar_analisis(video: Video, analisis: Analisis) -> None:
    """Copia el `Analisis` a las columnas de `video` (no hace commit)."""
    video.duracion = analisis.duracion_s
    video.idioma = analisis.idioma.codigo
    video.transcripcion = {
        "version_contrato": analisis.version_contrato,
        "idioma": analisis.idioma.model_dump(mode="json"),
        "segmentos": [s.model_dump(mode="json") for s in analisis.transcripcion],
    }
    video.fotogramas = [f.model_dump(mode="json") for f in analisis.fotogramas]


def leer_analisis(video: Video) -> Analisis:
    """Rearma y valida el `Analisis` guardado con `guardar_analisis`."""
    datos: dict[str, Any] = video.transcripcion or {}
    return Analisis.model_validate(
        {
            "version_contrato": datos.get("version_contrato"),
            "video_id": video.id,
            "duracion_s": video.duracion,
            "idioma": datos.get("idioma"),
            "transcripcion": datos.get("segmentos"),
            "fotogramas": video.fotogramas or [],
        }
    )


def marcar_interrumpidos(session: Session) -> int:
    """Pasa a error los videos que quedaron en cola o procesando (la cola vive en memoria)."""
    resultado = session.execute(
        update(Video)
        .where(Video.proceso.in_((EN_COLA, PROCESANDO)))
        .values(proceso=ERROR, error=ERROR_REINICIO)
    )
    session.commit()
    if resultado.rowcount:
        logger.warning(
            "Videos interrumpidos por el reinicio, ahora en error: %d", resultado.rowcount
        )
    return resultado.rowcount


class Procesador:
    """Encola análisis de videos. `ejecutar` recibe cada trabajo como función sin argumentos."""

    def __init__(
        self,
        sesiones: FabricaSesiones,
        media: Path,
        ejecutar: Callable[[Callable[[], None]], Any],
        executor: ThreadPoolExecutor | None = None,
    ):
        self._sesiones = sesiones
        self._media = media
        self._ejecutar = ejecutar
        self._executor = executor

    @classmethod
    def con_hilo(cls, sesiones: FabricaSesiones, media: Path) -> "Procesador":
        """Procesador de producción: un hilo trabajador (un modelo en GPU a la vez)."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analisis")
        return cls(sesiones, media, executor.submit, executor)

    def encolar(self, video_id: int, idioma: str | None, transcriptor: Transcriptor) -> None:
        self._ejecutar(lambda: self.procesar(video_id, idioma, transcriptor))

    def cerrar(self) -> None:
        """Apaga el hilo sin esperar: los trabajos pendientes se marcan al volver a arrancar."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def procesar(self, video_id: int, idioma: str | None, transcriptor: Transcriptor) -> None:
        """Analiza el video y guarda el resultado; nunca deja escapar una excepción."""
        try:
            with self._sesiones() as session:
                self._procesar(session, video_id, idioma, transcriptor)
        except Exception as exc:  # el hilo no tiene a quién avisar: se registra y sigue
            logger.error(
                "Video %d: no se pudo registrar el resultado (%s)", video_id, type(exc).__name__
            )

    def _procesar(
        self, session: Session, video_id: int, idioma: str | None, transcriptor: Transcriptor
    ) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        video.proceso, video.etapa, video.progreso, video.error = PROCESANDO, None, 0, None
        session.commit()
        archivo = self._media / video.archivo

        def al_avanzar(etapa: str, porcentaje: int) -> None:
            video.etapa, video.progreso = etapa, porcentaje
            if etapa != "listo":  # "listo" se guarda junto con el resultado
                session.commit()

        try:
            analisis = analizar_video(
                archivo, video_id, idioma, transcriptor, archivo.parent, al_avanzar
            )
        except ErrorMedios as exc:
            self._fallar(session, video_id, str(exc))
            return
        except Exception as exc:
            session.rollback()
            etapa = session.get(Video, video_id).etapa or "inicio"
            self._fallar(session, video_id, f"falló la etapa {etapa} ({type(exc).__name__})")
            return
        guardar_analisis(video, analisis)
        video.proceso, video.error = LISTO, None
        session.commit()
        logger.info(
            "Video %d listo: %.1f s, %d segmentos",
            video_id,
            analisis.duracion_s,
            len(analisis.transcripcion),
        )

    @staticmethod
    def _fallar(session: Session, video_id: int, mensaje: str) -> None:
        session.rollback()
        video = session.get(Video, video_id)
        video.proceso, video.error = ERROR, mensaje
        session.commit()
        logger.error("Video %d: %s", video_id, mensaje)
