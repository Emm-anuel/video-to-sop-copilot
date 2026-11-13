"""Aplicación FastAPI. Uvicorn la sirve como `sopvid.plataforma.api.main:app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from sopvid import __version__
from sopvid.percepcion.subidas import limpiar_caducadas
from sopvid.plataforma.api import health, sops, subidas, videos
from sopvid.plataforma.config import get_settings
from sopvid.plataforma.db import get_sessionmaker
from sopvid.plataforma.hardware import get_hardware, get_plan_dispositivos, registrar
from sopvid.plataforma.procesamiento import (
    FabricaSesiones,
    Procesador,
    marcar_interrumpidos,
    marcar_sops_interrumpidos,
)

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

    Al arrancar, los videos y los SOP que quedaron en cola o en proceso pasan a error: la cola
    vive en memoria y no sobrevive a un reinicio. También se borran las subidas por partes sin
    actividad desde hace `SUBIDA_CADUCIDAD_H` horas. Si la base no responde, la API arranca igual y
    `/health` lo informa. También se registra dónde va a correr cada etapa (GPU o CPU,
    ADR-018), con un aviso si la configuración no cuadra con el equipo.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        registrar(get_plan_dispositivos(), get_hardware().motivo_sin_gpu)
        # Las subidas por partes abandonadas no se quedan en media (RNF-09). Con los ajustes de
        # la app (las pruebas los reemplazan), no los del entorno.
        settings = app.dependency_overrides.get(get_settings, get_settings)()
        try:
            limpiar_caducadas(settings.media_path, settings.subida_caducidad_h)
        except OSError as exc:
            logger.warning("No se limpiaron las subidas caducadas: %s", exc)
        fabrica = sesiones or get_sessionmaker()
        if recuperar_interrumpidos:
            try:
                with fabrica() as session:
                    marcar_interrumpidos(session)
                    marcar_sops_interrumpidos(session)
            except SQLAlchemyError as exc:
                logger.warning("No se revisaron videos interrumpidos: %s", type(exc).__name__)
        app.state.procesador = Procesador.con_hilo(fabrica, get_settings().media_path)
        yield
        app.state.procesador.cerrar()

    _configurar_logs()
    app = FastAPI(title="AI Co-Pilot Video-to-SOP", version=__version__, lifespan=lifespan)
    app.middleware("http")(videos.limitar_content_length)
    app.include_router(health.router)
    app.include_router(sops.router)
    app.include_router(videos.router)
    app.include_router(subidas.router)
    return app


app = create_app()
