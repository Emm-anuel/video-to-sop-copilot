"""Publicar un video en la búsqueda exacta (RF-32): `POST` y `DELETE /videos/{id}/publicar`.

Con la base de pruebas (`db_session`, se revierte al final), videos ya analizados guardados con
`dobles.guardar_video` y transcripciones inventadas. La publicación al terminar
(`PUBLICAR_AL_TERMINAR`) corre el trabajo completo con `generar_video` (se salta sin ffmpeg).
"""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dobles import SEGMENTOS, Entorno, guardar_video
from sopvid.contrato import EstadoPublicacion
from sopvid.lenguaje import busqueda
from sopvid.lenguaje.busqueda import publicar_al_terminar

PALABRAS = sum(len(s.palabras) for s in SEGMENTOS)


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def test_publicar_indexa_y_marca_el_video(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session)

    r = client.post(f"/videos/{video.id}/publicar")

    assert r.status_code == 200
    estado = EstadoPublicacion.model_validate(r.json())
    assert (estado.video_id, estado.publicado, estado.palabras_indexadas) == (
        video.id,
        True,
        PALABRAS,
    )
    assert estado.publicado_en is not None
    guardado = entorno.video(video.id)
    assert guardado.publicado
    assert guardado.publicado_en == estado.publicado_en
    assert busqueda.contar(entorno.session, guardado) == PALABRAS


def test_el_estado_del_video_dice_si_esta_publicado(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session)
    assert client.get(f"/videos/{video.id}").json()["publicado"] is False

    client.post(f"/videos/{video.id}/publicar")
    assert client.get(f"/videos/{video.id}").json()["publicado"] is True

    client.delete(f"/videos/{video.id}/publicar")
    assert client.get(f"/videos/{video.id}").json()["publicado"] is False


def test_publicar_otra_vez_reemplaza_sin_duplicar(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session)

    primera = client.post(f"/videos/{video.id}/publicar").json()
    segunda = client.post(f"/videos/{video.id}/publicar").json()

    assert primera["palabras_indexadas"] == segunda["palabras_indexadas"] == PALABRAS
    assert busqueda.contar(entorno.session, entorno.video(video.id)) == PALABRAS
    assert datetime.fromisoformat(segunda["publicado_en"]) >= datetime.fromisoformat(
        primera["publicado_en"]
    )


def test_quitar_borra_el_indice_y_desmarca(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session)
    client.post(f"/videos/{video.id}/publicar")

    r = client.delete(f"/videos/{video.id}/publicar")

    assert r.status_code == 200
    assert r.json() == {
        "video_id": video.id,
        "publicado": False,
        "publicado_en": None,
        "palabras_indexadas": 0,
    }
    guardado = entorno.video(video.id)
    assert (guardado.publicado, guardado.publicado_en) == (False, None)
    assert busqueda.contar(entorno.session, guardado) == 0


def test_quitar_un_video_sin_publicar_no_falla(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session, proceso="procesando")
    r = client.delete(f"/videos/{video.id}/publicar")
    assert r.status_code == 200
    assert r.json()["publicado"] is False


@pytest.mark.parametrize("proceso", ["en_cola", "procesando", "error", "afinidad_baja"])
def test_409_si_el_analisis_no_termino(client: TestClient, entorno: Entorno, proceso: str) -> None:
    video = guardar_video(entorno.session, proceso=proceso)

    r = client.post(f"/videos/{video.id}/publicar")

    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["proceso"] == proceso
    assert "no ha terminado" in detalle["mensaje"]
    assert not entorno.video(video.id).publicado
    assert busqueda.contar(entorno.session, entorno.video(video.id)) == 0


@pytest.mark.parametrize("metodo", ["post", "delete"])
def test_404_si_el_video_no_existe(client: TestClient, metodo: str) -> None:
    r = getattr(client, metodo)("/videos/999999999/publicar")
    assert r.status_code == 404


# ── PUBLICAR_AL_TERMINAR ──────────────────────────────────────────────────────────────────────


def test_al_terminar_publica_si_esta_encendido(
    db_session: Session, tmp_path: Path, generar_video
) -> None:
    entorno = Entorno(db_session, tmp_path, al_terminar=publicar_al_terminar)
    with TestClient(entorno.app) as client:
        datos = {"titulo": "Cambio de filtro", "modo": "generar"}
        archivo = {"archivo": ("operador.mp4", generar_video().read_bytes(), "video/mp4")}
        video_id = client.post("/videos", files=archivo, data=datos).json()["id"]
        entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert video.proceso == "listo"
    assert video.publicado and video.publicado_en is not None
    assert busqueda.contar(db_session, video) == PALABRAS


def test_al_terminar_no_publica_por_defecto(client: TestClient, entorno: Entorno, generar_video):
    datos = {"titulo": "Cambio de filtro", "modo": "generar"}
    archivo = {"archivo": ("operador.mp4", generar_video().read_bytes(), "video/mp4")}
    video_id = client.post("/videos", files=archivo, data=datos).json()["id"]
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert video.proceso == "listo"
    assert (video.publicado, video.publicado_en) == (False, None)


def test_si_publicar_al_terminar_falla_el_video_sigue_listo(
    db_session: Session, tmp_path: Path, generar_video
) -> None:
    def falla(session: Session, video_id: int) -> None:
        raise RuntimeError("base caída")

    entorno = Entorno(db_session, tmp_path, al_terminar=falla)
    with TestClient(entorno.app) as client:
        datos = {"titulo": "Cambio de filtro", "modo": "generar"}
        archivo = {"archivo": ("operador.mp4", generar_video().read_bytes(), "video/mp4")}
        video_id = client.post("/videos", files=archivo, data=datos).json()["id"]
        entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert (video.proceso, video.publicado) == ("listo", False)
