"""Fixtures compartidas.

Los tests usan una base PostgreSQL real (docker compose localmente o el servicio
de GitHub Actions en CI). Si la base no está arriba, fallan: no se saltan.

`generar_video` crea videos sintéticos con ffmpeg en `tmp_path` (ningún medio se versiona); las
pruebas que la usan se saltan si ffmpeg no está instalado.
"""

import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.db import get_engine


@pytest.fixture(scope="session")
def engine() -> Engine:
    return get_engine()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """Sesión dentro de una transacción que se revierte al final: no deja filas en la base.

    `commit()` y `rollback()` del test actúan sobre un savepoint, así que una IntegrityError
    no invalida la transacción externa.
    """
    with engine.connect() as conn:
        transaccion = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaccion.rollback()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def generar_video(tmp_path: Path) -> Callable[..., Path]:
    """Fábrica de videos sintéticos (lavfi: testsrc + sine) en `tmp_path`.

    Usa códecs nativos de ffmpeg (mpeg4 + aac), así que no depende de libx264. El audio va en
    estéreo a 44.1 kHz para que las pruebas demuestren la conversión a mono 16 kHz.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe no están instalados")

    def generar(nombre: str = "video.mp4", con_audio: bool = True, segundos: int = 3) -> Path:
        destino = tmp_path / nombre
        args = [
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={segundos}:size=160x120:rate=10",
        ]  # fmt: skip
        if con_audio:
            args += [
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}:sample_rate=44100",
                "-c:a", "aac", "-ac", "2",
            ]  # fmt: skip
        args += ["-c:v", "mpeg4", "-shortest", str(destino)]
        subprocess.run(args, check=True, capture_output=True, timeout=60)
        return destino

    return generar
