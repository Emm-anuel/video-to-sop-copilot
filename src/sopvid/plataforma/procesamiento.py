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
`revalidar` repite solo la validación, sin Whisper (ADR-019). Un reporte nuevo reemplaza al
anterior.

Dónde corrió cada modelo (ADR-018) va en los metadatos del reporte: la GPU que ve la API, el
dispositivo con que transcribió Whisper (se toma de su `Transcripcion`) y, desde la validación,
el de Gemma.

Un error deja `proceso="error"` y un mensaje sin texto del video: el de `ErrorMedios` (solo
nombra el archivo y la causa) o la etapa y el tipo de excepción. Nunca `str(exc)` de otros
errores: un `ValidationError` de pydantic incluye el texto transcrito.

Un modelo pesado a la vez (ADR-014): cada trabajo corre con `CANDADO_MODELO_PESADO`, el mismo
que toma `POST /sops` para convertir un SOP con Gemma. Un SOP adjunto a `POST /videos` (RF-02)
llega como `videos/<id>/sop_adjunto.<ext>` y se convierte aquí, al empezar la validación y
dentro del trabajo, no en la petición: después se guarda como cualquier SOP (`guardar_sop`),
el video queda con su `sop_id` y el adjunto se borra. Si Ollama no responde, el error es el
mismo reprocesable de la validación y `revalidar` vuelve a convertirlo.
"""

import logging
import shutil
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from sopvid.contrato import SOP, Analisis, Dispositivos
from sopvid.lenguaje.lectura_sop import (
    EXTENSIONES,
    ErrorConversionLLM,
    ErrorLectura,
    convertir_documento,
    extraer_texto,
)
from sopvid.lenguaje.llm import ClienteLLM, LLMError, LLMNoDisponible
from sopvid.lenguaje.sop_markdown import ResultadoConversion
from sopvid.lenguaje.validacion import INICIO_ETAPA, FabricaValidacion, Validacion, validar
from sopvid.percepcion.medios import ErrorMedios
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion, Transcriptor
from sopvid.plataforma.config import get_settings
from sopvid.plataforma.hardware import CANDADO_MODELO_PESADO, CandadoModeloPesado, get_hardware
from sopvid.plataforma.modelos import PROCESOS_VIDEO, Reporte, Sop, Video

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
SOP_ADJUNTO = "sop_adjunto"  # nombre del SOP adjunto en la carpeta del video, sin extensión
TITULO_SOP_MAX = 300  # largo de `sops.titulo`
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


@dataclass(frozen=True)
class SopLeido:
    """El archivo original de un SOP y su conversión, listos para `guardar_sop`."""

    datos: bytes
    extension: str
    conversion: ResultadoConversion


def guardar_sop(session: Session, media: Path, leido: SopLeido) -> Sop:
    """Agrega la fila del SOP (sin commit) y escribe el original en
    `media/sops/<id>/original.<ext>`; en la fila va la ruta relativa, nunca el nombre original.

    Si la escritura falla, revierte la sesión y borra la carpeta. Quien llama hace el commit y,
    si algo falla después, borra `carpeta_sop(media, fila.id)`.
    """
    sop = leido.conversion.sop
    fila = Sop(
        titulo=sop.titulo,
        origen="cargado",
        archivo_original="",
        contenido=sop.model_dump(mode="json"),
    )
    session.add(fila)
    session.flush()  # asigna el id
    relativa = PurePosixPath("sops", str(fila.id), f"original{leido.extension}")
    destino = media / relativa
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(leido.datos)
    except BaseException:
        session.rollback()
        shutil.rmtree(destino.parent, ignore_errors=True)
        raise
    fila.archivo_original = str(relativa)
    return fila


def carpeta_sop(media: Path, sop_id: int) -> Path:
    return media / "sops" / str(sop_id)


def ruta_sop_adjunto(video_id: int, extension: str) -> PurePosixPath:
    """Ruta relativa a `media` donde `POST /videos` deja el SOP adjunto por convertir."""
    return PurePosixPath("videos", str(video_id), f"{SOP_ADJUNTO}{extension}")


def sop_adjunto(media: Path, video: Video) -> Path | None:
    """El SOP adjunto que espera conversión en la carpeta del video, si hay uno."""
    for extension in EXTENSIONES:
        ruta = media / ruta_sop_adjunto(video.id, extension)
        if ruta.is_file():
            return ruta
    return None


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
        gpu: Callable[[], str | None] | None = None,
        candado: CandadoModeloPesado = CANDADO_MODELO_PESADO,
    ):
        """`gpu` da el nombre de la GPU para los metadatos (por defecto, la que detecta la API);
        `candado`, el de modelo pesado que comparte con `POST /sops` (ADR-014)."""
        self._candado = candado
        self._sesiones = sesiones
        self._gpu = gpu or _gpu_detectada
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
        """Encola solo la validación, sobre el análisis ya guardado (ADR-019)."""
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
        """Analiza (y valida) el video y guarda el resultado; nunca deja escapar una excepción.

        Todo el trabajo corre con el candado de modelo pesado: espera a que lo suelte una
        conversión de SOP en curso."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
                self._procesar(session, video_id, idioma, transcriptor, validacion)
        except Exception as exc:  # el hilo no tiene a quién avisar: se registra y sigue
            logger.error(
                "Video %d: no se pudo registrar el resultado (%s)", video_id, type(exc).__name__
            )

    def procesar_validacion(self, video_id: int, validacion: FabricaValidacion) -> None:
        """Valida con el análisis guardado, con el candado de modelo pesado; nunca deja escapar
        una excepción."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
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
        sin_sop = video.sop_id is None and sop_adjunto(self._media, video) is None
        if valida and (sin_sop or validacion is None):
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        archivo = self._media / video.archivo
        fin = FIN_ANALISIS_VALIDAR if valida else 100
        cronometro = _Cronometro()
        registrado = _TranscriptorRegistrado(transcriptor)

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
                archivo, video_id, idioma, registrado, archivo.parent, al_avanzar
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
        dispositivos = _dispositivos(self._gpu(), registrado.ultima)
        self._validar(session, video, analisis, validacion, cronometro.segundos(), dispositivos)

    def _revalidar(self, session: Session, video_id: int, validacion: FabricaValidacion) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        video.proceso, video.error = PROCESANDO, None
        video.etapa, video.progreso = "segmentacion", FIN_ANALISIS_VALIDAR
        session.commit()
        if video.sop_id is None and sop_adjunto(self._media, video) is None:
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        try:
            analisis = leer_analisis(video)
        except Exception as exc:
            self._fallar(session, video_id, f"no se pudo leer el análisis ({type(exc).__name__})")
            return
        # Sin Whisper: solo se sabe la GPU; Gemma se completa en la validación.
        self._validar(session, video, analisis, validacion, {}, Dispositivos(gpu=self._gpu()))

    def _validar(
        self,
        session: Session,
        video: Video,
        analisis: Analisis,
        fabrica: FabricaValidacion,
        segundos_analisis: Mapping[str, float],
        dispositivos: Dispositivos,
    ) -> None:
        """Valida, guarda el reporte y deja el video listo; si algo falla, en error."""
        video_id = video.id

        def al_avanzar(etapa: str, porcentaje: int) -> None:
            video.etapa, video.progreso = etapa, porcentaje
            session.commit()

        deps = None
        try:
            deps = fabrica()
            if video.sop_id is None:
                self._convertir_adjunto(session, video, deps.llm)
            assert video.sop is not None
            sop = SOP.model_validate(video.sop.contenido)
            validacion = validar(
                analisis,
                sop,
                deps,
                al_avanzar=al_avanzar,
                segundos_analisis=segundos_analisis,
                dispositivos=dispositivos,
            )
        except LLMNoDisponible:
            self._fallar(session, video_id, ERROR_LLM.format(id=video_id))
            return
        except _ErrorAdjunto as exc:
            self._fallar(session, video_id, str(exc))
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

    def _convertir_adjunto(self, session: Session, video: Video, llm: ClienteLLM) -> None:
        """Convierte el SOP adjunto (plantilla o Gemma 4, igual que `POST /sops`), lo guarda,
        se lo asigna al video y borra el adjunto. El trabajo ya tiene el candado.

        Ollama caído → `LLMNoDisponible` (error reprocesable, el adjunto se queda). Un documento
        que no se puede leer o convertir → `_ErrorAdjunto` con un mensaje sin texto del SOP.
        """
        ruta = sop_adjunto(self._media, video)
        if ruta is None:
            raise _ErrorAdjunto(ERROR_SIN_SOP)
        video.etapa = "conversion_sop"
        session.commit()
        datos = ruta.read_bytes()
        settings = get_settings()
        try:
            texto = extraer_texto(datos, ruta.suffix)
            conversion = convertir_documento(
                texto,
                lambda: nullcontext(llm),
                plazo_s=settings.llm_health_timeout_s,
                num_ctx=settings.llm_num_ctx,
                num_ctx_max=settings.llm_num_ctx_sop,
            )
        except LLMNoDisponible:
            raise
        except LLMError as exc:
            mensaje = f"Ollama falló al convertir el SOP ({type(exc).__name__})"
            raise LLMNoDisponible(mensaje) from exc
        except (ErrorLectura, ErrorConversionLLM) as exc:
            raise _ErrorAdjunto(f"SOP adjunto: {exc}") from None
        if len(conversion.sop.titulo) > TITULO_SOP_MAX:
            raise _ErrorAdjunto(f"SOP adjunto: el título pasa de {TITULO_SOP_MAX} caracteres")
        fila = guardar_sop(session, self._media, SopLeido(datos, ruta.suffix, conversion))
        video.sop_id = fila.id
        try:
            session.commit()
        except BaseException:
            session.rollback()
            shutil.rmtree(carpeta_sop(self._media, fila.id), ignore_errors=True)
            raise
        session.refresh(video)
        ruta.unlink(missing_ok=True)
        logger.info(
            "Video %d: SOP adjunto convertido como SOP %d (%s, %d advertencias)",
            video.id,
            fila.id,
            conversion.metodo,
            len(conversion.advertencias),
        )

    @staticmethod
    def _fallar(session: Session, video_id: int, mensaje: str) -> None:
        session.rollback()
        video = session.get(Video, video_id)
        video.proceso, video.error = ERROR, mensaje
        session.commit()
        logger.error("Video %d: %s", video_id, mensaje)


class _ErrorAdjunto(Exception):  # noqa: N818
    """El SOP adjunto no se pudo leer o convertir; el mensaje no cita el documento."""


class _TranscriptorRegistrado:
    """Pasa la llamada al transcriptor y guarda su `Transcripcion` (dispositivo y respaldo)."""

    def __init__(self, base: Transcriptor):
        self._base = base
        self.ultima: Transcripcion | None = None

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        self.ultima = self._base.transcribir(audio, idioma, al_segmento=al_segmento)
        return self.ultima


def _gpu_detectada() -> str | None:
    gpu = get_hardware().gpu
    return None if gpu is None else gpu.nombre


def _dispositivos(gpu: str | None, transcripcion: Transcripcion | None) -> Dispositivos:
    """Lo que se sabe al terminar el análisis; ctranslate2 llama "cuda" a la GPU."""
    if transcripcion is None:
        return Dispositivos(gpu=gpu)
    return Dispositivos(
        gpu=gpu,
        transcripcion="gpu" if transcripcion.dispositivo == "cuda" else "cpu",
        transcripcion_respaldo_cpu=transcripcion.respaldo_cpu,
    )


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
