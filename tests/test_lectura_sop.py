"""Pruebas de la lectura del SOP en PDF y Word (RF-01, RF-02) y de su conversión (ADR-015).

Los PDF y Word se generan aquí, en memoria, a partir de tests/fixtures/sop_filtro_agua.md
(inventado por el equipo): uno sigue la plantilla, otro trae los pasos en una tabla y otro va en
prosa. El LLM es el `OllamaFalso` de tests/dobles.py (sin GPU ni Ollama). Las pruebas de la API
usan la base de conftest.py (`db_session`, revertida al final).
"""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import docx
import pytest
from fastapi.testclient import TestClient
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dobles import Entorno, OllamaFalso
from sopvid.contrato import SOP
from sopvid.lenguaje import lectura_sop
from sopvid.lenguaje.juez import RespuestaInvalida
from sopvid.lenguaje.lectura_sop import (
    ESQUEMA_SOP_LIBRE,
    MAX_INTENTOS,
    MENSAJE_ESCANEADO,
    MENSAJE_PDF_ILEGIBLE,
    MENSAJE_WORD_ILEGIBLE,
    ErrorConversionLLM,
    ErrorLectura,
    cargar_prompt,
    convertir_con_llm,
    convertir_documento,
    extraer_texto,
    lineas_tabla,
    validar_respuesta,
)
from sopvid.lenguaje.llm import LLMNoDisponible
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.api.sops import MENSAJE_LLM_NO_DISPONIBLE
from sopvid.plataforma.modelos import Sop, Video
from sopvid.texto import NO_IDENTIFICADO

FIXTURES = Path(__file__).parent / "fixtures"
MD = (FIXTURES / "sop_filtro_agua.md").read_text(encoding="utf-8")
SOP_MD = convertir_sop(MD).sop
SOP_EJEMPLO = json.loads((FIXTURES / "sop_ejemplo.json").read_text(encoding="utf-8"))
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ── Documentos de prueba ─────────────────────────────────────────────────────────────────────


def docx_desde_markdown(md: str) -> bytes:
    """Word que sigue la plantilla con estilos de Word: "#" → Heading 1, "- " → List Bullet."""
    documento = docx.Document()
    for linea in md.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        nivel = len(linea) - len(linea.lstrip("#"))
        if nivel:
            documento.add_heading(linea[nivel:].strip(), level=nivel)
        elif linea.startswith("- "):
            documento.add_paragraph(linea[2:], style="List Bullet")
        else:
            documento.add_paragraph(linea)
    return _guardar(documento)


def docx_con_tabla(sop: SOP) -> bytes:
    """Los pasos en una tabla, entre dos párrafos: no sigue la plantilla."""
    documento = docx.Document()
    documento.add_heading(sop.titulo, level=0)
    documento.add_paragraph(f"Responsable: {sop.resumen.responsable.valor}")
    tabla = documento.add_table(rows=1, cols=4)
    for celda, texto in zip(
        tabla.rows[0].cells, ["No.", "Paso", "Descripción", "Tiempo (min)"], strict=True
    ):
        celda.text = texto
    for p in sop.pasos:
        fila = tabla.add_row().cells
        fila[0].text, fila[1].text = str(p.numero), p.nombre
        fila[2].text, fila[3].text = p.descripcion, f"{p.tiempo_esperado_min:g}"
    documento.add_paragraph("Fin del procedimiento.")
    return _guardar(documento)


def prosa(sop: SOP) -> list[str]:
    """El SOP contado en párrafos, sin secciones, listas ni nombres de paso."""
    r = sop.resumen
    conectores = ["Para empezar", "Luego", "Después", "A continuación", "Más tarde", "Al final"]
    parrafos = [
        f"Este procedimiento lo hace el {r.responsable.valor.lower()} en la "
        f"{r.lugar.valor.lower()}. Su objetivo: {r.objetivo.valor.lower()}",
        "Se necesitan "
        + ", ".join(e.nombre.lower() for e in r.equipo_operacion[:-1])
        + f" y {r.equipo_operacion[-1].nombre.lower()}.",
    ]
    for conector, p in zip(conectores, sop.pasos, strict=True):
        parrafos.append(f"{conector}, hay que {p.descripcion[0].lower()}{p.descripcion[1:]}")
    return parrafos


def docx_en_prosa(sop: SOP) -> bytes:
    documento = docx.Document()
    documento.add_heading(sop.titulo, level=0)
    for parrafo in prosa(sop):
        documento.add_paragraph(parrafo)
    return _guardar(documento)


def pdf_desde_markdown(md: str) -> bytes:
    """PDF con el texto de la plantilla tal cual; las líneas largas se parten por el ancho."""
    estilo = getSampleStyleSheet()["Normal"]
    estilo.spaceAfter = 4
    bloques = [Paragraph(escape(linea), estilo) for linea in md.splitlines() if linea.strip()]
    salida = io.BytesIO()
    SimpleDocTemplate(salida, pagesize=A4).build(bloques)
    return salida.getvalue()


def pdf_con_tabla() -> bytes:
    estilos = getSampleStyleSheet()
    tabla = Table(
        [["No.", "Paso", "Responsable"], ["1", "Cerrar la llave", "Técnico"], ["2", "Purgar", ""]]
    )
    tabla.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    salida = io.BytesIO()
    SimpleDocTemplate(salida, pagesize=A4).build(
        [
            Paragraph("Antes de la tabla.", estilos["Normal"]),
            tabla,
            Paragraph("Después de la tabla.", estilos["Normal"]),
        ]
    )
    return salida.getvalue()


def pdf_escaneado() -> bytes:
    """Un PDF solo con dibujos, como una página escaneada: sin texto seleccionable."""
    salida = io.BytesIO()
    lienzo = canvas.Canvas(salida, pagesize=A4)
    lienzo.rect(72, 72, 300, 400, fill=1)
    lienzo.showPage()
    lienzo.save()
    return salida.getvalue()


def _guardar(documento: Any) -> bytes:
    salida = io.BytesIO()
    documento.save(salida)
    return salida.getvalue()


def respuesta_llm(sop: SOP = SOP_MD, **cambios: Any) -> dict[str, Any]:
    """Lo que respondería Gemma 4 por `ESQUEMA_SOP_LIBRE` para `sop`."""
    r = sop.resumen

    def dato(d: Any) -> dict[str, Any]:
        return {"valor": d.valor, "confianza": d.confianza}

    datos = {
        "titulo": sop.titulo,
        "resumen": {
            "objetivo": dato(r.objetivo),
            "alcance": dato(r.alcance),
            "responsable": dato(r.responsable),
            "lugar": dato(r.lugar),
            "horario_frecuencia": dato(r.horario_frecuencia),
            "duracion_total_min": r.duracion_total_min,
            "roles": [e.model_dump() for e in r.roles],
            "equipo_operacion": [e.model_dump() for e in r.equipo_operacion],
            "riesgos": [x.model_dump() for x in r.riesgos],
            "en_caso_de_falla": [f.model_dump() for f in r.en_caso_de_falla],
        },
        "pasos": [
            {
                "cita_origen": p.descripcion,  # está en la plantilla, en la tabla y en la prosa
                "nombre": p.nombre,
                "descripcion": p.descripcion,
                "responsable": p.responsable,
                "equipo": p.equipo,
                "puntos_validacion": p.puntos_validacion,
                "tiempo_esperado_min": p.tiempo_esperado_min,
                "confianza": "alta",
                "campos_inferidos": [],
            }
            for p in sop.pasos
        ],
    }
    return datos | cambios


class _SinLLM:
    """Fábrica que falla si se llama: el camino de la plantilla no debe crear el cliente."""

    def __call__(self) -> Any:
        raise AssertionError("no debía llamar al LLM")


# ── Extracción: PDF ──────────────────────────────────────────────────────────────────────────


def test_pdf_con_plantilla_sale_igual_que_el_markdown() -> None:
    texto = extraer_texto(pdf_desde_markdown(MD), ".PDF")

    resultado = convertir_documento(texto, _SinLLM())

    assert resultado.metodo == "plantilla"
    assert resultado.advertencias == []
    assert resultado.sop == SOP_MD  # las líneas partidas por el ancho se volvieron a unir


def test_pdf_tabla_en_su_lugar_y_legible() -> None:
    lineas = extraer_texto(pdf_con_tabla(), ".pdf").splitlines()

    assert lineas == [
        "Antes de la tabla.",
        "No.: 1 | Paso: Cerrar la llave | Responsable: Técnico",
        "No.: 2 | Paso: Purgar",
        "Después de la tabla.",
    ]


def test_pdf_sin_texto_parece_escaneado() -> None:
    with pytest.raises(ErrorLectura) as exc:
        extraer_texto(pdf_escaneado(), ".pdf")
    assert str(exc.value) == MENSAJE_ESCANEADO


@pytest.mark.parametrize(
    "datos", [b"no soy un pdf", b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog", b""], ids=repr
)
def test_pdf_corrupto(datos: bytes) -> None:
    with pytest.raises(ErrorLectura) as exc:
        extraer_texto(datos, ".pdf")
    assert str(exc.value) == MENSAJE_PDF_ILEGIBLE


# ── Extracción: Word ─────────────────────────────────────────────────────────────────────────


def test_word_con_plantilla_sale_igual_que_el_markdown() -> None:
    texto = extraer_texto(docx_desde_markdown(MD), ".docx")

    resultado = convertir_documento(texto, _SinLLM())

    assert texto.splitlines()[:3] == [
        "# Cambio del cartucho del filtro de agua",
        "## Resumen",
        "- Objetivo: " + SOP_MD.resumen.objetivo.valor,
    ]
    assert (resultado.metodo, resultado.advertencias) == ("plantilla", [])
    assert resultado.sop == SOP_MD


def test_word_tabla_de_pasos_en_orden_de_documento() -> None:
    lineas = extraer_texto(docx_con_tabla(SOP_MD), ".docx").splitlines()

    paso = SOP_MD.pasos[0]
    assert lineas[0] == f"# {SOP_MD.titulo}"  # el estilo Title es un encabezado de nivel 1
    assert lineas[1] == "Responsable: Técnico de mantenimiento"
    assert lineas[2] == (
        f"No.: 1 | Paso: {paso.nombre} | Descripción: {paso.descripcion} | Tiempo (min): 0.5"
    )
    assert len(lineas) == 3 + len(SOP_MD.pasos)
    assert lineas[-1] == "Fin del procedimiento."  # después de la tabla, no antes


def test_word_listas_numeradas_vinetas_y_encabezados() -> None:
    documento = docx.Document()
    documento.add_heading("Procedimiento inventado", level=1)
    documento.add_heading("Pasos", level=2)
    for texto in ["Cerrar la llave", "Purgar el aire"]:
        documento.add_paragraph(texto, style="List Number")
    documento.add_paragraph("Responsable: Técnico", style="List Bullet")
    documento.add_paragraph("Revisar fugas", style="List Number")  # la lista sigue: 3
    documento.add_paragraph("")  # vacío: no cuenta ni sale

    lineas = extraer_texto(_guardar(documento), ".docx").splitlines()

    assert lineas == [
        "# Procedimiento inventado",
        "## Pasos",
        "1. Cerrar la llave",
        "2. Purgar el aire",
        "- Responsable: Técnico",
        "3. Revisar fugas",
    ]


@pytest.mark.parametrize("datos", [b"PK\x03\x04roto", b"no soy un docx", b""], ids=repr)
def test_word_corrupto(datos: bytes) -> None:
    with pytest.raises(ErrorLectura) as exc:
        extraer_texto(datos, ".docx")
    assert str(exc.value) == MENSAJE_WORD_ILEGIBLE


def test_word_sin_texto() -> None:
    with pytest.raises(ErrorLectura, match="no tiene texto"):
        extraer_texto(_guardar(docx.Document()), ".docx")


def test_texto_que_no_es_utf8() -> None:
    with pytest.raises(ErrorLectura, match="UTF-8"):
        extraer_texto("Válvula".encode("latin-1"), ".txt")


@pytest.mark.parametrize(
    ("filas", "esperado"),
    [
        (
            [["Objetivo", "Cambiar el filtro"], ["Lugar", None]],
            ["Objetivo: Cambiar el filtro", "Lugar"],
        ),
        (
            [["No.", "Paso", "Equipo"], ["1", "Cerrar\nla llave", ""], [None, None, None]],
            ["No.: 1 | Paso: Cerrar la llave"],
        ),
        ([["", "B", "C"], ["1", "", "3"]], ["B | C", "1 | 3"]),  # sin encabezado completo
        ([], []),
    ],
)
def test_lineas_tabla(filas: list, esperado: list[str]) -> None:
    assert lineas_tabla(filas) == esperado


# ── Conversión con el LLM ────────────────────────────────────────────────────────────────────


def test_esquema_sin_referencias_ni_tiempos_del_video() -> None:
    texto = json.dumps(ESQUEMA_SOP_LIBRE)
    assert "$ref" not in texto and "$defs" not in texto
    pasos = ESQUEMA_SOP_LIBRE["properties"]["pasos"]["items"]["properties"]
    assert not {"numero", "t_inicio", "t_fin"} & set(pasos)
    assert "fuente" not in texto  # la pone el código


def test_prompt_versionado_lleva_el_texto_del_documento() -> None:
    prompt = cargar_prompt()
    mensajes = lectura_sop.construir_mensajes(prompt, "  Texto inventado del documento.  ")

    assert prompt.version == "sop_texto_libre_v2"
    assert cargar_prompt("sop_texto_libre_v1").version == "sop_texto_libre_v1"  # se conserva
    assert mensajes[0]["role"] == "system" and "infinitivo" in mensajes[0]["content"]
    assert "Texto inventado del documento." in mensajes[1]["content"]


def test_validar_respuesta_arma_el_sop_con_fuente_documento() -> None:
    texto = extraer_texto(docx_con_tabla(SOP_MD), ".docx")

    resultado = validar_respuesta(respuesta_llm(), texto)

    assert resultado.metodo == "llm"
    assert resultado.advertencias == []  # los nombres están en la tabla y en infinitivo
    assert [p.numero for p in resultado.sop.pasos] == [1, 2, 3, 4, 5, 6]
    assert resultado.sop.resumen.objetivo.fuente == "documento"
    assert resultado.sop.pasos == SOP_MD.pasos


def test_validar_respuesta_marca_lo_que_no_esta_en_el_documento() -> None:
    datos = respuesta_llm()
    # El nombre es libre: lo que se verifica es la cita.
    datos["pasos"][0] |= {"nombre": "Equiparse con el EPP"}
    datos["pasos"][1] |= {"cita_origen": "girar la manija roja dos vueltas", "responsable": None}
    datos["pasos"][2] |= {"nombre": "Liberación de presión", "campos_inferidos": ["equipo"]}
    datos["pasos"][3] |= {"cita_origen": "Aflojar el vaso"}  # 3 palabras: no alcanza
    datos["resumen"]["riesgos"][0] |= {"paso": 9, "nivel": None}
    texto = extraer_texto(docx_con_tabla(SOP_MD), ".docx")

    resultado = validar_respuesta(datos, texto)

    avisos = {(a.tipo, a.mensaje.split(";")[0]) for a in resultado.advertencias}
    sin_evidencia = {m for t, m in avisos if t == "paso_sin_evidencia"}
    assert sin_evidencia == {
        "la cita del paso 2 no aparece tal cual en el documento",
        "la cita del paso 4 no aparece tal cual en el documento",
    }
    assert ("infinitivo", "el nombre del paso 3 no empieza con un infinitivo") in avisos
    assert ("valor_invalido", "el riesgo 1 no trae nivel en el documento") in avisos
    assert ("valor_invalido", "el riesgo 1 cita el paso 9, que no existe") in avisos
    paso2, paso3 = resultado.sop.pasos[1:3]
    # Sin responsable: se hereda del resumen, con confianza media, como en la plantilla.
    assert (paso2.responsable, paso2.confianza, paso2.campos_inferidos) == (
        "Técnico de mantenimiento",
        "media",
        ["responsable"],
    )
    assert (paso3.confianza, paso3.campos_inferidos) == ("baja", ["equipo"])
    riesgo = resultado.sop.resumen.riesgos[0]
    assert (riesgo.nivel, riesgo.paso) == ("medio", None)
    assert all(a.linea is None for a in resultado.advertencias)


@pytest.mark.parametrize(
    ("cita", "verificada"),
    [
        ("Girar la llave de paso que está antes del filtro", True),
        ("GIRAR LA LLAVE, de paso que está", True),  # normalizada
        ("la llave", False),  # menos de 4 palabras
        ("girar la llave de paso hacia la izquierda", False),  # no está
        # Más de 25 palabras: se recortan a 25 y el recorte sigue siendo literal.
        (SOP_MD.pasos[3].descripcion + " y algo más que no está", True),
    ],
)
def test_cita_verificada(cita: str, verificada: bool) -> None:
    texto = MD
    assert lectura_sop.cita_verificada(cita, texto) is verificada


def test_validar_respuesta_sin_responsable_en_ningun_lado() -> None:
    datos = respuesta_llm()
    datos["resumen"]["responsable"] = {"valor": None, "confianza": "alta"}
    datos["pasos"][0]["responsable"] = None

    paso = validar_respuesta(datos, "texto").sop.pasos[0]

    assert (paso.responsable, paso.confianza) == (NO_IDENTIFICADO, "baja")


@pytest.mark.parametrize(
    ("cambios", "motivo"),
    [
        ({"titulo": "  "}, "el título está vacío"),
        ({"pasos": []}, "no hay pasos"),
        ({"pasos": [respuesta_llm()["pasos"][0] | {"nombre": " "}]}, "el paso 1 no tiene nombre"),
        ({"extra": 1}, "extra: extra_forbidden"),
    ],
)
def test_validar_respuesta_invalida(cambios: dict, motivo: str) -> None:
    with pytest.raises(RespuestaInvalida, match=motivo):
        validar_respuesta(respuesta_llm(**cambios), "texto")


def test_convertir_con_llm_reintenta_con_el_motivo() -> None:
    ollama = OllamaFalso([])
    ollama.respuestas_sop = ["{roto", respuesta_llm(pasos=[]), respuesta_llm()]

    with ollama.cliente() as llm:
        resultado = convertir_con_llm("texto del documento", llm)

    assert resultado.metodo == "llm"
    assert ollama.eventos == ["chat:sop"] * 3
    tercera = ollama.mensajes_sop[2]
    # 2 iniciales + corrección del JSON roto + respuesta anterior y su corrección.
    assert [m["role"] for m in tercera] == ["system", "user", "user", "assistant", "user"]
    assert "JSON válido" in tercera[2]["content"]
    assert "no hay pasos" in tercera[4]["content"]


def test_convertir_con_llm_sin_respuesta_valida() -> None:
    ollama = OllamaFalso([])
    ollama.respuestas_sop = [respuesta_llm(titulo="")]

    with ollama.cliente() as llm, pytest.raises(ErrorConversionLLM, match="plantilla"):
        convertir_con_llm("texto", llm)
    assert len(ollama.mensajes_sop) == MAX_INTENTOS


def test_convertir_documento_sin_plantilla_usa_el_llm_y_lo_descarga() -> None:
    ollama = OllamaFalso([])
    ollama.respuestas_sop = [respuesta_llm()]
    texto = extraer_texto(docx_en_prosa(SOP_MD), ".docx")

    resultado = convertir_documento(texto, ollama.cliente)

    assert resultado.metodo == "llm"
    assert ollama.eventos == ["tags", "chat:sop", "descargar"]
    assert "hay que colocarse los guantes" in ollama.mensajes_sop[0][1]["content"]
    # Los nombres de la plantilla no están en la prosa, pero las citas sí: hay evidencia.
    assert not [a for a in resultado.advertencias if a.tipo == "paso_sin_evidencia"]


def test_convertir_documento_con_texto_ignorado_usa_el_llm() -> None:
    """Pasa la plantilla pero con texto que se ignoraría: lo lee el LLM para no perder pasos."""
    ollama = OllamaFalso([])
    ollama.respuestas_sop = [respuesta_llm()]

    resultado = convertir_documento("Código SOP-INV-1\n" + MD, ollama.cliente)

    assert resultado.metodo == "llm"


def test_convertir_documento_sin_ollama() -> None:
    ollama = OllamaFalso([], disponible=False)

    with pytest.raises(LLMNoDisponible):
        convertir_documento("Solo un párrafo sin pasos.", ollama.cliente)
    assert ollama.mensajes_sop == []


# ── API: POST /sops ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def cargar(client: TestClient, contenido: bytes, nombre: str):
    return client.post("/sops", files={"archivo": (nombre, contenido, "application/octet-stream")})


def _filas(session: Session, modelo: type = Sop) -> int:
    return session.scalar(select(func.count()).select_from(modelo))


def _sin_archivos(entorno: Entorno, carpeta: str = "sops") -> bool:
    ruta = entorno.settings.media_path / carpeta
    return not ruta.exists() or not any(ruta.iterdir())


def test_api_pdf_con_plantilla(client: TestClient, entorno: Entorno) -> None:
    pdf = pdf_desde_markdown(MD)

    r = cargar(client, pdf, "Procedimiento.PDF")

    assert r.status_code == 201
    cuerpo = r.json()
    assert (cuerpo["metodo"], cuerpo["advertencias"]) == ("plantilla", [])
    fila = entorno.session.get(Sop, cuerpo["id"])
    assert fila.contenido == SOP_EJEMPLO  # igual que el .md
    assert fila.archivo_original == f"sops/{fila.id}/original.pdf"
    assert (entorno.settings.media_path / fila.archivo_original).read_bytes() == pdf
    assert entorno.eventos == []  # sin LLM


def test_api_word_con_tabla_de_pasos(client: TestClient, entorno: Entorno) -> None:
    entorno.ollama.respuestas_sop = [respuesta_llm()]

    r = cargar(client, docx_con_tabla(SOP_MD), "procedimiento.docx")

    assert r.status_code == 201
    cuerpo = r.json()
    assert (cuerpo["metodo"], cuerpo["advertencias"]) == ("llm", [])
    assert entorno.eventos == ["tags", "chat:sop", "descargar"]
    fila = entorno.session.get(Sop, cuerpo["id"])
    assert SOP.model_validate(fila.contenido).pasos == SOP_MD.pasos
    assert fila.archivo_original.endswith("/original.docx")


def test_api_pdf_sin_texto_422(client: TestClient, entorno: Entorno) -> None:
    antes = _filas(entorno.session)

    r = cargar(client, pdf_escaneado(), "escaneado.pdf")

    assert r.status_code == 422
    assert r.json()["detail"] == MENSAJE_ESCANEADO
    assert _filas(entorno.session) == antes
    assert _sin_archivos(entorno)


@pytest.mark.parametrize("nombre", ["roto.pdf", "roto.docx"])
def test_api_archivo_corrupto_422(client: TestClient, entorno: Entorno, nombre: str) -> None:
    antes = _filas(entorno.session)

    r = cargar(client, b"PK\x03\x04 esto no es un documento", nombre)

    assert r.status_code == 422
    assert "dañado" in r.json()["detail"]
    assert _filas(entorno.session) == antes
    assert entorno.eventos == []


@pytest.mark.parametrize("caida", ["apagado", "en_chat"])
def test_api_ollama_caido_503(client: TestClient, entorno: Entorno, caida: str) -> None:
    if caida == "apagado":
        entorno.ollama.disponible = False
    else:
        entorno.ollama.caido_en_chat = True
    antes = _filas(entorno.session)

    r = cargar(client, docx_en_prosa(SOP_MD), "prosa.docx")

    assert r.status_code == 503
    assert r.json()["detail"] == MENSAJE_LLM_NO_DISPONIBLE
    assert _filas(entorno.session) == antes  # no se guarda un SOP a medias
    assert _sin_archivos(entorno)


def test_api_respuesta_invalida_del_llm_422(client: TestClient, entorno: Entorno) -> None:
    entorno.ollama.respuestas_sop = ["{roto"]
    antes = _filas(entorno.session)

    r = cargar(client, docx_en_prosa(SOP_MD), "prosa.docx")

    assert r.status_code == 422
    assert "intentos" in r.json()["detail"]
    assert _filas(entorno.session) == antes
    assert entorno.eventos[-1] == "descargar"  # suelta el modelo también si falla


def test_api_documento_demasiado_grande(client: TestClient, entorno: Entorno, monkeypatch) -> None:
    monkeypatch.setattr("sopvid.plataforma.api.sops.SOP_DOCUMENTO_MAX_BYTES", 1000)

    r = cargar(client, pdf_desde_markdown(MD), "grande.pdf")

    assert r.status_code == 413


# ── API: POST /videos con el SOP adjunto (RF-02) ─────────────────────────────────────────────


def subir(client: TestClient, sop: tuple[str, bytes] | None, **datos: str):
    archivos = {"archivo": ("operador.mp4", b"\x00" * 100, "video/mp4")}
    if sop is not None:
        archivos["sop"] = (sop[0], sop[1], "application/octet-stream")
    formulario = {"titulo": "Cambio de filtro", "modo": "validar", **datos}
    return client.post("/videos", files=archivos, data=formulario)


@pytest.mark.parametrize("formato", ["pdf", "docx"])
def test_api_video_con_sop_adjunto_usa_el_mismo_camino(
    client: TestClient, entorno: Entorno, formato: str
) -> None:
    if formato == "pdf":
        sop, metodo = ("procedimiento.pdf", pdf_desde_markdown(MD)), "plantilla"
    else:
        sop, metodo = ("procedimiento.docx", docx_con_tabla(SOP_MD)), "llm"
        entorno.ollama.respuestas_sop = [respuesta_llm()]

    r = subir(client, sop)
    directo = cargar(client, sop[1], sop[0]).json()  # el mismo archivo por POST /sops

    assert r.status_code == 202
    cuerpo = r.json()
    video = entorno.video(cuerpo["id"])
    fila = entorno.session.get(Sop, video.sop_id)
    assert cuerpo["sop"]["id"] == fila.id
    assert cuerpo["sop"]["codigo"] == fila.codigo
    assert cuerpo["sop"]["metodo"] == directo["metodo"] == metodo
    assert cuerpo["sop"]["advertencias"] == directo["advertencias"]
    assert fila.contenido == entorno.session.get(Sop, directo["id"]).contenido
    assert fila.archivo_original == f"sops/{fila.id}/original.{formato}"
    assert len(entorno.pendientes) == 1  # el video quedó en cola para validar


def test_api_video_con_sop_adjunto_y_ollama_caido(client: TestClient, entorno: Entorno) -> None:
    entorno.ollama.disponible = False
    antes = (_filas(entorno.session), _filas(entorno.session, Video))

    r = subir(client, ("prosa.docx", docx_en_prosa(SOP_MD)))

    assert r.status_code == 503
    assert (_filas(entorno.session), _filas(entorno.session, Video)) == antes
    assert _sin_archivos(entorno) and _sin_archivos(entorno, "videos")
    assert entorno.pendientes == []


def test_api_video_sop_adjunto_se_revierte_si_falla_el_video(
    client: TestClient, entorno: Entorno
) -> None:
    """El video pasa del límite al copiarlo: tampoco queda el SOP adjunto."""
    antes = _filas(entorno.session)
    archivos = {
        "archivo": ("operador.mp4", b"\x00" * int(1.5 * 1024 * 1024), "video/mp4"),
        "sop": ("procedimiento.pdf", pdf_desde_markdown(MD), "application/pdf"),
    }

    r = client.post("/videos", files=archivos, data={"titulo": "Filtro", "modo": "validar"})

    assert r.status_code == 413
    assert _filas(entorno.session) == antes
    assert _sin_archivos(entorno) and _sin_archivos(entorno, "videos")


@pytest.mark.parametrize(
    ("datos", "detalle"),
    [
        ({"sop_id": "1"}, "no los dos"),
        ({"modo": "generar"}, "no van con modo=generar"),
    ],
)
def test_api_video_sop_adjunto_invalido(
    client: TestClient, entorno: Entorno, datos: dict, detalle: str
) -> None:
    r = subir(client, ("procedimiento.md", MD.encode()), **datos)

    assert r.status_code == 422
    assert detalle in r.json()["detail"]
    assert entorno.pendientes == []


def test_api_video_sin_ningun_sop(client: TestClient, entorno: Entorno) -> None:
    r = subir(client, None)

    assert r.status_code == 422
    assert r.json()["detail"] == "sop_id o sop es obligatorio con modo=validar"
