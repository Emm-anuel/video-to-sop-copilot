"""PDF del reporte (RF-29) y del SOP generado (RF-30): `salidas/pdf.py` y `GET /videos/{id}/pdf`,
`GET /sops/{id}/pdf`.

Las pruebas de `salidas.pdf` usan los ejemplos del contrato (`reporte_ejemplo*.json`,
`sop_generado_ejemplo.json`, inventados) y leen el PDF con pdfplumber: secciones en el orden de
§13, encabezado y pie en cada hoja, acentos, enlaces y QR con su segundo. Las de la API usan la
base de pruebas y videos sintéticos de ffmpeg (`generar_video`), como `test_videos.py`.
"""

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from PIL import Image as ImagenPIL
from sqlalchemy.orm import Session

from dobles import Entorno, guardar_sop, guardar_video
from sopvid.contrato import SOP, ReporteValidacion
from sopvid.salidas import pdf

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://192.168.0.20:4200"
VIDEO = pdf.InfoVideo(id=1, titulo="Revisión del piñón en la cañería", duracion=157.8, idioma="es")


def _reporte(nombre: str = "reporte_ejemplo.json") -> ReporteValidacion:
    return ReporteValidacion.model_validate_json((FIXTURES / nombre).read_text(encoding="utf-8"))


def _sop() -> SOP:
    return SOP.model_validate_json(
        (FIXTURES / "sop_generado_ejemplo.json").read_text(encoding="utf-8")
    )


def _paginas(contenido: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        return [p.extract_text() or "" for p in doc.pages]


def _enlaces(contenido: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        return [h["uri"] for p in doc.pages for h in p.hyperlinks]


def _pdf_reporte(reporte: ReporteValidacion | None = None, **kwargs) -> bytes:
    return pdf.pdf_reporte(reporte or _reporte(), video=VIDEO, base_url=BASE, **kwargs)


def _pdf_sop(sop: SOP | None = None, video: pdf.InfoVideo | None = VIDEO) -> bytes:
    return pdf.pdf_sop(
        sop or _sop(),
        codigo="SOP-0042",
        fecha=datetime(2026, 11, 12, 18, 0, tzinfo=UTC),
        base_url=BASE,
        video=video,
    )


def _en_orden(texto: str, titulos: list[str]) -> None:
    posiciones = [texto.find(t) for t in titulos]
    assert -1 not in posiciones, list(zip(titulos, posiciones, strict=True))
    assert posiciones == sorted(posiciones)


def _encabezado_y_pie(paginas: list[str], codigo: str) -> None:
    total = len(paginas)
    for numero, texto in enumerate(paginas, start=1):
        assert f"Página {numero} de {total}" in texto
        assert codigo in texto.splitlines()[0]  # el encabezado va arriba, en cada hoja


# ── RF-29 · Reporte ──────────────────────────────────────────────────────────────────────────


def test_reporte_con_todas_las_secciones_en_orden_y_pie_en_cada_hoja() -> None:
    paginas = _paginas(_pdf_reporte())

    texto = "\n".join(paginas)
    _en_orden(
        texto,
        ["Reporte de cumplimiento", "71.43 %", "Amarillo", "Afinidad de contexto: 87 / 100"]
        + [f"{n}. {t}" for n, t in enumerate(pdf.SECCIONES_REPORTE, start=2)],
    )
    _encabezado_y_pie(paginas, "SOP-0001")
    assert "Revisión del piñón en la cañería" in paginas[0]  # acentos y ñ, fuente embebida
    assert "PROVISIONAL" not in texto
    # La sección 8 (revisión) espera a RF-21.
    assert "8. Revisi" not in texto


def test_reporte_provisional_lo_dice_en_la_portada() -> None:
    paginas = _paginas(_pdf_reporte(_reporte("reporte_ejemplo_provisional.json")))

    assert "REPORTE PROVISIONAL" in paginas[0]
    assert "Pares sin revisar por el juez" in paginas[0]


def test_reporte_faltan_y_sobran_con_su_segundo_y_cita() -> None:
    reporte = _reporte()
    texto = "\n".join(_paginas(_pdf_reporte(reporte)))

    faltan = texto.split("4. Pasos que faltan")[1].split("5. Pasos que sobran")[0]
    sobran = texto.split("5. Pasos que sobran")[1].split("6. Personas y tiempos")[0]
    falta = next(f for f in reporte.filas if f.estado == "Falta")
    pedido = reporte.sop.pasos[falta.paso_sop - 1]
    assert f"Paso {falta.paso_sop} · {pedido.nombre}" in faltan
    assert pedido.descripcion in faltan
    sobra = next(f for f in reporte.filas if f.estado == "Sobra" and f.marco_operador is None)
    assert f"{pdf.mmss(sobra.t_inicio)} · {sobra.nombre_video}" in sobran
    assert f"«{sobra.cita}»" in sobran
    # La intro y el cierre del operador no son Sobra (ADR-016).
    for marco in (f for f in reporte.filas if f.marco_operador is not None):
        assert marco.nombre_video not in sobran


def test_cada_hallazgo_lleva_qr_y_enlace_con_su_segundo(monkeypatch) -> None:
    codificados: list[str] = []
    original = pdf.dibujo_qr

    def registrar(url: str, lado: float = pdf.LADO_QR):
        codificados.append(url)
        return original(url, lado)

    monkeypatch.setattr(pdf, "dibujo_qr", registrar)
    reporte = _reporte()

    contenido = _pdf_reporte(reporte)

    esperados = [f"{BASE}/v/1?t={f.t_inicio:.1f}" for f in reporte.filas if pdf.es_hallazgo(f)]
    # Parcial, fuera de orden, responsable distinto, excede y el Sobra; nunca un Falta ni la
    # intro o el cierre del operador.
    assert len(esperados) == 5
    assert codificados == esperados
    assert _enlaces(contenido) == esperados
    assert f"{BASE}/v/1?t=55.5" in esperados  # el Parcial del paso 3 (t_inicio 55.51)


def test_url_video_redondea_a_un_decimal_y_quita_la_diagonal_final() -> None:
    assert pdf.url_video("http://localhost:4200/", 7, 12.46) == "http://localhost:4200/v/7?t=12.5"
    assert pdf.url_video(BASE, 7, 0) == f"{BASE}/v/7?t=0.0"


def _jpeg(tmp_path: Path) -> Path:
    ruta = tmp_path / "cuadro.jpg"
    ImagenPIL.new("RGB", (160, 120), (40, 120, 200)).save(ruta)
    return ruta


def _x0_texto_evidencia(contenido: bytes) -> float:
    """Dónde empieza el texto de la evidencia ("Segundo mm:ss · enlace"): el "Segundo" más a la
    izquierda (los de los encabezados de las tablas quedan más a la derecha)."""
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        return min(w["x0"] for p in doc.pages for w in p.extract_words() if w["text"] == "Segundo")


def test_evidencia_con_miniatura_y_sin_imagen_sin_huecos(tmp_path: Path) -> None:
    cuadro = _jpeg(tmp_path)
    pedidos: list[float] = []

    def miniatura(t: float) -> Path:
        pedidos.append(t)
        return cuadro

    con = _pdf_reporte(miniatura=miniatura)
    sin = _pdf_reporte(miniatura=lambda _t: None)

    with pdfplumber.open(io.BytesIO(con)) as doc:
        assert sum(len(p.images) for p in doc.pages) == 5
    with pdfplumber.open(io.BytesIO(sin)) as doc:
        assert sum(len(p.images) for p in doc.pages) == 0
    assert len(pedidos) == 5
    # Sin imagen, el texto ocupa el lugar de la miniatura: no queda una columna vacía.
    assert _x0_texto_evidencia(sin) < pdf.MARGEN_X + 20
    assert _x0_texto_evidencia(con) > pdf.MARGEN_X + pdf.ANCHO_MINIATURA


def test_citas_y_nombres_largos_no_se_salen_de_la_pagina() -> None:
    reporte = _reporte()
    larga = "palabra " * 70 + "x" * 120  # 600 caracteres y una "palabra" sin espacios
    filas = [
        f.model_copy(update={"cita": larga, "nombre_sop": f.nombre_sop and f.nombre_sop * 6})
        if f.cita
        else f
        for f in reporte.filas
    ]
    contenido = _pdf_reporte(reporte.model_copy(update={"filas": filas}))

    limite = pdf.PAGINA[0] - pdf.MARGEN_X + 1
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        for pagina in doc.pages:
            assert all(c["x1"] <= limite for c in pagina.chars), pagina.page_number


# ── RF-30 · SOP generado ─────────────────────────────────────────────────────────────────────


def test_sop_con_todas_las_secciones_un_qr_y_pie_en_cada_hoja(monkeypatch) -> None:
    codificados: list[str] = []
    original = pdf.dibujo_qr
    monkeypatch.setattr(
        pdf, "dibujo_qr", lambda url, lado=pdf.LADO_QR: codificados.append(url) or original(url)
    )
    sop = _sop()

    contenido = _pdf_sop(sop)
    paginas = _paginas(contenido)

    texto = "\n".join(paginas)
    _en_orden(
        texto,
        [sop.titulo, "Código SOP-0042", "Versión 1.0", "Fecha 12/11/2026"]
        + ["Idioma del video español", "Duración del video 02:37"]
        + [f"{n}. {t}" for n, t in enumerate(pdf.SECCIONES_SOP, start=2)],
    )
    _encabezado_y_pie(paginas, "SOP-0042")
    # Un solo QR, al video desde el inicio, y el mismo enlace en texto.
    assert codificados == [f"{BASE}/v/1?t=0.0"]
    assert _enlaces(contenido) == codificados
    # Casilla por punto de validación y menciones de las palabras clave.
    n_puntos = sum(len(p.puntos_validacion) for p in sop.pasos)
    assert texto.count(pdf.CASILLA) == n_puntos
    for palabra in sop.palabras_clave:
        assert f"{palabra.termino} " in texto
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        filas = [r for p in doc.pages for t in p.extract_tables() for r in t]
    menciones = {r[0]: r[2] for r in filas if len(r) == 3}
    assert menciones == {"Palabra clave": "Menciones"} | {
        p.termino: str(p.menciones) for p in sop.palabras_clave
    }


def _filas_de_tablas(contenido: bytes) -> list[list[str]]:
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        return [
            [(c or "").replace("\n", " ") for c in r]
            for p in doc.pages
            for t in p.extract_tables()
            for r in t
        ]


def test_asterisco_en_lo_inferido_sin_revisar_y_no_en_lo_revisado() -> None:
    sop = _sop()
    alcance = sop.resumen.alcance.model_copy(update={"valor": "Solo la línea 3 a 25 °C"})
    assert alcance.fuente == "inferido" and not alcance.revisado
    paso2 = sop.pasos[1].model_copy(update={"campos_inferidos": ["responsable"]})
    sin_revisar = sop.model_copy(
        update={
            "resumen": sop.resumen.model_copy(update={"alcance": alcance}),
            "pasos": [sop.pasos[0], paso2, *sop.pasos[2:]],
        }
    )
    # En el editor: confirmar el alcance lo marca revisado y saca el campo del paso (ADR-025).
    revisado = sin_revisar.model_copy(
        update={
            "resumen": sin_revisar.resumen.model_copy(
                update={"alcance": alcance.model_copy(update={"revisado": True})}
            ),
            "pasos": [
                sop.pasos[0],
                paso2.model_copy(update={"campos_inferidos": []}),
                *sop.pasos[2:],
            ],
        }
    )

    antes = {r[0]: r for r in _filas_de_tablas(_pdf_sop(sin_revisar))}
    despues = {r[0]: r for r in _filas_de_tablas(_pdf_sop(revisado))}

    assert antes["Alcance"][1] == "Solo la línea 3 a 25 °C *"
    assert despues["Alcance"][1] == "Solo la línea 3 a 25 °C"
    assert antes["2"][3] == f"{paso2.responsable} *"
    assert despues["2"][3] == paso2.responsable
    # Un punto de validación inferido (paso 1 del ejemplo) lleva asterisco y su casilla.
    assert antes["1"][5].startswith(pdf.CASILLA) and antes["1"][5].endswith("*")


def test_sop_sin_video_no_lleva_qr_idioma_ni_duracion() -> None:
    contenido = _pdf_sop(video=None)

    texto = "\n".join(_paginas(contenido))
    assert _enlaces(contenido) == []
    assert "Idioma del video" not in texto
    assert "Duración del video" not in texto
    assert "4. Puntos y palabras clave" in texto


# ── API ──────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    entorno = Entorno(db_session, tmp_path)
    entorno.settings = entorno.settings.model_copy(update={"app_url_publica": BASE})
    return entorno


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _subir(client: TestClient, video: bytes, **datos: str) -> int:
    formulario = {"titulo": "Revisión de la línea", "modo": "generar", **datos}
    r = client.post(
        "/videos", data=formulario, files={"archivo": ("operador.mp4", video, "video/mp4")}
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _es_pdf(r) -> bytes:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith('attachment; filename="')
    assert r.headers["content-disposition"].endswith('.pdf"')
    assert r.content.startswith(b"%PDF")
    return r.content


def test_pdf_del_reporte_con_miniaturas_y_enlaces_al_segundo(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    sop = guardar_sop(entorno.session)
    video_id = _subir(client, generar_video().read_bytes(), modo="validar", sop_id=str(sop.id))
    entorno.correr_pendientes()
    reporte = ReporteValidacion.model_validate(client.get(f"/videos/{video_id}/reporte").json())

    contenido = _es_pdf(client.get(f"/videos/{video_id}/pdf"))

    hallazgos = [f for f in reporte.filas if pdf.es_hallazgo(f)]
    assert hallazgos  # el Parcial del juez
    assert _enlaces(contenido) == [f"{BASE}/v/{video_id}?t={f.t_inicio:.1f}" for f in hallazgos]
    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        assert sum(len(p.images) for p in doc.pages) == len(hallazgos)
    assert sop.codigo in _paginas(contenido)[0]


def test_pdf_del_reporte_de_un_video_sin_imagen(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    sop = guardar_sop(entorno.session)
    archivo = generar_video("voz.mp4", imagen="ninguna")
    video_id = _subir(client, archivo.read_bytes(), modo="validar", sop_id=str(sop.id))
    entorno.correr_pendientes()

    contenido = _es_pdf(client.get(f"/videos/{video_id}/pdf"))

    with pdfplumber.open(io.BytesIO(contenido)) as doc:
        assert sum(len(p.images) for p in doc.pages) == 0
    assert _enlaces(contenido)  # el QR y el enlace se quedan


def test_pdf_del_sop_generado_y_el_mismo_desde_la_biblioteca(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _subir(client, generar_video().read_bytes())
    entorno.correr_pendientes()
    sop_id = entorno.video(video_id).sop_id

    del_video = _es_pdf(client.get(f"/videos/{video_id}/pdf"))
    de_biblioteca = _es_pdf(client.get(f"/sops/{sop_id}/pdf"))

    for contenido in (del_video, de_biblioteca):
        assert _enlaces(contenido) == [f"{BASE}/v/{video_id}?t=0.0"]
        assert "Revisión de la línea de agua" in _paginas(contenido)[0]


def test_pdf_usa_el_sop_corregido_en_el_editor(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _subir(client, generar_video().read_bytes())
    entorno.correr_pendientes()
    sop_id = entorno.video(video_id).sop_id
    sop = SOP.model_validate(client.get(f"/videos/{video_id}/sop").json())
    corregido = sop.model_copy(update={"titulo": "Revisión corregida de la línea"})
    assert client.put(f"/sops/{sop_id}", json=corregido.model_dump(mode="json")).status_code == 200

    contenido = _es_pdf(client.get(f"/videos/{video_id}/pdf"))

    assert "Revisión corregida de la línea" in _paginas(contenido)[0]


def test_pdf_de_sop_para_ver_va_inline(client: TestClient, entorno: Entorno) -> None:
    """`?ver=true` ("Ver SOP" de `/buscar`): el mismo PDF, para abrirlo en otra pestaña."""
    sop = guardar_sop(entorno.session)

    r = client.get(f"/sops/{sop.id}/pdf", params={"ver": "true"})

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith('inline; filename="')
    assert r.content.startswith(b"%PDF")


def test_pdf_de_un_sop_cargado_sin_qr(client: TestClient, entorno: Entorno) -> None:
    sop = guardar_sop(entorno.session)

    contenido = _es_pdf(client.get(f"/sops/{sop.id}/pdf"))

    assert _enlaces(contenido) == []
    assert sop.codigo in _paginas(contenido)[0]


@pytest.mark.parametrize("proceso", ["en_cola", "procesando"])
def test_pdf_409_mientras_procesa(client: TestClient, entorno: Entorno, proceso: str) -> None:
    video = guardar_video(entorno.session, proceso=proceso, modo="validar")

    r = client.get(f"/videos/{video.id}/pdf")

    assert r.status_code == 409
    assert r.json()["detail"]["proceso"] == proceso
    assert "sigue en proceso" in r.json()["detail"]["mensaje"]


def test_pdf_409_explicado_si_se_detuvo_por_afinidad(client: TestClient, entorno: Entorno) -> None:
    video = guardar_video(entorno.session, proceso="afinidad_baja", modo="validar")

    r = client.get(f"/videos/{video.id}/pdf")

    assert r.status_code == 409
    assert "afinidad baja" in r.json()["detail"]["mensaje"]
    assert "Continúa la validación" in r.json()["detail"]["mensaje"]


@pytest.mark.parametrize("modo", ["validar", "generar"])
def test_pdf_404_sin_reporte_ni_sop_generado(
    client: TestClient, entorno: Entorno, modo: str
) -> None:
    video = guardar_video(entorno.session, proceso="error", modo=modo)

    r = client.get(f"/videos/{video.id}/pdf")

    assert r.status_code == 404
    esperado = "el video no tiene reporte" if modo == "validar" else "el video no tiene un SOP"
    assert r.json()["detail"]["mensaje"].startswith(esperado)


def test_pdf_404_si_el_video_no_existe(client: TestClient) -> None:
    assert client.get("/videos/999999999/pdf").status_code == 404


def test_pdf_de_sop_409_si_no_esta_listo(client: TestClient, entorno: Entorno) -> None:
    sop = guardar_sop(entorno.session)
    sop.estado, sop.contenido, sop.titulo = "convirtiendo", None, None
    entorno.session.commit()

    assert client.get(f"/sops/{sop.id}/pdf").status_code == 409
