"""Pruebas de la subida por partes (RF-06): `/uploads` y `POST /videos` con `upload_id`.

Los archivos se generan en la prueba (`generar_video`, con ffmpeg; sin él se saltan) o son bytes
inventados; ningún medio se versiona. Las partes miden pocos KB (`SUBIDA_PARTE_MB` fraccionario).
"""

import hashlib
import math
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dobles import Entorno, guardar_sop
from sopvid.percepcion import subidas
from sopvid.plataforma.modelos import Video

MB = 1024 * 1024


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _partes_de(entorno: Entorno, bytes_parte: int) -> None:
    entorno.settings.subida_parte_mb = bytes_parte / MB
    assert entorno.settings.subida_parte_bytes == bytes_parte


def _abrir(client: TestClient, tamano: int, nombre: str = "operador.mp4"):
    return client.post("/uploads", json={"nombre": nombre, "tamano": tamano})


def _parte(client: TestClient, upload_id: str, offset: int, datos: bytes):
    return client.put(
        f"/uploads/{upload_id}",
        params={"offset": offset},
        content=datos,
        headers={"Content-Type": "application/octet-stream"},
    )


def _subir_en_partes(client: TestClient, contenido: bytes, partes: int, nombre: str) -> str:
    """Abre la subida y manda `contenido` en `partes` partes; devuelve el `upload_id`."""
    abierta = _abrir(client, len(contenido), nombre)
    assert abierta.status_code == 201, abierta.text
    upload_id = abierta.json()["upload_id"]
    tamano_parte = abierta.json()["tamano_parte"]
    assert math.ceil(len(contenido) / tamano_parte) == partes
    for offset in range(0, len(contenido), tamano_parte):
        r = _parte(client, upload_id, offset, contenido[offset : offset + tamano_parte])
        assert r.status_code == 200, r.text
    return upload_id


def _crear_video(client: TestClient, upload_id: str, **datos: str):
    formulario = {"titulo": "Cambio de filtro", "modo": "generar", "upload_id": upload_id, **datos}
    return client.post("/videos", data=formulario)


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _filas(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Video))


def _carpeta(entorno: Entorno, upload_id: str) -> Path:
    return subidas.carpeta_subidas(entorno.settings.media_path) / upload_id


# ── Subida completa ──────────────────────────────────────────────────────────


def test_subida_en_tres_partes_arma_el_mismo_archivo(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    contenido = generar_video("operador.mp4").read_bytes()
    _partes_de(entorno, math.ceil(len(contenido) / 3))

    upload_id = _subir_en_partes(client, contenido, 3, "operador.mp4")
    estado = client.get(f"/uploads/{upload_id}").json()
    assert (estado["recibidos"], estado["tamano"], estado["completo"]) == (
        len(contenido),
        len(contenido),
        True,
    )
    r = _crear_video(client, upload_id)

    assert r.status_code == 202, r.text
    video = entorno.video(r.json()["id"])
    assert r.headers["location"] == f"/videos/{video.id}"
    assert video.archivo == f"videos/{video.id}/video.mp4"  # nunca el nombre original
    guardado = entorno.settings.media_path / video.archivo
    assert _sha(guardado.read_bytes()) == _sha(contenido)
    assert not _carpeta(entorno, upload_id).exists()  # la subida se consumió
    assert client.get(f"/uploads/{upload_id}").status_code == 404
    assert len(entorno.pendientes) == 1
    entorno.correr_pendientes()
    assert entorno.video(video.id).proceso == "listo"


def test_la_subida_no_guarda_el_nombre_original(client: TestClient, entorno: Entorno) -> None:
    r = _abrir(client, 100, nombre="Planta Norte - Laura.MP4")

    meta = (_carpeta(entorno, r.json()["upload_id"]) / subidas.ARCHIVO_META).read_text()
    assert "Laura" not in meta and "Planta" not in meta
    assert '".mp4"' in meta


def test_parte_repetida_no_duplica_ni_corrompe(client: TestClient, entorno: Entorno) -> None:
    contenido = os.urandom(10_000)
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, len(contenido)).json()["upload_id"]

    primera = _parte(client, upload_id, 0, contenido[:4_000])
    repetida = _parte(client, upload_id, 0, contenido[:4_000])

    assert primera.status_code == repetida.status_code == 200
    assert primera.json()["recibidos"] == repetida.json()["recibidos"] == 4_000
    _parte(client, upload_id, 4_000, contenido[4_000:8_000])
    _parte(client, upload_id, 4_000, contenido[4_000:8_000])  # se perdió la respuesta
    final = _parte(client, upload_id, 8_000, contenido[8_000:])
    assert final.json() | {"upload_id": ""} == {
        "upload_id": "",
        "tamano": 10_000,
        "tamano_parte": 4_000,
        "recibidos": 10_000,
        "completo": True,
    }
    armado = (_carpeta(entorno, upload_id) / subidas.ARCHIVO_DATOS).read_bytes()
    assert _sha(armado) == _sha(contenido)


def test_parte_que_empieza_atras_solo_anexa_lo_que_falta(
    client: TestClient, entorno: Entorno
) -> None:
    contenido = os.urandom(6_000)
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, len(contenido)).json()["upload_id"]
    _parte(client, upload_id, 0, contenido[:3_000])

    r = _parte(client, upload_id, 2_000, contenido[2_000:6_000])

    assert r.json()["recibidos"] == 6_000
    armado = (_carpeta(entorno, upload_id) / subidas.ARCHIVO_DATOS).read_bytes()
    assert armado == contenido


def test_offset_adelantado_da_409_con_el_offset_correcto(
    client: TestClient, entorno: Entorno
) -> None:
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, 10_000).json()["upload_id"]
    _parte(client, upload_id, 0, b"a" * 4_000)

    r = _parte(client, upload_id, 8_000, b"c" * 2_000)

    assert r.status_code == 409
    assert r.json()["detail"]["offset"] == 4_000
    assert r.json()["detail"]["tamano"] == 10_000
    assert client.get(f"/uploads/{upload_id}").json()["recibidos"] == 4_000


def test_parte_que_pasa_del_tamano_declarado_da_409(client: TestClient, entorno: Entorno) -> None:
    """El archivo real es más grande que lo declarado: el tamaño no coincide."""
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, 5_000).json()["upload_id"]
    _parte(client, upload_id, 0, b"a" * 4_000)

    r = _parte(client, upload_id, 4_000, b"b" * 2_000)

    assert r.status_code == 409
    assert r.json()["detail"]["offset"] == 4_000
    assert client.get(f"/uploads/{upload_id}").json()["recibidos"] == 4_000


def test_subida_incompleta_da_409_y_se_conserva(client: TestClient, entorno: Entorno) -> None:
    """El archivo real es más chico que lo declarado: el video no se crea."""
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, 10_000).json()["upload_id"]
    _parte(client, upload_id, 0, b"a" * 4_000)
    antes = _filas(entorno.session)

    r = _crear_video(client, upload_id)

    assert r.status_code == 409
    assert r.json()["detail"]["recibidos"] == 4_000
    assert r.json()["detail"]["tamano"] == 10_000
    assert _filas(entorno.session) == antes
    assert client.get(f"/uploads/{upload_id}").json()["recibidos"] == 4_000  # se puede seguir


def test_parte_mayor_que_tamano_parte_da_413(client: TestClient, entorno: Entorno) -> None:
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, 10_000).json()["upload_id"]

    r = _parte(client, upload_id, 0, b"a" * 4_001)

    assert r.status_code == 413
    assert client.get(f"/uploads/{upload_id}").json()["recibidos"] == 0


def test_parte_mayor_sin_content_length_se_corta_al_recibirla(
    client: TestClient, entorno: Entorno
) -> None:
    """Sin `Content-Length` (cuerpo en flujo), el middleware no puede decidir: corta el conteo."""
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, 10_000).json()["upload_id"]

    def flujo() -> Iterator[bytes]:
        yield b"a" * 3_000
        yield b"b" * 3_000

    r = client.put(f"/uploads/{upload_id}", params={"offset": 0}, content=flujo())

    assert r.status_code == 413
    assert client.get(f"/uploads/{upload_id}").json()["recibidos"] == 0
    assert not list(_carpeta(entorno, upload_id).glob("*.tmp"))


def test_tamano_mayor_que_el_limite_da_413(client: TestClient, entorno: Entorno) -> None:
    r = _abrir(client, 2 * MB)  # SUBIDA_MAX_MB=1 en el entorno de pruebas

    assert r.status_code == 413
    assert "1 MB" in r.json()["detail"]
    assert not subidas.carpeta_subidas(entorno.settings.media_path).exists()


@pytest.mark.parametrize("nombre", ["notas.txt", "video.wmv", "sin_extension"])
def test_extension_no_permitida_da_415(client: TestClient, entorno: Entorno, nombre: str) -> None:
    r = _abrir(client, 100, nombre=nombre)

    assert r.status_code == 415
    assert not subidas.carpeta_subidas(entorno.settings.media_path).exists()


@pytest.mark.parametrize("tamano", [0, -5])
def test_tamano_no_positivo_da_422(client: TestClient, tamano: int) -> None:
    assert _abrir(client, tamano).status_code == 422


def test_avi_por_partes_se_acepta(client: TestClient, entorno: Entorno, generar_video) -> None:
    contenido = generar_video("operador.avi").read_bytes()
    _partes_de(entorno, math.ceil(len(contenido) / 2))

    upload_id = _subir_en_partes(client, contenido, 2, "OPERADOR.AVI")
    r = _crear_video(client, upload_id)

    assert r.status_code == 202, r.text
    video = entorno.video(r.json()["id"])
    assert video.archivo.endswith("/video.avi")
    entorno.correr_pendientes()
    assert entorno.video(video.id).proceso == "listo"


def test_archivo_que_no_es_video_da_422_y_se_descarta(client: TestClient, entorno: Entorno) -> None:
    contenido = b"esto no es un video, solo texto inventado " * 50
    _partes_de(entorno, 1_000)
    upload_id = _subir_en_partes(client, contenido, 3, "operador.mp4")
    antes = _filas(entorno.session)

    r = _crear_video(client, upload_id)

    assert r.status_code == 422
    assert _filas(entorno.session) == antes
    assert not _carpeta(entorno, upload_id).exists()
    carpeta_videos = entorno.settings.media_path / "videos"
    assert not carpeta_videos.exists() or not any(carpeta_videos.iterdir())
    assert entorno.pendientes == []


# ── Identificador, consumo y cancelación ─────────────────────────────────────


@pytest.mark.parametrize("upload_id", ["0" * 32, "../../etc", "no-es-hex"])
def test_upload_id_inexistente_da_404(client: TestClient, upload_id: str) -> None:
    assert client.get(f"/uploads/{upload_id}").status_code == 404
    assert _parte(client, upload_id, 0, b"a").status_code == 404
    assert client.delete(f"/uploads/{upload_id}").status_code == 404
    assert _crear_video(client, upload_id).status_code == 404


def test_upload_ya_consumido_da_404(client: TestClient, entorno: Entorno, generar_video) -> None:
    contenido = generar_video().read_bytes()
    _partes_de(entorno, len(contenido))
    upload_id = _subir_en_partes(client, contenido, 1, "operador.mp4")
    assert _crear_video(client, upload_id).status_code == 202

    assert _crear_video(client, upload_id).status_code == 404
    assert _parte(client, upload_id, 0, contenido).status_code == 404


def test_cancelar_borra_lo_recibido(client: TestClient, entorno: Entorno) -> None:
    _partes_de(entorno, 4_000)
    upload_id = _abrir(client, 10_000).json()["upload_id"]
    _parte(client, upload_id, 0, b"a" * 4_000)

    assert client.delete(f"/uploads/{upload_id}").status_code == 204

    assert not _carpeta(entorno, upload_id).exists()
    assert client.get(f"/uploads/{upload_id}").status_code == 404
    assert client.delete(f"/uploads/{upload_id}").status_code == 404


@pytest.mark.parametrize("con_archivo", [True, False])
def test_archivo_y_upload_id_son_excluyentes(
    client: TestClient, entorno: Entorno, con_archivo: bool
) -> None:
    upload_id = _abrir(client, 100).json()["upload_id"]
    formulario = {"titulo": "Cambio de filtro", "modo": "generar"}
    if con_archivo:
        r = client.post(
            "/videos",
            data={**formulario, "upload_id": upload_id},
            files={"archivo": ("operador.mp4", b"\x00" * 100, "video/mp4")},
        )
    else:
        r = client.post("/videos", data=formulario)

    assert r.status_code == 422
    assert "upload_id" in r.json()["detail"]
    assert _carpeta(entorno, upload_id).exists()  # la subida no se toca


def test_formulario_invalido_no_consume_la_subida(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    contenido = generar_video().read_bytes()
    _partes_de(entorno, len(contenido))
    upload_id = _subir_en_partes(client, contenido, 1, "operador.mp4")

    r = _crear_video(client, upload_id, modo="validar")  # sin sop_id

    assert r.status_code == 422
    assert client.get(f"/uploads/{upload_id}").json()["completo"] is True


# ── Mismos campos que la subida simple ───────────────────────────────────────


@pytest.mark.parametrize(("campo", "esperado"), [("true", True), ("false", False), (None, False)])
@pytest.mark.parametrize("camino", ["archivo", "upload_id"])
def test_analizar_imagenes_llega_igual_por_los_dos_caminos(
    client: TestClient,
    entorno: Entorno,
    generar_video,
    monkeypatch: pytest.MonkeyPatch,
    camino: str,
    campo: str | None,
    esperado: bool,
) -> None:
    encolados: list[bool] = []
    original = entorno.procesador.encolar

    def encolar(*args, imagenes: bool = False, **kwargs) -> None:
        encolados.append(imagenes)
        original(*args, imagenes=imagenes, **kwargs)

    monkeypatch.setattr(entorno.procesador, "encolar", encolar)
    contenido = generar_video().read_bytes()
    datos = {} if campo is None else {"analizar_imagenes": campo}
    if camino == "archivo":
        r = client.post(
            "/videos",
            data={"titulo": "Cambio de filtro", "modo": "generar", **datos},
            files={"archivo": ("operador.mp4", contenido, "video/mp4")},
        )
    else:
        _partes_de(entorno, len(contenido))
        r = _crear_video(client, _subir_en_partes(client, contenido, 1, "operador.mp4"), **datos)

    assert r.status_code == 202, r.text
    assert entorno.video(r.json()["id"]).analizar_imagenes is esperado
    assert encolados == [esperado]
    assert client.get(f"/videos/{r.json()['id']}").json()["analizar_imagenes"] is esperado


def test_upload_id_con_sop_id_titulo_e_idioma(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    contenido = generar_video().read_bytes()
    _partes_de(entorno, len(contenido))
    sop = guardar_sop(entorno.session)
    upload_id = _subir_en_partes(client, contenido, 1, "operador.mov")

    r = _crear_video(
        client, upload_id, modo="validar", sop_id=str(sop.id), idioma="ES", titulo="  Filtro  "
    )

    assert r.status_code == 202, r.text
    video = entorno.video(r.json()["id"])
    assert (video.titulo, video.modo, video.idioma, video.sop_id) == (
        "Filtro",
        "validar",
        "es",
        sop.id,
    )
    assert video.archivo.endswith("/video.mov")


def test_upload_id_con_sop_adjunto(client: TestClient, entorno: Entorno, generar_video) -> None:
    contenido = generar_video().read_bytes()
    _partes_de(entorno, len(contenido))
    upload_id = _subir_en_partes(client, contenido, 1, "operador.mp4")
    sop_md = (Path(__file__).parent / "fixtures" / "sop_filtro_agua.md").read_bytes()

    r = client.post(
        "/videos",
        data={"titulo": "Cambio de filtro", "modo": "validar", "upload_id": upload_id},
        files={"sop": ("sop.md", sop_md, "text/markdown")},
    )

    assert r.status_code == 202, r.text
    assert r.json()["sop_id"] is not None
    assert entorno.video(r.json()["id"]).sop_id == r.json()["sop_id"]
    assert len(entorno.pendientes) == 2  # el SOP primero, después el video


def test_si_falla_al_registrar_la_subida_se_conserva(
    client: TestClient, entorno: Entorno, generar_video, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un error después de mover el archivo lo devuelve a la subida: se puede reintentar."""
    contenido = generar_video().read_bytes()
    _partes_de(entorno, len(contenido))
    upload_id = _subir_en_partes(client, contenido, 1, "operador.mp4")
    original = entorno.session.commit
    llamadas = {"n": 0}

    def commit_que_falla() -> None:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("la base se cayó")
        original()

    monkeypatch.setattr(entorno.session, "commit", commit_que_falla)
    with pytest.raises(RuntimeError):
        _crear_video(client, upload_id)

    armado = _carpeta(entorno, upload_id) / subidas.ARCHIVO_DATOS
    assert _sha(armado.read_bytes()) == _sha(contenido)
    assert _crear_video(client, upload_id).status_code == 202


# ── Limpieza por edad (RNF-09) ───────────────────────────────────────────────


def _envejecer(carpeta: Path, horas: float) -> None:
    marca = time.time() - horas * 3600
    for ruta in [*carpeta.iterdir(), carpeta]:
        os.utime(ruta, (marca, marca))


def test_limpieza_al_abrir_otra_subida(client: TestClient, entorno: Entorno) -> None:
    vieja = _abrir(client, 100).json()["upload_id"]
    reciente = _abrir(client, 100).json()["upload_id"]
    _envejecer(_carpeta(entorno, vieja), entorno.settings.subida_caducidad_h + 1)

    _abrir(client, 100)

    assert not _carpeta(entorno, vieja).exists()
    assert _carpeta(entorno, reciente).exists()


def test_limpieza_al_arrancar(entorno: Entorno) -> None:
    media = entorno.settings.media_path
    vieja = subidas.crear(media, ".mp4", 100, 50)
    reciente = subidas.crear(media, ".mp4", 100, 50)
    _envejecer(_carpeta(entorno, vieja.upload_id), entorno.settings.subida_caducidad_h + 1)

    with TestClient(entorno.app):
        pass

    assert not _carpeta(entorno, vieja.upload_id).exists()
    assert _carpeta(entorno, reciente.upload_id).exists()


# ── Módulo de armado, sin API ────────────────────────────────────────────────


def _temporal(tmp_path: Path, datos: bytes) -> Path:
    ruta = tmp_path / f"parte-{len(list(tmp_path.glob('parte-*')))}.bin"
    ruta.write_bytes(datos)
    return ruta


def test_guardar_parte_en_orden_y_errores(tmp_path: Path) -> None:
    media = tmp_path / "media"
    estado = subidas.crear(media, ".mp4", 10, 4)

    def guardar(offset: int, datos: bytes) -> subidas.EstadoSubida:
        return subidas.guardar_parte(media, estado.upload_id, offset, _temporal(tmp_path, datos))

    assert guardar(0, b"abcd").recibidos == 4
    with pytest.raises(subidas.OffsetInesperado) as adelantado:
        guardar(8, b"ij")
    assert adelantado.value.recibidos == 4
    with pytest.raises(subidas.ParteGrande):
        guardar(4, b"efghi")
    assert guardar(4, b"efgh").recibidos == 8
    with pytest.raises(subidas.PasaDelTamano):
        guardar(8, b"ijk")
    with pytest.raises(subidas.SubidaIncompleta), subidas.reservada(media, estado.upload_id):
        pass
    assert guardar(8, b"ij").completo
    with subidas.reservada(media, estado.upload_id) as (completo, archivo):
        assert completo.completo
        assert archivo.read_bytes() == b"abcdefghij"


def test_limpiar_caducadas_salta_la_que_esta_en_uso(tmp_path: Path) -> None:
    media = tmp_path / "media"
    en_uso = subidas.crear(media, ".mp4", 10, 4)
    _envejecer(subidas.carpeta_subidas(media) / en_uso.upload_id, 48)

    with subidas.candado(en_uso.upload_id):
        assert subidas.limpiar_caducadas(media, 24) == 0
    assert subidas.limpiar_caducadas(media, 24) == 1
