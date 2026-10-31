"""Pruebas de `/videos` (RF-06 del MVP, RF-10), del reporte (RF-19, RF-20) y de la cola.

Usan la base de pruebas de conftest.py (`db_session`, que se revierte al final), un transcriptor
falso y un procesador que guarda los trabajos en vez de correrlos en un hilo: la prueba decide
cuándo corren, en su mismo hilo y con la misma sesión, para ver el estado antes, durante y
después del análisis. Los videos salen de `generar_video` (ffmpeg); sin ffmpeg esas pruebas se
saltan.

La validación corre con `ValidadorFalso`: el `validar_y_guardar` de verdad, con la heurística para
los pasos y un emparejamiento de mentira, así que no hace falta MiniLM ni Ollama.
"""

import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apoyo import fila, resultado
from sopvid.contrato import (
    SOP,
    Analisis,
    Idioma,
    Palabra,
    PasoVideo,
    ResultadoEmparejamiento,
    Segmento,
)
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion
from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.api.videos import get_procesador, get_transcriptor
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Reporte, Sop, Video
from sopvid.plataforma.procesamiento import ERROR_REINICIO, Procesador
from sopvid.plataforma.validacion import validar_y_guardar

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMA = RAIZ / "docs" / "contrato" / "analisis.schema.json"
SOP_MD = (RAIZ / "tests" / "fixtures" / "sop_filtro_agua.md").read_bytes()
MB = 1024 * 1024


def _segmento(id_: int, t: float, t_fin: float, texto: str) -> Segmento:
    palabras = texto.split()
    paso = (t_fin - t) / len(palabras)
    return Segmento(
        id=id_,
        t_inicio=t,
        t_fin=t_fin,
        texto=texto,
        palabras=[
            Palabra(w=w, t=round(t + i * paso, 3), t_fin=round(t + (i + 1) * paso, 3))
            for i, w in enumerate(palabras)
        ],
    )


SEGMENTOS = [
    _segmento(0, 0.0, 0.9, "Primero reviso el manómetro."),
    _segmento(1, 1.0, 1.9, "Después cierro la válvula."),
    _segmento(2, 2.0, 2.8, "Por último anoto la lectura."),
]


class TranscriptorFalso:
    """Entrega SEGMENTOS por `al_segmento`; `antes(i)` corre antes de cada uno."""

    def __init__(self, antes: Callable[[int], None] | None = None, error: Exception | None = None):
        self.antes, self.error = antes, error
        self.idiomas: list[str | None] = []

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        self.idiomas.append(idioma)
        for i, segmento in enumerate(SEGMENTOS):
            if self.antes is not None:
                self.antes(i)
            if self.error is not None:
                raise self.error
            if al_segmento is not None:
                al_segmento(segmento)
        return Transcripcion(
            idioma=Idioma(
                codigo=idioma or "es", confianza=1.0 if idioma else 0.97, fijado_a_mano=bool(idioma)
            ),
            segmentos=list(SEGMENTOS),
            duracion_s=3.0,
            modelo="falso",
            dispositivo="cpu",
            compute_type="int8",
            segundos=0.0,
        )


class EmparejadorFalso:
    """`Emparejador` sin MiniLM: los primeros pasos del video cumplen los primeros del SOP.

    Los pasos del SOP que no alcanzan paso del video quedan *Falta* y los del video que sobran,
    *Sobra*. `ResultadoEmparejamiento` se arma con `tests/apoyo.py`, que ya lo deja coherente.
    """

    def emparejar(
        self, sop: SOP, pasos_video: Sequence[PasoVideo], *, transcripcion: Sequence[Segmento] = ()
    ) -> ResultadoEmparejamiento:
        pasos = list(pasos_video)
        filas = []
        for i in range(len(sop.pasos)):
            if i < len(pasos):
                filas.append(fila("Cumple", sop=i, video=i, pasos_video=pasos))
            else:
                filas.append(fila("Falta", sop=i, pasos_video=pasos))
        for j in range(len(sop.pasos), len(pasos)):
            filas.append(fila("Sobra", video=j, pasos_video=pasos))
        return resultado(sop, pasos, filas)


class ValidadorFalso:
    """`validar_y_guardar` de verdad, con la heurística y el emparejador de mentira."""

    def __init__(self) -> None:
        self.llamadas = 0
        self.error: Exception | None = None

    def __call__(self, session: Session, video: Video):
        self.llamadas += 1
        if self.error is not None:
            raise self.error
        return validar_y_guardar(session, video, llm=None, emparejador=EmparejadorFalso())


class Entorno:
    """App con la sesión de la prueba, ajustes en `tmp_path` y trabajos que corren a mano."""

    def __init__(self, db_session: Session, tmp_path: Path):
        self.session = db_session
        self.settings = Settings(media_dir=tmp_path / "media", subida_max_mb=1)
        self.pendientes: list[Callable[[], None]] = []
        self.transcriptor = TranscriptorFalso()
        self.validador = ValidadorFalso()
        procesador = Procesador(
            lambda: nullcontext(db_session),
            self.settings.media_path,
            self.pendientes.append,
            validador=self.validador,
        )

        def sesion() -> Iterator[Session]:
            yield db_session

        self.app = create_app(
            sesiones=lambda: nullcontext(db_session), recuperar_interrumpidos=False
        )
        self.app.dependency_overrides[get_session] = sesion
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.app.dependency_overrides[get_procesador] = lambda: procesador
        self.app.dependency_overrides[get_transcriptor] = lambda: self.transcriptor

    def correr_pendientes(self) -> None:
        while self.pendientes:
            self.pendientes.pop(0)()

    def video(self, video_id: int) -> Video:
        video = self.session.get(Video, video_id)
        self.session.refresh(video)
        return video


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def subir(
    client: TestClient,
    contenido: bytes,
    nombre: str = "operador.mp4",
    sop: tuple[str, bytes] | None = ("sop.md", SOP_MD),
    **datos: str,
):
    """POST /videos; por defecto con un SOP en Markdown, porque `modo=validar` lo exige."""
    formulario = {"titulo": "Cambio de filtro", "modo": "validar", **datos}
    archivos = {"archivo": (nombre, contenido, "video/mp4")}
    if sop is not None:
        archivos["sop"] = (sop[0], sop[1], "text/markdown")
    return client.post("/videos", files=archivos, data=formulario)


def _filas(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Video))


def _sops(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Sop))


# ── Subida ───────────────────────────────────────────────────────────────────


def test_subida_aceptada(client: TestClient, entorno: Entorno, generar_video) -> None:
    contenido = generar_video("operador.mp4").read_bytes()

    r = subir(client, contenido, idioma="ES")

    assert r.status_code == 202
    cuerpo = r.json()
    assert cuerpo["proceso"] == "en_cola"
    assert r.headers["location"] == f"/videos/{cuerpo['id']}"
    video = entorno.video(cuerpo["id"])
    assert (video.titulo, video.modo, video.proceso, video.progreso) == (
        "Cambio de filtro",
        "validar",
        "en_cola",
        0,
    )
    assert video.idioma == "es"
    assert video.sop_id == cuerpo["sop_id"] is not None
    assert video.archivo == f"videos/{video.id}/video.mp4"  # nunca el nombre original
    guardado = entorno.settings.media_path / video.archivo
    assert guardado.read_bytes() == contenido
    assert len(entorno.pendientes) == 1


@pytest.mark.parametrize("nombre", ["notas.txt", "video.avi", "sin_extension"])
def test_extension_rechazada(client: TestClient, entorno: Entorno, nombre: str) -> None:
    antes = _filas(entorno.session)

    r = subir(client, b"\x00" * 100, nombre=nombre)

    assert r.status_code == 415
    assert _filas(entorno.session) == antes
    assert entorno.pendientes == []


def test_extension_en_mayusculas_se_acepta(client: TestClient, entorno: Entorno) -> None:
    r = subir(client, b"\x00" * 100, nombre="OPERADOR.MOV")

    assert r.status_code == 202
    assert entorno.video(r.json()["id"]).archivo.endswith("/video.mov")


@pytest.mark.parametrize("datos", [{"modo": "auditar"}, {"idioma": "español"}, {"titulo": "   "}])
def test_formulario_invalido(client: TestClient, entorno: Entorno, datos: dict) -> None:
    antes = _filas(entorno.session)

    r = subir(client, b"\x00" * 100, **datos)

    assert r.status_code == 422
    assert _filas(entorno.session) == antes


def test_tamano_excedido_al_copiar(client: TestClient, entorno: Entorno) -> None:
    """1.5 MB con límite de 1 MB: pasa el Content-Length (holgura) y lo detiene la copia."""
    antes = _filas(entorno.session)

    r = subir(client, b"\x00" * int(1.5 * MB))

    assert r.status_code == 413
    assert "1 MB" in r.json()["detail"]
    assert _filas(entorno.session) == antes
    carpeta = entorno.settings.media_path / "videos"
    assert not carpeta.exists() or not any(carpeta.iterdir())
    assert entorno.pendientes == []


def test_tamano_excedido_por_content_length(client: TestClient, entorno: Entorno) -> None:
    """3 MB con límite de 1 MB: el middleware responde antes de leer el cuerpo."""
    antes = _filas(entorno.session)

    r = subir(client, b"\x00" * 3 * MB)

    assert r.status_code == 413
    assert _filas(entorno.session) == antes
    assert not (entorno.settings.media_path / "videos").exists()


# ── Análisis ─────────────────────────────────────────────────────────────────


def test_avance_hasta_listo_y_txt_en_vivo(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = subir(client, generar_video().read_bytes()).json()["id"]
    url = f"/videos/{video_id}"
    # Antes de empezar: en cola y TXT vacío (200, no 404).
    assert client.get(url).json()["proceso"] == "en_cola"
    txt = client.get(f"{url}/transcripcion.txt")
    assert (txt.status_code, txt.text) == (200, "")
    assert txt.headers["content-type"] == "text/plain; charset=utf-8"

    durante: list[tuple[str, str, int, list[str]]] = []

    def antes(i: int) -> None:
        estado = client.get(url).json()
        lineas = client.get(f"{url}/transcripcion.txt").text.splitlines()
        durante.append((estado["proceso"], estado["etapa"], estado["progreso"], lineas))

    entorno.transcriptor.antes = antes
    entorno.correr_pendientes()

    # Mientras transcribe: procesando, etapa transcripcion y el TXT con lo ya escrito (RF-10).
    assert [d[:2] for d in durante] == [("procesando", "transcripcion")] * 3
    assert [len(d[3]) for d in durante] == [0, 1, 2]
    assert durante[1][3] == ["[00:00] Primero reviso el manómetro."]
    progresos = [d[2] for d in durante]
    assert progresos == sorted(progresos) and 15 <= progresos[0] < progresos[-1] < 100

    final = client.get(url).json()
    assert (final["proceso"], final["etapa"], final["progreso"]) == ("listo", "listo", 100)
    assert final["duracion"] == pytest.approx(3, abs=0.2)
    assert final["idioma"] == "es"
    assert final["error"] is None
    assert len(client.get(f"{url}/transcripcion.txt").text.splitlines()) == 3


def test_analisis_409_antes_de_terminar_y_completo_despues(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = subir(client, generar_video().read_bytes()).json()["id"]

    r = client.get(f"/videos/{video_id}/analisis")
    assert r.status_code == 409
    assert r.json()["detail"]["proceso"] == "en_cola"

    entorno.correr_pendientes()
    r = client.get(f"/videos/{video_id}/analisis")

    assert r.status_code == 200
    datos = r.json()
    esquema = json.loads(ESQUEMA.read_text(encoding="utf-8"))
    assert sorted(Draft202012Validator(esquema).iter_errors(datos), key=str) == []
    analisis = Analisis.model_validate(datos)
    assert analisis.video_id == video_id
    assert [s.texto for s in analisis.transcripcion] == [s.texto for s in SEGMENTOS]
    assert analisis.idioma == Idioma(codigo="es", confianza=0.97, fijado_a_mano=False)
    # Opción 1: el idioma completo y los segmentos van en el JSONB `transcripcion`.
    guardado = entorno.video(video_id).transcripcion
    assert set(guardado) == {"version_contrato", "idioma", "segmentos"}


def test_idioma_fijado_llega_al_transcriptor(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = subir(client, generar_video().read_bytes(), idioma="es").json()["id"]
    entorno.correr_pendientes()

    assert entorno.transcriptor.idiomas == ["es"]
    assert client.get(f"/videos/{video_id}/analisis").json()["idioma"]["fijado_a_mano"] is True


def test_video_sin_audio_queda_en_error(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = subir(client, generar_video(con_audio=False).read_bytes()).json()["id"]
    entorno.correr_pendientes()

    estado = client.get(f"/videos/{video_id}").json()
    assert estado["proceso"] == "error"
    assert estado["error"] == "video.mp4: el video no tiene pista de audio"
    assert client.get(f"/videos/{video_id}/analisis").status_code == 409


def test_error_inesperado_sin_texto_del_video(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    entorno.transcriptor.error = ValueError("Primero reviso el manómetro")
    video_id = subir(client, generar_video().read_bytes()).json()["id"]
    entorno.correr_pendientes()

    estado = client.get(f"/videos/{video_id}").json()
    assert estado["proceso"] == "error"
    assert estado["error"] == "falló la etapa transcripcion (ValueError)"
    assert "manómetro" not in estado["error"]


@pytest.mark.parametrize("sufijo", ["", "/transcripcion.txt", "/analisis", "/reporte"])
def test_404_si_el_video_no_existe(client: TestClient, sufijo: str) -> None:
    r = client.get(f"/videos/999999999{sufijo}")
    assert r.status_code == 404


# ── Arranque ─────────────────────────────────────────────────────────────────


def test_al_arrancar_marca_interrumpidos(db_session: Session) -> None:
    filas = {
        proceso: Video(titulo=proceso, archivo="x", modo="generar", proceso=proceso)
        for proceso in ("en_cola", "procesando", "listo", "error")
    }
    filas["error"].error = "otro error"
    db_session.add_all(filas.values())
    db_session.commit()

    app = create_app(sesiones=lambda: nullcontext(db_session))
    with TestClient(app):
        pass

    for video in filas.values():
        db_session.refresh(video)
    assert (filas["en_cola"].proceso, filas["en_cola"].error) == ("error", ERROR_REINICIO)
    assert (filas["procesando"].proceso, filas["procesando"].error) == ("error", ERROR_REINICIO)
    assert (filas["listo"].proceso, filas["listo"].error) == ("listo", None)
    assert filas["error"].error == "otro error"


# ── SOP de referencia y reporte (RF-03, RF-19, RF-20) ────────────────────────


def test_validar_exige_el_sop(client: TestClient, entorno: Entorno) -> None:
    antes = (_filas(entorno.session), _sops(entorno.session))

    r = subir(client, b"\x00" * 100, sop=None)

    assert r.status_code == 422
    assert "SOP" in r.json()["detail"]
    assert (_filas(entorno.session), _sops(entorno.session)) == antes
    assert entorno.pendientes == []


def test_sop_que_no_sigue_la_plantilla(client: TestClient, entorno: Entorno) -> None:
    antes = (_filas(entorno.session), _sops(entorno.session))

    r = subir(client, b"\x00" * 100, sop=("sop.md", b"Cambio de filtro\nsin pasos ni titulo\n"))

    assert r.status_code == 422
    assert "plantilla" in r.json()["detail"].lower() or "título" in r.json()["detail"]
    assert (_filas(entorno.session), _sops(entorno.session)) == antes


def test_sop_en_mayusculas_y_con_bom(client: TestClient, entorno: Entorno) -> None:
    """PowerShell escribe el TXT con BOM; el archivo con BOM convierte igual."""
    r = subir(client, b"\x00" * 100, sop=("SOP.MD", b"\xef\xbb\xbf" + SOP_MD))

    assert r.status_code == 202
    assert entorno.video(r.json()["id"]).sop_id is not None


@pytest.mark.parametrize(
    ("caso", "sop", "codigo"),
    [
        ("extensión", ("sop.pdf", SOP_MD), 415),
        ("no UTF-8", ("sop.md", b"# T\xedtulo\n## Pasos\n### 1. Algo\n"), 422),
        ("vacío", ("sop.md", b""), 422),
    ],
)
def test_sop_invalido(
    client: TestClient, entorno: Entorno, caso: str, sop: tuple[str, bytes], codigo: int
) -> None:
    antes = (_filas(entorno.session), _sops(entorno.session))

    r = subir(client, b"\x00" * 100, sop=sop)

    assert r.status_code == codigo, caso
    assert (_filas(entorno.session), _sops(entorno.session)) == antes


def test_sop_id_inexistente(client: TestClient, entorno: Entorno) -> None:
    r = subir(client, b"\x00" * 100, sop=None, sop_id="999999")

    assert r.status_code == 404
    assert _filas(entorno.session) == 0


def test_el_mismo_sop_dos_veces_reutiliza_la_fila(client: TestClient, entorno: Entorno) -> None:
    """La biblioteca no se llena de copias: mismo título y contenido, misma fila de `sops`."""
    primero = subir(client, b"\x00" * 100).json()
    segundo = subir(client, b"\x00" * 100).json()

    assert primero["sop_id"] == segundo["sop_id"]
    assert _sops(entorno.session) == 1
    assert _filas(entorno.session) == 2


def test_sop_id_ya_guardado_se_puede_usar(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    sop_id = subir(client, b"\x00" * 100).json()["sop_id"]

    r = subir(client, generar_video().read_bytes(), sop=None, sop_id=str(sop_id))

    assert r.status_code == 202
    assert r.json()["sop_id"] == sop_id
    assert _sops(entorno.session) == 1


def test_reporte_de_punta_a_punta(client: TestClient, entorno: Entorno, generar_video) -> None:
    video_id = subir(client, generar_video().read_bytes()).json()["id"]

    r = client.get(f"/videos/{video_id}/reporte")
    assert r.status_code == 409
    assert r.json()["detail"]["proceso"] == "en_cola"

    entorno.correr_pendientes()

    r = client.get(f"/videos/{video_id}/reporte")
    assert r.status_code == 200
    reporte = r.json()
    assert reporte["video_id"] == video_id
    assert reporte["sop_id"] is not None
    assert reporte["sop_titulo"]
    assert reporte["semaforo"] in ("verde", "amarillo", "rojo")
    assert 0 <= reporte["cumplimiento"] <= 100
    # Sin Ollama, los pasos salen de la heurística y así se registra (RNF-06).
    assert reporte["pasos_del_video"]["metodo"] == "heuristica"
    assert reporte["pasos_del_video"]["pasos"] >= 1

    filas = reporte["filas"]
    assert [f["orden"] for f in filas] == list(range(1, len(filas) + 1))
    assert sum(reporte["resumen"]["conteo"].values()) + reporte["resumen"]["marco_operador"] == len(
        filas
    )
    con_video = [f for f in filas if f["paso_video"] is not None]
    assert con_video
    assert all(f["t_inicio"] is not None and f["cita"] for f in con_video)
    assert all(f["cita"] in " ".join(s.texto for s in SEGMENTOS) for f in con_video)

    guardado = entorno.session.scalars(select(Reporte)).one()
    assert guardado.video_id == video_id
    assert guardado.cumplimiento == Decimal(str(reporte["cumplimiento"]))
    assert guardado.afinidad is None  # RF-17 llega en S5
    assert entorno.video(video_id).pasos_video
    estado = client.get(f"/videos/{video_id}").json()
    assert (estado["proceso"], estado["etapa"], estado["progreso"]) == ("listo", "listo", 100)


def test_reporte_en_modo_generar_no_existe(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = subir(client, generar_video().read_bytes(), sop=None, modo="generar").json()["id"]
    entorno.correr_pendientes()

    r = client.get(f"/videos/{video_id}/reporte")

    assert r.status_code == 404
    assert "modo generar" in r.json()["detail"]
    assert entorno.validador.llamadas == 0


def test_validacion_fallida_deja_error_y_conserva_la_transcripcion(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    entorno.validador.error = ValueError("Primero reviso el manómetro.")
    video_id = subir(client, generar_video().read_bytes()).json()["id"]
    entorno.correr_pendientes()

    estado = client.get(f"/videos/{video_id}").json()
    assert estado["proceso"] == "error"
    assert estado["error"] == "falló la etapa validacion (ValueError)"
    assert "manómetro" not in estado["error"]
    # El análisis se confirmó antes de validar: la transcripción no se pierde.
    assert entorno.video(video_id).transcripcion is not None
    assert client.get(f"/videos/{video_id}/reporte").status_code == 409
    assert entorno.session.scalars(select(Reporte)).all() == []
