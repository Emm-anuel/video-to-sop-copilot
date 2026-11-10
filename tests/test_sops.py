"""Pruebas de `/sops`: carga del SOP de referencia en Markdown o TXT (RF-03, ADR-015).

`POST /sops` responde 202 y la conversión corre en el trabajador: aquí, la `ColaTrabajos` del
`Entorno` de tests/dobles.py, que la prueba corre a mano (`correr_pendientes`) para ver el estado
antes y después. Usan la base de conftest.py (`db_session`, revertida al final) y los SOP
inventados de tests/fixtures/ (README de esa carpeta). El LLM es el `OllamaFalso`; PDF y Word
se prueban en test_lectura_sop.py.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dobles import Entorno, OllamaFalso
from sopvid.plataforma.api.sops import SOP_MAX_BYTES
from sopvid.plataforma.modelos import Sop
from sopvid.plataforma.procesamiento import MENSAJE_SOP_SIN_LLM, marcar_sops_interrumpidos

FIXTURES = Path(__file__).parent / "fixtures"
MD = (FIXTURES / "sop_filtro_agua.md").read_bytes()
SOP_EJEMPLO = json.loads((FIXTURES / "sop_ejemplo.json").read_text(encoding="utf-8"))
ESQUEMA_ESTADO = json.loads(
    (Path(__file__).resolve().parents[1] / "docs/contrato/sop_estado.schema.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def ollama(entorno: Entorno) -> OllamaFalso:
    return entorno.ollama


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def cargar(client: TestClient, contenido: bytes, nombre: str = "procedimiento.md"):
    return client.post("/sops", files={"archivo": (nombre, contenido, "text/markdown")})


def convertido(client: TestClient, entorno: Entorno, contenido: bytes, nombre: str = "p.md"):
    """Sube el SOP, corre la cola y devuelve su estado final (`GET /sops/{id}/estado`)."""
    r = cargar(client, contenido, nombre)
    assert r.status_code == 202, r.text
    entorno.correr_pendientes()
    estado = client.get(f"/sops/{r.json()['id']}/estado")
    assert estado.status_code == 200
    Draft202012Validator(ESQUEMA_ESTADO).validate(estado.json())
    return estado.json()


def _filas(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Sop))


def test_carga_markdown_en_cola_y_luego_listo(
    client: TestClient, entorno: Entorno, ollama: OllamaFalso
) -> None:
    r = cargar(client, MD)

    assert r.status_code == 202
    cuerpo = r.json()
    Draft202012Validator(ESQUEMA_ESTADO).validate(cuerpo)
    assert re.fullmatch(r"SOP-\d{4,}", cuerpo["codigo"])
    assert (cuerpo["estado"], cuerpo["titulo"], cuerpo["advertencias"]) == ("en_cola", None, [])
    assert r.headers["location"] == f"/sops/{cuerpo['id']}/estado"
    fila = entorno.session.get(Sop, cuerpo["id"])
    # Ruta relativa a MEDIA_DIR, nunca el nombre original; el archivo ya está guardado.
    assert fila.archivo_original == f"sops/{fila.id}/original.md"
    assert (entorno.settings.media_path / fila.archivo_original).read_bytes() == MD
    assert len(entorno.pendientes) == 1
    assert client.get(f"/sops/{cuerpo['id']}").status_code == 409  # todavía no

    entorno.correr_pendientes()

    estado = client.get(r.headers["location"]).json()
    assert estado == {
        "id": cuerpo["id"],
        "codigo": cuerpo["codigo"],
        "estado": "listo",
        "titulo": "Cambio del cartucho del filtro de agua",
        "metodo": "plantilla",
        "mensaje": None,
        "advertencias": [],
        "origen": "cargado",
        "en_biblioteca": True,  # un SOP cargado entra solo a la biblioteca (RF-27)
    }
    assert ollama.eventos == []  # con plantilla, sin LLM
    entorno.session.refresh(fila)
    assert (fila.origen, fila.estado, fila.contenido) == ("cargado", "listo", SOP_EJEMPLO)


def test_carga_txt_con_advertencias(client: TestClient, entorno: Entorno) -> None:
    # El TXT simple con un salto en la numeración (6 → 7): se renumera y se avisa.
    simple = (FIXTURES / "sop_filtro_agua_simple.txt").read_bytes()
    contenido = simple.replace(b"6. Abrir", b"7. Abrir")

    estado = convertido(client, entorno, contenido, "PROCEDIMIENTO.TXT")

    [advertencia] = estado["advertencias"]
    assert (advertencia["tipo"], advertencia["linea"]) == ("numeracion", 11)
    assert "se esperaba el paso 6 y llegó el 7" in advertencia["mensaje"]
    fila = entorno.session.get(Sop, estado["id"])
    assert fila.archivo_original.endswith("/original.txt")
    # La conversión queda en la base (migración 0003), igual que en el estado.
    assert (fila.metodo, fila.advertencias) == ("plantilla", [advertencia])
    detalle = client.get(f"/sops/{estado['id']}").json()
    assert (detalle["metodo"], detalle["advertencias"]) == ("plantilla", [advertencia])


def test_carga_con_bom_y_crlf(client: TestClient, entorno: Entorno) -> None:
    contenido = "﻿".encode() + MD.replace(b"\n", b"\r\n")

    estado = convertido(client, entorno, contenido)

    assert (estado["estado"], estado["advertencias"]) == ("listo", [])


SIN_PLANTILLA = "# Procedimiento inventado\n\nPrimero se cierra la llave de paso y se purga.\n"
RESPUESTA_SIN_PLANTILLA = {
    "titulo": "Procedimiento inventado",
    "resumen": {
        **dict.fromkeys(["objetivo", "alcance", "responsable", "lugar", "horario_frecuencia"]),
        "duracion_total_min": None,
        **{c: [] for c in ["roles", "riesgos", "en_caso_de_falla"]},
    },
    "pasos": [
        {
            "cita_origen": "Primero se cierra la llave de paso",
            "nombre": "Cerrar la llave de paso",
            "descripcion": "",
            "responsable": None,
            "equipo": [],
            "puntos_validacion": [],
            "tiempo_esperado_min": None,
        }
    ],
}


@pytest.mark.parametrize("nombre", ["procedimiento.md", "procedimiento.txt"])
def test_sin_plantilla_lo_convierte_el_llm(
    client: TestClient, entorno: Entorno, ollama: OllamaFalso, nombre: str
) -> None:
    """Un .md o .txt sin plantilla pasa por el mismo camino del LLM que PDF y Word (ADR-015)."""
    ollama.respuestas_sop = [RESPUESTA_SIN_PLANTILLA]

    estado = convertido(client, entorno, SIN_PLANTILLA.encode(), nombre)

    assert (estado["estado"], estado["metodo"], estado["advertencias"]) == ("listo", "llm", [])
    assert ollama.eventos == ["tags", "chat:sop", "descargar"]
    fila = entorno.session.get(Sop, estado["id"])
    assert fila.contenido["pasos"][0]["nombre"] == "Cerrar la llave de paso"


def test_sin_plantilla_y_sin_ollama_queda_en_error(
    client: TestClient, entorno: Entorno, ollama: OllamaFalso
) -> None:
    ollama.disponible = False

    estado = convertido(client, entorno, SIN_PLANTILLA.encode())

    assert (estado["estado"], estado["mensaje"]) == ("error", MENSAJE_SOP_SIN_LLM)
    assert estado["titulo"] is None
    r = client.get(f"/sops/{estado['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["estado"] == "error"


@pytest.mark.parametrize("nombre", ["procedimiento.doc", "procedimiento.odt", "sin_extension"])
def test_extension_no_permitida(client: TestClient, entorno: Entorno, nombre: str) -> None:
    antes = _filas(entorno.session)

    r = cargar(client, MD, nombre=nombre)

    assert r.status_code == 415
    assert _filas(entorno.session) == antes
    assert not (entorno.settings.media_path / "sops").exists()
    assert entorno.pendientes == []


def test_archivo_que_no_es_utf8(client: TestClient, entorno: Entorno) -> None:
    antes = _filas(entorno.session)

    r = cargar(client, MD.decode("utf-8").encode("latin-1"))

    assert r.status_code == 422
    assert r.json()["detail"] == "el archivo debe estar en UTF-8"
    assert _filas(entorno.session) == antes
    assert entorno.pendientes == []


def test_archivo_demasiado_grande(client: TestClient, entorno: Entorno) -> None:
    antes = _filas(entorno.session)

    r = cargar(client, MD + b" " * SOP_MAX_BYTES)

    assert r.status_code == 413
    assert _filas(entorno.session) == antes


def test_titulo_demasiado_largo(client: TestClient, entorno: Entorno) -> None:
    largo = MD.replace(b"Cambio del cartucho del filtro de agua", b"X" * 301, 1)

    estado = convertido(client, entorno, largo)

    assert estado["estado"] == "error"
    assert "300" in estado["mensaje"]


def test_consulta_del_sop(client: TestClient, entorno: Entorno) -> None:
    estado = convertido(client, entorno, MD)

    r = client.get(f"/sops/{estado['id']}")

    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["id"], cuerpo["codigo"], cuerpo["origen"]) == (
        estado["id"],
        estado["codigo"],
        "cargado",
    )
    assert cuerpo["sop"] == SOP_EJEMPLO
    assert (cuerpo["metodo"], cuerpo["advertencias"]) == ("plantilla", [])
    assert "creado" in cuerpo


def test_consulta_de_un_sop_sin_conversion_guardada(client: TestClient, entorno: Entorno) -> None:
    """Un SOP generado o cargado antes de la migración 0003: metodo None y sin advertencias."""
    fila = Sop(titulo="Generado", origen="generado", contenido=SOP_EJEMPLO)
    entorno.session.add(fila)
    entorno.session.commit()

    cuerpo = client.get(f"/sops/{fila.id}").json()
    estado = client.get(f"/sops/{fila.id}/estado").json()

    assert (cuerpo["metodo"], cuerpo["advertencias"]) == (None, [])
    assert estado["estado"] == "listo"  # los anteriores a la migración 0004 quedan listos


@pytest.mark.parametrize("ruta", ["/sops/999999999", "/sops/999999999/estado"])
def test_consulta_404(client: TestClient, ruta: str) -> None:
    assert client.get(ruta).status_code == 404


def test_al_arrancar_los_sop_interrumpidos_quedan_en_error(
    client: TestClient, entorno: Entorno
) -> None:
    sop_id = cargar(client, MD).json()["id"]  # en cola; la cola se pierde con el reinicio

    assert marcar_sops_interrumpidos(entorno.session) >= 1

    estado = client.get(f"/sops/{sop_id}/estado").json()
    assert estado["estado"] == "error" and "reinicio" in estado["mensaje"]
