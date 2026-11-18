"""Biblioteca de SOP (RF-05): `GET /sops` y `DELETE /sops/{id}`, y `DELETE /videos/{id}`.

Usan la base de conftest.py (`db_session`, revertida al final) con SOP inventados (`SOP_PRUEBA` de
tests/dobles.py). La base de desarrollo puede traer otros SOP: las pruebas miran solo los suyos.
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dobles import SOP_PRUEBA, Entorno, guardar_sop
from sopvid.plataforma.modelos import Palabra, Reporte, Sop, Video
from sopvid.plataforma.procesamiento import carpeta_sop


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _sop(session: Session, titulo: str = "SOP de prueba", **cambios) -> Sop:
    """Un SOP listo en la biblioteca, salvo lo que cambie la prueba."""
    datos = {
        "titulo": titulo,
        "origen": "cargado",
        "contenido": SOP_PRUEBA.model_copy(update={"titulo": titulo}).model_dump(mode="json"),
    }
    fila = Sop(**(datos | cambios))
    session.add(fila)
    session.commit()
    return fila


def _video(session: Session, sop: Sop | None, modo: str = "validar") -> Video:
    video = Video(titulo="Video de prueba", archivo="videos/x/video.mp4", modo=modo, sop=sop)
    session.add(video)
    session.commit()
    return video


def _reporte(session: Session, video: Video, sop: Sop) -> Reporte:
    reporte = Reporte(
        video=video, sop=sop, afinidad=80, cumplimiento=Decimal("87.50"), resultado={}
    )
    session.add(reporte)
    session.commit()
    return reporte


def _listados(client: TestClient) -> dict[int, dict]:
    r = client.get("/sops")
    assert r.status_code == 200
    return {s["id"]: s for s in r.json()}


# ── GET /sops ────────────────────────────────────────────────────────────────────────────────


def test_lista_solo_los_listos_en_la_biblioteca(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    cargado = _sop(s, "Cargado listo")
    guardado = _sop(s, "Generado y guardado", origen="generado")
    sin_guardar = _sop(s, "Generado sin guardar", origen="generado", en_biblioteca=False)
    en_cola = _sop(s, None, estado="en_cola", contenido=None)
    convirtiendo = _sop(s, None, estado="convirtiendo", contenido=None)
    con_error = _sop(s, None, estado="error", contenido=None, error="no se pudo leer")

    listados = _listados(client)

    assert cargado.id in listados and guardado.id in listados
    for fuera in (sin_guardar, en_cola, convirtiendo, con_error):
        assert fuera.id not in listados
    assert listados[cargado.id] == {
        "id": cargado.id,
        "codigo": cargado.codigo,
        "titulo": "Cargado listo",
        "origen": "cargado",
        "creado": listados[cargado.id]["creado"],
        "videos_validados": 0,
    }
    assert listados[guardado.id]["origen"] == "generado"


def test_cuenta_los_videos_validados_con_cada_sop(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = _sop(s)
    for _ in range(2):
        _reporte(s, _video(s, sop), sop)
    _video(s, sop)  # en cola: todavía sin reporte, no cuenta como validado
    otro = _sop(s, "Sin videos")

    listados = _listados(client)

    assert listados[sop.id]["videos_validados"] == 2
    assert listados[otro.id]["videos_validados"] == 0


def test_del_mas_nuevo_al_mas_viejo(client: TestClient, entorno: Entorno) -> None:
    primero = _sop(entorno.session, "Primero")
    segundo = _sop(entorno.session, "Segundo")
    ids = [s["id"] for s in client.get("/sops").json()]
    # En la misma transacción `creado` es igual: desempata el id.
    assert ids.index(segundo.id) < ids.index(primero.id)


# ── DELETE /sops/{id} ────────────────────────────────────────────────────────────────────────


def test_borra_un_sop_sin_uso_y_su_carpeta(client: TestClient, entorno: Entorno) -> None:
    sop = _sop(entorno.session)
    carpeta = carpeta_sop(entorno.settings.media_path, sop.id)
    carpeta.mkdir(parents=True)
    (carpeta / "original.md").write_text("# SOP inventado", encoding="utf-8")
    sop_id = sop.id

    r = client.delete(f"/sops/{sop_id}")

    assert r.status_code == 204 and r.content == b""
    entorno.session.expire_all()
    assert entorno.session.get(Sop, sop_id) is None
    assert not carpeta.exists()
    assert client.get(f"/sops/{sop_id}").status_code == 404
    assert sop_id not in _listados(client)


def test_borra_un_sop_en_error(client: TestClient, entorno: Entorno) -> None:
    sop = _sop(entorno.session, None, estado="error", contenido=None, error="dañado")
    assert client.delete(f"/sops/{sop.id}").status_code == 204


def test_borrar_404(client: TestClient) -> None:
    assert client.delete("/sops/999999").status_code == 404


def test_409_si_un_video_lo_usa_y_no_borra_nada(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = _sop(s)
    video = _video(s, sop)  # en cola, sin reporte todavía

    r = client.delete(f"/sops/{sop.id}")

    assert r.status_code == 409
    assert r.json()["detail"] == {
        "mensaje": f"El SOP {sop.codigo} no se puede eliminar: 1 video lo usa como referencia.",
        "videos": 1,
        "reportes": 0,
    }
    s.expire_all()
    assert s.get(Sop, sop.id) is not None and s.get(Video, video.id).sop_id == sop.id


def test_409_con_videos_validados(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = _sop(s)
    for _ in range(2):
        _reporte(s, _video(s, sop), sop)

    detalle = client.delete(f"/sops/{sop.id}").json()["detail"]

    assert detalle["mensaje"] == (
        f"El SOP {sop.codigo} no se puede eliminar: 2 videos lo usan como referencia y sus 2 "
        "reportes dependen de él."
    )
    assert (detalle["videos"], detalle["reportes"]) == (2, 2)


def test_409_si_solo_un_reporte_lo_referencia(client: TestClient, entorno: Entorno) -> None:
    # El video apunta hoy a otro SOP, pero su reporte se hizo con este: el reporte lo protege.
    s = entorno.session
    sop, otro = _sop(s), _sop(s, "Otro")
    _reporte(s, _video(s, otro), sop)

    r = client.delete(f"/sops/{sop.id}")

    assert r.status_code == 409
    assert r.json()["detail"]["mensaje"] == (
        f"El SOP {sop.codigo} no se puede eliminar: 1 video lo usa como referencia y su reporte "
        "depende de él."
    )


def test_409_un_generado_lo_sigue_usando_su_video(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = _sop(s, origen="generado")
    video = _video(s, sop, modo="generar")

    r = client.delete(f"/sops/{sop.id}")

    assert r.status_code == 409
    assert r.json()["detail"]["mensaje"] == (
        f"El SOP {sop.codigo} no se puede eliminar: se generó desde el video {video.id}, que lo "
        "sigue usando."
    )


def test_409_generado_y_ademas_usado_como_referencia(client: TestClient, entorno: Entorno) -> None:
    # Se guardó en la biblioteca y otro video se validó con él: el mensaje dice las dos cosas.
    s = entorno.session
    sop = _sop(s, origen="generado")
    origen = _video(s, sop, modo="generar")
    _reporte(s, _video(s, sop), sop)

    detalle = client.delete(f"/sops/{sop.id}").json()["detail"]

    assert detalle["mensaje"] == (
        f"El SOP {sop.codigo} no se puede eliminar: se generó desde el video {origen.id}, que lo "
        "sigue usando; además, 1 video lo usa como referencia y su reporte depende de él."
    )
    assert (detalle["videos"], detalle["reportes"]) == (2, 1)


@pytest.mark.parametrize("estado", ["en_cola", "convirtiendo"])
def test_409_mientras_se_convierte(client: TestClient, entorno: Entorno, estado: str) -> None:
    sop = _sop(entorno.session, None, estado=estado, contenido=None)

    r = client.delete(f"/sops/{sop.id}")

    assert r.status_code == 409
    assert r.json()["detail"] == {
        "mensaje": f"El SOP {sop.codigo} se está convirtiendo: espera a que termine para "
        "eliminarlo.",
        "estado": estado,
    }
    entorno.session.expire_all()
    assert entorno.session.get(Sop, sop.id) is not None


def test_guardar_sop_de_dobles_entra_a_la_lista(client: TestClient, entorno: Entorno) -> None:
    # El SOP que usan las demás pruebas de la API (cargado, listo) sale en la biblioteca.
    assert guardar_sop(entorno.session).id in _listados(client)


# ── DELETE /videos/{id} ──────────────────────────────────────────────────────────────────────


def _carpeta_video(entorno: Entorno, video: Video) -> Path:
    carpeta = entorno.settings.media_path / "videos" / str(video.id)
    carpeta.mkdir(parents=True)
    (carpeta / "video.mp4").write_bytes(b"inventado")
    return carpeta


def test_borra_un_video_con_reporte_palabras_y_carpeta(
    client: TestClient, entorno: Entorno
) -> None:
    s = entorno.session
    sop = _sop(s)
    video = _video(s, sop)
    video.proceso = "listo"
    _reporte(s, video, sop)
    s.add(
        Palabra(
            video_id=video.id,
            palabra_normalizada="hola",
            palabra_original="Hola",
            t_inicio=0.0,
            t_fin=0.5,
            posicion=0,
        )
    )
    s.commit()
    carpeta = _carpeta_video(entorno, video)
    video_id, sop_id = video.id, sop.id

    r = client.delete(f"/videos/{video_id}")

    assert r.status_code == 200
    assert r.json() == {"id": video_id, "sop_eliminado": None, "sop_conservado": None}
    s.expire_all()
    assert s.get(Video, video_id) is None
    assert (
        s.scalar(select(func.count()).select_from(Reporte).where(Reporte.video_id == video_id)) == 0
    )
    assert (
        s.scalar(select(func.count()).select_from(Palabra).where(Palabra.video_id == video_id)) == 0
    )
    assert not carpeta.exists()
    # Un SOP cargado es de la biblioteca: no se va con el video.
    assert s.get(Sop, sop_id) is not None
    assert client.get(f"/videos/{video_id}").status_code == 404


def test_borra_el_sop_generado_junto_con_el_video(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = _sop(s, "Generado", origen="generado", en_biblioteca=False)
    video = _video(s, sop, modo="generar")
    video.proceso = "listo"
    s.commit()
    carpeta_v = _carpeta_video(entorno, video)
    carpeta_s = carpeta_sop(entorno.settings.media_path, sop.id)
    carpeta_s.mkdir(parents=True)
    video_id, sop_id, codigo = video.id, sop.id, sop.codigo

    r = client.delete(f"/videos/{video_id}")

    assert r.status_code == 200
    assert r.json() == {
        "id": video_id,
        "sop_eliminado": {"id": sop_id, "codigo": codigo, "titulo": "Generado"},
        "sop_conservado": None,
    }
    s.expire_all()
    assert s.get(Video, video_id) is None and s.get(Sop, sop_id) is None
    assert not carpeta_v.exists() and not carpeta_s.exists()


def test_conserva_el_sop_generado_si_otro_video_lo_usa(
    client: TestClient, entorno: Entorno
) -> None:
    # Se guardó en la biblioteca y otro video se validó con él: se va el video, no el SOP.
    s = entorno.session
    sop = _sop(s, origen="generado")
    origen = _video(s, sop, modo="generar")
    origen.proceso = "listo"
    otro = _video(s, sop)
    _reporte(s, otro, sop)
    origen_id, sop_id, otro_id = origen.id, sop.id, otro.id

    r = client.delete(f"/videos/{origen_id}")

    assert r.status_code == 200
    detalle = r.json()
    assert detalle["sop_eliminado"] is None
    assert "se conserva" in detalle["sop_conservado"]
    s.expire_all()
    assert s.get(Video, origen_id) is None
    assert s.get(Sop, sop_id) is not None and s.get(Video, otro_id) is not None


def test_borra_un_video_sin_sop_todavia(client: TestClient, entorno: Entorno) -> None:
    # Modo generar que falló antes de crear el SOP.
    video = _video(entorno.session, None, modo="generar")
    video.proceso = "error"
    entorno.session.commit()
    video_id = video.id

    r = client.delete(f"/videos/{video_id}")

    assert r.status_code == 200
    assert r.json() == {"id": video_id, "sop_eliminado": None, "sop_conservado": None}


@pytest.mark.parametrize("proceso", ["en_cola", "procesando"])
def test_409_si_el_video_esta_en_proceso(
    client: TestClient, entorno: Entorno, proceso: str
) -> None:
    s = entorno.session
    sop = _sop(s, origen="generado", en_biblioteca=False)
    video = _video(s, sop, modo="generar")
    video.proceso = proceso
    s.commit()
    carpeta = _carpeta_video(entorno, video)

    r = client.delete(f"/videos/{video.id}")

    assert r.status_code == 409
    assert r.json()["detail"]["proceso"] == proceso
    s.expire_all()
    assert s.get(Video, video.id) is not None and s.get(Sop, sop.id) is not None
    assert carpeta.exists()


def test_borrar_video_404(client: TestClient) -> None:
    assert client.delete("/videos/999999").status_code == 404
