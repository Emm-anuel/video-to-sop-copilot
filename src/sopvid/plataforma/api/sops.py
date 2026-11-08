"""Carga del SOP de referencia (RF-01, RF-02, RF-03, ADR-015) y su consulta.

`POST /sops` acepta Markdown, TXT, PDF y Word (.docx). `leer_sop` saca el texto
(`lectura_sop.extraer_texto`) y lo convierte igual en los cuatro formatos
(`lectura_sop.convertir_documento`): con la plantilla si la sigue (`convertir_sop`, sin LLM) y,
si no, con Gemma 4. La respuesta dice cuál (`metodo`). Si hace falta el LLM y
Ollama no responde, 503 sin guardar nada: el usuario vuelve a subir el archivo cuando Ollama esté
arriba (mismo criterio que ADR-019). `POST /videos` usa `leer_sop` y `guardar_sop` cuando el SOP
viene adjunto al video (RF-02).

`guardar_sop` crea la fila con el SOP del contrato en `contenido` y deja el archivo original en
`MEDIA_DIR/sops/<id>/original.<ext>`; en la fila va la ruta relativa a `MEDIA_DIR`, nunca el
nombre original. Un SOP se lee entero en memoria: hasta `SOP_MAX_BYTES` si es texto y hasta
`SOP_DOCUMENTO_MAX_BYTES` si es PDF o Word (pueden traer imágenes).
"""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sopvid.contrato import SOP
from sopvid.lenguaje.lectura_sop import (
    EXTENSIONES,
    EXTENSIONES_TEXTO,
    ErrorConversionLLM,
    ErrorLectura,
    convertir_documento,
    extraer_texto,
)
from sopvid.lenguaje.llm import ClienteLLM, LLMError
from sopvid.lenguaje.sop_markdown import MetodoConversion, ResultadoConversion
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Sop

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sops"])

SOP_MAX_BYTES = 1024 * 1024
SOP_DOCUMENTO_MAX_BYTES = 20 * 1024 * 1024
TITULO_MAX = 300  # largo de `sops.titulo`
MENSAJE_LLM_NO_DISPONIBLE = (
    "El SOP no sigue la plantilla y el LLM (Ollama) no responde, así que no se guardó nada. "
    "Vuelve a subirlo cuando Ollama esté arriba, o súbelo con la plantilla "
    "(docs/contrato/plantilla_sop.md)."
)

# Crea el cliente del LLM; solo se llama si el documento no sigue la plantilla.
FabricaLLM = Callable[[], ClienteLLM]


class AdvertenciaSOP(BaseModel):
    tipo: str
    linea: int | None
    mensaje: str


class SopCreado(BaseModel):
    id: int
    codigo: str
    titulo: str
    metodo: MetodoConversion
    advertencias: list[AdvertenciaSOP]


class SopDetalle(BaseModel):
    id: int
    codigo: str
    origen: str
    creado: datetime
    sop: SOP


@dataclass(frozen=True)
class SopLeido:
    """El archivo original y su conversión, listos para `guardar_sop`."""

    datos: bytes
    extension: str
    conversion: ResultadoConversion


def get_fabrica_llm(settings: Annotated[Settings, Depends(get_settings)]) -> FabricaLLM:
    """Gemma 4 por Ollama (LLM_*) para los PDF y Word sin plantilla."""
    return lambda: ClienteLLM.desde_settings(settings)


def leer_sop(archivo: UploadFile, settings: Settings, fabrica_llm: FabricaLLM) -> SopLeido:
    """Lee y convierte el SOP subido, sin tocar la base.

    Errores como `HTTPException`: 415 por la extensión, 413 por el tamaño, 422 si no se puede
    leer o convertir, y 503 si hace falta el LLM y Ollama no responde o se cae.
    """
    extension = Path(archivo.filename or "").suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(415, f"extensión no permitida; usa {', '.join(EXTENSIONES)}")
    maximo = SOP_MAX_BYTES if extension in EXTENSIONES_TEXTO else SOP_DOCUMENTO_MAX_BYTES
    datos = archivo.file.read(maximo + 1)
    if len(datos) > maximo:
        raise HTTPException(413, f"el SOP pasa del límite de {maximo // (1024 * 1024)} MB")
    try:
        texto = extraer_texto(datos, extension)
        conversion = convertir_documento(texto, fabrica_llm, plazo_s=settings.llm_health_timeout_s)
    except (ErrorLectura, ErrorConversionLLM) as exc:
        raise HTTPException(422, str(exc)) from None
    except LLMError as exc:
        logger.warning("SOP sin convertir: LLM no disponible (%s)", type(exc).__name__)
        raise HTTPException(503, MENSAJE_LLM_NO_DISPONIBLE) from None
    if len(conversion.sop.titulo) > TITULO_MAX:
        raise HTTPException(422, f"el título del SOP pasa de {TITULO_MAX} caracteres")
    return SopLeido(datos, extension, conversion)


def guardar_sop(session: Session, settings: Settings, leido: SopLeido) -> Sop:
    """Agrega la fila (sin commit) y escribe el original.

    Si la escritura falla, revierte la sesión y borra la carpeta. Quien llama hace el commit y,
    si algo falla después, borra `carpeta_sop(settings, fila.id)`.
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
    destino = settings.media_path / relativa
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(leido.datos)
    except BaseException:
        session.rollback()
        shutil.rmtree(destino.parent, ignore_errors=True)
        raise
    fila.archivo_original = str(relativa)
    return fila


def carpeta_sop(settings: Settings, sop_id: int) -> Path:
    return settings.media_path / "sops" / str(sop_id)


def sop_creado(fila: Sop, conversion: ResultadoConversion) -> SopCreado:
    """Respuesta de un SOP ya guardado (después del commit y el refresh, para tener `codigo`)."""
    return SopCreado(
        id=fila.id,
        codigo=fila.codigo,
        titulo=fila.titulo,
        metodo=conversion.metodo,
        advertencias=[
            AdvertenciaSOP(tipo=a.tipo, linea=a.linea, mensaje=a.mensaje)
            for a in conversion.advertencias
        ],
    )


@router.post("/sops", status_code=201, response_model=SopCreado)
def cargar_sop(
    response: Response,
    archivo: Annotated[
        UploadFile, File(description="SOP en Markdown (.md), texto (.txt), PDF o Word (.docx)")
    ],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    fabrica_llm: Annotated[FabricaLLM, Depends(get_fabrica_llm)],
) -> SopCreado:
    leido = leer_sop(archivo, settings, fabrica_llm)
    fila = guardar_sop(session, settings, leido)
    session.commit()
    session.refresh(fila)  # `codigo` lo calcula la base
    logger.info(
        "SOP %d cargado (%s, %s): %d pasos, %d advertencias",
        fila.id,
        leido.extension,
        leido.conversion.metodo,
        len(leido.conversion.sop.pasos),
        len(leido.conversion.advertencias),
    )
    response.headers["Location"] = f"/sops/{fila.id}"
    return sop_creado(fila, leido.conversion)


@router.get("/sops/{sop_id}", response_model=SopDetalle)
def detalle_sop(sop_id: int, session: Annotated[Session, Depends(get_session)]) -> SopDetalle:
    fila = session.get(Sop, sop_id)
    if fila is None:
        raise HTTPException(404, "SOP no encontrado")
    return SopDetalle(
        id=fila.id,
        codigo=fila.codigo,
        origen=fila.origen,
        creado=fila.creado,
        sop=SOP.model_validate(fila.contenido),
    )
