"""Cola de análisis de videos y paso del `Analisis` a la fila de `videos`.

Un solo trabajador (`ThreadPoolExecutor(max_workers=1)`): un modelo en GPU a la vez (ADR-014).
Cada trabajo corre `analizar_video` con su propia sesión y va actualizando `proceso`, `etapa` y
`progreso`; al terminar guarda el `Analisis` en las columnas (`guardar_analisis`).

Cómo se guarda el `Analisis` (sin migración): `duracion`, `idioma` (código) y `fotogramas` en
sus columnas, y en `transcripcion` (JSONB) un dict con la versión del contrato, el idioma
completo (código, confianza y si se fijó a mano) y los segmentos. `leer_analisis` lo rearma.

En modo validar (con `sop_id`), tras guardar el `Analisis` y hacer commit sigue la validación
(`sopvid.lenguaje.validacion.validar`: pasos del video → emparejamiento con el juez → porcentaje)
y se guardan el `Reporte` y `videos.pasos_video`. El avance del análisis se escala a 0–45 y la
validación sigue de 45 a 100 sin retroceder; `proceso="listo"` llega junto con el reporte. Si
Ollama no responde al empezar la validación, el video queda en error con el análisis guardado, y
`revalidar` repite solo la validación, sin Whisper (ADR-017). Un reporte nuevo reemplaza al
anterior.

Un error deja `proceso="error"` y un mensaje sin texto del video: el de `ErrorMedios` (solo
nombra el archivo y la causa) o la etapa y el tipo de excepción. Nunca `str(exc)` de otros
errores: un `ValidationError` de pydantic incluye el texto transcrito.
"""

import logging
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from sopvid.contrato import SOP, Analisis
from sopvid.lenguaje.llm import LLMNoDisponible
from sopvid.lenguaje.validacion import INICIO_ETAPA, FabricaValidacion, Validacion, validar
from sopvid.percepcion.medios import ErrorMedios
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.transcripcion import Transcriptor
from sopvid.plataforma.modelos import PROCESOS_VIDEO, Reporte, Video

logger = logging.getLogger(__name__)

# Fábrica de sesiones: `sessionmaker` en producción; en pruebas, la sesión de la prueba.
FabricaSesiones = Callable[[], AbstractContextManager[Session]]

# Los cuatro valores de `videos.proceso` (CHECK de modelos.py), en su orden.
EN_COLA, PROCESANDO, LISTO, ERROR = PROCESOS_VIDEO
ERROR_REINICIO = "interrumpido por reinicio"
ERROR_LLM = (
    "LLM no disponible: el análisis quedó guardado; repite la validación con "
    "POST /videos/{id}/validar cuando Ollama responda"
)
ERROR_SIN_SOP = "el video es de modo validar y no tiene SOP de referencia"
# En modo validar el análisis llega hasta aquí; la validación sigue hasta 100.
FIN_ANALISIS_VALIDAR = INICIO_ETAPA["segmentacion"]


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


def guardar_reporte(session: Session, video: Video, validacion: Validacion) -> None:
    """Guarda el reporte, que reemplaza al anterior, y los pasos del video (no hace commit).

    `cumplimiento` se guarda a dos decimales; el valor sin redondear y el semáforo calculado con
    él van en `resultado`.
    """
    assert video.sop_id is not None
    session.execute(delete(Reporte).where(Reporte.video_id == video.id))
    session.expire(video, ["reporte"])
    guardado = validacion.resultado
    session.add(
        Reporte(
            video_id=video.id,
            sop_id=video.sop_id,
            afinidad=None,  # RF-17, post-MVP
            cumplimiento=Decimal(f"{guardado.cumplimiento:.2f}"),
            resultado=guardado.model_dump(mode="json"),
        )
    )
    video.pasos_video = [p.model_dump(mode="json") for p in validacion.pasos_video]


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

    def encolar(
        self,
        video_id: int,
        idioma: str | None,
        transcriptor: Transcriptor,
        validacion: FabricaValidacion | None = None,
    ) -> None:
        """Encola el análisis; con `validacion` (modo validar), también la validación."""
        self._ejecutar(lambda: self.procesar(video_id, idioma, transcriptor, validacion))

    def revalidar(self, video_id: int, validacion: FabricaValidacion) -> None:
        """Encola solo la validación, sobre el análisis ya guardado (ADR-017)."""
        self._ejecutar(lambda: self.procesar_validacion(video_id, validacion))

    def cerrar(self) -> None:
        """Apaga el hilo sin esperar: los trabajos pendientes se marcan al volver a arrancar."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def procesar(
        self,
        video_id: int,
        idioma: str | None,
        transcriptor: Transcriptor,
        validacion: FabricaValidacion | None = None,
    ) -> None:
        """Analiza (y valida) el video y guarda el resultado; nunca deja escapar una excepción."""
        try:
            with self._sesiones() as session:
                self._procesar(session, video_id, idioma, transcriptor, validacion)
        except Exception as exc:  # el hilo no tiene a quién avisar: se registra y sigue
            logger.error(
                "Video %d: no se pudo registrar el resultado (%s)", video_id, type(exc).__name__
            )

    def procesar_validacion(self, video_id: int, validacion: FabricaValidacion) -> None:
        """Valida con el análisis guardado; nunca deja escapar una excepción."""
        try:
            with self._sesiones() as session:
                self._revalidar(session, video_id, validacion)
        except Exception as exc:
            logger.error(
                "Video %d: no se pudo registrar la validación (%s)", video_id, type(exc).__name__
            )

    def _procesar(
        self,
        session: Session,
        video_id: int,
        idioma: str | None,
        transcriptor: Transcriptor,
        validacion: FabricaValidacion | None,
    ) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        video.proceso, video.etapa, video.progreso, video.error = PROCESANDO, None, 0, None
        session.commit()
        valida = video.modo == "validar"
        if valida and (video.sop_id is None or validacion is None):
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        archivo = self._media / video.archivo
        fin = FIN_ANALISIS_VALIDAR if valida else 100
        cronometro = _Cronometro()

        def al_avanzar(etapa: str, porcentaje: int) -> None:
            cronometro.marcar(etapa)
            if etapa == "listo":  # se guarda junto con el resultado
                if not valida:
                    video.etapa, video.progreso = etapa, porcentaje
                return
            video.etapa, video.progreso = etapa, porcentaje * fin // 100
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
        if not valida:
            video.proceso, video.error = LISTO, None
            session.commit()
            logger.info(
                "Video %d listo: %.1f s, %d segmentos",
                video_id,
                analisis.duracion_s,
                len(analisis.transcripcion),
            )
            return
        session.commit()  # el análisis queda guardado aunque falle la validación (ADR-017)
        assert validacion is not None
        self._validar(session, video, analisis, validacion, cronometro.segundos())

    def _revalidar(self, session: Session, video_id: int, validacion: FabricaValidacion) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        video.proceso, video.error = PROCESANDO, None
        video.etapa, video.progreso = "segmentacion", FIN_ANALISIS_VALIDAR
        session.commit()
        if video.sop_id is None:
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        try:
            analisis = leer_analisis(video)
        except Exception as exc:
            self._fallar(session, video_id, f"no se pudo leer el análisis ({type(exc).__name__})")
            return
        self._validar(session, video, analisis, validacion, {})

    def _validar(
        self,
        session: Session,
        video: Video,
        analisis: Analisis,
        fabrica: FabricaValidacion,
        segundos_analisis: Mapping[str, float],
    ) -> None:
        """Valida, guarda el reporte y deja el video listo; si algo falla, en error."""
        video_id = video.id

        def al_avanzar(etapa: str, porcentaje: int) -> None:
            video.etapa, video.progreso = etapa, porcentaje
            session.commit()

        deps = None
        try:
            deps = fabrica()
            assert video.sop is not None
            sop = SOP.model_validate(video.sop.contenido)
            validacion = validar(
                analisis, sop, deps, al_avanzar=al_avanzar, segundos_analisis=segundos_analisis
            )
        except LLMNoDisponible:
            self._fallar(session, video_id, ERROR_LLM.format(id=video_id))
            return
        except Exception as exc:
            session.rollback()
            etapa = session.get(Video, video_id).etapa or "segmentacion"
            self._fallar(session, video_id, f"falló la etapa {etapa} ({type(exc).__name__})")
            return
        finally:
            if deps is not None:
                deps.cerrar()
        guardar_reporte(session, video, validacion)
        video.etapa, video.progreso = "listo", 100
        video.proceso, video.error = LISTO, None
        session.commit()
        logger.info(
            "Video %d listo con reporte: %.1f %% (%s)",
            video_id,
            validacion.resultado.cumplimiento,
            validacion.resultado.semaforo,
        )

    @staticmethod
    def _fallar(session: Session, video_id: int, mensaje: str) -> None:
        session.rollback()
        video = session.get(Video, video_id)
        video.proceso, video.error = ERROR, mensaje
        session.commit()
        logger.error("Video %d: %s", video_id, mensaje)


class _Cronometro:
    """Segundos de cada etapa del análisis: desde que empieza hasta que empieza la siguiente."""

    def __init__(self, reloj: Callable[[], float] = time.perf_counter):
        self._reloj = reloj
        self._marcas: list[tuple[str, float]] = []

    def marcar(self, etapa: str) -> None:
        if not self._marcas or self._marcas[-1][0] != etapa:
            self._marcas.append((etapa, self._reloj()))

    def segundos(self) -> dict[str, float]:
        return {
            etapa: round(fin - inicio, 2) for (etapa, inicio), (_, fin) in pairwise(self._marcas)
        }
