"""Miniatura por paso (RF-11, ADR-024): solo ffmpeg, sin modelo, y `GET /videos/{id}/thumb`.

Los videos son sintéticos (fixture `generar_video`: testsrc, pantalla negra o solo audio, con un
tono); nada del cliente. Transcriptor, Ollama y juez son los dobles de tests/dobles.py.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dobles import Entorno, guardar_sop
from sopvid.contrato import Aviso, ReporteValidacion, es_provisional
from sopvid.percepcion import medios
from sopvid.percepcion import miniaturas as mini
from sopvid.percepcion.medios import MedioInvalido

# ── Funciones puras ──────────────────────────────────────────────────────────────────────────


def test_el_nombre_lleva_el_segundo_en_milisegundos() -> None:
    assert mini.nombre_miniatura(12.5) == "t000012500.jpg"
    assert mini.nombre_miniatura(0) == "t000000000.jpg"
    assert mini.nombre_miniatura(-1) == "t000000000.jpg"


def test_buscar_la_guardada_a_un_segundo_o_menos(tmp_path: Path) -> None:
    for t in (10.0, 20.0):
        (tmp_path / mini.nombre_miniatura(t)).write_bytes(b"jpg")
    (tmp_path / "otra.jpg").write_bytes(b"no cuenta")
    assert mini.buscar(tmp_path, 10.0).name == "t000010000.jpg"
    assert mini.buscar(tmp_path, 10.9).name == "t000010000.jpg"
    assert mini.buscar(tmp_path, 19.2).name == "t000020000.jpg"  # la más cercana
    assert mini.buscar(tmp_path, 11.5) is None  # a más de 1 s (RNF-03)
    assert mini.buscar(tmp_path / "no-existe", 10.0) is None


def test_el_aviso_sin_imagen_es_informativo() -> None:
    aviso = mini.aviso_sin_imagen()
    assert aviso.tipo == "sin_imagen"
    assert not es_provisional([aviso])
    assert es_provisional([aviso, Aviso(tipo="imagenes_incompletas", detalle="1 de 4")])


# ── Con ffmpeg ───────────────────────────────────────────────────────────────────────────────


def test_una_miniatura_por_segundo_en_su_nombre(generar_video, tmp_path: Path) -> None:
    video = generar_video(segundos=3)
    carpeta = tmp_path / "miniaturas"
    resultado = mini.generar_miniaturas(video, carpeta, [0.5, 1.5, 2.9, 1.5], 3.0, 320)
    assert not resultado.sin_imagen
    assert resultado.fallidas == 0
    assert sorted(p.name for p in carpeta.glob("t*.jpg")) == [
        "t000000500.jpg",
        "t000001500.jpg",
        "t000002900.jpg",
    ]
    assert all(p.read_bytes()[:2] == b"\xff\xd8" for p in resultado.archivos)  # JPEG


def test_todas_las_miniaturas_en_una_sola_llamada_a_ffmpeg(
    generar_video, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apagada la descripción, lo único que agregan las miniaturas es ffmpeg: una llamada por
    tanda (`CUADROS_POR_LLAMADA`), no una por miniatura."""
    video = generar_video(segundos=3)
    llamadas: list[list[str]] = []
    ejecutar = medios._ejecutar

    def contar(args: list[str], timeout_s: float | None):
        llamadas.append(args)
        return ejecutar(args, timeout_s)

    monkeypatch.setattr(medios, "_ejecutar", contar)
    tiempos = [0.1 * k for k in range(1, 26)]  # 25 > CUADROS_POR_LLAMADA (20)
    resultado = mini.generar_miniaturas(video, tmp_path / "m", tiempos, 3.0, 320)
    extracciones = [a for a in llamadas if "-map" in a]
    assert len(extracciones) == 2  # 20 + 5
    assert (len(resultado.archivos), resultado.fallidas) == (25, 0)
    # Cada salida es su propio cuadro, igual que sacándolo solo.
    solo = medios.extraer_cuadro(video, 2.5, tmp_path / "solo.jpg", 320)
    assert (tmp_path / "m" / "t000002500.jpg").read_bytes() == solo.read_bytes()


def test_el_reporte_saca_cada_segundo_y_la_peticion_reusa_a_un_segundo(
    generar_video, tmp_path: Path
) -> None:
    video = generar_video(segundos=3)
    carpeta = tmp_path / "miniaturas"
    mini.generar_miniaturas(video, carpeta, [1.0], 3.0, 320)
    mini.generar_miniaturas(video, carpeta, [1.0, 1.4], 3.0, 320)  # filas a 0.4 s: dos JPEG
    assert sorted(p.name for p in carpeta.glob("t*.jpg")) == ["t000001000.jpg", "t000001400.jpg"]
    # La petición por segundo (RNF-03) reusa la más cercana a ≤ 1 s, sin sacar otra.
    assert mini.asegurar(video, carpeta, 2.3, 3.0, 320).name == "t000001400.jpg"
    assert len(list(carpeta.glob("t*.jpg"))) == 2


@pytest.mark.parametrize("imagen", ["ninguna", "negra"])
def test_sin_imagen_no_hay_miniaturas_y_queda_la_marca(
    generar_video, tmp_path: Path, imagen: str
) -> None:
    video = generar_video(segundos=3, imagen=imagen)
    carpeta = tmp_path / "miniaturas"
    resultado = mini.generar_miniaturas(video, carpeta, [0.5, 1.5], 3.0, 320)
    assert resultado.sin_imagen
    assert resultado.archivos == []
    assert list(carpeta.glob("t*.jpg")) == []
    assert mini.sin_imagen_marcado(carpeta)


def test_imagen_visible_distingue_barras_de_negro(generar_video) -> None:
    assert medios.imagen_visible(generar_video("a.mp4", segundos=2), 2.0)
    assert not medios.imagen_visible(generar_video("b.mp4", segundos=2, imagen="negra"), 2.0)
    assert not medios.tiene_imagen(generar_video("c.mp4", segundos=2, imagen="ninguna"))


def test_el_cuadro_respeta_el_lado_mayor(generar_video, tmp_path: Path) -> None:
    video = generar_video(segundos=2)  # 160x120: no se agranda
    grande = medios.extraer_cuadro(video, 1.0, tmp_path / "g.jpg", 320)
    chico = medios.extraer_cuadro(video, 1.0, tmp_path / "c.jpg", 64)
    assert grande.stat().st_size > chico.stat().st_size
    assert not list(tmp_path.glob("*.part"))


# ── En la validación y en la API ─────────────────────────────────────────────────────────────


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _validar(client: TestClient, entorno: Entorno, video: Path) -> int:
    sop = guardar_sop(entorno.session)
    r = client.post(
        "/videos",
        files={"archivo": ("operador.mp4", video.read_bytes(), "video/mp4")},
        data={"titulo": "Revisión", "modo": "validar", "sop_id": str(sop.id)},
    )
    assert r.status_code == 202
    entorno.correr_pendientes()
    return r.json()["id"]


def _carpeta(entorno: Entorno, video_id: int) -> Path:
    return entorno.settings.media_path / "videos" / str(video_id) / "miniaturas"


def test_la_validacion_deja_una_miniatura_por_fila_con_segundo(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _validar(client, entorno, generar_video())
    reporte = ReporteValidacion.model_validate(client.get(f"/videos/{video_id}/reporte").json())
    con_segundo = [f.t_inicio for f in reporte.filas if f.t_inicio is not None]
    assert con_segundo
    nombres = {p.name for p in _carpeta(entorno, video_id).glob("t*.jpg")}
    assert nombres == {mini.nombre_miniatura(t) for t in con_segundo}
    assert "miniaturas" in reporte.metadatos.segundos
    assert all(a.tipo != "sin_imagen" for a in reporte.metadatos.avisos)


def test_video_solo_audio_sin_miniaturas_y_aviso_que_no_es_provisional(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _validar(client, entorno, generar_video(imagen="ninguna"))
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert [a["tipo"] for a in reporte["metadatos"]["avisos"]] == ["sin_imagen"]
    assert reporte["provisional"] is False  # como A y B: el resto sigue igual
    assert list(_carpeta(entorno, video_id).glob("t*.jpg")) == []
    assert client.get(f"/videos/{video_id}/thumb", params={"t": 1.0}).status_code == 404


def test_thumb_guardada_sin_llamar_a_ffmpeg(
    client: TestClient, entorno: Entorno, generar_video, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_id = _validar(client, entorno, generar_video())
    guardada = sorted(_carpeta(entorno, video_id).glob("t*.jpg"))[0]
    t = int(guardada.stem[1:]) / 1000

    def sin_ffmpeg(*args, **kwargs):
        raise AssertionError("no debía llamar a ffmpeg")

    monkeypatch.setattr(mini, "extraer_cuadro", sin_ffmpeg)
    r = client.get(f"/videos/{video_id}/thumb", params={"t": t + 0.4})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "max-age=86400" in r.headers["cache-control"]
    assert r.content == guardada.read_bytes()


def test_thumb_nueva_se_genera_y_queda_en_cache(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _validar(client, entorno, generar_video(segundos=3))
    carpeta = _carpeta(entorno, video_id)
    for archivo in carpeta.glob("t*.jpg"):  # que no quede ninguna cerca de 2.95 s
        if abs(int(archivo.stem[1:]) / 1000 - 2.95) <= 1:
            archivo.unlink()
    antes = {p.name for p in carpeta.glob("t*.jpg")}
    r = client.get(f"/videos/{video_id}/thumb", params={"t": 2.95})
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"
    assert {p.name for p in carpeta.glob("t*.jpg")} - antes == {"t000002950.jpg"}


def test_thumb_fuera_de_rango_o_de_un_video_que_no_existe(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _validar(client, entorno, generar_video(segundos=3))
    assert client.get(f"/videos/{video_id}/thumb", params={"t": 3.5}).status_code == 400
    assert client.get(f"/videos/{video_id}/thumb", params={"t": -1}).status_code == 400
    assert client.get("/videos/999999/thumb", params={"t": 1}).status_code == 404


def test_un_error_de_ffmpeg_en_las_miniaturas_no_tira_el_reporte(
    client: TestClient, entorno: Entorno, generar_video, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falla(*args, **kwargs):
        raise MedioInvalido("video.mp4: ffmpeg no pudo extraer el cuadro")

    monkeypatch.setattr(mini, "extraer_cuadros", falla)
    video_id = _validar(client, entorno, generar_video())
    assert entorno.video(video_id).proceso == "listo"
    assert list(_carpeta(entorno, video_id).glob("t*.jpg")) == []
    assert client.get(f"/videos/{video_id}/reporte").json()["provisional"] is False
