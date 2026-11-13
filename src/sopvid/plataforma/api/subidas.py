"""Subida del video por partes (RF-06): `/uploads`.

`POST /uploads` abre una subida y dice el tamaño de parte (`SUBIDA_PARTE_MB`, 16 por defecto);
`PUT /uploads/{id}?offset=N` recibe una parte en el cuerpo; `GET /uploads/{id}` dice cuánto ha
llegado (para reanudar) y `DELETE /uploads/{id}` la cancela. Al completarla, `POST /videos` con
`upload_id` (en lugar de `archivo`) la valida con ffprobe y la encola como la subida simple.

El armado vive en `sopvid.percepcion.subidas`, en disco (`media/subidas/<id>/`), sin tabla. Una
parte repetida no duplica nada; un offset adelantado da 409 con el offset correcto en
`detail.offset`; una parte mayor que el tamaño de parte, 413 (antes de leerla si el
`Content-Length` ya lo dice, en `videos.limitar_content_length`). Las subidas abandonadas se
borran por edad (`SUBIDA_CADUCIDAD_H`) al arrancar y en cada `POST /uploads` (RNF-09).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from sopvid.percepcion import subidas
from sopvid.plataforma.api.videos import (
    SUBIDA_NO_ENCONTRADA,
    detalle_parte,
    detalle_tamano,
    extension_video,
)
from sopvid.plataforma.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["uploads"])


class PedidoSubida(BaseModel):
    """`nombre` solo sirve para la extensión: no se guarda."""

    nombre: str = Field(min_length=1, max_length=255)
    tamano: int = Field(gt=0, description="Bytes del archivo completo")


class EstadoSubidaApi(BaseModel):
    upload_id: str
    tamano: int
    tamano_parte: int
    recibidos: int
    completo: bool


def _respuesta(estado: subidas.EstadoSubida) -> EstadoSubidaApi:
    return EstadoSubidaApi(
        upload_id=estado.upload_id,
        tamano=estado.tamano,
        tamano_parte=estado.tamano_parte,
        recibidos=estado.recibidos,
        completo=estado.completo,
    )


def conflicto(error: subidas.OffsetInesperado | subidas.PasaDelTamano) -> HTTPException:
    """409 con el offset en el que sigue la subida, para que el cliente se reacomode."""
    if isinstance(error, subidas.PasaDelTamano):
        mensaje = "la parte pasa del tamaño declarado al abrir la subida"
    else:
        mensaje = f"se esperaba la parte en el offset {error.recibidos}"
    return HTTPException(
        409, {"mensaje": mensaje, "offset": error.recibidos, "tamano": error.tamano}
    )


@router.post("/uploads", status_code=201, response_model=EstadoSubidaApi)
def crear_subida(
    pedido: PedidoSubida,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> EstadoSubidaApi:
    """Abre una subida: 201 con `upload_id` y `tamano_parte`. 415 por la extensión, 413 si
    `tamano` pasa de `SUBIDA_MAX_MB`. Antes borra las subidas caducadas."""
    extension = extension_video(pedido.nombre)
    if pedido.tamano > settings.subida_max_bytes:
        raise HTTPException(413, detalle_tamano(settings))
    subidas.limpiar_caducadas(settings.media_path, settings.subida_caducidad_h)
    estado = subidas.crear(
        settings.media_path, extension, pedido.tamano, settings.subida_parte_bytes
    )
    logger.info(
        "Subida %s abierta (%s, %.1f MB en partes de %.1f MB)",
        estado.upload_id,
        extension,
        estado.tamano / 1e6,
        estado.tamano_parte / 1e6,
    )
    response.headers["Location"] = f"/uploads/{estado.upload_id}"
    return _respuesta(estado)


@router.put("/uploads/{upload_id}", response_model=EstadoSubidaApi)
async def recibir_parte(
    upload_id: str,
    request: Request,
    offset: Annotated[int, Query(ge=0, description="Byte del archivo donde empieza la parte")],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EstadoSubidaApi:
    """Recibe una parte (el cuerpo, binario) y la anexa si `offset` es el siguiente.

    Idempotente: una parte ya recibida responde 200 sin escribir. 409 con
    `{"mensaje", "offset", "tamano"}` si el offset está adelantado o la parte pasa del tamaño
    declarado; 413 si la parte pasa de `tamano_parte`; 404 si la subida no existe.
    """
    media = settings.media_path
    try:
        actual = subidas.estado(media, upload_id)
        temporal = subidas.temporal_parte(media, upload_id)
    except subidas.SubidaNoEncontrada:
        raise HTTPException(404, SUBIDA_NO_ENCONTRADA) from None
    try:
        recibido = 0
        with temporal.open("wb") as salida:
            async for bloque in request.stream():
                recibido += len(bloque)
                if recibido > actual.tamano_parte:
                    raise HTTPException(413, detalle_parte(actual.tamano_parte))
                salida.write(bloque)
        nuevo = await run_in_threadpool(subidas.guardar_parte, media, upload_id, offset, temporal)
    except subidas.SubidaNoEncontrada:
        raise HTTPException(404, SUBIDA_NO_ENCONTRADA) from None
    except subidas.ParteGrande:
        raise HTTPException(413, detalle_parte(actual.tamano_parte)) from None
    except (subidas.OffsetInesperado, subidas.PasaDelTamano) as exc:
        raise conflicto(exc) from None
    except FileNotFoundError:  # la carpeta se borró mientras llegaba la parte (cancelada)
        raise HTTPException(404, SUBIDA_NO_ENCONTRADA) from None
    finally:
        temporal.unlink(missing_ok=True)
    return _respuesta(nuevo)


@router.get("/uploads/{upload_id}", response_model=EstadoSubidaApi)
def estado_subida(
    upload_id: str, settings: Annotated[Settings, Depends(get_settings)]
) -> EstadoSubidaApi:
    """Cuánto ha llegado: el cliente reanuda desde `recibidos`."""
    try:
        return _respuesta(subidas.estado(settings.media_path, upload_id))
    except subidas.SubidaNoEncontrada:
        raise HTTPException(404, SUBIDA_NO_ENCONTRADA) from None


@router.delete("/uploads/{upload_id}", status_code=204)
def cancelar_subida(upload_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Cancela la subida y borra lo recibido (RNF-09): 204, o 404 si no existe."""
    try:
        subidas.descartar(settings.media_path, upload_id)
    except subidas.SubidaNoEncontrada:
        raise HTTPException(404, SUBIDA_NO_ENCONTRADA) from None
