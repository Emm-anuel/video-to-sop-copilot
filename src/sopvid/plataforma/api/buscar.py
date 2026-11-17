"""Búsqueda exacta (§11, RF-33 a RF-35, RF-37): `POST /buscar` y `GET /buscar/opciones`.

La consulta, la unión de RF-35 y la frase viven en `lenguaje/busqueda.py`; aquí se arma la
respuesta, la miniatura de cada resultado y el registro en `busquedas`. Solo videos publicados:
un `video_id` sin publicar responde igual que uno que no existe (cero resultados, no un error).
"""

import math
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from sopvid.contrato import (
    ConsultaBusqueda,
    OpcionesBusqueda,
    RespuestaBusqueda,
    ResultadoBusqueda,
    VideoDeBusqueda,
)
from sopvid.lenguaje import busqueda
from sopvid.percepcion import miniaturas
from sopvid.plataforma.api.acceso import requiere_busqueda
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Busqueda

# Vista de búsqueda (§11, ADR-027).
router = APIRouter(tags=["búsqueda"], dependencies=[Depends(requiere_busqueda)])

SIN_PALABRAS = "La consulta no tiene palabras que buscar: escribe al menos una palabra o número."


def url_miniatura(video_id: int, t: float) -> str:
    """La ruta de `GET /videos/{id}/thumb` en el segundo `t`, truncado a centésimas (redondear
    hacia arriba podría pasar de la duración y dar 400)."""
    return f"/videos/{video_id}/thumb?t={math.floor(t * 100) / 100:.2f}"


def _sin_imagen(media: Path, archivo: str) -> bool:
    """True si el video ya se marcó sin imagen (ADR-024): solo mira el disco."""
    if not archivo:
        return True
    carpeta = miniaturas.carpeta_miniaturas((media / archivo).parent)
    return miniaturas.sin_imagen_marcado(carpeta)


@router.post("/buscar", response_model=RespuestaBusqueda)
def buscar(
    pedido: ConsultaBusqueda,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RespuestaBusqueda:
    """Busca la palabra o la frase exacta en los videos publicados (ver `lenguaje/busqueda.py`).
    **400** si la consulta no tiene palabras (vacía o solo signos); no se registra. Cada búsqueda
    válida se guarda en `busquedas` con el total ya unido."""
    inicio = time.perf_counter()
    consulta = " ".join(pedido.consulta.split())
    tokens = busqueda.normalizar_consulta(consulta)
    if not tokens:
        raise HTTPException(400, SIN_PALABRAS)
    total, coincidencias = busqueda.buscar(
        session,
        tokens,
        video_id=pedido.video_id,
        sop_id=pedido.sop_id,
        unir_s=settings.busqueda_unir_s,
        limite=settings.busqueda_max_resultados,
    )
    frases = busqueda.frases(session, coincidencias)
    videos = {c.video_id: c.archivo for c in coincidencias}  # una vez por video
    sin_imagen = {v: _sin_imagen(settings.media_path, a) for v, a in videos.items()}
    resultados = [
        ResultadoBusqueda(
            video=VideoDeBusqueda(id=c.video_id, titulo=c.titulo),
            sop=c.sop,
            t_inicio=c.t_inicio,
            t_fin=c.t_fin,
            miniatura=None if sin_imagen[c.video_id] else url_miniatura(c.video_id, c.t_inicio),
            frase=f.texto,
            rango=f.rango,
            recorte_inicio=f.recorte_inicio,
            recorte_fin=f.recorte_fin,
            coincidencias=c.coincidencias,
        )
        for c, f in zip(coincidencias, frases, strict=True)
    ]
    session.add(Busqueda(consulta=consulta, num_resultados=total))
    session.commit()
    return RespuestaBusqueda(
        consulta=consulta,
        consulta_normalizada=" ".join(tokens),
        total=total,
        resultados=resultados,
        milisegundos=round((time.perf_counter() - inicio) * 1000, 2),
    )


@router.get("/buscar/opciones", response_model=OpcionesBusqueda)
def opciones_busqueda(session: Annotated[Session, Depends(get_session)]) -> OpcionesBusqueda:
    """Los selectores de `/buscar` (RF-37): videos publicados y SOP con al menos uno."""
    return busqueda.opciones(session)
