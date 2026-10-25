"""Subida de videos completos (RF-06 del MVP) y consulta del análisis.

`POST /videos` guarda el archivo en `MEDIA_DIR/videos/<id>/video.<ext>`, crea la fila con
`proceso="en_cola"` y encola el análisis; responde 202 con el id. El archivo se copia por
bloques; en la fila va la ruta relativa a `MEDIA_DIR`, nunca el nombre original. El tamaño se
limita dos veces: `limitar_content_length` rechaza la petición antes de recibirla si el
`Content-Length` ya excede el límite, y la copia cuenta los bytes reales.

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
from sopvid.percepcion.pipeline import ARCHIVO_TXT
from sopvid.percepcion.transcripcion import Transcriptor, TranscriptorWhisper
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import MODOS_VIDEO, Video
from sopvid.plataforma.procesamiento import EN_COLA, LISTO, Procesador, leer_analisis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["videos"])

EXTENSIONES = (".mp4", ".mov", ".mkv", ".webm")
BLOQUE = 1024 * 1024
# Holgura para los campos del formulario y los separadores multipart en el Content-Length.
HOLGURA_FORMULARIO = 1024 * 1024
_IDIOMA = re.compile(r"^[a-z]{2,3}$")


class VideoCreado(BaseModel):
    id: int
    proceso: str


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

    video = Video(titulo=titulo, archivo="", modo=modo, idioma=idioma, proceso=EN_COLA)
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
    return VideoCreado(id=video.id, proceso=video.proceso)


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


def _detalle_tamano(settings: Settings) -> str:
    return f"el video pasa del límite de {settings.subida_max_mb} MB"
