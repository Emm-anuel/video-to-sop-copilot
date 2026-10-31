"""Cola de análisis de videos y paso del `Analisis` a la fila de `videos`.

Un solo trabajador (`ThreadPoolExecutor(max_workers=1)`): un modelo en GPU a la vez (ADR-014).
Cada trabajo corre `analizar_video` con su propia sesión y va actualizando `proceso`, `etapa` y
`progreso`; al terminar guarda el `Analisis` en las columnas (`guardar_analisis`).

Si el video se subió con `modo="validar"` y su SOP, el mismo trabajo sigue con la validación
(`plataforma.validacion`): pasos del video, emparejamiento y reporte. El análisis se confirma
antes de empezar para que un fallo de la validación no borre una transcripción de varios minutos;
en ese caso el video queda en `proceso="error"` con `etapa="validacion"`, porque lo que se pidió
(el reporte) no existe. `etapa="validacion"` y `progreso` 95 cubren esa segunda mitad: el
detalle por paso llega en S5.

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
from sopvid.plataforma.modelos import MODOS_VIDEO, PROCESOS_VIDEO, Video

logger = logging.getLogger(__name__)

# Fábrica de sesiones: `sessionmaker` en producción; en pruebas, la sesión de la prueba.
FabricaSesiones = Callable[[], AbstractContextManager[Session]]
# Trabajo de validación: recibe la sesión y el video y guarda el reporte (`validacion.py`).
Validador = Callable[[Session, Video], Any]

# Los cuatro valores de `videos.proceso` (CHECK de modelos.py), en su orden.
EN_COLA, PROCESANDO, LISTO, ERROR = PROCESOS_VIDEO
# Los dos valores de `videos.modo`; solo `validar` sigue con la validación.
VALIDAR, GENERAR = MODOS_VIDEO
# Etapa de la segunda mitad del trabajo (la primera la informa `analizar_video`).
VALIDACION = "validacion"
PROGRESO_VALIDACION = 95
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
    """Encola análisis de videos. `ejecutar` recibe cada trabajo como función sin argumentos.

    `validador` reemplaza a `validacion.validar_y_guardar` (pruebas): el trabajo lo llama con la
    sesión del hilo y el video, después del análisis, cuando el video es de `modo="validar"`.
    """

    def __init__(
        self,
        sesiones: FabricaSesiones,
        media: Path,
        ejecutar: Callable[[Callable[[], None]], Any],
        executor: ThreadPoolExecutor | None = None,
        validador: Validador | None = None,
    ):
        self._sesiones = sesiones
        self._media = media
        self._ejecutar = ejecutar
        self._executor = executor
        self._validador = validador

    @classmethod
    def con_hilo(
        cls,
        sesiones: FabricaSesiones,
        media: Path,
        validador: Validador | None = None,
    ) -> "Procesador":
        """Procesador de producción: un hilo trabajador (un modelo en GPU a la vez)."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analisis")
        return cls(sesiones, media, executor.submit, executor, validador)

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
        # El análisis se confirma antes de la validación: si la validación falla, la
        # transcripción (minutos de GPU) no se pierde.
        session.commit()
        if (
            video.modo == VALIDAR
            and video.sop_id is not None
            and not self._validar(session, video_id)
        ):
            return
        video.proceso, video.etapa, video.progreso, video.error = LISTO, LISTO, 100, None
        session.commit()
        logger.info(
            "Video %d listo: %.1f s, %d segmentos",
            video_id,
            analisis.duracion_s,
            len(analisis.transcripcion),
        )

    def _validar(self, session: Session, video_id: int) -> bool:
        """Valida el video contra su SOP; si falla, lo deja en error y devuelve `False`."""
        video = session.get(Video, video_id)
        video.etapa, video.progreso = VALIDACION, PROGRESO_VALIDACION
        session.commit()
        validador = self._validador or _validador_por_defecto()
        try:
            validador(session, video)
        except Exception as exc:  # el mensaje no lleva texto del video: solo el tipo
            self._fallar(session, video_id, f"falló la etapa {VALIDACION} ({type(exc).__name__})")
            return False
        return True

    @staticmethod
    def _fallar(session: Session, video_id: int, mensaje: str) -> None:
        session.rollback()
        video = session.get(Video, video_id)
        video.proceso, video.error = ERROR, mensaje
        session.commit()
        logger.error("Video %d: %s", video_id, mensaje)


def _validador_por_defecto() -> Validador:
    """`validacion.validar_y_guardar`, importado aquí para no cerrar el ciclo entre los dos.

    `validacion` importa `leer_analisis` de este módulo, así que la importación va dentro de la
    función y no en la cabecera.
    """
    from sopvid.plataforma.validacion import validar_y_guardar

    return validar_y_guardar
