"""Pruebas de `/sops`: carga del SOP de referencia en Markdown o TXT (RF-03, ADR-015).

Usan la base de conftest.py (`db_session`, revertida al final) y los SOP inventados de
tests/fixtures/ (README de esa carpeta).
"""

import json
import re
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.api.sops import SOP_MAX_BYTES
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Sop

FIXTURES = Path(__file__).parent / "fixtures"
MD = (FIXTURES / "sop_filtro_agua.md").read_bytes()
SOP_EJEMPLO = json.loads((FIXTURES / "sop_ejemplo.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(media_dir=tmp_path / "media")


@pytest.fixture
def client(db_session: Session, settings: Settings) -> Iterator[TestClient]:
    def sesion() -> Iterator[Session]:
        yield db_session

    app = create_app(sesiones=lambda: nullcontext(db_session), recuperar_interrumpidos=False)
    app.dependency_overrides[get_session] = sesion
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as cliente:
        yield cliente


def cargar(client: TestClient, contenido: bytes, nombre: str = "procedimiento.md"):
    return client.post("/sops", files={"archivo": (nombre, contenido, "text/markdown")})


def _filas(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Sop))


def test_carga_markdown(client: TestClient, db_session: Session, settings: Settings) -> None:
    r = cargar(client, MD)

    assert r.status_code == 201
    cuerpo = r.json()
    assert re.fullmatch(r"SOP-\d{4,}", cuerpo["codigo"])
    assert cuerpo["titulo"] == "Cambio del cartucho del filtro de agua"
    assert cuerpo["advertencias"] == []
    assert r.headers["location"] == f"/sops/{cuerpo['id']}"
    fila = db_session.get(Sop, cuerpo["id"])
    assert (fila.origen, fila.codigo) == ("cargado", cuerpo["codigo"])
    assert fila.contenido == SOP_EJEMPLO  # el SOP del contrato, como lo da el script
    # Ruta relativa a MEDIA_DIR, nunca el nombre original.
    assert fila.archivo_original == f"sops/{fila.id}/original.md"
    assert (settings.media_path / fila.archivo_original).read_bytes() == MD


def test_carga_txt_con_advertencias(client: TestClient, db_session: Session) -> None:
    # El TXT simple con un salto en la numeración (6 → 7): se renumera y se avisa.
    simple = (FIXTURES / "sop_filtro_agua_simple.txt").read_bytes()
    contenido = simple.replace(b"6. Abrir", b"7. Abrir")

    r = cargar(client, contenido, nombre="PROCEDIMIENTO.TXT")

    assert r.status_code == 201
    cuerpo = r.json()
    [advertencia] = cuerpo["advertencias"]
    assert (advertencia["tipo"], advertencia["linea"]) == ("numeracion", 11)
    assert "se esperaba el paso 6 y llegó el 7" in advertencia["mensaje"]
    assert db_session.get(Sop, cuerpo["id"]).archivo_original.endswith("/original.txt")


def test_carga_con_bom_y_crlf(client: TestClient) -> None:
    contenido = "﻿".encode() + MD.replace(b"\n", b"\r\n")

    r = cargar(client, contenido)

    assert r.status_code == 201
    assert r.json()["advertencias"] == []


def test_error_sop_da_422_con_el_mensaje(
    client: TestClient, db_session: Session, settings: Settings
) -> None:
    antes = _filas(db_session)

    r = cargar(client, "# Procedimiento inventado\n\nSolo un párrafo.\n".encode())

    assert r.status_code == 422
    assert "no tiene pasos" in r.json()["detail"]
    assert _filas(db_session) == antes
    assert not (settings.media_path / "sops").exists()


@pytest.mark.parametrize("nombre", ["procedimiento.doc", "procedimiento.odt", "sin_extension"])
def test_extension_no_permitida(
    client: TestClient, db_session: Session, settings: Settings, nombre: str
) -> None:
    antes = _filas(db_session)

    r = cargar(client, MD, nombre=nombre)

    assert r.status_code == 415
    assert _filas(db_session) == antes
    assert not (settings.media_path / "sops").exists()


def test_archivo_que_no_es_utf8(client: TestClient, db_session: Session) -> None:
    antes = _filas(db_session)

    r = cargar(client, MD.decode("utf-8").encode("latin-1"))

    assert r.status_code == 422
    assert r.json()["detail"] == "el archivo debe estar en UTF-8"
    assert _filas(db_session) == antes


def test_archivo_demasiado_grande(client: TestClient, db_session: Session) -> None:
    antes = _filas(db_session)

    r = cargar(client, MD + b" " * SOP_MAX_BYTES)

    assert r.status_code == 413
    assert _filas(db_session) == antes


def test_titulo_demasiado_largo(client: TestClient, db_session: Session) -> None:
    antes = _filas(db_session)
    largo = MD.replace(b"Cambio del cartucho del filtro de agua", b"X" * 301, 1)

    r = cargar(client, largo)

    assert r.status_code == 422
    assert "300" in r.json()["detail"]
    assert _filas(db_session) == antes


def test_consulta_del_sop(client: TestClient) -> None:
    creado = cargar(client, MD).json()

    r = client.get(f"/sops/{creado['id']}")

    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["id"], cuerpo["codigo"], cuerpo["origen"]) == (
        creado["id"],
        creado["codigo"],
        "cargado",
    )
    assert cuerpo["sop"] == SOP_EJEMPLO
    assert "creado" in cuerpo


def test_consulta_404(client: TestClient) -> None:
    assert client.get("/sops/999999999").status_code == 404
