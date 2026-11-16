"""Clave de acceso por vista (§11, RNF-10, ADR-027): `X-Clave-Acceso`, la cookie de `POST /acceso`
y el token `k` de los enlaces del PDF (`/v/<id>`).

Con la base de pruebas (`db_session`, se revierte al final) y `dobles.Entorno`, con sus `Settings`
cambiados por unos con claves inventadas. Las claves de aquí son de prueba, no de nadie.
"""

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from dobles import Entorno, guardar_sop, guardar_video
from sopvid.contrato import GeneracionSOP
from sopvid.lenguaje import busqueda
from sopvid.lenguaje.llm import get_cliente_llm
from sopvid.plataforma import acceso
from sopvid.plataforma.api import acceso as acceso_api
from sopvid.plataforma.config import Settings
from sopvid.plataforma.hardware import PlanDispositivos, get_plan_dispositivos
from sopvid.plataforma.modelos import Sop, Video
from sopvid.salidas import pdf
from sopvid.salidas.pdf import url_video

CARGA = "carga-de-prueba"
BUSQUEDA = "busqueda-de-prueba"
SECRETO = "secreto-de-prueba-" + "x" * 32
CLAVES = {"carga": CARGA, "busqueda": BUSQUEDA}
OTRA = {"carga": "busqueda", "busqueda": "carga"}
AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
VIDEO_FALSO = bytes(range(256)) * 16


def _con_claves(settings: Settings, carga: str = CARGA, busq: str = BUSQUEDA, secreto=SECRETO):
    return settings.model_copy(
        update={
            "clave_carga": SecretStr(carga),
            "clave_busqueda": SecretStr(busq),
            "secreto_enlaces": SecretStr(secreto),
        }
    )


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    db_session.execute(update(Video).values(publicado=False, publicado_en=None))
    entorno = Entorno(db_session, tmp_path)
    entorno.settings = _con_claves(entorno.settings)  # la app lee `entorno.settings` en cada uso
    return entorno


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


@pytest.fixture(autouse=True)
def sin_espera(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acceso_api, "RETRASO_CLAVE_S", 0)


def _video(
    entorno: Entorno,
    archivo: Path | None = None,
    *,
    publicar: bool = False,
    sop: Sop | None = None,
) -> Video:
    """Un video listo con su archivo en `media` (el de `archivo` o bytes de relleno)."""
    video = guardar_video(entorno.session, modo="validar" if sop else "generar", sop=sop)
    destino = entorno.settings.media_path / "videos" / str(video.id) / "video.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if archivo is None:
        destino.write_bytes(VIDEO_FALSO)
    else:
        shutil.copyfile(archivo, destino)
    video.archivo = f"videos/{video.id}/video.mp4"
    video.duracion = 3.0
    if publicar:
        busqueda.publicar(entorno.session, video, AHORA)
    entorno.session.commit()
    return video


def _encabezado(credencial: str, vista: str) -> dict[str, str]:
    """`correcta`, `ninguna`, `equivocada` o `otra` (la clave de la otra vista)."""
    valores = {
        "correcta": CLAVES[vista],
        "equivocada": "no-es-la-clave",
        "otra": CLAVES[OTRA[vista]],
    }
    return {acceso.ENCABEZADO: valores[credencial]} if credencial in valores else {}


# ── Cada grupo de rutas con su clave, sin clave, con una equivocada y con la de la otra vista ──

RUTAS_CARGA = [
    ("GET", "/sops", None),
    ("GET", "/videos", None),
    ("GET", "/videos/estimacion?duracion_s=60&modo=generar", None),
    ("GET", "/uploads/no-existe", None),
    ("DELETE", "/videos/999999/publicar", None),
]
RUTAS_BUSQUEDA = [
    ("GET", "/buscar/opciones", None),
    ("POST", "/buscar", {"consulta": "válvula"}),
]


def _pedir(client: TestClient, metodo: str, ruta: str, cuerpo, encabezados):
    return client.request(metodo, ruta, json=cuerpo, headers=encabezados)


@pytest.mark.parametrize("credencial", ["correcta", "ninguna", "equivocada", "otra"])
@pytest.mark.parametrize(
    ("vista", "metodo", "ruta", "cuerpo"),
    [("carga", *r) for r in RUTAS_CARGA] + [("busqueda", *r) for r in RUTAS_BUSQUEDA],
)
def test_cada_vista_pide_su_clave(
    client: TestClient, vista: str, metodo: str, ruta: str, cuerpo, credencial: str
) -> None:
    r = _pedir(client, metodo, ruta, cuerpo, _encabezado(credencial, vista))
    if credencial == "correcta":
        assert r.status_code != 401, r.text
    else:
        assert r.status_code == 401
        nombre = "carga" if vista == "carga" else "búsqueda"
        assert r.json() == {"detail": f"Falta la clave de la vista de {nombre} o no es correcta."}


@pytest.mark.parametrize("credencial", ["carga", "busqueda", "ninguna", "equivocada"])
def test_video_miniatura_y_ver_sop_con_cualquiera_de_las_dos(
    client: TestClient, entorno: Entorno, generar_video, credencial: str
) -> None:
    sop = guardar_sop(entorno.session)
    video = _video(entorno, generar_video(), publicar=True, sop=sop)
    encabezados = {
        "carga": {acceso.ENCABEZADO: CARGA},
        "busqueda": {acceso.ENCABEZADO: BUSQUEDA},
        "equivocada": {acceso.ENCABEZADO: "no-es-la-clave"},
    }.get(credencial, {})
    respuestas = [
        client.get(f"/videos/{video.id}/video", headers=encabezados),
        client.get(f"/videos/{video.id}/thumb", params={"t": 1.0}, headers=encabezados),
        client.get(f"/sops/{sop.id}/pdf", params={"ver": "true"}, headers=encabezados),
    ]
    if credencial in ("carga", "busqueda"):
        assert [r.status_code for r in respuestas] == [200, 200, 200]
    else:
        assert [r.status_code for r in respuestas] == [401, 401, 401]
        assert respuestas[0].json() == {
            "detail": "Falta la clave de acceso o el enlace no es válido."
        }


def test_pdf_del_sop_como_adjunto_solo_con_la_de_carga(
    client: TestClient, entorno: Entorno
) -> None:
    sop = guardar_sop(entorno.session)
    _video(entorno, publicar=True, sop=sop)
    ruta = f"/sops/{sop.id}/pdf"
    assert client.get(ruta, headers={acceso.ENCABEZADO: CARGA}).status_code == 200
    r = client.get(ruta, headers={acceso.ENCABEZADO: BUSQUEDA})
    assert r.status_code == 401
    assert r.json() == {"detail": "Falta la clave de la vista de carga o no es correcta."}


def test_con_la_de_busqueda_solo_lo_publicado(client: TestClient, entorno: Entorno) -> None:
    """Un video sin publicar (y el SOP sin videos publicados) da 404, como en `POST /buscar`; con
    la de carga, el mismo video sí."""
    sop = guardar_sop(entorno.session)
    video = _video(entorno, sop=sop)
    busq = {acceso.ENCABEZADO: BUSQUEDA}
    assert client.get(f"/videos/{video.id}/video", headers=busq).status_code == 404
    assert client.get(f"/videos/{video.id}/thumb?t=1", headers=busq).status_code == 404
    assert client.get(f"/sops/{sop.id}/pdf?ver=true", headers=busq).status_code == 404
    assert client.get("/videos/999999/video", headers=busq).status_code == 404
    carga = {acceso.ENCABEZADO: CARGA}
    assert client.get(f"/videos/{video.id}/video", headers=carga).status_code == 200


# ── La cookie de POST /acceso: para <img>, <video> y descargas, que no mandan encabezados ──


def test_la_cookie_abre_video_y_miniatura(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video = _video(entorno, generar_video())
    assert client.get(f"/videos/{video.id}/video").status_code == 401

    r = client.post("/acceso", json={"vista": "carga", "clave": CARGA})

    assert r.status_code == 204
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{acceso.NOMBRE_COOKIE['carga']}=")
    assert CARGA not in cookie  # lleva un HMAC, no la clave
    for atributo in ("HttpOnly", "Path=/", "SameSite=strict"):
        assert atributo in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.lower()  # de sesión
    assert "Secure" not in cookie  # http: con Secure, el navegador no la mandaría

    rango = client.get(f"/videos/{video.id}/video", headers={"Range": "bytes=0-99"})
    assert rango.status_code == 206
    miniatura = client.get(f"/videos/{video.id}/thumb", params={"t": 1.0})
    assert miniatura.status_code == 200
    assert miniatura.content[:2] == b"\xff\xd8"
    assert client.get(f"/videos/{video.id}/download/txt").status_code == 200
    # La cookie de carga no abre la búsqueda.
    assert client.get("/buscar/opciones").status_code == 401


def test_la_cookie_de_busqueda_abre_la_miniatura_de_un_publicado(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video = _video(entorno, generar_video(), publicar=True)
    assert client.post("/acceso", json={"vista": "busqueda", "clave": BUSQUEDA}).status_code == 204
    assert client.get(f"/videos/{video.id}/thumb", params={"t": 1.0}).status_code == 200
    assert client.get("/buscar/opciones").status_code == 200
    assert client.get("/videos").status_code == 401


def test_cookie_alterada_o_de_otra_clave_no_sirve(client: TestClient, entorno: Entorno) -> None:
    client.cookies.set(acceso.NOMBRE_COOKIE["carga"], "0" * 64)
    assert client.get("/sops").status_code == 401
    # La de una clave anterior: cambiar la clave cierra las sesiones.
    vieja = acceso.valor_cookie(_con_claves(entorno.settings, carga="clave-anterior"), "carga")
    client.cookies.set(acceso.NOMBRE_COOKIE["carga"], vieja)
    assert client.get("/sops").status_code == 401


def test_delete_acceso_cierra_la_sesion(client: TestClient) -> None:
    client.post("/acceso", json={"vista": "carga", "clave": CARGA})
    client.post("/acceso", json={"vista": "busqueda", "clave": BUSQUEDA})
    assert client.get("/sops").status_code == 200

    r = client.delete("/acceso", params={"vista": "carga"})

    assert r.status_code == 204
    assert client.get("/sops").status_code == 401
    assert client.get("/buscar/opciones").status_code == 200
    client.delete("/acceso")
    assert client.get("/buscar/opciones").status_code == 401


def test_post_acceso_con_clave_equivocada_espera_y_da_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    esperas: list[float] = []

    async def dormir(segundos: float) -> None:
        esperas.append(segundos)

    monkeypatch.setattr(acceso_api, "RETRASO_CLAVE_S", 1.0)
    monkeypatch.setattr(acceso_api.asyncio, "sleep", dormir)

    r = client.post("/acceso", json={"vista": "carga", "clave": BUSQUEDA})

    assert r.status_code == 401
    assert r.json() == {"detail": "La clave de la vista de carga no es correcta."}
    assert "set-cookie" not in r.headers
    assert esperas == [1.0]
    assert client.post("/acceso", json={"vista": "carga", "clave": CARGA}).status_code == 204
    assert esperas == [1.0]  # con la correcta no espera


def test_get_acceso_dice_que_vistas_abre_la_peticion(client: TestClient) -> None:
    cerrada = {"abierta": False, "sesion": False}
    assert client.get("/acceso").json() == {"carga": cerrada, "busqueda": cerrada}

    client.post("/acceso", json={"vista": "busqueda", "clave": BUSQUEDA})

    assert client.get("/acceso").json() == {
        "carga": cerrada,
        "busqueda": {"abierta": False, "sesion": True},
    }
    con_encabezado = client.get("/acceso", headers={acceso.ENCABEZADO: CARGA}).json()
    assert con_encabezado["carga"] == {"abierta": False, "sesion": True}


# ── El token de /v/<id> (QR del PDF) ──


def test_el_token_del_enlace_abre_solo_su_video(client: TestClient, entorno: Entorno) -> None:
    uno, otro = _video(entorno), _video(entorno)
    k = acceso.token_enlace(entorno.settings, uno.id)
    assert k is not None and len(k) == 22

    assert client.get(f"/videos/{uno.id}/video", params={"k": k}).status_code == 200
    assert client.get(f"/videos/{otro.id}/video", params={"k": k}).status_code == 401
    alterado = k[:-1] + ("A" if k[-1] != "A" else "B")
    assert client.get(f"/videos/{uno.id}/video", params={"k": alterado}).status_code == 401
    # Solo el video y su miniatura: el token no abre el resto de la vista de carga.
    assert client.get(f"/videos/{uno.id}", params={"k": k}).status_code == 401
    assert client.get(f"/videos/{uno.id}/download/txt", params={"k": k}).status_code == 401


def test_sin_secreto_los_enlaces_quedan_abiertos(client: TestClient, entorno: Entorno) -> None:
    entorno.settings = _con_claves(entorno.settings, secreto="")
    video = _video(entorno)
    assert acceso.token_enlace(entorno.settings, video.id) is None
    assert client.get(f"/videos/{video.id}/video").status_code == 200
    assert client.get("/sops").status_code == 401  # las claves siguen


def test_url_del_qr_con_y_sin_token() -> None:
    assert url_video("http://x:4200/", 7, 12.34) == "http://x:4200/v/7?t=12.3"
    assert url_video("http://x:4200", 7, 0, "abc_-") == "http://x:4200/v/7?t=0.0&k=abc_-"


def test_el_pdf_lleva_el_token_en_sus_enlaces(
    client: TestClient, entorno: Entorno, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET /sops/{id}/pdf` de un SOP generado arma el QR de la portada con el token del video."""
    sop = guardar_sop(entorno.session)
    video = _video(entorno, sop=sop)
    generacion = GeneracionSOP(
        video_id=video.id, pasos_video=1, agrupacion="uno_a_uno", grupos=[[1]]
    )
    sop.generacion = generacion.model_dump(mode="json")
    entorno.session.commit()
    vistos: list[pdf.InfoVideo | None] = []
    original = pdf.pdf_sop

    def espia(*args, **kwargs):
        vistos.append(kwargs.get("video"))
        return original(*args, **kwargs)

    monkeypatch.setattr(pdf, "pdf_sop", espia)
    r = client.get(f"/sops/{sop.id}/pdf", headers={acceso.ENCABEZADO: CARGA})

    assert r.status_code == 200, r.text
    assert vistos[0] is not None
    assert vistos[0].token_enlace == acceso.token_enlace(entorno.settings, video.id)


# ── Vistas abiertas, rutas sin clave y configuración ──


def test_clave_vacia_deja_la_vista_abierta(client: TestClient, entorno: Entorno) -> None:
    entorno.settings = _con_claves(entorno.settings, carga="", busq="  ")
    assert client.get("/sops").status_code == 200
    assert client.get("/buscar/opciones").status_code == 200
    abierta = {"abierta": True, "sesion": False}
    assert client.get("/acceso").json() == {"carga": abierta, "busqueda": abierta}
    r = client.post("/acceso", json={"vista": "carga", "clave": "lo-que-sea"})
    assert r.status_code == 204
    assert "set-cookie" not in r.headers


def test_una_vista_abierta_no_abre_la_otra(client: TestClient, entorno: Entorno) -> None:
    entorno.settings = _con_claves(entorno.settings, busq="")
    assert client.get("/buscar/opciones").status_code == 200
    assert client.get("/sops").status_code == 401


def test_health_y_docs_no_piden_clave(client: TestClient) -> None:
    class LLMCaido:
        def disponible(self, timeout_s=None):
            return False

    plan = PlanDispositivos(
        gpu=None, nucleos=4, transcripcion="cpu", compute_type="int8", llm="auto"
    )
    client.app.dependency_overrides[get_cliente_llm] = LLMCaido
    client.app.dependency_overrides[get_plan_dispositivos] = lambda: plan

    salud = client.get("/health")

    assert salud.status_code == 200
    assert salud.json()["avisos"] == []  # claves puestas y secreto largo
    assert client.get("/docs").status_code == 200
    esquema = client.get("/openapi.json").json()
    assert esquema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-Clave-Acceso"


def test_avisos_de_la_configuracion() -> None:
    abiertas = Settings(clave_carga="", clave_busqueda="", secreto_enlaces="")
    assert acceso.avisos(abiertas) == [
        "CLAVE_CARGA vacía: la vista de carga está abierta (solo para desarrollo)",
        "CLAVE_BUSQUEDA vacía: la vista de búsqueda está abierta (solo para desarrollo)",
        "SECRETO_ENLACES vacío: los enlaces y QR de los PDF abren el video sin token",
    ]
    corto = Settings(clave_carga="a", clave_busqueda="b", secreto_enlaces="corto")
    assert acceso.avisos(corto) == ["SECRETO_ENLACES tiene menos de 32 caracteres"]


def test_claves_iguales_no_arrancan() -> None:
    with pytest.raises(ValidationError, match="no pueden ser iguales"):
        Settings(clave_carga="misma", clave_busqueda=" misma ")
    Settings(clave_carga="", clave_busqueda="")  # las dos vacías sí


def test_encabezados_para_scripts() -> None:
    settings = Settings(clave_carga="", clave_busqueda="b", secreto_enlaces="")
    assert acceso.encabezados(settings, "carga") == {}
    assert acceso.encabezados(settings, "busqueda") == {"X-Clave-Acceso": "b"}


def test_clave_con_acentos(client: TestClient, entorno: Entorno) -> None:
    """`compare_digest` con `str` no ASCII lanza TypeError: se compara en bytes UTF-8."""
    assert client.post("/acceso", json={"vista": "carga", "clave": "contraseña"}).status_code == 401
    entorno.settings = _con_claves(entorno.settings, carga="contraseña")
    assert acceso.clave_correcta(entorno.settings, "carga", "contraseña")
    assert client.post("/acceso", json={"vista": "carga", "clave": "contraseña"}).status_code == 204
    assert client.get("/sops").status_code == 200
