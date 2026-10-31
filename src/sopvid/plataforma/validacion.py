"""Validación de un video contra su SOP: pasos → emparejamiento → reporte (RF-14, RF-19, RF-20).

Encadena lo que ya existe, sin agregar lógica de decisión: `segmentacion.segmentar` saca los
pasos del video sin ver el SOP (regla 5 de CLAUDE.md), el `Emparejador` hace la cascada
(ADR-012, ADR-013) y `lenguaje.reporte.armar_reporte` calcula el porcentaje y el semáforo. El
resultado va a `reportes` (uno por video) y los pasos del video, a `videos.pasos_video`.

Lo corre el trabajador de `procesamiento` al terminar el análisis, cuando el video se subió con
`modo="validar"` y su SOP: así la transcripción y la validación comparten el mismo turno de GPU
(un modelo a la vez, ADR-014) y la pantalla solo consulta `GET /videos/{id}`.

El LLM y el emparejador se pueden inyectar: con `llm=None` los pasos salen de la heurística y no
hay juez, y con un `Emparejador` propio no se carga MiniLM. Las pruebas usan eso; en producción
se arman desde la configuración. Si Ollama no responde, `segmentar` cae a la heurística y el
juez deja los pares dudosos como "sin revisar" (zona_gris), sin fallar el reporte.

Un error aquí deja el video en `proceso="error"` con la etapa, sin texto del video en el mensaje:
lo mismo que el resto de `procesamiento` (un `ValidationError` de pydantic lleva el texto
transcrito).
"""

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from sopvid.contrato import SOP, Analisis
from sopvid.lenguaje.emparejamiento import Emparejador, EmparejadorMiniLM
from sopvid.lenguaje.juez import JuezGemma
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.reporte import OrigenPasos, Reporte, armar_reporte
from sopvid.percepcion.segmentacion import segmentar
from sopvid.plataforma.modelos import Reporte as ReporteORM
from sopvid.plataforma.modelos import Sop, Video
from sopvid.plataforma.procesamiento import leer_analisis
from sopvid.plataforma.sops import SinSOP, contrato_de

logger = logging.getLogger(__name__)


def validar_y_guardar(
    session: Session,
    video: Video,
    *,
    llm: ClienteLLM | None = None,
    emparejador: Emparejador | None = None,
) -> Reporte:
    """Valida el video contra el SOP de su fila y guarda el reporte. Devuelve el `Reporte`.

    Lanza `SinSOP` si el video no tiene SOP. Sin `llm` ni `emparejador`, arma los de producción
    (Ollama y MiniLM) y cierra el cliente al terminar.
    """
    fila = _fila_del_sop(session, video)
    sop = contrato_de(fila)
    analisis = leer_analisis(video)
    if llm is not None or emparejador is not None:
        return _validar(session, video, fila, sop, analisis, llm, emparejador)
    with ClienteLLM.desde_settings() as cliente:
        return _validar(session, video, fila, sop, analisis, cliente, None)


def leer_reporte(video: Video) -> Reporte | None:
    """El reporte guardado del video, o `None` si todavía no hay."""
    if video.reporte is None:
        return None
    return Reporte.model_validate(video.reporte.resultado)


def _fila_del_sop(session: Session, video: Video) -> Sop:
    if video.sop_id is None:
        raise SinSOP(f"el video {video.id} no tiene SOP")
    fila = session.get(Sop, video.sop_id)
    if fila is None:
        raise SinSOP(f"el SOP {video.sop_id} del video {video.id} no existe")
    return fila


def _validar(
    session: Session,
    video: Video,
    fila: Sop,
    sop: SOP,
    analisis: Analisis,
    llm: ClienteLLM | None,
    emparejador: Emparejador | None,
) -> Reporte:
    segmentacion = segmentar(analisis, llm)
    video.pasos_video = [paso.model_dump(mode="json") for paso in segmentacion.pasos]
    if emparejador is None:
        # El juez necesita la transcripción para leer la narración de cada paso; sin ella (video
        # mudo), se empareja sin juez y los pares dudosos quedan como "sin revisar".
        juez = JuezGemma(llm) if llm is not None and analisis.transcripcion else None
        emparejador = EmparejadorMiniLM(juez=juez)
    resultado = emparejador.emparejar(sop, segmentacion.pasos, transcripcion=analisis.transcripcion)
    reporte = armar_reporte(
        video.id,
        sop,
        resultado,
        OrigenPasos(
            metodo=segmentacion.metodo,
            modelo=segmentacion.modelo,
            pasos=len(segmentacion.pasos),
        ),
        sop_id=fila.id,
    )
    _guardar(session, video, fila, reporte)
    logger.info(
        "Video %d validado: %.2f %% (%s), %d filas, %d paso(s) del video por %s",
        video.id,
        reporte.cumplimiento,
        reporte.semaforo,
        len(reporte.filas),
        len(segmentacion.pasos),
        segmentacion.metodo,
    )
    return reporte


def _guardar(session: Session, video: Video, fila: Sop, reporte: Reporte) -> None:
    """Escribe (o reemplaza) la fila de `reportes` del video. Hace commit."""
    datos = reporte.model_dump(mode="json")
    cumplimiento = Decimal(str(reporte.cumplimiento))
    existente = video.reporte
    if existente is None:
        # `video.reporte = ...` fija los dos lados de la relación: el ORM pone video_id y la
        # próxima lectura del video ya ve el reporte.
        video.reporte = ReporteORM(
            sop_id=fila.id,
            cumplimiento=cumplimiento,
            resultado=datos,
        )
    else:
        existente.sop_id = fila.id
        existente.cumplimiento = cumplimiento
        existente.resultado = datos
    # RF-17 (afinidad con la ficha de contexto) llega en S5: la columna queda vacía.
    video.reporte.afinidad = None
    session.commit()
