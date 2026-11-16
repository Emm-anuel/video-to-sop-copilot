"""Clave de acceso por vista (§11, RNF-10, ADR-027): dependencias y `/acceso`.

Cada router declara qué vista pide con una dependencia (`requiere_carga`, `requiere_busqueda`,
`requiere_medios`, `requiere_pdf_sop`); ninguna ruta revisa la clave por su cuenta. La clave llega
en `X-Clave-Acceso` o en la cookie de sesión que deja `POST /acceso`: `<img>`, `<video>` y los
enlaces de descarga no pueden mandar encabezados. `/health`, `/docs` y `/acceso` no piden nada.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sopvid.lenguaje.busqueda import sop_con_publicado, video_publicado
from sopvid.plataforma import acceso
from sopvid.plataforma.acceso import NOMBRE_COOKIE, NOMBRE_VISTA, VISTAS, Vista
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session

router = APIRouter(tags=["acceso"])

# Espera ante una clave equivocada en POST /acceso: frena probar claves a mano sin bloquear el
# trabajador (asyncio). No es un límite de intentos (pendiente en #30, ADR-027).
RETRASO_CLAVE_S = 1.0

_encabezado = APIKeyHeader(
    name=acceso.ENCABEZADO,
    auto_error=False,
    description="Clave de la vista de carga o de la de búsqueda (§11).",
)


def vistas_concedidas(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    clave: Annotated[str | None, Security(_encabezado)] = None,
) -> frozenset[Vista]:
    """Las vistas que abre esta petición: abiertas, por el encabezado o por su cookie."""
    return frozenset(
        vista
        for vista in VISTAS
        if acceso.abierta(settings, vista)
        or acceso.clave_correcta(settings, vista, clave)
        or acceso.cookie_correcta(settings, vista, request.cookies.get(NOMBRE_COOKIE[vista]))
    )


Concedidas = Annotated[frozenset[Vista], Depends(vistas_concedidas)]


def sin_clave(vista: Vista | None = None) -> HTTPException:
    """401 con el porqué en español; sin `vista`, cuando sirven las dos o un enlace."""
    if vista is None:
        return HTTPException(401, "Falta la clave de acceso o el enlace no es válido.")
    return HTTPException(
        401, f"Falta la clave de la vista de {NOMBRE_VISTA[vista]} o no es correcta."
    )


def requiere_carga(vistas: Concedidas) -> None:
    """SOP, subidas y videos (§11, vista de carga)."""
    if "carga" not in vistas:
        raise sin_clave("carga")


def requiere_busqueda(vistas: Concedidas) -> None:
    """`POST /buscar` y `GET /buscar/opciones` (§11, vista de búsqueda)."""
    if "busqueda" not in vistas:
        raise sin_clave("busqueda")


def requiere_medios(
    video_id: int,
    vistas: Concedidas,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    k: Annotated[
        str | None, Query(description="Token del enlace del PDF (`/v/<id>?k=`), solo de este video")
    ] = None,
) -> None:
    """`/videos/{id}/video` y `/thumb`: la clave de carga, el token `k` de ese video o, sin
    `SECRETO_ENLACES`, cualquiera (como los enlaces). Con la de búsqueda, solo un video
    publicado; uno sin publicar da 404, como si no existiera (igual que `POST /buscar`)."""
    if (
        "carga" in vistas
        or acceso.enlaces_abiertos(settings)
        or acceso.enlace_correcto(settings, video_id, k)
    ):
        return
    if "busqueda" not in vistas:
        raise sin_clave()
    if not video_publicado(session, video_id):
        raise HTTPException(404, {"mensaje": "video no encontrado"})


def requiere_pdf_sop(
    sop_id: int,
    vistas: Concedidas,
    session: Annotated[Session, Depends(get_session)],
    ver: bool = False,
) -> None:
    """`GET /sops/{id}/pdf`: la clave de carga; con `ver=true` ("Ver SOP" de `/buscar`), también
    la de búsqueda si el SOP tiene un video publicado (si no, 404)."""
    if "carga" in vistas:
        return
    if not ver or "busqueda" not in vistas:
        raise sin_clave("carga" if not ver else None)
    if not sop_con_publicado(session, sop_id):
        raise HTTPException(404, {"mensaje": "SOP no encontrado"})


class PedidoAcceso(BaseModel):
    vista: Vista
    clave: str = Field(max_length=200)


class EstadoVista(BaseModel):
    """`abierta`: sin clave, entra cualquiera. `sesion`: esta petición trae la clave o la cookie."""

    abierta: bool
    sesion: bool


class EstadoAcceso(BaseModel):
    carga: EstadoVista
    busqueda: EstadoVista


@router.post("/acceso", status_code=204)
async def entrar(
    pedido: PedidoAcceso,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Con la clave correcta deja la cookie de la vista: HttpOnly, SameSite=Strict y de sesión
    del navegador (sin Max-Age). Con la vista abierta, 204 sin cookie. Con una equivocada, 401
    tras `RETRASO_CLAVE_S`."""
    vista = pedido.vista
    if acceso.abierta(settings, vista):
        return
    if not acceso.clave_correcta(settings, vista, pedido.clave):
        await asyncio.sleep(RETRASO_CLAVE_S)
        raise HTTPException(401, f"La clave de la vista de {NOMBRE_VISTA[vista]} no es correcta.")
    response.set_cookie(
        NOMBRE_COOKIE[vista],
        acceso.valor_cookie(settings, vista),
        path="/",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )


@router.get("/acceso", response_model=EstadoAcceso)
def estado_acceso(
    settings: Annotated[Settings, Depends(get_settings)],
    vistas: Concedidas,
) -> EstadoAcceso:
    """Qué vistas están abiertas y cuáles abre esta petición (la cookie es HttpOnly: el
    frontend no la ve, pregunta aquí)."""

    def estado(vista: Vista) -> EstadoVista:
        abierta = acceso.abierta(settings, vista)
        return EstadoVista(abierta=abierta, sesion=not abierta and vista in vistas)

    return EstadoAcceso(carga=estado("carga"), busqueda=estado("busqueda"))


@router.delete("/acceso", status_code=204)
def salir(
    request: Request,
    response: Response,
    vista: Annotated[Vista | None, Query(description="Sin ella, cierra las dos")] = None,
) -> None:
    """Cierra la sesión de `vista` (o de las dos): borra su cookie."""
    for v in (vista,) if vista else VISTAS:
        response.delete_cookie(
            NOMBRE_COOKIE[v],
            path="/",
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
