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
el reporte lleva el aviso "contexto_sin_generar", así que `revalidar` la vuelve a intentar.

Modo generar (sin SOP, ADR-023): tras el análisis (0–40), en una sola carga de Gemma, ficha de
contexto → pasos del video (`videos.pasos_video`, como en modo validar) → SOP generado
(`sopvid.lenguaje.sop_generado`). El SOP se guarda en `sops` con `origen="generado"`, fuera de la
biblioteca, con sus advertencias y `sops.generacion`, y `videos.sop_id` apunta a él (§10). Si
Ollama no responde al empezar, o no hay pasos del video, el video queda en error con el análisis
guardado y `regenerar` lo repite sin Whisper; reusa la ficha y la segmentación guardadas (RNF-07),
salvo `segmentar=True`. Un SOP generado que ya está en la biblioteca no se pisa: se crea otro.

Imágenes (RF-11, ADR-024): con `imagenes=True` en `encolar` (la API resuelve `analizar_imagenes`
contra `FOTOGRAMAS_DESCRIBIR`), en los dos modos se describen N imágenes antes de la ficha, en la
misma carga de Gemma, y quedan en `videos.fotogramas`; el análisis llega entonces a 35 y la etapa
"fotogramas" avanza de 35 a 45. Apagada, la etapa no aparece. Al repetir (`revalidar`,
`regenerar`) no se vuelven a describir: se usan las guardadas. Al terminar la validación o la
generación, ya sin Gemma, se saca una miniatura por fila del reporte con segundo o por paso del SOP
generado (`percepcion.miniaturas`, solo ffmpeg); sin imagen visible, el aviso informativo
"sin_imagen" (o la advertencia del SOP). Una falla de ffmpeg ahí no detiene nada.

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
from dataclasses import asdict, replace
from decimal import Decimal
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from sopvid.contrato import (
    SOP,
    Analisis,
    AvisoConversion,
    Contexto,
    Dispositivos,
    SegmentacionGuardada,
)
from sopvid.lenguaje.lectura_sop import (
    AjustesConversion,
    ErrorConversionLLM,
    ErrorLectura,
    convertir_documento,
    extraer_texto,
)
from sopvid.lenguaje.llm import ClienteLLM, LLMError, LLMNoDisponible, LLMTiempoExcedido
from sopvid.lenguaje.sop_generado import SinPasosDelVideo, generar_sop
from sopvid.lenguaje.validacion import (
    INICIO_ETAPA,
    DescribirImagenes,
    Detenida,
    FabricaValidacion,
    Validacion,
    avisos_de,
    inicio_etapas,
    segmentacion_de,
    segmentacion_guardada,
    validar,
)
from sopvid.percepcion.contexto import ResultadoContexto, generar_contexto
from sopvid.percepcion.fotogramas import (
    ResultadoFotogramas,
    cuantas_imagenes,
    describir_fotogramas,
    imagenes_de,
)
from sopvid.percepcion.medios import ErrorMedios
from sopvid.percepcion.miniaturas import (
    ResultadoMiniaturas,
    aviso_sin_imagen,
    carpeta_miniaturas,
    generar_miniaturas,
)
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.segmentacion import Segmentacion, segmentar
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
ERROR_LLM_GENERAR = (
    "LLM no disponible: el análisis quedó guardado; repite la generación con "
    "POST /videos/{id}/generar cuando Ollama responda"
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
MENSAJE_SOP_GENERADO_REINICIO = (
    "La generación se interrumpió por un reinicio del servidor; repítela con "
    "POST /videos/{id}/generar."
)
# Prioridad en la cola: menor va antes.
PRIORIDAD_SOP, PRIORIDAD_VIDEO = 0, 1
# Crea el cliente del LLM para una conversión (la API inyecta Gemma 4 por Ollama).
FabricaLLM = Callable[[], AbstractContextManager[ClienteLLM]]
Trabajo = Callable[[], None]
# En modo validar el análisis llega hasta aquí; la validación (desde la ficha de contexto)
# sigue hasta 100.
FIN_ANALISIS_VALIDAR = INICIO_ETAPA["contexto"]
# En modo generar el análisis llega hasta aquí; después, el avance de cada etapa de Gemma.
FIN_ANALISIS_GENERAR = 40
INICIO_GENERAR = {
    "contexto": 40,
    "segmentacion": 50,
    "sop_pasos": 65,
    "sop_resumen": 85,
    "sop_claves": 92,
}
# Con la descripción de imágenes (ADR-024): el análisis llega a 35 y las imágenes van de 35 a 45.
INICIO_GENERAR_IMAGENES = {
    "fotogramas": 35,
    "contexto": 45,
    "segmentacion": 55,
    "sop_pasos": 68,
    "sop_resumen": 86,
    "sop_claves": 93,
}


def inicio_generar(imagenes: bool) -> dict[str, int]:
    """La tabla de avance del modo generar, con o sin la etapa de imágenes."""
    return INICIO_GENERAR_IMAGENES if imagenes else INICIO_GENERAR


def fin_analisis(valida: bool, imagenes: bool) -> int:
    """Hasta dónde llega el avance del análisis: la primera etapa de Gemma del modo."""
    tabla = inicio_etapas(imagenes) if valida else inicio_generar(imagenes)
    return min(tabla.values())


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
    _guardar_fotogramas(video, validacion.resultado_fotogramas)


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
    _guardar_fotogramas(video, detenida.resultado_fotogramas)


def _guardar_fotogramas(video: Video, descritos: ResultadoFotogramas | None) -> None:
    """Las imágenes descritas en este proceso van a `videos.fotogramas` (y al `Analisis` que se
    lee al repetir); sin descripción (apagada o repetida), no se tocan."""
    if descritos is not None:
        video.fotogramas = [f.model_dump(mode="json") for f in descritos.fotogramas]


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
    """Pasa a error los SOP que quedaron en cola o convirtiendo (la cola vive en memoria). Un
    SOP generado se repite desde su video; uno cargado, subiéndolo otra vez."""
    interrumpido = Sop.estado.in_((SOP_EN_COLA, SOP_CONVIRTIENDO))
    total = 0
    for generado, mensaje in ((False, MENSAJE_SOP_REINICIO), (True, MENSAJE_SOP_GENERADO_REINICIO)):
        resultado = session.execute(
            update(Sop)
            .where(interrumpido, (Sop.origen == "generado") == generado)
            .values(estado=SOP_ERROR, error=mensaje)
        )
        total += resultado.rowcount
    session.commit()
    if total:
        logger.warning("SOP interrumpidos por el reinicio, ahora en error: %d", total)
    return total


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
        *,
        imagenes: bool = False,
    ) -> None:
        """Encola el análisis. `validacion` da las dependencias del LLM: en modo validar, para la
        validación (con la ficha de contexto); en modo generar, para la ficha y el SOP. Con
        `imagenes`, se describen imágenes antes de la ficha (ADR-024)."""
        self._cola.poner(
            lambda: self.procesar(video_id, idioma, transcriptor, validacion, imagenes=imagenes)
        )

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

    def regenerar(
        self, video_id: int, fabrica: FabricaValidacion, *, segmentar: bool = False
    ) -> None:
        """Encola solo la generación del SOP, sobre el análisis guardado (ADR-023, criterio de
        ADR-019). Reusa la ficha y la segmentación guardadas (RNF-07), salvo con `segmentar`."""
        self._cola.poner(lambda: self.procesar_generacion(video_id, fabrica, segmentar=segmentar))

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
        *,
        imagenes: bool = False,
    ) -> None:
        """Analiza (y valida) el video y guarda el resultado; nunca deja escapar una excepción.
        Corre con el candado de modelo pesado."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
                self._procesar(session, video_id, idioma, transcriptor, validacion, imagenes)
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

    def procesar_generacion(
        self, video_id: int, fabrica: FabricaValidacion, *, segmentar: bool = False
    ) -> None:
        """Repite la generación con el análisis guardado, con el candado de modelo pesado; nunca
        deja escapar una excepción."""
        try:
            with self._candado.tomar(), self._sesiones() as session:
                self._regenerar(session, video_id, fabrica, segmentar)
        except Exception as exc:
            logger.error(
                "Video %d: no se pudo registrar la generación (%s)", video_id, type(exc).__name__
            )

    def _procesar(
        self,
        session: Session,
        video_id: int,
        idioma: str | None,
        transcriptor: Transcriptor,
        validacion: FabricaValidacion | None,
        imagenes: bool = False,
    ) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        video.proceso, video.etapa, video.progreso, video.error = PROCESANDO, None, 0, None
        session.commit()
        valida = video.modo == "validar"
        # Sin dependencias del LLM no hay quién describa las imágenes.
        imagenes = imagenes and validacion is not None
        if valida and (video.sop is None or validacion is None):
            self._fallar(session, video_id, ERROR_SIN_SOP)
            return
        if valida and video.sop.estado == SOP_ERROR:  # sin gastar Whisper
            self._fallar(session, video_id, error_de_sop(video.sop))
            return
        archivo = self._media / video.archivo
        fin = fin_analisis(valida, imagenes)
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
        if not valida and validacion is not None:
            session.commit()  # el análisis queda guardado aunque falle la generación
            self._generar(session, video_id, analisis, validacion, imagenes=imagenes)
            return
        if not valida:  # sin dependencias del LLM: solo el análisis
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
        self._validar(
            session,
            video,
            analisis,
            validacion,
            cronometro.segundos(),
            dispositivos,
            imagenes=imagenes,
        )

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

    def _regenerar(
        self, session: Session, video_id: int, fabrica: FabricaValidacion, segmentar: bool
    ) -> None:
        video = session.get(Video, video_id)
        if video is None:
            logger.warning("Video %d: ya no existe; se omite", video_id)
            return
        contexto = _contexto_guardado(video)
        guardada = None if segmentar else leer_segmentacion(video)
        segmentacion = segmentacion_de(guardada) if guardada and guardada.reusable else None
        logger.info(
            "Video %d: genera el SOP; %s",
            video_id,
            "reusa la segmentación guardada"
            if segmentacion is not None
            else "vuelve a segmentar" + (" (pedido)" if segmentar else ""),
        )
        try:
            analisis = leer_analisis(video)
        except Exception as exc:
            self._fallar(session, video_id, f"no se pudo leer el análisis ({type(exc).__name__})")
            return
        self._generar(
            session, video_id, analisis, fabrica, contexto=contexto, segmentacion=segmentacion
        )

    def _generar(
        self,
        session: Session,
        video_id: int,
        analisis: Analisis,
        fabrica: FabricaValidacion,
        *,
        contexto: Contexto | None = None,
        segmentacion: Segmentacion | None = None,
        imagenes: bool = False,
    ) -> None:
        """Modo generar (ADR-023): [imágenes →] ficha → pasos del video → SOP generado, en una
        sola carga de Gemma, y guarda el SOP. Con `contexto` o `segmentacion` (guardados) no se
        vuelven a pedir; con la ficha guardada tampoco se describen imágenes. Sin Ollama al
        empezar o sin pasos del video, el video queda en error (y el SOP también, si ya se había
        creado). Nunca lanza."""
        video = session.get(Video, video_id)
        video.proceso, video.error = PROCESANDO, None
        imagenes = imagenes and contexto is None
        tabla = inicio_generar(imagenes)
        primera = "contexto" if contexto is None else "segmentacion"
        if contexto is not None and segmentacion is not None:
            primera = "sop_pasos"
        if imagenes:
            primera = "fotogramas"
        video.etapa, video.progreso = primera, tabla[primera]
        session.commit()

        def avanzar(etapa: str, porcentaje: int | None = None) -> None:
            video.etapa = etapa
            video.progreso = tabla[etapa] if porcentaje is None else porcentaje
            session.commit()

        contexto_reusado, segmentacion_reusada = contexto is not None, segmentacion is not None
        resultado_contexto: ResultadoContexto | None = None
        resultado_fotogramas: ResultadoFotogramas | None = None
        fila: Sop | None = None
        deps = None
        try:
            deps = fabrica()
            llm = deps.llm
            if not llm.disponible(get_settings().llm_health_timeout_s):
                self._fallar(session, video_id, ERROR_LLM_GENERAR.format(id=video_id))
                return
            try:
                if imagenes:
                    rango = tabla["contexto"] - tabla["fotogramas"]
                    n = cuantas_imagenes("generar", None, analisis.duracion_s)
                    resultado_fotogramas = self._describidor(session, video, analisis, n)(
                        llm,
                        lambda fraccion: avanzar(
                            "fotogramas", tabla["fotogramas"] + int(rango * min(fraccion, 1.0))
                        ),
                    )
                    analisis = analisis.model_copy(
                        update={"fotogramas": resultado_fotogramas.fotogramas}
                    )
                    _guardar_fotogramas(video, resultado_fotogramas)
                    session.commit()
                if contexto is None:
                    avanzar("contexto")
                    resultado_contexto = generar_contexto(analisis, llm)
                    if resultado_contexto.generado:
                        contexto = resultado_contexto.contexto
                        video.contexto = contexto.model_dump(mode="json")
                        session.commit()
                if segmentacion is None:
                    avanzar("segmentacion")
                    segmentacion = segmentar(analisis, llm)
                    guardada = segmentacion_guardada(segmentacion)
                    video.pasos_video = guardada.model_dump(mode="json")
                    session.commit()
                if not segmentacion.pasos:
                    raise SinPasosDelVideo(
                        "No hay pasos del video para redactar el SOP: la transcripción quedó "
                        "vacía o sin pasos. Revisa el audio y vuelve a generar."
                    )
                fila = _fila_generada(session, video)
                session.commit()
                generado = generar_sop(
                    analisis,
                    segmentacion.pasos,
                    llm,
                    contexto,
                    embedder=deps.embedder,
                    al_avanzar=avanzar,
                )
            finally:
                # Antes de descargar: después Ollama ya no lo lista (ADR-018).
                dispositivo = llm.dispositivo_cargado()
                llm.descargar()
        except SinPasosDelVideo as exc:
            self._fallar(session, video_id, str(exc), sop_id=fila.id if fila else None)
            return
        except Exception as exc:
            session.rollback()
            etapa = session.get(Video, video_id).etapa or "generacion"
            mensaje = f"falló la etapa {etapa} ({type(exc).__name__})"
            self._fallar(session, video_id, mensaje, sop_id=fila.id if fila else None)
            return
        finally:
            if deps is not None:
                deps.cerrar()

        avisos = [
            AvisoConversion(tipo=a.tipo, mensaje=a.detalle)
            for a in avisos_de(
                segmentacion, None, resultado_contexto, analisis, resultado_fotogramas
            )
        ]
        # Ya sin Gemma: una miniatura por paso del SOP generado, en su inicio (ADR-024).
        video = session.get(Video, video_id)
        miniaturas = self._miniaturas(
            video, analisis, [p.t_inicio for p in generado.sop.pasos if p.t_inicio is not None]
        )
        if miniaturas.sin_imagen and not any(a.tipo == "sin_imagen" for a in avisos):
            aviso = aviso_sin_imagen()
            avisos.append(AvisoConversion(tipo=aviso.tipo, mensaje=aviso.detalle))
        fila = session.get(Sop, fila.id)
        fila.titulo = generado.sop.titulo
        fila.contenido = generado.sop.model_dump(mode="json")
        fila.advertencias = [a.model_dump() for a in (*avisos, *generado.advertencias)]
        fila.generacion = generado.generacion.model_copy(
            update={
                "dispositivo_llm": dispositivo,
                "contexto_reusado": contexto_reusado,
                "segmentacion_reusada": segmentacion_reusada,
                "imagenes": imagenes_de(resultado_fotogramas, analisis),
            }
        ).model_dump(mode="json")
        fila.estado, fila.error = SOP_LISTO, None
        video = session.get(Video, video_id)
        video.etapa, video.progreso = "listo", 100
        video.proceso, video.error = LISTO, None
        session.commit()
        logger.info(
            "Video %d listo con SOP generado %d: %d pasos, %d advertencias",
            video_id,
            fila.id,
            len(generado.sop.pasos),
            len(fila.advertencias),
        )

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
        imagenes: bool = False,
    ) -> None:
        """Valida, guarda el reporte y deja el video listo; si algo falla, en error. Con
        `contexto` (la ficha guardada) no se vuelve a generar, y con `segmentacion` (la guardada,
        RNF-07) no se vuelve a segmentar. Con `imagenes` (y sin ficha guardada), se describen N
        imágenes antes de la ficha, N = los pasos del SOP (ADR-024). Si la validación se detiene
        por afinidad baja (sin `continuar`), guarda la detención y deja el video en
        "afinidad_baja". Con el reporte listo, una miniatura por fila con segundo.

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
        describir: DescribirImagenes | None = None
        try:
            deps = fabrica()
            sop = SOP.model_validate(sop_fila.contenido)
            if imagenes and contexto is None:
                n = cuantas_imagenes("validar", len(sop.pasos), analisis.duracion_s)
                describir = self._describidor(session, video, analisis, n)
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
                describir_imagenes=describir,
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
            video.etapa = "afinidad"
            video.progreso = inicio_etapas(describir is not None)["segmentacion"]
            video.proceso, video.error = AFINIDAD_BAJA, None
            session.commit()
            logger.info(
                "Video %d en afinidad baja (%d): espera a que quien carga decida",
                video_id,
                validacion.detencion.afinidad.valor,
            )
            return
        validacion = self._con_miniaturas(video, analisis, validacion)
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

    def _describidor(
        self, session: Session, video: Video, analisis: Analisis, n: int
    ) -> DescribirImagenes:
        """Describe `n` imágenes del video con el cliente que se le pase (misma carga de Gemma).
        Lleva la cuenta en `videos.imagenes_hechas` e `imagenes_total` para la pantalla de avance
        (RF-08); el commit va aquí para que la cuenta inicial (0 de N) se vea antes del primer
        lote."""
        archivo = self._media / video.archivo

        def contar(hechas: int, total: int) -> None:
            video.imagenes_hechas, video.imagenes_total = hechas, total
            session.commit()

        def describir(llm: ClienteLLM, al_avanzar: Callable[[float], None]) -> ResultadoFotogramas:
            return describir_fotogramas(
                archivo,
                archivo.parent,
                analisis.duracion_s,
                n,
                llm,
                al_avanzar=al_avanzar,
                al_contar=contar,
            )

        return describir

    def _miniaturas(
        self, video: Video, analisis: Analisis, tiempos: list[float]
    ) -> ResultadoMiniaturas:
        """Una miniatura por segundo de `tiempos` (ADR-024); nunca lanza."""
        archivo = self._media / video.archivo
        try:
            return generar_miniaturas(
                archivo,
                carpeta_miniaturas(archivo.parent),
                tiempos,
                analisis.duracion_s,
                get_settings().miniatura_lado_px,
            )
        except Exception as exc:  # p. ej. sin permisos en la carpeta: el resultado se guarda igual
            logger.warning("Video %d: miniaturas sin generar (%s)", video.id, type(exc).__name__)
            return ResultadoMiniaturas()

    def _con_miniaturas(
        self, video: Video, analisis: Analisis, validacion: Validacion
    ) -> Validacion:
        """Saca una miniatura por fila del reporte con segundo y devuelve la validación con
        `segundos["miniaturas"]` y, sin imagen visible, el aviso informativo "sin_imagen"."""
        pasos = validacion.resultado.resultado.clasificacion.pasos
        miniaturas = self._miniaturas(
            video, analisis, [p.t_inicio for p in pasos if p.t_inicio is not None]
        )
        metadatos = validacion.resultado.metadatos
        avisos = list(metadatos.avisos)
        if miniaturas.sin_imagen and not any(a.tipo == "sin_imagen" for a in avisos):
            avisos.append(aviso_sin_imagen())
        metadatos = metadatos.model_copy(
            update={
                "avisos": avisos,
                "segundos": {**metadatos.segundos, "miniaturas": miniaturas.segundos},
            }
        )
        resultado = validacion.resultado.model_copy(update={"metadatos": metadatos})
        return replace(validacion, resultado=resultado)

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
    def _fallar(
        session: Session, video_id: int, mensaje: str, *, sop_id: int | None = None
    ) -> None:
        """Deja el video en error con `mensaje` (y su SOP generado, si se pasa)."""
        session.rollback()
        if sop_id is not None and (fila := session.get(Sop, sop_id)) is not None:
            fila.estado, fila.error = SOP_ERROR, mensaje
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


def _fila_generada(session: Session, video: Video) -> Sop:
    """La fila del SOP generado del video, en "convirtiendo": la que ya tenía si es generada y
    no está en la biblioteca; si no, una nueva (un SOP de la biblioteca puede ser la referencia de
    otros videos y no se pisa). `videos.sop_id` apunta a ella. No hace commit."""
    previa = session.get(Sop, video.sop_id) if video.sop_id is not None else None
    if previa is not None and previa.origen == "generado" and not previa.en_biblioteca:
        fila = previa
    else:
        fila = Sop(origen="generado", en_biblioteca=False)
        session.add(fila)
    fila.estado, fila.error = SOP_CONVIRTIENDO, None
    session.flush()
    video.sop_id = fila.id
    return fila


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
