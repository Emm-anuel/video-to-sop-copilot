"""Carga del SOP de referencia (RF-01, RF-02, RF-03, ADR-015) y su consulta.

`POST /sops` acepta Markdown, TXT, PDF y Word (.docx) y siempre responde 202: revisa la
extensión, el tamaño y que se pueda sacar el texto (`leer_archivo_sop`: 415, 413 o 422 sin
guardar nada), crea la fila en "en_cola" con el original y encola la conversión en el
trabajador, antes que el siguiente video. `Location` apunta a `GET /sops/{id}/estado`
(`EstadoSop` del contrato: en_cola, convirtiendo, listo o error, con el mensaje y las
advertencias al terminar). La plantilla también pasa por el trabajador y termina al instante;
un SOP sin plantilla lo convierte Gemma 4 (`lectura_sop.convertir_documento`).

`GET /sops/{id}` da el SOP del contrato y 409 mientras no esté listo. `POST /videos` usa
`leer_archivo_sop` y `procesamiento.crear_sop_en_cola` cuando el SOP viene adjunto (RF-02).

Un SOP se lee entero en memoria: hasta `SOP_MAX_BYTES` si es texto y hasta
`SOP_DOCUMENTO_MAX_BYTES` si es PDF o Word (pueden traer imágenes).
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sopvid.contrato import SOP, AvisoConversion, EstadoSop, MetodoConversionSop
from sopvid.lenguaje.lectura_sop import (
    EXTENSIONES,
    EXTENSIONES_TEXTO,
    AjustesConversion,
    ErrorLectura,
    extraer_texto,
)
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Sop
from sopvid.plataforma.procesamiento import (
    SOP_LISTO,
    FabricaLLM,
    Procesador,
    carpeta_sop,
    crear_sop_en_cola,
)

__all__ = ["FabricaLLM", "carpeta_sop", "get_fabrica_llm", "get_procesador", "leer_archivo_sop"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sops"])

SOP_MAX_BYTES = 1024 * 1024
SOP_DOCUMENTO_MAX_BYTES = 20 * 1024 * 1024


class SopDetalle(BaseModel):
    """`metodo` y `advertencias`: cómo se convirtió (None y [] en un SOP generado o anterior a
    la migración 0003)."""

    id: int
    codigo: str
    origen: str
    creado: datetime
    metodo: MetodoConversionSop | None
    advertencias: list[AvisoConversion]
    sop: SOP


@dataclass(frozen=True)
class ArchivoSop:
    """El archivo subido, ya revisado (extensión, tamaño y texto legible)."""

    datos: bytes
    extension: str


def get_procesador(request: Request) -> Procesador:
    return request.app.state.procesador


def get_fabrica_llm(settings: Annotated[Settings, Depends(get_settings)]) -> FabricaLLM:
    """Gemma 4 por Ollama (LLM_*) para los SOP sin plantilla; se usa dentro del trabajo."""
    return lambda: ClienteLLM.desde_settings(settings)


def leer_archivo_sop(archivo: UploadFile) -> ArchivoSop:
    """Revisa la extensión y el tamaño y que se pueda sacar el texto, sin convertir. Errores
    como `HTTPException`: 415 por la extensión, 413 por el tamaño y 422 si no se puede leer
    (PDF escaneado, archivo dañado, texto que no es UTF-8)."""
    extension = Path(archivo.filename or "").suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(415, f"extensión no permitida; usa {', '.join(EXTENSIONES)}")
    maximo = SOP_MAX_BYTES if extension in EXTENSIONES_TEXTO else SOP_DOCUMENTO_MAX_BYTES
    datos = archivo.file.read(maximo + 1)
    if len(datos) > maximo:
        raise HTTPException(413, f"el SOP pasa del límite de {maximo // (1024 * 1024)} MB")
    try:
        extraer_texto(datos, extension)
    except ErrorLectura as exc:
        raise HTTPException(422, str(exc)) from None
    return ArchivoSop(datos, extension)


def estado_sop(fila: Sop) -> EstadoSop:
    """`EstadoSop` de la fila (después del commit, para tener `codigo`)."""
    return EstadoSop(
        id=fila.id,
        codigo=fila.codigo,
        estado=fila.estado,
        titulo=fila.titulo,
        metodo=fila.metodo,
        mensaje=fila.error,
        advertencias=[AvisoConversion.model_validate(a) for a in fila.advertencias or []],
    )


@router.post("/sops", status_code=202, response_model=EstadoSop)
def cargar_sop(
    response: Response,
    archivo: Annotated[
        UploadFile, File(description="SOP en Markdown (.md), texto (.txt), PDF o Word (.docx)")
    ],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    procesador: Annotated[Procesador, Depends(get_procesador)],
    fabrica_llm: Annotated[FabricaLLM, Depends(get_fabrica_llm)],
) -> EstadoSop:
    """Encola la conversión y responde 202; el resultado, en `GET /sops/{id}/estado`."""
    leido = leer_archivo_sop(archivo)
    fila = crear_sop_en_cola(session, settings.media_path, leido.datos, leido.extension)
    session.commit()
    session.refresh(fila)  # `codigo` lo calcula la base
    procesador.encolar_sop(fila.id, fabrica_llm, AjustesConversion.desde_settings(settings))
    logger.info("SOP %d en cola (%s)", fila.id, leido.extension)
    response.headers["Location"] = f"/sops/{fila.id}/estado"
    return estado_sop(fila)


@router.get("/sops/{sop_id}/estado", response_model=EstadoSop)
def consultar_estado_sop(
    sop_id: int, session: Annotated[Session, Depends(get_session)]
) -> EstadoSop:
    """Dónde va la conversión; con "listo", el método y las advertencias."""
    return estado_sop(_buscar(session, sop_id))


@router.get("/sops/{sop_id}", response_model=SopDetalle)
def detalle_sop(sop_id: int, session: Annotated[Session, Depends(get_session)]) -> SopDetalle:
    """El SOP del contrato; 409 mientras la conversión no esté lista (o si falló)."""
    fila = _buscar(session, sop_id)
    if fila.estado != SOP_LISTO:
        raise HTTPException(
            409, {"mensaje": "el SOP no está listo", "estado": fila.estado, "error": fila.error}
        )
    return SopDetalle(
        id=fila.id,
        codigo=fila.codigo,
        origen=fila.origen,
        creado=fila.creado,
        metodo=fila.metodo,
        advertencias=[AvisoConversion.model_validate(a) for a in fila.advertencias],
        sop=SOP.model_validate(fila.contenido),
    )


def _buscar(session: Session, sop_id: int) -> Sop:
    fila = session.get(Sop, sop_id)
    if fila is None:
        raise HTTPException(404, "SOP no encontrado")
    return fila
