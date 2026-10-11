"""GET /health: estado de la API, de la conexión real a la base y del LLM local.

El LLM es opcional (profile "llm" de docker compose): su estado se informa, pero no cambia
el código de respuesta, y la consulta se corta a los LLM_HEALTH_TIMEOUT_S.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from sopvid.lenguaje.llm import ClienteLLM, get_cliente_llm
from sopvid.plataforma.config import get_settings
from sopvid.plataforma.db import get_session, ping

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    session: Annotated[Session, Depends(get_session)],
    llm: Annotated[ClienteLLM, Depends(get_cliente_llm)],
) -> JSONResponse:
    estado_llm = (
        "ok" if llm.disponible(timeout_s=get_settings().llm_health_timeout_s) else "no_disponible"
    )
    try:
        ping(session)
    except SQLAlchemyError:
        # El detalle va al log, no a la respuesta (puede incluir host/usuario).
        logger.exception("Health check: la base de datos no responde")
        return JSONResponse(
            status_code=503, content={"status": "error", "db": "error", "llm": estado_llm}
        )
    return JSONResponse(content={"status": "ok", "db": "ok", "llm": estado_llm})
