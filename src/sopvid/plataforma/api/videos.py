"""Subida de videos completos (RF-06 del MVP), consulta del análisis y del reporte (RF-20).

`POST /videos` guarda el archivo en `MEDIA_DIR/videos/<id>/video.<ext>`, crea la fila con
`proceso="en_cola"` y encola el análisis; responde 202 con el id. El archivo se copia por
bloques; en la fila va la ruta relativa a `MEDIA_DIR`, nunca el nombre original. El tamaño se
limita dos veces: `limitar_content_length` rechaza la petición antes de recibirla si el
`Content-Length` ya excede el límite, y la copia cuenta los bytes reales.

Con `modo="validar"` entra también el SOP: el archivo `sop` (Markdown o TXT, se convierte con
código, ADR-015) o un `sop_id` de la biblioteca. Se convierte aquí, antes de gastar GPU, para
devolver el error de plantilla de inmediato; el trabajador hace la validación al terminar el
análisis y `GET /videos/{id}/reporte` la entrega.

La subida por partes de 16 MB con reintentos es de S5; aquí no está.
"""

import logging
import re
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sopvid.contrato import Analisis
from sopvid.lenguaje.reporte import Reporte
from sopvid.lenguaje.sop_markdown import ErrorSOP
from sopvid.percepcion.pipeline import ARCHIVO_TXT
from sopvid.percepcion.transcripcion import Transcriptor, TranscriptorWhisper
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import MODOS_VIDEO, Video
from sopvid.plataforma.procesamiento import (
    EN_COLA,
    LISTO,
    VALIDAR,
    Procesador,
    leer_analisis,
)
from sopvid.plataforma.sops import SinSOP, guardar_sop, sop_de
from sopvid.plataforma.validacion import leer_reporte

logger = logging.getLogger(__name__)

router = APIRouter(tags=["videos"])

EXTENSIONES = (".mp4", ".mov", ".mkv", ".webm")
EXTENSIONES_SOP = (".md", ".markdown", ".txt")
BLOQUE = 1024 * 1024
# Un SOP de referencia es texto: 2 MB es holgura de sobra para la plantilla.
LIMITE_SOP = 2 * BLOQUE
# Holgura para los campos del formulario y los separadores multipart en el Content-Length.
HOLGURA_FORMULARIO = 1024 * 1024
_IDIOMA = re.compile(r"^[a-z]{2,3}$")


class VideoCreado(BaseModel):
    id: int
    proceso: str
    sop_id: int | None = None


class EstadoVideo(BaseModel):
    id: int
    titulo: str
    modo: str
    proceso: str
    etapa: str | None
    progreso: int
    duracion: float | None
    idioma: str | None
    error: str | None
    creado: datetime


def get_procesador(request: Request) -> Procesador:
    return request.app.state.procesador


def get_transcriptor(settings: Annotated[Settings, Depends(get_settings)]) -> Transcriptor:
    """Transcriptor según WHISPER_*; el modelo solo se carga al transcribir."""
    return TranscriptorWhisper(settings)


async def limitar_content_length(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: 413 antes de recibir el cuerpo si `Content-Length` ya excede el límite."""
    if request.method == "POST" and request.url.path == "/videos":
        settings = request.app.dependency_overrides.get(get_settings, get_settings)()
        largo = request.headers.get("content-length")
        maximo = settings.subida_max_bytes + HOLGURA_FORMULARIO
        if largo and largo.isdigit() and int(largo) > maximo:
            return JSONResponse(status_code=413, content={"detail": _detalle_tamano(settings)})
    return await call_next(request)


@router.post("/videos", status_code=202, response_model=VideoCreado)
def subir_video(
    response: Response,
    archivo: Annotated[UploadFile, File(description="Video completo: mp4, mov, mkv o webm")],
    titulo: Annotated[str, Form(min_length=1, max_length=300)],
    modo: Annotated[str, Form(description="validar | generar")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    procesador: Annotated[Procesador, Depends(get_procesador)],
    transcriptor: Annotated[Transcriptor, Depends(get_transcriptor)],
    idioma: Annotated[str | None, Form(description="ISO 639-1 para fijarlo (p. ej. es)")] = None,
    sop: Annotated[
        UploadFile | None, File(description="SOP de referencia en Markdown o TXT (validar)")
    ] = None,
    sop_id: Annotated[int | None, Form(description="id de un SOP ya guardado")] = None,
) -> VideoCreado:
    extension = Path(archivo.filename or "").suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(415, f"extensión no permitida; usa {', '.join(EXTENSIONES)}")
    if modo not in MODOS_VIDEO:
        raise HTTPException(422, f"modo debe ser uno de {', '.join(MODOS_VIDEO)}")
    titulo = titulo.strip()
    if not titulo:
        raise HTTPException(422, "el título no puede ir vacío")
    idioma = (idioma or "").strip().lower() or None
    if idioma is not None and not _IDIOMA.match(idioma):
        raise HTTPException(422, "idioma debe ser un código ISO 639-1, p. ej. 'es'")
    if sop is not None and sop_id is not None:
        raise HTTPException(422, "usa el archivo 'sop' o 'sop_id', no los dos")
    if modo == VALIDAR and sop is None and sop_id is None:
        raise HTTPException(422, "modo validar necesita el SOP: el archivo 'sop' o un 'sop_id'")
    if sop is not None and Path(sop.filename or "").suffix.lower() not in EXTENSIONES_SOP:
        raise HTTPException(415, f"el SOP va en {', '.join(EXTENSIONES_SOP)}")

    # El SOP se resuelve antes de escribir nada: si la plantilla no sirve, la petición falla sin
    # gastar GPU ni dejar filas a medias.
    fila_sop = None
    if sop is not None:
        try:
            fila_sop = guardar_sop(session, _texto_de(sop))
        except ErrorSOP as exc:
            session.rollback()
            raise HTTPException(422, str(exc)) from None
    elif sop_id is not None:
        try:
            fila_sop = sop_de(session, sop_id)
        except SinSOP as exc:
            raise HTTPException(404, str(exc)) from None

    video = Video(
        titulo=titulo,
        archivo="",
        modo=modo,
        idioma=idioma,
        proceso=EN_COLA,
        sop_id=fila_sop.id if fila_sop is not None else None,
    )
    session.add(video)
    session.flush()  # asigna el id
    relativa = PurePosixPath("videos", str(video.id), f"video{extension}")
    destino = settings.media_path / relativa
    try:
        _copiar(archivo.file, destino, settings.subida_max_bytes)
    except _TamanoExcedido:
        session.rollback()
        shutil.rmtree(destino.parent, ignore_errors=True)
        raise HTTPException(413, _detalle_tamano(settings)) from None
    except BaseException:
        session.rollback()
        shutil.rmtree(destino.parent, ignore_errors=True)
        raise
    video.archivo = str(relativa)
    session.commit()
    logger.info(
        "Video %d recibido (%s, %.1f MB)", video.id, extension, destino.stat().st_size / 1e6
    )

    procesador.encolar(video.id, idioma, transcriptor)
    response.headers["Location"] = f"/videos/{video.id}"
    return VideoCreado(id=video.id, proceso=video.proceso, sop_id=video.sop_id)


@router.get("/videos/{video_id}", response_model=EstadoVideo)
def estado_video(video_id: int, session: Annotated[Session, Depends(get_session)]) -> EstadoVideo:
    video = _buscar(session, video_id)
    return EstadoVideo.model_validate(video, from_attributes=True)


@router.get("/videos/{video_id}/transcripcion.txt")
def transcripcion_txt(
    video_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """El TXT tal como va (RF-10): vacío si la transcripción todavía no empieza."""
    video = _buscar(session, video_id)
    ruta = settings.media_path / "videos" / str(video.id) / ARCHIVO_TXT
    contenido = ruta.read_bytes() if ruta.is_file() else b""
    return Response(
        content=contenido,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="transcripcion-{video.id}.txt"'},
    )


@router.get("/videos/{video_id}/analisis", response_model=Analisis)
def analisis_video(video_id: int, session: Annotated[Session, Depends(get_session)]) -> Analisis:
    video = _buscar(session, video_id)
    if video.proceso != LISTO:
        raise HTTPException(
            409, {"mensaje": "el análisis no ha terminado", "proceso": video.proceso}
        )
    return leer_analisis(video)


@router.get("/videos/{video_id}/reporte", response_model=Reporte)
def reporte_video(video_id: int, session: Annotated[Session, Depends(get_session)]) -> Reporte:
    """El reporte de validación (RF-20): porcentaje, semáforo y la tabla con cita y segundo."""
    video = _buscar(session, video_id)
    if video.proceso != LISTO:
        raise HTTPException(
            409, {"mensaje": "la validación no ha terminado", "proceso": video.proceso}
        )
    reporte = leer_reporte(video)
    if reporte is None:
        raise HTTPException(404, "el video no tiene reporte: se subió con modo generar o sin SOP")
    return reporte


def _buscar(session: Session, video_id: int) -> Video:
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video no encontrado")
    return video


class _TamanoExcedido(Exception):  # noqa: N818 (nombre de dominio)
    pass


def _copiar(origen: BinaryIO, destino: Path, limite: int) -> None:
    """Copia por bloques sin cargar el archivo en memoria; falla si pasa de `limite` bytes."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destino.open("wb") as salida:
        while bloque := origen.read(BLOQUE):
            total += len(bloque)
            if total > limite:
                raise _TamanoExcedido
            salida.write(bloque)


def _texto_de(archivo: UploadFile) -> str:
    """El SOP como texto UTF-8 (el BOM se descarta: PowerShell lo agrega)."""
    contenido = archivo.file.read(LIMITE_SOP + 1)
    if len(contenido) > LIMITE_SOP:
        raise HTTPException(413, f"el SOP pasa del límite de {LIMITE_SOP // BLOQUE} MB")
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "el SOP debe estar en UTF-8") from None


def _detalle_tamano(settings: Settings) -> str:
    return f"el video pasa del límite de {settings.subida_max_mb} MB"
