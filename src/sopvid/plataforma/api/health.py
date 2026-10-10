"""GET /health: estado de la API y de la conexión real a la base."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from sopvid.plataforma.db import get_session, ping

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    try:
        ping(session)
    except SQLAlchemyError:
        # El detalle va al log, no a la respuesta (puede incluir host/usuario).
        logger.exception("Health check: la base de datos no responde")
        return JSONResponse(status_code=503, content={"status": "error", "db": "error"})
    return JSONResponse(content={"status": "ok", "db": "ok"})
