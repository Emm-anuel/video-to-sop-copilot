"""Aplicación FastAPI. Uvicorn la sirve como `sopvid.plataforma.api.main:app`."""

from fastapi import FastAPI

from sopvid import __version__
from sopvid.plataforma.api import health


def create_app() -> FastAPI:
    app = FastAPI(title="AI Co-Pilot Video-to-SOP", version=__version__)
    app.include_router(health.router)
    return app


app = create_app()
