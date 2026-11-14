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
    # Sin marcar videos interrumpidos: el lifespan no debe tocar filas de la base de desarrollo.
    app = create_app(recuperar_interrumpidos=False)
    with TestClient(app) as test_client:
        yield test_client


# Fuentes para `drawtext`: sin fontconfig (Windows), ffmpeg necesita la ruta del archivo.
_FUENTES = (
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _filtro_texto(texto: str) -> str | None:
    """`drawtext` con `texto` y la primera fuente que exista, o None si no hay ninguna."""
    fuente = next((f for f in _FUENTES if Path(f).is_file()), None)
    if fuente is None:
        return None
    ruta = fuente.replace(":", r"\:")
    return (
        f"drawtext=fontfile='{ruta}':text='{texto}':fontsize=20:fontcolor=white:"
        "box=1:boxcolor=black@0.7:x=8:y=8"
    )


@pytest.fixture
def generar_video(tmp_path: Path) -> Callable[..., Path]:
    """Fábrica de videos sintéticos (lavfi: testsrc + sine) en `tmp_path`.

    Usa códecs nativos de ffmpeg (mpeg4 + aac), así que no depende de libx264. El audio va en
    estéreo a 44.1 kHz para que las pruebas demuestren la conversión a mono 16 kHz.

    `imagen`: "testsrc" (barras de prueba), "negra" (pantalla negra, como una grabación de solo
    voz) o "ninguna" (sin pista de video). `texto` lo dibuja con `drawtext` si hay una fuente y el
    ffmpeg lo soporta; si no, el video sale sin texto (las pruebas no dependen de leerlo).
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe no están instalados")

    def generar(
        nombre: str = "video.mp4",
        con_audio: bool = True,
        segundos: int = 3,
        imagen: str = "testsrc",
        texto: str | None = None,
    ) -> Path:
        destino = tmp_path / nombre
        fuentes = {
            "testsrc": f"testsrc=duration={segundos}:size=160x120:rate=10",
            "negra": f"color=c=black:size=160x120:duration={segundos}:rate=10",
        }
        args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
        if imagen != "ninguna":
            args += ["-f", "lavfi", "-i", fuentes[imagen]]
        if con_audio:
            args += [
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}:sample_rate=44100",
                "-c:a", "aac", "-ac", "2",
            ]  # fmt: skip
        if imagen == "ninguna":
            subprocess.run([*args, str(destino)], check=True, capture_output=True, timeout=60)
            return destino
        salida = ["-c:v", "mpeg4", "-shortest", str(destino)]
        filtro = _filtro_texto(texto) if texto else None
        if filtro is not None:
            con_texto = subprocess.run(
                [*args, "-vf", filtro, *salida], capture_output=True, timeout=60, check=False
            )
            if con_texto.returncode == 0:
                return destino
        subprocess.run([*args, *salida], check=True, capture_output=True, timeout=60)
        return destino

    return generar
