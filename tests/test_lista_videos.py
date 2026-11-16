"""Lista de videos (`GET /videos`, pantalla 6).

Con la base de pruebas (`db_session`, se revierte al final) y videos inventados guardados con
`dobles.guardar_video`. La base de desarrollo puede tener otros videos: las pruebas solo miran
los que crean (por id o con un filtro por un SOP propio).
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dobles import Entorno, guardar_sop, guardar_video
from sopvid.contrato import VideoResumen
from sopvid.plataforma.modelos import Reporte, Sop, Video


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _lista(client: TestClient, **filtros) -> list[dict]:
    r = client.get("/videos", params=filtros)
    assert r.status_code == 200, r.text
    for v in r.json():
        VideoResumen.model_validate(v)
    return r.json()


def _ids(client: TestClient, **filtros) -> list[int]:
    return [v["id"] for v in _lista(client, **filtros)]


def _reporte(
    session: Session, video: Video, sop: Sop, cumplimiento: str | None, semaforo: str | None
) -> None:
    resultado = {} if semaforo is None else {"semaforo": semaforo}
    session.add(
        Reporte(
            video=video,
            sop=sop,
            afinidad=80,
            cumplimiento=None if cumplimiento is None else Decimal(cumplimiento),
            resultado=resultado,
        )
    )
    session.commit()


def test_del_mas_reciente_al_mas_antiguo(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    viejo = guardar_video(s, creado=datetime(2026, 11, 1, tzinfo=UTC))
    nuevo = guardar_video(s, creado=datetime(2026, 11, 3, tzinfo=UTC))
    # Creado después pero con fecha anterior: manda la fecha, no el id.
    medio = guardar_video(s, creado=datetime(2026, 11, 2, tzinfo=UTC))

    mios = [i for i in _ids(client) if i in {viejo.id, nuevo.id, medio.id}]

    assert mios == [nuevo.id, medio.id, viejo.id]


def test_campos_de_un_video_validado_con_reporte(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = guardar_sop(s)
    video = guardar_video(
        s, titulo="Revisión de la línea", modo="validar", sop=sop, analizar_imagenes=True
    )
    _reporte(s, video, sop, "87.50", "amarillo")

    (fila,) = _lista(client, sop_id=sop.id)

    assert fila == {
        "id": video.id,
        "titulo": "Revisión de la línea",
        "creado": fila["creado"],
        "duracion": 2.8,
        "modo": "validar",
        "proceso": "listo",
        "etapa": None,
        "error": None,
        "cumplimiento": 87.5,
        "semaforo": "amarillo",
        "sop": {"id": sop.id, "codigo": sop.codigo, "titulo": sop.titulo},
        "analizar_imagenes": True,
        "publicado": False,
        "publicado_en": None,
    }


def test_sin_reporte_ni_sop_van_en_null(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session, proceso="error", error="falló la etapa audio")

    fila = next(v for v in _lista(client) if v["id"] == video.id)

    assert (fila["sop"], fila["cumplimiento"], fila["semaforo"]) == (None, None, None)
    assert (fila["proceso"], fila["error"]) == ("error", "falló la etapa audio")
    assert fila["analizar_imagenes"] is False  # NULL en la base (videos anteriores a la 0007)


def test_afinidad_baja_no_lleva_porcentaje(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop = guardar_sop(s)
    video = guardar_video(s, modo="validar", proceso="afinidad_baja", sop=sop)
    _reporte(s, video, sop, None, None)

    (fila,) = _lista(client, sop_id=sop.id)

    assert (fila["proceso"], fila["cumplimiento"], fila["semaforo"]) == (
        "afinidad_baja",
        None,
        None,
    )


def test_mientras_se_repite_la_validacion_no_muestra_el_reporte_anterior(
    client: TestClient, entorno: Entorno
) -> None:
    s = entorno.session
    sop = guardar_sop(s)
    video = guardar_video(s, modo="validar", proceso="en_cola", sop=sop)
    _reporte(s, video, sop, "100.00", "verde")

    (fila,) = _lista(client, sop_id=sop.id)

    assert (fila["cumplimiento"], fila["semaforo"]) == (None, None)


def test_un_video_publicado_trae_su_fecha(client: TestClient, entorno: Entorno) -> None:
    sop = guardar_sop(entorno.session)
    video = guardar_video(entorno.session, modo="validar", sop=sop)
    publicado_en = client.post(f"/videos/{video.id}/publicar").json()["publicado_en"]

    (fila,) = _lista(client, sop_id=sop.id)

    assert fila["publicado"] is True
    assert datetime.fromisoformat(fila["publicado_en"]) == datetime.fromisoformat(publicado_en)


def test_filtros(client: TestClient, entorno: Entorno) -> None:
    s = entorno.session
    sop, otro_sop = guardar_sop(s), guardar_sop(s)
    validado = guardar_video(s, modo="validar", sop=sop)
    en_error = guardar_video(s, modo="validar", proceso="error", sop=sop)
    generado = guardar_video(s, modo="generar", sop=sop)  # el SOP que se generó de él
    ajeno = guardar_video(s, modo="validar", sop=otro_sop)
    client.post(f"/videos/{generado.id}/publicar")

    assert set(_ids(client, sop_id=sop.id)) == {validado.id, en_error.id, generado.id}
    assert set(_ids(client, sop_id=sop.id, modo="validar")) == {validado.id, en_error.id}
    assert _ids(client, sop_id=sop.id, modo="generar") == [generado.id]
    assert _ids(client, sop_id=sop.id, proceso="error") == [en_error.id]
    assert _ids(client, sop_id=sop.id, publicado=True) == [generado.id]
    assert set(_ids(client, sop_id=sop.id, publicado=False)) == {validado.id, en_error.id}
    assert _ids(client, sop_id=sop.id, modo="generar", proceso="error") == []
    assert ajeno.id in _ids(client, modo="validar")
    assert ajeno.id not in _ids(client, sop_id=sop.id)


def test_un_filtro_sin_coincidencias_da_lista_vacia(client: TestClient, entorno: Entorno) -> None:
    sop = guardar_sop(entorno.session)
    assert _lista(client, sop_id=sop.id) == []


@pytest.mark.parametrize(
    "filtros",
    [{"modo": "otro"}, {"proceso": "terminado"}, {"publicado": "quizas"}, {"sop_id": "uno"}],
)
def test_filtro_invalido_da_422(client: TestClient, filtros: dict) -> None:
    assert client.get("/videos", params=filtros).status_code == 422


def test_no_choca_con_el_estado_de_un_video(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session)
    r = client.get(f"/videos/{video.id}")
    assert r.status_code == 200
    assert r.json()["id"] == video.id
