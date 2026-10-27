"""Carga del SOP de referencia en Markdown o TXT (RF-03, ADR-015) y su consulta.

`POST /sops` convierte el archivo con `convertir_sop` (plantilla y código, sin LLM), guarda la
fila con el SOP del contrato en `contenido` y el archivo original en
`MEDIA_DIR/sops/<id>/original.<ext>`. En la fila va la ruta relativa a `MEDIA_DIR`, nunca el
nombre original. Un SOP es texto: se lee entero en memoria, hasta `SOP_MAX_BYTES`.

PDF y Word (RF-01) llegan en S5.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sopvid.contrato import SOP
from sopvid.lenguaje.sop_markdown import ErrorSOP, convertir_sop
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Sop

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sops"])

EXTENSIONES = (".md", ".txt")
SOP_MAX_BYTES = 1024 * 1024
TITULO_MAX = 300  # largo de `sops.titulo`


class AdvertenciaSOP(BaseModel):
    tipo: str
    linea: int | None
    mensaje: str


class SopCreado(BaseModel):
    id: int
    codigo: str
    titulo: str
    advertencias: list[AdvertenciaSOP]


class SopDetalle(BaseModel):
    id: int
    codigo: str
    origen: str
    creado: datetime
    sop: SOP


@router.post("/sops", status_code=201, response_model=SopCreado)
def cargar_sop(
    response: Response,
    archivo: Annotated[UploadFile, File(description="SOP en Markdown (.md) o texto (.txt)")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SopCreado:
    extension = Path(archivo.filename or "").suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(415, f"extensión no permitida; usa {', '.join(EXTENSIONES)}")
    datos = archivo.file.read(SOP_MAX_BYTES + 1)
    if len(datos) > SOP_MAX_BYTES:
        raise HTTPException(413, f"el SOP pasa del límite de {SOP_MAX_BYTES // (1024 * 1024)} MB")
    try:
        texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "el archivo debe estar en UTF-8") from None
    try:
        conversion = convertir_sop(texto)
    except ErrorSOP as exc:
        raise HTTPException(422, str(exc)) from None
    sop = conversion.sop
    if len(sop.titulo) > TITULO_MAX:
        raise HTTPException(422, f"el título del SOP pasa de {TITULO_MAX} caracteres")

    fila = Sop(
        titulo=sop.titulo,
        origen="cargado",
        archivo_original="",
        contenido=sop.model_dump(mode="json"),
    )
    session.add(fila)
    session.flush()  # asigna el id
    relativa = PurePosixPath("sops", str(fila.id), f"original{extension}")
    destino = settings.media_path / relativa
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    except BaseException:
        session.rollback()
        shutil.rmtree(destino.parent, ignore_errors=True)
        raise
    fila.archivo_original = str(relativa)
    session.commit()
    session.refresh(fila)  # `codigo` lo calcula la base
    logger.info(
        "SOP %d cargado: %d pasos, %d advertencias",
        fila.id,
        len(sop.pasos),
        len(conversion.advertencias),
    )
    response.headers["Location"] = f"/sops/{fila.id}"
    return SopCreado(
        id=fila.id,
        codigo=fila.codigo,
        titulo=fila.titulo,
        advertencias=[
            AdvertenciaSOP(tipo=a.tipo, linea=a.linea, mensaje=a.mensaje)
            for a in conversion.advertencias
        ],
    )


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
