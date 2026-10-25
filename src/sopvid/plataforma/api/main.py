"""Aplicación FastAPI. Uvicorn la sirve como `sopvid.plataforma.api.main:app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from sopvid import __version__
from sopvid.plataforma.api import health, videos
from sopvid.plataforma.config import get_settings
from sopvid.plataforma.db import get_sessionmaker
from sopvid.plataforma.procesamiento import FabricaSesiones, Procesador, marcar_interrumpidos

logger = logging.getLogger(__name__)


def _configurar_logs() -> None:
    """INFO de `sopvid` a la salida de errores (uvicorn solo configura sus propios loggers).

    Sin esto, los avisos de carga del modelo ("Whisper … cargado en cuda/float16") y el resumen
    de cada análisis no se ven. Los mensajes nunca llevan texto del video.
    """
    raiz = logging.getLogger("sopvid")
    if raiz.handlers:
        return
    manejador = logging.StreamHandler()
    manejador.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    raiz.addHandler(manejador)
    raiz.setLevel(logging.INFO)


def create_app(
    sesiones: FabricaSesiones | None = None, recuperar_interrumpidos: bool = True
) -> FastAPI:
    """Crea la app. `sesiones` reemplaza al sessionmaker (pruebas).

    Al arrancar, los videos que quedaron en cola o procesando pasan a error: la cola vive en
    memoria y no sobrevive a un reinicio. Si la base no responde, la API arranca igual y
    `/health` lo informa.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        fabrica = sesiones or get_sessionmaker()
        if recuperar_interrumpidos:
            try:
                with fabrica() as session:
                    marcar_interrumpidos(session)
            except SQLAlchemyError as exc:
                logger.warning("No se revisaron videos interrumpidos: %s", type(exc).__name__)
        app.state.procesador = Procesador.con_hilo(fabrica, get_settings().media_path)
        yield
        app.state.procesador.cerrar()

    _configurar_logs()
    app = FastAPI(title="AI Co-Pilot Video-to-SOP", version=__version__, lifespan=lifespan)
    app.middleware("http")(videos.limitar_content_length)
    app.include_router(health.router)
    app.include_router(videos.router)
    return app


app = create_app()
