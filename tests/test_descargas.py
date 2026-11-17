"""Descargas de la transcripción (RF-31): `GET /videos/{id}/download/{tipo}`.

Con la base de pruebas (`db_session`, se revierte al final) y videos ya analizados guardados con
`dobles.guardar_video`, con transcripciones inventadas. No hace falta ffmpeg ni Whisper.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from dobles import SEGMENTOS, Entorno, guardar_video
from sopvid.contrato import Analisis, Palabra, Segmento
from test_salidas import leer_srt

ESQUEMA = Path(__file__).resolve().parents[1] / "docs" / "contrato" / "analisis.schema.json"

# Inventados: acentos, ñ y signos en el texto; un segmento vacío que el SRT no escribe.
CON_ACENTOS = [
    Segmento(
        id=0,
        t_inicio=0.0,
        t_fin=2.5,
        texto="Reviso el piñón y la cañería.",
        palabras=[Palabra(w="Reviso", t=0.0, t_fin=0.4), Palabra(w="piñón", t=0.8, t_fin=1.2)],
    ),
    Segmento(id=1, t_inicio=2.5, t_fin=3.0, texto=""),
    Segmento(id=2, t_inicio=3.0, t_fin=65.25, texto="¿Quién apagó el compresor?"),
]


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _nombre(r) -> str:
    disposicion = r.headers["content-disposition"]
    assert disposicion.startswith("attachment; ")
    return disposicion.removeprefix('attachment; filename="').removesuffix('"')


def test_txt_completo_con_nombre_legible(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session, CON_ACENTOS, titulo="Revisión del piñón: línea 3")

    r = client.get(f"/videos/{video.id}/download/txt")

    assert r.status_code == 200
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert _nombre(r) == "revision_del_pinon_linea_3.txt"
    assert r.content.decode("utf-8") == (
        "[00:00] Reviso el piñón y la cañería.\n[00:02] \n[00:03] ¿Quién apagó el compresor?\n"
    )


def test_srt_valido_y_en_utf8(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session, CON_ACENTOS, titulo="Revisión del piñón")

    r = client.get(f"/videos/{video.id}/download/srt")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-subrip; charset=utf-8"
    assert _nombre(r) == "revision_del_pinon.srt"
    assert leer_srt(r.content.decode("utf-8")) == [
        (0, 2500, "Reviso el piñón y la cañería."),
        (3000, 65250, "¿Quién apagó el compresor?"),
    ]


def test_json_es_el_analisis_y_valida_contra_el_esquema(
    client: TestClient, entorno: Entorno
) -> None:
    video = guardar_video(entorno.session, CON_ACENTOS, titulo="Revisión del piñón")

    r = client.get(f"/videos/{video.id}/download/json")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json; charset=utf-8"
    assert _nombre(r) == "revision_del_pinon.json"
    assert "piñón".encode() in r.content  # UTF-8 tal cual, sin escapes ñ
    datos = json.loads(r.content.decode("utf-8"))
    esquema = json.loads(ESQUEMA.read_text(encoding="utf-8"))
    assert sorted(Draft202012Validator(esquema).iter_errors(datos), key=str) == []
    assert datos == client.get(f"/videos/{video.id}/analisis").json()
    assert Analisis.model_validate(datos).transcripcion == CON_ACENTOS


@pytest.mark.parametrize("tipo", ["txt", "srt", "json"])
def test_titulo_sin_letras_usa_el_id(client: TestClient, entorno: Entorno, tipo: str) -> None:
    video = guardar_video(entorno.session, titulo="¿¡!?")

    r = client.get(f"/videos/{video.id}/download/{tipo}")

    assert _nombre(r) == f"video_{video.id}.{tipo}"


@pytest.mark.parametrize("proceso", ["error", "afinidad_baja"])
def test_sirve_si_la_transcripcion_quedo_guardada(
    client: TestClient, entorno: Entorno, proceso: str
) -> None:
    """Ollama caído o afinidad baja: el análisis quedó guardado y se puede descargar."""
    video = guardar_video(entorno.session, proceso=proceso, modo="validar")

    r = client.get(f"/videos/{video.id}/download/srt")

    assert r.status_code == 200
    assert len(leer_srt(r.text)) == len(SEGMENTOS)


@pytest.mark.parametrize("proceso", ["en_cola", "procesando"])
@pytest.mark.parametrize("tipo", ["txt", "srt", "json"])
def test_409_mientras_procesa(
    client: TestClient, entorno: Entorno, proceso: str, tipo: str
) -> None:
    video = guardar_video(entorno.session, proceso=proceso)

    r = client.get(f"/videos/{video.id}/download/{tipo}")

    assert r.status_code == 409
    assert r.json()["detail"]["proceso"] == proceso


@pytest.mark.parametrize("tipo", ["txt", "srt", "json"])
def test_404_sin_transcripcion(client: TestClient, entorno: Entorno, tipo: str) -> None:
    video = guardar_video(entorno.session, proceso="error")
    video.transcripcion = None  # falló antes de transcribir (p. ej. sin pista de audio)
    entorno.session.commit()

    r = client.get(f"/videos/{video.id}/download/{tipo}")

    assert r.status_code == 404
    assert r.json()["detail"]["mensaje"] == "el video no tiene transcripción"


@pytest.mark.parametrize("tipo", ["txt", "srt", "json"])
def test_404_si_el_video_no_existe(client: TestClient, tipo: str) -> None:
    assert client.get(f"/videos/999999999/download/{tipo}").status_code == 404


@pytest.mark.parametrize("tipo", ["pdf", "TXT", "vtt", "txt.exe"])
def test_422_con_tipo_desconocido(client: TestClient, entorno: Entorno, tipo: str) -> None:
    video = guardar_video(entorno.session)

    assert client.get(f"/videos/{video.id}/download/{tipo}").status_code == 422


def test_el_txt_en_vivo_no_cambia(client: TestClient, entorno: Entorno) -> None:
    """`transcripcion.txt` (Procesando) sigue inline, con el archivo tal como va."""
    video = guardar_video(entorno.session)
    carpeta = entorno.settings.media_path / "videos" / str(video.id)
    carpeta.mkdir(parents=True)
    (carpeta / "transcripcion.txt").write_bytes(b"[00:00] Primero reviso\n")

    r = client.get(f"/videos/{video.id}/transcripcion.txt")

    assert r.text == "[00:00] Primero reviso\n"
    assert r.headers["content-disposition"] == f'inline; filename="transcripcion-{video.id}.txt"'
