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

Biblioteca (RF-05, RF-27): `GET /sops` lista los SOP listos y guardados en la biblioteca con
cuántos videos se validaron con cada uno. `DELETE /sops/{id}` borra uno que nadie usa (204); si
algún video o reporte lo referencia responde 409 con el porqué, nunca en cascada (la base lo
protege con RESTRICT y aquí solo se traduce a un mensaje que se entienda).

Un SOP se lee entero en memoria: hasta `SOP_MAX_BYTES` si es texto y hasta
`SOP_DOCUMENTO_MAX_BYTES` si es PDF o Word (pueden traer imágenes).
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sopvid.contrato import SOP, AvisoConversion, EstadoSop, GeneracionSOP, MetodoConversionSop
from sopvid.lenguaje.lectura_sop import (
    EXTENSIONES,
    EXTENSIONES_TEXTO,
    AjustesConversion,
    ErrorLectura,
    extraer_texto,
)
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import sop_a_markdown
from sopvid.lenguaje.tiempos import con_duracion_recalculada
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Reporte, Sop, Video
from sopvid.plataforma.procesamiento import (
    SOP_CONVIRTIENDO,
    SOP_EN_COLA,
    SOP_LISTO,
    TITULO_SOP_MAX,
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
    """`metodo`: cómo se convirtió un SOP cargado (None en uno generado o anterior a la migración
    0003). `advertencias`: las de la conversión o las de la generación (p. ej. `sop_incompleto`).
    `en_biblioteca` (RF-27) y `generacion` (cómo se generó desde el video, ADR-023; None en un
    SOP cargado)."""

    id: int
    codigo: str
    origen: str
    creado: datetime
    metodo: MetodoConversionSop | None
    advertencias: list[AvisoConversion]
    en_biblioteca: bool = True
    generacion: GeneracionSOP | None = None
    sop: SOP


class SopResumen(BaseModel):
    """Un SOP de la biblioteca en `GET /sops`. `videos_validados`: los videos con reporte de
    validación contra este SOP (uno por video)."""

    id: int
    codigo: str
    titulo: str
    origen: str
    creado: datetime
    videos_validados: int


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
        origen=fila.origen,
        en_biblioteca=fila.en_biblioteca,
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


@router.get("/sops", response_model=list[SopResumen])
def listar_sops(session: Annotated[Session, Depends(get_session)]) -> list[SopResumen]:
    """La biblioteca (RF-05): los SOP listos y guardados en ella, del más nuevo al más viejo. No
    lista los que están en cola, convirtiéndose o con error, ni los generados que nadie guardó."""
    validados = func.count(func.distinct(Reporte.video_id))
    filas = session.execute(
        select(Sop, validados)
        .outerjoin(Reporte, Reporte.sop_id == Sop.id)
        .where(Sop.en_biblioteca.is_(True), Sop.estado == SOP_LISTO)
        .group_by(Sop.id)
        .order_by(Sop.creado.desc(), Sop.id.desc())
    ).all()
    return [
        SopResumen(
            id=fila.id,
            codigo=fila.codigo,
            titulo=fila.titulo or "",
            origen=fila.origen,
            creado=fila.creado,
            videos_validados=n,
        )
        for fila, n in filas
    ]


@router.delete("/sops/{sop_id}", status_code=204)
def borrar_sop(
    sop_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Borra un SOP que nadie usa (RF-05) y su archivo original: 204. 409 si se está
    convirtiendo o si algún video o reporte lo referencia; nunca borra en cascada."""
    fila = _buscar(session, sop_id)
    if fila.estado in (SOP_EN_COLA, SOP_CONVIRTIENDO):
        raise HTTPException(
            409,
            {
                "mensaje": f"El SOP {fila.codigo} se está convirtiendo: espera a que termine "
                "para eliminarlo.",
                "estado": fila.estado,
            },
        )
    _sin_uso(session, fila)
    codigo = fila.codigo
    try:
        session.delete(fila)
        session.commit()
    except IntegrityError:
        # Un POST /videos lo tomó entre la revisión y el borrado: el RESTRICT de la base manda.
        session.rollback()
        _sin_uso(session, _buscar(session, sop_id))
        raise HTTPException(409, {"mensaje": f"El SOP {codigo} está en uso."}) from None
    shutil.rmtree(carpeta_sop(settings.media_path, sop_id), ignore_errors=True)
    logger.info("SOP %d eliminado", sop_id)
    return Response(status_code=204)


def _sin_uso(session: Session, fila: Sop) -> None:
    """409 con el porqué si algún video o reporte usa el SOP."""
    videos = session.scalars(select(Video.id).where(Video.sop_id == fila.id)).all()
    reportes = session.scalar(
        select(func.count()).select_from(Reporte).where(Reporte.sop_id == fila.id)
    )
    if not videos and not reportes:
        return
    reportes = reportes or 0
    # Un generado lo usa el video del que salió (modo generar) y, si se guardó en la biblioteca,
    # también los videos que se validaron con él: el mensaje dice las dos cosas.
    generadores = (
        session.scalars(
            select(Video.id).where(Video.sop_id == fila.id, Video.modo == "generar")
        ).all()
        if fila.origen == "generado"
        else []
    )
    partes: list[str] = []
    if generadores:
        lista = ", ".join(str(v) for v in generadores)
        if len(generadores) == 1:
            partes.append(f"se generó desde el video {lista}, que lo sigue usando")
        else:
            partes.append(f"se generó desde los videos {lista}, que lo siguen usando")
    n = max(len(videos) - len(generadores), reportes)
    if n:
        referencia = "1 video lo usa" if n == 1 else f"{n} videos lo usan"
        referencia += " como referencia"
        if reportes == 1:
            referencia += " y su reporte depende de él"
        elif reportes:
            referencia += f" y sus {reportes} reportes dependen de él"
        partes.append(referencia)
    motivo = "; además, ".join(partes)
    raise HTTPException(
        409,
        {
            "mensaje": f"El SOP {fila.codigo} no se puede eliminar: {motivo}.",
            "videos": len(videos),
            "reportes": reportes,
        },
    )


@router.get("/sops/{sop_id}/estado", response_model=EstadoSop)
def consultar_estado_sop(
    sop_id: int, session: Annotated[Session, Depends(get_session)]
) -> EstadoSop:
    """Dónde va la conversión; con "listo", el método y las advertencias."""
    return estado_sop(_buscar(session, sop_id))


# Antes que `/sops/{sop_id}`: si no, "5.md" llegaría ahí como un id inválido.
@router.get(
    "/sops/{sop_id}.md",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
def sop_en_markdown(
    sop_id: int, session: Annotated[Session, Depends(get_session)]
) -> PlainTextResponse:
    """El SOP en la plantilla Markdown (`sop_a_markdown`, ADR-015): `convertir_sop` lo vuelve a
    leer igual en lo que la plantilla lleva; la evidencia, los tiempos del video y los puntos y
    palabras clave solo viajan en el JSON. 409 si no está listo."""
    fila = _listo(session, sop_id)
    texto = sop_a_markdown(SOP.model_validate(fila.contenido))
    return PlainTextResponse(texto, media_type="text/markdown; charset=utf-8")


@router.get("/sops/{sop_id}", response_model=SopDetalle)
def detalle_sop(sop_id: int, session: Annotated[Session, Depends(get_session)]) -> SopDetalle:
    """El SOP del contrato; 409 mientras la conversión no esté lista (o si falló)."""
    return detalle(_listo(session, sop_id))


@router.put("/sops/{sop_id}", response_model=SopDetalle)
def corregir_sop(
    sop_id: int, sop: SOP, session: Annotated[Session, Depends(get_session)]
) -> SopDetalle:
    """Guarda la versión corregida del SOP, cargado o generado (RF-04, RF-26): el cuerpo es el
    `SOP` del contrato completo y uno que no lo cumple da 422 sin tocar el guardado. 409 si
    todavía no está listo. La duración total se pone al día (`tiempos.con_duracion_recalculada`):
    la narrada por el operador si la hay; si no, la suma de los pasos (ADR-025)."""
    fila = _listo(session, sop_id)
    if len(sop.titulo) > TITULO_SOP_MAX:
        raise HTTPException(422, f"el título pasa de {TITULO_SOP_MAX} caracteres")
    sop = con_duracion_recalculada(sop, _duracion_narrada(fila))
    fila.titulo, fila.contenido = sop.titulo, sop.model_dump(mode="json")
    session.commit()
    logger.info("SOP %d corregido: %d pasos", sop_id, len(sop.pasos))
    return detalle(fila)


@router.post("/sops/{sop_id}/biblioteca", response_model=EstadoSop)
def guardar_en_biblioteca(
    sop_id: int, session: Annotated[Session, Depends(get_session)]
) -> EstadoSop:
    """Guarda el SOP en la biblioteca (RF-27): desde aquí sirve como `sop_id` en `POST /videos`,
    sin conversión. Idempotente; 409 si no está listo."""
    fila = _listo(session, sop_id)
    if not fila.en_biblioteca:
        fila.en_biblioteca = True
        session.commit()
        logger.info("SOP %d guardado en la biblioteca", sop_id)
    return estado_sop(fila)


def _duracion_narrada(fila: Sop) -> float | None:
    """Los minutos que dijo el operador como duración total (`generacion.duracion_narrada`,
    ADR-021, ADR-023), o None si no la dijo o el SOP no se generó desde un video."""
    if not fila.generacion:
        return None
    narrada = GeneracionSOP.model_validate(fila.generacion).duracion_narrada
    if narrada is None or narrada.valor is None:
        return None
    return float(narrada.valor)


def detalle(fila: Sop) -> SopDetalle:
    return SopDetalle(
        id=fila.id,
        codigo=fila.codigo,
        origen=fila.origen,
        creado=fila.creado,
        metodo=fila.metodo,
        advertencias=[AvisoConversion.model_validate(a) for a in fila.advertencias],
        en_biblioteca=fila.en_biblioteca,
        generacion=GeneracionSOP.model_validate(fila.generacion) if fila.generacion else None,
        sop=SOP.model_validate(fila.contenido),
    )


def _buscar(session: Session, sop_id: int) -> Sop:
    fila = session.get(Sop, sop_id)
    if fila is None:
        raise HTTPException(404, "SOP no encontrado")
    return fila


def _listo(session: Session, sop_id: int) -> Sop:
    fila = _buscar(session, sop_id)
    if fila.estado != SOP_LISTO:
        raise HTTPException(
            409, {"mensaje": "el SOP no está listo", "estado": fila.estado, "error": fila.error}
        )
    return fila
