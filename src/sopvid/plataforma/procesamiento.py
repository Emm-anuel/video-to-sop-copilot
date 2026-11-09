"""Cola de trabajos (videos y conversión de SOP) y paso del `Analisis` a la fila de `videos`.

Un solo trabajador (`ColaTrabajos`, un hilo): un modelo pesado a la vez (ADR-014). La cola tiene
prioridad: un SOP en cola va antes que el siguiente video, sin interrumpir el que se está
procesando; dentro de cada prioridad, en orden de llegada. Cada trabajo de video corre
`analizar_video` con su propia sesión y va actualizando `proceso`, `etapa` y `progreso`; al
terminar guarda el `Analisis` en las columnas (`guardar_analisis`).

Cómo se guarda el `Analisis` (sin migración): `duracion`, `idioma` (código) y `fotogramas` en
sus columnas, y en `transcripcion` (JSONB) un dict con la versión del contrato, el idioma
completo (código, confianza y si se fijó a mano), el modelo de Whisper y los segmentos.
`leer_analisis` lo rearma.

En modo validar (con `sop_id`), tras guardar el `Analisis` y hacer commit sigue la validación
(`sopvid.lenguaje.validacion.validar`: ficha de contexto → pasos del video → emparejamiento con
el juez → porcentaje) y se guardan el `Reporte`, `videos.pasos_video` y `videos.contexto`. El
avance del análisis se escala a 0–40 y la validación sigue de 40 a 100 sin retroceder;
`proceso="listo"` llega junto con el reporte. Si Ollama no responde al empezar la validación, el
video queda en error con el análisis guardado, y `revalidar` repite solo la validación, sin
Whisper (ADR-019), con la ficha guardada si la hay. Un reporte nuevo reemplaza al anterior.

Segmentación guardada (RNF-07): `videos.pasos_video` guarda la segmentación completa
(`SegmentacionGuardada`: pasos antes de fusionar, método y modelo). `revalidar` la reusa en lugar
de volver a llamar a Gemma, porque Gemma no segmenta igual dos veces (ADR-022): con los mismos
pasos, el emparejamiento y el porcentaje salen iguales (la redacción del juez puede variar). Se
vuelve a segmentar si se pide (`segmentar=True`) o si la guardada no se puede reusar (heurística
de respaldo, pasos sin redactar o fila anterior, sin método).

Afinidad baja (ADR-020): si la validación se detiene porque el video parece no ser del SOP, se
guardan la ficha y un `Reporte` con la afinidad, `cumplimiento` en NULL y la `DetencionAfinidad`
en `resultado` (`guardar_detencion`), y el video queda en `proceso="afinidad_baja"`. `revalidar`
con `continuar=True` repite la validación sin Whisper ni ficha y sin detenerse.

Ficha de contexto (RF-12): `videos.contexto` solo se llena si se generó; si quedó vacía (Ollama
cayó a media validación, corte por tiempo, JSON inválido o transcripción vacía) se deja en NULL y
el reporte lleva el aviso "contexto_sin_generar", así que `revalidar` la vuelve a intentar. En
modo generar (sin SOP) la ficha corre sola tras el análisis (0–85, luego "contexto"), en su
propia ventana de Gemma; si Ollama no responde, el video queda listo sin ficha.

Dónde corrió cada modelo (ADR-018) va en los metadatos del reporte: la GPU que ve la API, el
dispositivo con que transcribió Whisper (se toma de su `Transcripcion`) y, desde la validación,
el de Gemma.

Un error deja `proceso="error"` y un mensaje sin texto del video: el de `ErrorMedios` (solo
nombra el archivo y la causa) o la etapa y el tipo de excepción. Nunca `str(exc)` de otros
errores: un `ValidationError` de pydantic incluye el texto transcrito.

Conversión del SOP (POST /sops y el SOP adjunto a POST /videos, RF-01 a RF-03): la petición
crea la fila en "en_cola" con el original (`crear_sop_en_cola`) y el trabajo `procesar_sop` la
pasa a "convirtiendo" y la deja en "listo" (título, SOP del contrato, método y advertencias) o
en "error" con un mensaje que dice qué hacer. Un video de modo validar espera a su SOP: como el
SOP va antes en la cola, al empezar el video ya está listo o en error; en error, el video falla
con el mensaje del SOP antes de transcribir.

Cada trabajo corre además con `CANDADO_MODELO_PESADO` (reentrante): hoy todo pasa por el mismo
hilo, pero protege si otro camino llegara a cargar Whisper o Gemma.
"""

import itertools
import logging
import queue
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import asdict
from decimal import Decimal
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from sopvid.contrato import SOP, Analisis, Contexto, Dispositivos, SegmentacionGuardada
from sopvid.lenguaje.lectura_sop import (
    AjustesConversion,
    ErrorConversionLLM,
    ErrorLectura,
    convertir_documento,
    extraer_texto,
)
from sopvid.lenguaje.llm import ClienteLLM, LLMError, LLMNoDisponible, LLMTiempoExcedido
from sopvid.lenguaje.validacion import (
    INICIO_ETAPA,
    Detenida,
    FabricaValidacion,
    Validacion,
    segmentacion_de,
    segmentacion_guardada,
    validar,
)
from sopvid.percepcion.contexto import ResultadoContexto, generar_contexto
from sopvid.percepcion.medios import ErrorMedios
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.segmentacion import Segmentacion
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion, Transcriptor
from sopvid.plataforma.config import get_settings
from sopvid.plataforma.hardware import CANDADO_MODELO_PESADO, CandadoModeloPesado, get_hardware
from sopvid.plataforma.modelos import PROCESOS_VIDEO, Reporte, Sop, Video

logger = logging.getLogger(__name__)

# Fábrica de sesiones: `sessionmaker` en producción; en pruebas, la sesión de la prueba.
FabricaSesiones = Callable[[], AbstractContextManager[Session]]

# Los valores de `videos.proceso` (CHECK de modelos.py), en su orden.
EN_COLA, PROCESANDO, LISTO, ERROR, AFINIDAD_BAJA = PROCESOS_VIDEO
ERROR_REINICIO = "interrumpido por reinicio"
ERROR_LLM = (
    "LLM no disponible: el análisis quedó guardado; repite la validación con "
    "POST /videos/{id}/validar cuando Ollama responda"
)
ERROR_SIN_SOP = "el video es de modo validar y no tiene SOP de referencia"
TITULO_SOP_MAX = 300  # largo de `sops.titulo`
# Estados de `sops.estado` (CHECK de modelos.py).
SOP_EN_COLA, SOP_CONVIRTIENDO, SOP_LISTO, SOP_ERROR = "en_cola", "convirtiendo", "listo", "error"
MENSAJE_SOP_SIN_LLM = (
    "El SOP no sigue la plantilla y el LLM (Ollama) no responde. Vuelve a subirlo cuando Ollama "
    "esté arriba, o súbelo con la plantilla (docs/contrato/plantilla_sop.md)."
)
MENSAJE_SOP_REINICIO = (
    "La conversión se interrumpió por un reinicio del servidor; vuelve a subirlo."
)
# Prioridad en la cola: menor va antes.
PRIORIDAD_SOP, PRIORIDAD_VIDEO = 0, 1
# Crea el cliente del LLM para una conversión (la API inyecta Gemma 4 por Ollama).
FabricaLLM = Callable[[], AbstractContextManager[ClienteLLM]]
Trabajo = Callable[[], None]
# En modo validar el análisis llega hasta aquí; la validación (desde la ficha de contexto)
# sigue hasta 100.
FIN_ANALISIS_VALIDAR = INICIO_ETAPA["contexto"]
# En modo generar el análisis llega hasta aquí y la ficha de contexto empieza.
FIN_ANALISIS_GENERAR = 85


def guardar_analisis(video: Video, analisis: Analisis) -> None:
    """Copia el `Analisis` a las columnas de `video` (no hace commit)."""
    video.duracion = analisis.duracion_s
    video.idioma = analisis.idioma.codigo
    video.transcripcion = {
        "version_contrato": analisis.version_contrato,
        "idioma": analisis.idioma.model_dump(mode="json"),
        "modelo_transcripcion": analisis.modelo_transcripcion,
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
            "modelo_transcripcion": datos.get("modelo_transcripcion"),
        }
    )


def guardar_reporte(session: Session, video: Video, validacion: Validacion) -> None:
    """Guarda el reporte, que reemplaza al anterior, los pasos del video y la ficha de contexto
    (no hace commit).

    `cumplimiento` se guarda a dos decimales; el valor sin redondear y el semáforo calculado con
    él van en `resultado`. La ficha solo se escribe si se generó en esta validación: vacía, queda
    NULL (la siguiente validación la vuelve a intentar); reusada, no se toca.
    """
    assert video.sop_id is not None
    session.execute(delete(Reporte).where(Reporte.video_id == video.id))
    session.expire(video, ["reporte"])
    guardado = validacion.resultado
    session.add(
        Reporte(
            video_id=video.id,
            sop_id=video.sop_id,
            afinidad=None if guardado.afinidad is None else guardado.afinidad.valor,
            cumplimiento=Decimal(f"{guardado.cumplimiento:.2f}"),
            resultado=guardado.model_dump(mode="json"),
        )
    )
    if validacion.segmentacion is not None:
        video.pasos_video = segmentacion_guardada(validacion.segmentacion).model_dump(mode="json")
    else:  # una Validacion armada a mano, sin la segmentación: solo los pasos, como antes
        video.pasos_video = [p.model_dump(mode="json") for p in validacion.pasos_video]
    _guardar_contexto(video, validacion.resultado_contexto)


def leer_segmentacion(video: Video) -> SegmentacionGuardada | None:
    """La segmentación guardada del video, o None si no hay, es de antes de RNF-07 (una lista
    sin método) o no valida."""
    if not isinstance(video.pasos_video, dict):
        return None
    try:
        return SegmentacionGuardada.model_validate(video.pasos_video)
    except Exception as exc:
        logger.warning(
            "Video %d: segmentación guardada inválida (%s)", video.id, type(exc).__name__
        )
        return None


def guardar_detencion(session: Session, video: Video, detenida: Detenida) -> None:
    """Guarda la detención por afinidad baja (ADR-020), que reemplaza al reporte anterior: un
    `Reporte` con la afinidad, sin cumplimiento y con la `DetencionAfinidad` en `resultado`. Los
    pasos del video de una validación anterior se borran (no corresponden a este resultado); la
    ficha, como en `guardar_reporte`. No hace commit.
    """
    assert video.sop_id is not None
    session.execute(delete(Reporte).where(Reporte.video_id == video.id))
    session.expire(video, ["reporte"])
    session.add(
        Reporte(
            video_id=video.id,
            sop_id=video.sop_id,
            afinidad=detenida.detencion.afinidad.valor,
            cumplimiento=None,
            resultado=detenida.detencion.model_dump(mode="json"),
        )
    )
    video.pasos_video = None
    _guardar_contexto(video, detenida.resultado_contexto)


def _guardar_contexto(video: Video, generada: ResultadoContexto | None) -> None:
    """La ficha solo se escribe si se generó en esta validación: vacía, queda NULL (la siguiente
    validación la vuelve a intentar); reusada (`generada` None), no se toca."""
    if generada is not None:
        video.contexto = generada.contexto.model_dump(mode="json") if generada.generado else None


def crear_sop_en_cola(session: Session, media: Path, datos: bytes, extension: str) -> Sop:
    """Agrega la fila del SOP en "en_cola" (sin commit) y escribe el original en
    `media/sops/<id>/original.<ext>`; en la fila va la ruta relativa, nunca el nombre original.

    Si la escritura falla, revierte la sesión y borra la carpeta. Quien llama hace el commit,
    encola la conversión (`Procesador.encolar_sop`) y, si algo falla antes del commit, borra
    `carpeta_sop(media, fila.id)`.
    """
    fila = Sop(origen="cargado", archivo_original="", estado=SOP_EN_COLA)
    session.add(fila)
    session.flush()  # asigna el id
    relativa = PurePosixPath("sops", str(fila.id), f"original{extension}")
    destino = media / relativa
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    except BaseException:
        session.rollback()
        shutil.rmtree(destino.parent, ignore_errors=True)
        raise
    fila.archivo_original = str(relativa)
    return fila


def carpeta_sop(media: Path, sop_id: int) -> Path:
    return media / "sops" / str(sop_id)


def error_de_sop(sop: Sop) -> str:
    """Mensaje para un video cuyo SOP de referencia no se pudo convertir."""
    return f"El SOP de referencia {sop.codigo} no se pudo convertir: {sop.error}"


def marcar_sops_interrumpidos(session: Session) -> int:
    """Pasa a error los SOP que quedaron en cola o convirtiendo (la cola vive en memoria)."""
    resultado = session.execute(
        update(Sop)
        .where(Sop.estado.in_((SOP_EN_COLA, SOP_CONVIRTIENDO)))
        .values(estado=SOP_ERROR, error=MENSAJE_SOP_REINICIO)
    )
    session.commit()
    if resultado.rowcount:
        logger.warning("SOP interrumpidos por el reinicio, ahora en error: %d", resultado.rowcount)
    return resultado.rowcount


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


class ColaTrabajos:
    """Cola de un solo trabajador con prioridad (`PRIORIDAD_SOP` antes que `PRIORIDAD_VIDEO`).

    Dentro de una prioridad, en orden de llegada. Un trabajo que ya empezó no se interrumpe. En
    producción la vacía un hilo (`iniciar`); en las pruebas, `correr_pendientes` en el hilo de la
    prueba. Los trabajos no deben lanzar (los del `Procesador` registran sus errores).
    """

    def __init__(self) -> None:
        self._cola: queue.PriorityQueue[tuple[int, int, Trabajo | None]] = queue.PriorityQueue()
        self._orden = itertools.count()

    def poner(self, trabajo: Trabajo, prioridad: int = PRIORIDAD_VIDEO) -> None:
        self._cola.put((prioridad, next(self._orden), trabajo))

    def pendientes(self) -> list[Trabajo]:
        """Los trabajos en espera, en el orden en que van a correr."""
        with self._cola.mutex:
            return [t for _, _, t in sorted(self._cola.queue) if t is not None]

    def correr_pendientes(self) -> None:
        """Corre en este hilo lo que haya, en orden de prioridad (pruebas)."""
        while True:
            try:
                _, _, trabajo = self._cola.get_nowait()
            except queue.Empty:
                return
            if trabajo is not None:
                trabajo()

    def iniciar(self) -> None:
        threading.Thread(target=self._bucle, name="analisis", daemon=True).start()

    def cerrar(self) -> None:
        """Descarta lo pendiente (se marca al volver a arrancar) y detiene el hilo sin esperar."""
        while True:
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break
        self._cola.put((-1, next(self._orden), None))

    def _bucle(self) -> None:
        while True:
            _, _, trabajo = self._cola.get()
            if trabajo is None:
                return
            try:
                trabajo()
            except Exception as exc:  # el hilo sigue con el siguiente
                logger.error("Trabajo de la cola falló (%s)", type(exc).__name__)


class Procesador:
    """Encola trabajos de video y de conversión de SOP en una `ColaTrabajos`."""

    def __init__(
        self,
        sesiones: FabricaSesiones,
        media: Path,
        cola: ColaTrabajos,
        gpu: Callable[[], str | None] | None = None,
        candado: CandadoModeloPesado = CANDADO_MODELO_PESADO,
    ):
        """`gpu` da el nombre de la GPU para los metadatos (por defecto, la que detecta la API);
        `candado`, el de modelo pesado (ADR-014)."""
        self._candado = candado
        self._sesiones = sesiones
        self._gpu = gpu or _gpu_detectada
        self._media = media
        self._cola = cola

    @classmethod
    def con_hilo(cls, sesiones: FabricaSesiones, media: Path) -> "Procesador":
        """Procesador de producción: un hilo trabajador (un modelo pesado a la vez)."""
        cola = ColaTrabajos()
        cola.iniciar()
        return cls(sesiones, media, cola)

    def encolar(
        self,
        video_id: int,
        idioma: str | None,
        transcriptor: Transcriptor,
        validacion: FabricaValidacion | None = None,
    ) -> None:
        """Encola el análisis. `validacion` da las dependencias del LLM: en modo validar, para la
        validación (con la ficha de contexto); en modo generar, solo para la ficha."""
        self._cola.poner(lambda: self.procesar(video_id, idioma, transcriptor, validacion))

    def revalidar(
        self,
        video_id: int,
        validacion: FabricaValidacion,
        *,
        continuar: bool = False,
        segmentar: bool = False,
    ) -> None:
        """Encola solo la validación, sobre el análisis ya guardado (ADR-019). Con `continuar`, no
        se detiene por afinidad baja (ADR-020): quien carga ya vio la advertencia. Reusa la
        segmentación guardada (RNF-07), salvo con `segmentar`."""
        self._cola.poner(
            lambda: self.procesar_validacion(
                video_id, validacion, continuar=continuar, segmentar=segmentar
            )
        )

    def encolar_sop(self, sop_id: int, fabrica_llm: FabricaLLM, ajustes: AjustesConversion) -> None:
        """Encola la conversión del SOP, antes que el siguiente video."""
        self._cola.poner(lambda: self.procesar_sop(sop_id, fabrica_llm, ajustes), PRIORIDAD_SOP)

    def cerrar(self) -> None:
        """Apaga el hilo sin esperar: los trabajos pendientes se marcan al volver a arrancar."""
        self._cola.cerrar()

    def procesar_sop(
        self, sop_id: int, fabrica_llm: FabricaLLM, ajustes: AjustesConversion
    ) -> None:
        """Convierte el SOP y guarda el resultado; nunca deja escapar una excepción."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
                self._convertir_sop(session, sop_id, fabrica_llm, ajustes)
        except Exception as exc:
            logger.error(
                "SOP %d: no se pudo registrar la conversión (%s)", sop_id, type(exc).__name__
            )

    def procesar(
        self,
        video_id: int,
        idioma: str | None,
        transcriptor: Transcriptor,
        validacion: FabricaValidacion | None = None,
    ) -> None:
        """Analiza (y valida) el video y guarda el resultado; nunca deja escapar una excepción.
        Corre con el candado de modelo pesado."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
                self._procesar(session, video_id, idioma, transcriptor, validacion)
        except Exception as exc:  # el hilo no tiene a quién avisar: se registra y sigue
            logger.error(
                "Video %d: no se pudo registrar el resultado (%s)", video_id, type(exc).__name__
            )

    def procesar_validacion(
        self,
        video_id: int,
        validacion: FabricaValidacion,
        *,
        continuar: bool = False,
        segmentar: bool = False,
    ) -> None:
        """Valida con el análisis guardado, con el candado de modelo pesado; nunca deja escapar
        una excepción."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
                self._revalidar(session, video_id, validacion, continuar, segmentar)
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
        if valida and (video.sop is None or validacion is None):
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        if valida and video.sop.estado == SOP_ERROR:  # sin gastar Whisper
            self._fallar(session, video_id, error_de_sop(video.sop))
            return
        archivo = self._media / video.archivo
        fin = FIN_ANALISIS_VALIDAR if valida else FIN_ANALISIS_GENERAR
        cronometro = _Cronometro()
        registrado = _TranscriptorRegistrado(transcriptor)

        def al_avanzar(etapa: str, porcentaje: int) -> None:
            cronometro.marcar(etapa)
            if etapa == "listo":  # se guarda junto con el resultado
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
            if validacion is not None:
                session.commit()  # el análisis queda guardado aunque falle la ficha
                self._contexto_sin_sop(session, video_id, analisis, validacion)
                video = session.get(Video, video_id)
            video.etapa, video.progreso = "listo", 100
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

    def _revalidar(
        self,
        session: Session,
        video_id: int,
        validacion: FabricaValidacion,
        continuar: bool,
        segmentar: bool = False,
    ) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        contexto = _contexto_guardado(video)
        guardada = None if segmentar else leer_segmentacion(video)
        segmentacion = segmentacion_de(guardada) if guardada and guardada.reusable else None
        logger.info(
            "Video %d: %s",
            video_id,
            "reusa la segmentación guardada"
            if segmentacion is not None
            else "vuelve a segmentar" + (" (pedido)" if segmentar else ""),
        )
        video.proceso, video.error = PROCESANDO, None
        # Con la ficha guardada se reusa y empieza por los pasos; sin ella, se genera primero.
        video.etapa = "contexto" if contexto is None else "segmentacion"
        video.progreso = FIN_ANALISIS_VALIDAR
        session.commit()
        if video.sop is None:
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        try:
            analisis = leer_analisis(video)
        except Exception as exc:
            self._fallar(session, video_id, f"no se pudo leer el análisis ({type(exc).__name__})")
            return
        # Sin Whisper: solo se sabe la GPU; Gemma se completa en la validación.
        self._validar(
            session,
            video,
            analisis,
            validacion,
            {},
            Dispositivos(gpu=self._gpu()),
            contexto,
            continuar=continuar,
            segmentacion=segmentacion,
        )

    def _contexto_sin_sop(
        self, session: Session, video_id: int, analisis: Analisis, fabrica: FabricaValidacion
    ) -> None:
        """Modo generar: la ficha de contexto en su propia ventana de Gemma (se descarga al
        terminar). Si Ollama no responde o la ficha queda vacía, el video sigue sin ficha (NULL):
        no hay reporte donde poner el aviso. Nunca lanza."""
        video = session.get(Video, video_id)
        video.etapa, video.progreso = "contexto", FIN_ANALISIS_GENERAR
        session.commit()
        deps = None
        try:
            deps = fabrica()
            if not deps.llm.disponible(get_settings().llm_health_timeout_s):
                logger.warning(
                    "Video %d: Ollama no responde; queda sin ficha de contexto", video_id
                )
                return
            try:
                generada = generar_contexto(analisis, deps.llm)
            finally:
                deps.llm.descargar()
            if generada.generado:
                video.contexto = generada.contexto.model_dump(mode="json")
                session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("Video %d: falló la ficha de contexto (%s)", video_id, type(exc).__name__)
        finally:
            if deps is not None:
                deps.cerrar()

    def _validar(
        self,
        session: Session,
        video: Video,
        analisis: Analisis,
        fabrica: FabricaValidacion,
        segundos_analisis: Mapping[str, float],
        dispositivos: Dispositivos,
        contexto: Contexto | None = None,
        *,
        continuar: bool = False,
        segmentacion: Segmentacion | None = None,
    ) -> None:
        """Valida, guarda el reporte y deja el video listo; si algo falla, en error. Con
        `contexto` (la ficha guardada) no se vuelve a generar, y con `segmentacion` (la guardada,
        RNF-07) no se vuelve a segmentar. Si la validación se detiene por
        afinidad baja (sin `continuar`), guarda la detención y deja el video en "afinidad_baja".

        El SOP de referencia tiene que estar listo: el suyo va antes en la cola, así que aquí ya
        terminó; si quedó en error, el video falla con ese mensaje.
        """
        video_id = video.id
        sop_fila = video.sop
        assert sop_fila is not None
        session.refresh(sop_fila)  # la conversión la guardó otro trabajo
        if sop_fila.estado != SOP_LISTO:
            mensaje = (
                error_de_sop(sop_fila)
                if sop_fila.estado == SOP_ERROR
                else f"El SOP de referencia {sop_fila.codigo} todavía no está listo"
            )
            self._fallar(session, video_id, mensaje)
            return

        def al_avanzar(etapa: str, porcentaje: int) -> None:
            video.etapa, video.progreso = etapa, porcentaje
            session.commit()

        deps = None
        try:
            deps = fabrica()
            sop = SOP.model_validate(sop_fila.contenido)
            validacion = validar(
                analisis,
                sop,
                deps,
                al_avanzar=al_avanzar,
                segundos_analisis=segundos_analisis,
                dispositivos=dispositivos,
                contexto=contexto,
                continuar=continuar,
                segmentacion=segmentacion,
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
        if isinstance(validacion, Detenida):
            guardar_detencion(session, video, validacion)
            video.etapa, video.progreso = "afinidad", INICIO_ETAPA["segmentacion"]
            video.proceso, video.error = AFINIDAD_BAJA, None
            session.commit()
            logger.info(
                "Video %d en afinidad baja (%d): espera a que quien carga decida",
                video_id,
                validacion.detencion.afinidad.valor,
            )
            return
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

    def _convertir_sop(
        self, session: Session, sop_id: int, fabrica_llm: FabricaLLM, ajustes: AjustesConversion
    ) -> None:
        """en_cola → convirtiendo → listo | error. El mensaje de error nunca cita el SOP."""
        fila = session.get(Sop, sop_id)
        if fila is None:
            logger.warning("SOP %d: ya no existe; se omite", sop_id)
            return
        fila.estado, fila.error = SOP_CONVIRTIENDO, None
        session.commit()
        ruta = PurePosixPath(fila.archivo_original or "")
        try:
            texto = extraer_texto((self._media / ruta).read_bytes(), ruta.suffix)
            conversion = convertir_documento(texto, fabrica_llm, ajustes=ajustes)
            if len(conversion.sop.titulo) > TITULO_SOP_MAX:
                raise ErrorLectura(f"el título del SOP pasa de {TITULO_SOP_MAX} caracteres")
        except (ErrorLectura, ErrorConversionLLM, LLMTiempoExcedido) as exc:
            mensaje = str(exc)
        except LLMError as exc:
            logger.warning("SOP %d: LLM no disponible (%s)", sop_id, type(exc).__name__)
            mensaje = MENSAJE_SOP_SIN_LLM
        except Exception as exc:
            mensaje = f"falló la conversión ({type(exc).__name__})"
        else:
            sop = conversion.sop
            fila.titulo, fila.contenido = sop.titulo, sop.model_dump(mode="json")
            fila.metodo = conversion.metodo
            fila.advertencias = [asdict(a) for a in conversion.advertencias]
            fila.estado, fila.error = SOP_LISTO, None
            session.commit()
            logger.info(
                "SOP %d listo (%s): %d pasos, %d advertencias",
                sop_id,
                conversion.metodo,
                len(sop.pasos),
                len(conversion.advertencias),
            )
            return
        session.rollback()
        fila = session.get(Sop, sop_id)
        fila.estado, fila.error = SOP_ERROR, mensaje
        session.commit()
        logger.error("SOP %d: %s", sop_id, mensaje)

    @staticmethod
    def _fallar(session: Session, video_id: int, mensaje: str) -> None:
        session.rollback()
        video = session.get(Video, video_id)
        video.proceso, video.error = ERROR, mensaje
        session.commit()
        logger.error("Video %d: %s", video_id, mensaje)


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


def _contexto_guardado(video: Video) -> Contexto | None:
    """La ficha de `videos.contexto`, o None si no hay (o no valida: se vuelve a generar)."""
    if video.contexto is None:
        return None
    try:
        return Contexto.model_validate(video.contexto)
    except Exception as exc:
        logger.warning(
            "Video %d: ficha de contexto guardada inválida (%s)", video.id, type(exc).__name__
        )
        return None


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
