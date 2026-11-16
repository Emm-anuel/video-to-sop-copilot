"""PDF del reporte de cumplimiento (RF-29) y del SOP generado (RF-30), en el orden de §13.

Los dos van en tamaño carta y en español, con DejaVu Sans embebida (acentos, ñ, ° y ☐), un
encabezado (título, código del SOP y fecha) y el pie "Página X de Y" en todas las hojas.

Todo segundo, cita y conteo sale tal cual de lo guardado: el `ReporteValidacion` de
`GET /videos/{id}/reporte` o el `SOP` de `sops.contenido` con las correcciones del editor
(regla 4). Aquí no hay LLM; el código solo da formato. Los QR y los enlaces llevan a
`<APP_URL_PUBLICA>/v/<id>?t=<segundo>&k=<token>` (§11, ADR-027), armados siempre con
`url_video`; sin `SECRETO_ENLACES`, sin `k`.

Funciones puras, como el resto de `salidas`: la API les pasa lo guardado, los datos del video y,
para el reporte, una función que da la miniatura de un segundo (o None si el video no tiene
imagen: entonces la evidencia va sin la columna de la imagen, sin huecos).
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from sopvid.contrato import (
    SOP,
    Confianza,
    Dato,
    FilaReporte,
    FuenteSOP,
    PasoSOP,
    ReporteValidacion,
)
from sopvid.percepcion.transcripcion import marca_tiempo

# ── Fuente, página y estilos ─────────────────────────────────────────────────────────────────

CARPETA_FUENTES = Path(__file__).parent / "fuentes"
FUENTE = "DejaVuSans"
FUENTE_NEGRITA = "DejaVuSans-Bold"

PAGINA = letter
MARGEN_X = 1.6 * cm
MARGEN_SUP = 2.2 * cm
MARGEN_INF = 1.8 * cm
# El marco de `SimpleDocTemplate` deja 6 pt de relleno por lado: una tabla más ancha se sale.
RELLENO_MARCO = 6
ANCHO_UTIL = PAGINA[0] - 2 * MARGEN_X - 2 * RELLENO_MARCO

LADO_QR = 2.6 * cm
ANCHO_MINIATURA = 4.2 * cm
# Un video vertical (celular) daría una miniatura muy alta: cabe en ANCHO × ALTO, sin deformarse.
ALTO_MINIATURA = 3.2 * cm

GRIS = colors.HexColor("#555555")
GRIS_CLARO = colors.HexColor("#dddddd")
FONDO_ENCABEZADO = colors.HexColor("#eef1f5")
COLOR_SEMAFORO = {
    "verde": colors.HexColor("#2e7d32"),
    "amarillo": colors.HexColor("#f9a825"),
    "rojo": colors.HexColor("#c62828"),
}

ETIQUETA_SEMAFORO = {"verde": "Verde", "amarillo": "Amarillo", "rojo": "Rojo"}
# Los mismos textos que la pantalla del reporte (frontend/src/app/reporte/reporte.ts).
ETIQUETA_ESTADO = {
    "Cumple": "Cumple",
    "Parcial": "Parcial",
    "Falta": "Falta",
    "Sobra": "Sobra",
    "zona_gris": "Sin revisar",
}
ETIQUETA_MARCO = {"intro": "Intro del operador", "cierre": "Cierre del operador"}
ETIQUETA_AVISO = {
    "segmentacion_heuristica": (
        "Pasos del video por heurística (el modelo de lenguaje no respondió)"
    ),
    "juez_sin_revisar": "Pares sin revisar por el juez",
    "pasos_sin_redactar": "Pasos del video sin redactar",
    "contexto_sin_generar": "Ficha de contexto sin generar",
    "transcripcion_no_referencia": "Transcripción con un Whisper que no es el de referencia",
    "imagenes_incompletas": "Imágenes sin describir",
    "sin_imagen": "Video sin imagen",
}
ETIQUETA_RESPONSABLE = {
    "coincide": "coincide",
    "distinto": "distinto",
    "no_identificado": "no identificado",
}
ETIQUETA_ROL = {"presente": "Presente", "mencionado": "Mencionado", "ausente": "Ausente"}
ETIQUETA_TIEMPO = {
    "en_tiempo": "en tiempo",
    "excede": "excede",
    "menor": "menor",
    "sin_referencia": "sin referencia",
}
ETIQUETA_HORARIO = {
    "coincide": "coincide",
    "distinto": "distinto",
    "no_mencionado": "no se menciona en el video",
    "sin_referencia": "el SOP no lo define",
}
ETIQUETA_CONFIANZA: dict[Confianza, str] = {"alta": "Alta", "media": "Media", "baja": "Baja"}
ETIQUETA_FUENTE: dict[FuenteSOP, str] = {
    "audio": "Audio",
    "visual": "Imagen",
    "inferido": "Inferido",
    "documento": "Documento",
}
ETIQUETA_CATEGORIA = {
    "equipo": "Equipo",
    "accion": "Acción",
    "seguridad": "Seguridad",
    "calidad": "Calidad",
    "lugar": "Lugar",
    "material": "Material",
    "otro": "Otro",
}
ETIQUETA_PARTICIPACION = {"participa": "participa", "mencionado": "mencionado"}
IDIOMAS = {
    "es": "español",
    "en": "inglés",
    "pt": "portugués",
    "fr": "francés",
    "de": "alemán",
    "it": "italiano",
}

CASILLA = "☐"
ASTERISCO = "*"
LEYENDA_ASTERISCO = (
    f"{ASTERISCO} Dato inferido: no tiene evidencia en el video y ninguna persona lo ha revisado."
)


def _registrar_fuentes() -> None:
    """Registra DejaVu Sans una sola vez por proceso (reportlab guarda el registro global)."""
    if FUENTE in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(FUENTE, CARPETA_FUENTES / "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont(FUENTE_NEGRITA, CARPETA_FUENTES / "DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily(
        FUENTE, normal=FUENTE, bold=FUENTE_NEGRITA, italic=FUENTE, boldItalic=FUENTE_NEGRITA
    )


def _estilo(nombre: str, **cambios: Any) -> ParagraphStyle:
    base: dict[str, Any] = {"fontName": FUENTE, "fontSize": 9, "leading": 11.5}
    return ParagraphStyle(nombre, **(base | cambios))


@dataclass(frozen=True)
class _Estilos:
    texto: ParagraphStyle
    chico: ParagraphStyle
    celda: ParagraphStyle
    celda_titulo: ParagraphStyle
    titulo: ParagraphStyle
    subtitulo: ParagraphStyle
    seccion: ParagraphStyle
    porcentaje: ParagraphStyle
    aviso: ParagraphStyle


def _estilos() -> _Estilos:
    _registrar_fuentes()
    return _Estilos(
        texto=_estilo("texto", spaceAfter=3),
        chico=_estilo("chico", fontSize=7.5, leading=9.5, textColor=GRIS),
        celda=_estilo("celda", fontSize=8, leading=10),
        celda_titulo=_estilo("celda_titulo", fontName=FUENTE_NEGRITA, fontSize=8, leading=10),
        titulo=_estilo("titulo", fontName=FUENTE_NEGRITA, fontSize=20, leading=25, spaceAfter=6),
        subtitulo=_estilo("subtitulo", fontSize=11, leading=14, textColor=GRIS, spaceAfter=12),
        seccion=_estilo(
            "seccion",
            fontName=FUENTE_NEGRITA,
            fontSize=13,
            leading=16,
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=1,
        ),
        porcentaje=_estilo(
            "porcentaje", fontName=FUENTE_NEGRITA, fontSize=30, leading=36, alignment=TA_CENTER
        ),
        aviso=_estilo("aviso", fontSize=9, leading=12, textColor=colors.HexColor("#7a4b00")),
    )


# ── Utilidades ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InfoVideo:
    """Lo que el PDF dice del video: de la fila `videos` (título, duración e idioma detectado)."""

    id: int
    titulo: str
    duracion: float | None = None
    idioma: str | None = None
    # Token firmado del enlace (`acceso.token_enlace`, ADR-027): abre este video sin clave.
    token_enlace: str | None = None


def url_video(base: str, video_id: int, t: float, token: str | None = None) -> str:
    """`<base>/v/<id>?t=<segundo>[&k=<token>]` (§11, ADR-027): el destino de cada QR y de cada
    enlace del PDF. El segundo va con un decimal (RNF-03 pide ±1 s); `base` sin "/" final. El
    token es base64url: no hace falta escaparlo."""
    url = f"{base.rstrip('/')}/v/{video_id}?t={t:.1f}"
    return f"{url}&k={token}" if token else url


def dibujo_qr(url: str, lado: float = LADO_QR) -> Drawing:
    """El QR de `url` como dibujo de `lado` × `lado` puntos (reportlab.graphics.barcode.qr)."""
    widget = QrCodeWidget(url)
    x0, y0, x1, y1 = widget.getBounds()
    dibujo = Drawing(lado, lado, transform=[lado / (x1 - x0), 0, 0, lado / (y1 - y0), 0, 0])
    dibujo.add(widget)
    return dibujo


def mmss(t: float | None) -> str:
    """`mm:ss` como en el TXT y en la pantalla; "—" sin segundo."""
    return "—" if t is None else marca_tiempo(t)


def _minutos(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor:.1f}".removesuffix(".0") + " min"


def _p(texto: str | None, estilo: ParagraphStyle) -> Paragraph:
    """Un párrafo con el texto escapado (las citas pueden traer <, > o &)."""
    return Paragraph(escape(texto or ""), estilo)


def _p_marcado(marcado: str, estilo: ParagraphStyle) -> Paragraph:
    """Un párrafo con marcado de reportlab ya armado (negritas, enlaces); el texto de lo guardado
    ya va escapado por quien lo arma."""
    return Paragraph(marcado, estilo)


def _cita(cita: str) -> str:
    return f"«{escape(cita)}»" if cita.strip() else ""


def _enlace(url: str) -> str:
    return f'<a href="{escape(url)}" color="#1a56b0"><u>{escape(url)}</u></a>'


def _fecha(momento: datetime, con_hora: bool = False) -> str:
    local = momento.astimezone() if momento.tzinfo is not None else momento
    return local.strftime("%d/%m/%Y %H:%M" if con_hora else "%d/%m/%Y")


def _tabla(
    filas: list[list[Any]],
    anchos: Sequence[float],
    *,
    encabezado: bool = True,
    estilo_extra: Iterable[tuple[Any, ...]] = (),
) -> Table:
    """Tabla con texto que se ajusta dentro de cada celda (`Paragraph`) y se parte entre hojas
    repitiendo el encabezado."""
    tabla = Table(filas, colWidths=list(anchos), repeatRows=1 if encabezado else 0, hAlign="LEFT")
    comandos: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, GRIS_CLARO),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if encabezado:
        comandos.append(("BACKGROUND", (0, 0), (-1, 0), FONDO_ENCABEZADO))
    tabla.setStyle(TableStyle([*comandos, *estilo_extra]))
    return tabla


def _lienzo(titulo: str, codigo: str, fecha: str) -> type[canvas.Canvas]:
    """Un `Canvas` que guarda cada hoja y, al cerrar, les dibuja el encabezado y el pie
    "Página X de Y" (el total solo se sabe al final)."""

    class Lienzo(canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._hojas: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 (API de reportlab)
            self._hojas.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._hojas)
            for numero, hoja in enumerate(self._hojas, start=1):
                self.__dict__.update(hoja)
                self._marco(numero, total)
                super().showPage()
            super().save()

        def _marco(self, numero: int, total: int) -> None:
            ancho, alto = PAGINA
            y = alto - 1.3 * cm
            derecha = f"{codigo}  ·  {fecha}"
            self.setFont(FUENTE, 8)
            self.setFillColor(GRIS)
            self.drawRightString(ancho - MARGEN_X, y, derecha)
            espacio = ANCHO_UTIL - pdfmetrics.stringWidth(derecha, FUENTE, 8) - 0.8 * cm
            self.setFont(FUENTE_NEGRITA, 8)
            self.drawString(MARGEN_X, y, _recortar(titulo, FUENTE_NEGRITA, 8, espacio))
            self.setStrokeColor(GRIS_CLARO)
            self.setLineWidth(0.6)
            self.line(MARGEN_X, y - 0.25 * cm, ancho - MARGEN_X, y - 0.25 * cm)
            self.setFont(FUENTE, 8)
            self.drawCentredString(ancho / 2, 1.0 * cm, f"Página {numero} de {total}")

    return Lienzo


def _recortar(texto: str, fuente: str, tamano: float, ancho: float) -> str:
    """`texto` recortado con "…" para que quepa en `ancho` (el encabezado es de una línea)."""
    if pdfmetrics.stringWidth(texto, fuente, tamano) <= ancho:
        return texto
    while texto and pdfmetrics.stringWidth(texto + "…", fuente, tamano) > ancho:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def _construir(
    historia: list[Flowable], titulo_doc: str, encabezado: tuple[str, str, str]
) -> bytes:
    salida = BytesIO()
    doc = SimpleDocTemplate(
        salida,
        pagesize=PAGINA,
        leftMargin=MARGEN_X,
        rightMargin=MARGEN_X,
        topMargin=MARGEN_SUP,
        bottomMargin=MARGEN_INF,
        title=titulo_doc,
        author="SOPVID",
        lang="es-MX",
    )
    doc.build(historia, canvasmaker=_lienzo(*encabezado))
    return salida.getvalue()


def _imagen(ruta: Path, ancho: float, alto: float) -> Image:
    """La imagen tan grande como quepa en `ancho` × `alto`, con su proporción."""
    w, h = ImageReader(str(ruta)).getSize()
    escala = min(ancho / w, alto / h)
    return Image(str(ruta), width=w * escala, height=h * escala)


# ── RF-29 · Reporte de cumplimiento ──────────────────────────────────────────────────────────

SECCIONES_REPORTE = (
    "Resumen de hallazgos",
    "Tabla paso a paso",
    "Pasos que faltan",
    "Pasos que sobran",
    "Personas y tiempos",
    "Evidencia",
)


def es_hallazgo(fila: FilaReporte) -> bool:
    """Lo que lleva evidencia en el PDF: todo lo que no es un *Cumple* limpio. Parcial, Sin
    revisar y Sobra (sin la intro ni el cierre del operador, ADR-016), y un par fuera de orden,
    con responsable distinto o que excede su tiempo. Un Falta no tiene segundo en el video."""
    if fila.marco_operador is not None or fila.estado == "Falta":
        return False
    return (
        fila.estado != "Cumple"
        or fila.fuera_de_orden
        or (fila.responsable is not None and fila.responsable.estado == "distinto")
        or (fila.tiempo is not None and fila.tiempo.estado == "excede")
    )


def _diferencias(fila: FilaReporte) -> list[str]:
    """Qué hace de la fila un hallazgo, en palabras."""
    textos = []
    if fila.estado != "Cumple":
        textos.append(ETIQUETA_ESTADO[fila.estado])
    if fila.fuera_de_orden:
        textos.append("Fuera de orden")
    if fila.responsable is not None and fila.responsable.estado == "distinto":
        r = fila.responsable
        textos.append(f"Responsable distinto (esperado: {r.esperado}; observado: {r.observado})")
    if fila.tiempo is not None and fila.tiempo.estado == "excede":
        t = fila.tiempo
        textos.append(
            f"Excede el tiempo ({_minutos(t.observado_min)} de {_minutos(t.esperado_min)})"
        )
    return textos


def _etiqueta_fila(fila: FilaReporte) -> str:
    if fila.marco_operador is not None:
        return ETIQUETA_MARCO[fila.marco_operador]
    etiqueta = ETIQUETA_ESTADO[fila.estado]
    return f"{etiqueta} · fuera de orden" if fila.fuera_de_orden else etiqueta


def pdf_reporte(
    reporte: ReporteValidacion,
    *,
    video: InfoVideo,
    base_url: str,
    miniatura: Callable[[float], Path | None] = lambda _t: None,
) -> bytes:
    """El PDF del reporte de cumplimiento (RF-29) en el orden de §13: portada, resumen de
    hallazgos, tabla paso a paso, pasos que faltan, pasos que sobran, personas y tiempos, y
    evidencia de cada hallazgo (`es_hallazgo`) con miniatura, cita, QR al segundo y el mismo
    enlace en texto. La sección de revisión (8) espera a RF-21.

    `miniatura(t)` da la imagen de ese segundo o None (video sin imagen o ffmpeg falló): sin
    ninguna, la evidencia va sin la columna de la imagen.
    """
    e = _estilos()
    fecha = _fecha(reporte.creado)
    historia: list[Flowable] = []
    historia += _portada_reporte(reporte, video, e)
    historia.append(PageBreak())
    historia += _resumen_reporte(reporte, e)
    historia += _tabla_reporte(reporte, e)
    historia += _faltan(reporte, e)
    historia += _sobran(reporte, e)
    historia += _personas_y_tiempos(reporte, e)
    historia += _evidencia(reporte, video, base_url, miniatura, e)
    titulo = f"Reporte de cumplimiento · {reporte.sop.titulo}"
    return _construir(historia, titulo, (titulo, reporte.sop.codigo, fecha))


def _seccion(numero: int, titulo: str, e: _Estilos) -> Paragraph:
    return _p(f"{numero}. {titulo}", e.seccion)


def _portada_reporte(r: ReporteValidacion, video: InfoVideo, e: _Estilos) -> list[Flowable]:
    partes: list[Flowable] = [
        _p("Reporte de cumplimiento", e.titulo),
        _p(r.sop.titulo, e.subtitulo),
    ]
    if r.provisional:
        avisos = [a for a in r.metadatos.avisos if a.tipo != "sin_imagen"]
        lineas = "<br/>".join(f"· {escape(ETIQUETA_AVISO.get(a.tipo, a.tipo))}" for a in avisos)
        recuadro = _tabla(
            [
                [_p_marcado("<b>REPORTE PROVISIONAL</b>", e.aviso)],
                [_p("Hubo fallas del sistema que afectan al resultado:", e.aviso)],
                [_p_marcado(lineas, e.aviso)],
            ],
            [ANCHO_UTIL],
            encabezado=False,
            estilo_extra=[
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#f9a825")),
                ("GRID", (0, 0), (-1, -1), 0, colors.white),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff8e1")),
            ],
        )
        partes += [recuadro, Spacer(1, 10)]
    duracion = f" · {mmss(video.duracion)}" if video.duracion is not None else ""
    datos = [
        ["Video", f"{video.titulo} (n.º {video.id}{duracion})"],
        ["SOP de referencia", f"{r.sop.codigo} · {r.sop.titulo}"],
        ["Fecha del reporte", _fecha(r.creado, con_hora=True)],
    ]
    partes.append(
        _tabla(
            [[_p(a, e.celda_titulo), _p(b, e.celda)] for a, b in datos],
            [4 * cm, ANCHO_UTIL - 4 * cm],
            encabezado=False,
        )
    )
    partes.append(Spacer(1, 16))
    color = COLOR_SEMAFORO[r.semaforo]
    porcentaje = Table(
        [
            [
                _p(f"{r.cumplimiento:.2f} %", e.porcentaje),
                _p_marcado(
                    f'<font color="{color.hexval()}" size="22">●</font>  '
                    f"<b>{ETIQUETA_SEMAFORO[r.semaforo]}</b><br/>"
                    '<font size="8" color="#555555">Cumplimiento con semáforo</font>',
                    _estilo("semaforo", fontSize=13, leading=20),
                ),
            ]
        ],
        colWidths=[7 * cm, ANCHO_UTIL - 7 * cm],
        hAlign="LEFT",
    )
    porcentaje.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (0, 0), 2, color),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (0, 0), 8),
                ("BOTTOMPADDING", (0, 0), (0, 0), 10),
                ("LEFTPADDING", (1, 0), (1, 0), 14),
            ]
        )
    )
    partes += [porcentaje, Spacer(1, 16)]
    if r.afinidad is None:
        partes.append(_p("Afinidad de contexto: no calculada (sin ficha de contexto).", e.texto))
    else:
        bajo = " — bajo el umbral" if r.afinidad.bajo_umbral else ""
        partes.append(
            _p_marcado(
                f"<b>Afinidad de contexto:</b> {r.afinidad.valor} / 100{escape(bajo)}", e.texto
            )
        )
        partes.append(_p(r.afinidad.explicacion, e.chico))
    return partes


def _resumen_reporte(r: ReporteValidacion, e: _Estilos) -> list[Flowable]:
    c = r.conteo
    filas = [
        ["Cumple", c.cumple],
        ["Parcial", c.parcial],
        ["Fuera de orden", c.fuera_de_orden],
        ["Falta", c.falta],
        ["Sobra", c.sobra],
        ["Sin revisar", c.sin_revisar],
        ["Personas con diferencias", c.personas_con_diferencias],
        ["Pasos fuera de tiempo", c.pasos_fuera_de_tiempo],
    ]
    partes: list[Flowable] = [
        _seccion(2, SECCIONES_REPORTE[0], e),
        _tabla(
            [[_p("Concepto", e.celda_titulo), _p("Cantidad", e.celda_titulo)]]
            + [[_p(a, e.celda), _p(str(b), e.celda)] for a, b in filas],
            [8 * cm, 3 * cm],
        ),
    ]
    if c.marco_operador:
        partes.append(
            _p(
                f"Intro y cierre del operador: {c.marco_operador} (no cuentan como Sobra).",
                e.chico,
            )
        )
    return partes


def _tabla_reporte(r: ReporteValidacion, e: _Estilos) -> list[Flowable]:
    encabezado = [
        _p(x, e.celda_titulo)
        for x in (
            "N.º",
            "Paso",
            "Estado",
            "Responsable (esperado / observado)",
            "Tiempo (esperado / observado)",
            "Segundo",
        )
    ]
    filas: list[list[Any]] = [encabezado]
    for f in r.filas:
        if f.paso_sop is not None:
            paso = escape(f.nombre_sop or "")
            if f.nombre_video and f.estado != "Falta":
                paso += (
                    f'<br/><font size="7" color="#555555">Video: {escape(f.nombre_video)}</font>'
                )
        else:
            paso = escape(f.nombre_video or "")
        if f.rescatado:
            paso += '<br/><font size="7" color="#555555">Armado con varios fragmentos</font>'
        if f.responsable is None:
            responsable = "—"
        else:
            rr = f.responsable
            responsable = (
                f"{escape(rr.esperado)} / {escape(rr.observado or 'sin identificar')}"
                f'<br/><font size="7" color="#555555">{ETIQUETA_RESPONSABLE[rr.estado]}</font>'
            )
        if f.tiempo is None:
            tiempo = "—"
        else:
            t = f.tiempo
            narrado = " (narrado)" if t.origen == "narrado" else ""
            tiempo = (
                f"{_minutos(t.esperado_min)} / {_minutos(t.observado_min)}"
                f'<br/><font size="7" color="#555555">{ETIQUETA_TIEMPO[t.estado]}{narrado}</font>'
            )
        filas.append(
            [
                _p(str(f.paso_sop) if f.paso_sop is not None else "–", e.celda),
                _p_marcado(paso, e.celda),
                _p(_etiqueta_fila(f), e.celda),
                _p_marcado(responsable, e.celda),
                _p_marcado(tiempo, e.celda),
                _p(mmss(f.t_inicio), e.celda),
            ]
        )
    anchos = [1.0 * cm, 5.6 * cm, 2.4 * cm, 4.2 * cm, 3.2 * cm]
    anchos.append(ANCHO_UTIL - sum(anchos))
    return [_seccion(3, SECCIONES_REPORTE[1], e), _tabla(filas, anchos)]


def _faltan(r: ReporteValidacion, e: _Estilos) -> list[Flowable]:
    partes: list[Flowable] = [_seccion(4, SECCIONES_REPORTE[2], e)]
    pasos = {p.numero: p for p in r.sop.pasos}
    faltan = [f for f in r.filas if f.estado == "Falta"]
    if not faltan:
        return [*partes, _p("Ninguno: todos los pasos del SOP aparecen en el video.", e.texto)]
    for f in faltan:
        paso = pasos.get(f.paso_sop) if f.paso_sop is not None else None
        nombre = paso.nombre if paso else (f.nombre_sop or "")
        descripcion = paso.descripcion if paso else ""
        texto = f"<b>Paso {f.paso_sop} · {escape(nombre)}</b>"
        if descripcion:
            texto += f"<br/>{escape(descripcion)}"
        partes.append(_p_marcado(texto, e.texto))
    return partes


def _sobran(r: ReporteValidacion, e: _Estilos) -> list[Flowable]:
    partes: list[Flowable] = [_seccion(5, SECCIONES_REPORTE[3], e)]
    sobran = [f for f in r.filas if f.estado == "Sobra" and f.marco_operador is None]
    if not sobran:
        return [*partes, _p("Ninguno.", e.texto)]
    for f in sobran:
        texto = f"<b>{mmss(f.t_inicio)} · {escape(f.nombre_video or '')}</b>"
        if f.cita.strip():
            texto += f"<br/>{_cita(f.cita)}"
        partes.append(_p_marcado(texto, e.texto))
    return partes


def _personas_y_tiempos(r: ReporteValidacion, e: _Estilos) -> list[Flowable]:
    partes: list[Flowable] = [_seccion(6, SECCIONES_REPORTE[4], e)]
    if r.roles:
        filas: list[list[Any]] = [
            [_p(x, e.celda_titulo) for x in ("Rol del SOP", "Estado", "Persona", "Segundo", "Cita")]
        ]
        for rol in r.roles:
            estado = ETIQUETA_ROL[rol.estado]
            if rol.estado == "ausente" and not rol.con_pasos:
                estado += " (apoyo, no suma)"
            filas.append(
                [
                    _p(rol.rol, e.celda),
                    _p(estado, e.celda),
                    _p(rol.persona or "—", e.celda),
                    _p(mmss(rol.t), e.celda),
                    _p_marcado(_cita(rol.cita), e.celda),
                ]
            )
        anchos = [4.2 * cm, 2.8 * cm, 3.6 * cm, 1.9 * cm]
        anchos.append(ANCHO_UTIL - sum(anchos))
        partes.append(_tabla(filas, anchos))
    else:
        partes.append(_p("Roles: no se registraron en este reporte.", e.texto))
    partes.append(Spacer(1, 6))
    total = r.tiempo_total
    if total is None:
        partes.append(_p("Tiempo total: no se registró en este reporte.", e.texto))
    else:
        esperado = (
            f" de {_minutos(total.esperado_min)} esperados"
            if total.esperado_min is not None
            else ""
        )
        partes.append(
            _p_marcado(
                f"<b>Tiempo total:</b> {_minutos(total.observado_min)}{esperado} "
                f"({ETIQUETA_TIEMPO[total.estado]})",
                e.texto,
            )
        )
    h = r.horario
    if h is None:
        partes.append(_p("Horario: no se registró en este reporte.", e.texto))
    else:
        texto = f"<b>Horario:</b> {ETIQUETA_HORARIO[h.estado]}"
        if h.esperado:
            texto += f" · esperado: {escape(h.esperado)}"
        if h.observado:
            texto += f" · observado: {escape(h.observado)} ({mmss(h.t)})"
        if h.cita.strip():
            texto += f"<br/>{_cita(h.cita)}"
        partes.append(_p_marcado(texto, e.texto))
    return partes


def _evidencia(
    r: ReporteValidacion,
    video: InfoVideo,
    base_url: str,
    miniatura: Callable[[float], Path | None],
    e: _Estilos,
) -> list[Flowable]:
    partes: list[Flowable] = [_seccion(7, SECCIONES_REPORTE[5], e)]
    hallazgos = [f for f in r.filas if es_hallazgo(f)]
    if not hallazgos:
        partes.append(_p("Sin hallazgos: todos los pares cumplen.", e.texto))
    faltan = sum(f.estado == "Falta" for f in r.filas)
    if faltan:
        partes.append(
            _p(
                f"Los pasos que faltan ({faltan}) no tienen segundo en el video: "
                "están en la sección 4.",
                e.chico,
            )
        )
    for f in hallazgos:
        partes.append(
            KeepTogether([Spacer(1, 6), _bloque_evidencia(f, video, base_url, miniatura, e)])
        )
    return partes


def _bloque_evidencia(
    f: FilaReporte,
    video: InfoVideo,
    base_url: str,
    miniatura: Callable[[float], Path | None],
    e: _Estilos,
) -> Table:
    if f.paso_sop is not None:
        titulo = f"Paso {f.paso_sop} · {escape(f.nombre_sop or '')}"
    else:
        titulo = f"Paso del video · {escape(f.nombre_video or '')}"
    lineas = [f"<b>{titulo}</b>", escape(" · ".join(_diferencias(f)))]
    if f.cita.strip():
        lineas.append(_cita(f.cita))
    if f.justificacion:
        lineas.append(f'<font color="#555555">Juez: {escape(f.justificacion)}</font>')
    celdas: list[Any] = []
    anchos: list[float] = []
    if f.t_inicio is not None:
        url = url_video(base_url, video.id, f.t_inicio, video.token_enlace)
        lineas.append(f"Segundo {mmss(f.t_inicio)} · {_enlace(url)}")
        ruta = miniatura(f.t_inicio)
        if ruta is not None:
            celdas.append(_imagen(ruta, ANCHO_MINIATURA, ALTO_MINIATURA))
            anchos.append(ANCHO_MINIATURA + 0.3 * cm)
        texto = _p_marcado("<br/>".join(lineas), e.celda)
        celdas += [texto, dibujo_qr(url)]
        anchos += [ANCHO_UTIL - sum(anchos) - LADO_QR - 0.3 * cm, LADO_QR + 0.3 * cm]
    else:
        lineas.append("Sin segundo en el video.")
        celdas.append(_p_marcado("<br/>".join(lineas), e.celda))
        anchos.append(ANCHO_UTIL)
    tabla = Table([celdas], colWidths=anchos, hAlign="LEFT")
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, GRIS_CLARO),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tabla


# ── RF-30 · SOP generado ─────────────────────────────────────────────────────────────────────

SECCIONES_SOP = ("Cuadro resumen", "Procedimiento paso a paso", "Puntos y palabras clave")


def inferido(x: Dato | Any) -> bool:
    """Un dato del resumen, un riesgo, una falla o un punto clave lleva asterisco si es inferido
    y ninguna persona lo revisó (ADR-025), la misma regla que el editor (`leyenda()` en
    frontend/src/app/sop/edicion.ts)."""
    return getattr(x, "fuente", None) == "inferido" and not getattr(x, "revisado", False)


def item_inferido(paso: PasoSOP, campo: str, valor: str) -> bool:
    """Un elemento de `equipo` o `puntos_validacion` lleva asterisco si su campo sigue en
    `campos_inferidos` (el editor lo saca al editarlo o confirmarlo) y su evidencia es inferida
    o no tiene (lo agregó el modelo sin cita)."""
    if campo not in paso.campos_inferidos:
        return False
    evidencias = [x for x in paso.evidencia if x.campo == campo and x.valor == valor]
    return not evidencias or any(x.fuente == "inferido" for x in evidencias)


def pdf_sop(
    sop: SOP,
    *,
    codigo: str,
    fecha: datetime,
    base_url: str,
    video: InfoVideo | None = None,
) -> bytes:
    """El PDF del SOP (RF-30) en el orden de §13: portada con un QR al video (t=0), cuadro
    resumen con la confianza de cada dato, procedimiento paso a paso con una casilla por punto de
    validación y asterisco en lo inferido sin revisar, y puntos y palabras clave. Los opcionales
    de RF-28 quedan fuera.

    `sop` es el guardado, con las correcciones del editor. Sin `video` (un SOP cargado de la
    biblioteca), la portada no lleva QR, idioma ni duración.
    """
    e = _estilos()
    historia: list[Flowable] = []
    historia += _portada_sop(sop, codigo, fecha, video, base_url, e)
    historia.append(PageBreak())
    historia += _cuadro_resumen(sop, e)
    historia += _procedimiento(sop, e)
    historia += _claves(sop, e)
    return _construir(historia, sop.titulo, (sop.titulo, codigo, _fecha(fecha)))


def _con_asterisco(texto: str, marca: bool) -> str:
    return f"{escape(texto)} {ASTERISCO}" if marca else escape(texto)


def _portada_sop(
    sop: SOP,
    codigo: str,
    fecha: datetime,
    video: InfoVideo | None,
    base_url: str,
    e: _Estilos,
) -> list[Flowable]:
    partes: list[Flowable] = [
        _p(sop.titulo, e.titulo),
        _p("Procedimiento operativo estándar", e.subtitulo),
    ]
    datos = [
        ["Código", codigo],
        ["Versión", sop.resumen.version or "1.0"],
        ["Fecha", _fecha(fecha)],
    ]
    if video is not None:
        idioma = IDIOMAS.get(video.idioma or "", video.idioma or "—")
        datos += [
            ["Idioma del video", idioma],
            ["Duración del video", mmss(video.duracion)],
        ]
    partes.append(
        _tabla(
            [[_p(a, e.celda_titulo), _p(b, e.celda)] for a, b in datos],
            [4.5 * cm, ANCHO_UTIL - 4.5 * cm],
            encabezado=False,
        )
    )
    if video is not None:
        url = url_video(base_url, video.id, 0, video.token_enlace)
        qr = Table(
            [
                [
                    dibujo_qr(url),
                    _p_marcado(f"<b>Ver el video desde el inicio</b><br/>{_enlace(url)}", e.texto),
                ]
            ],
            colWidths=[LADO_QR + 0.4 * cm, ANCHO_UTIL - LADO_QR - 0.4 * cm],
            hAlign="LEFT",
        )
        qr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        partes += [Spacer(1, 16), qr]
    partes += [Spacer(1, 16), _p(LEYENDA_ASTERISCO, e.chico)]
    return partes


def _evidencia_dato(fuente: FuenteSOP, t: float | None) -> str:
    etiqueta = ETIQUETA_FUENTE[fuente]
    return etiqueta if t is None else f"{etiqueta} · {mmss(t)}"


def _cuadro_resumen(sop: SOP, e: _Estilos) -> list[Flowable]:
    r = sop.resumen
    filas: list[list[Any]] = [
        [_p(x, e.celda_titulo) for x in ("Dato", "Valor", "Confianza", "Evidencia")]
    ]

    def dato(nombre: str, d: Dato) -> None:
        filas.append(
            [
                _p(nombre, e.celda_titulo),
                _p_marcado(_con_asterisco(d.valor or "—", inferido(d)), e.celda),
                _p(ETIQUETA_CONFIANZA[d.confianza], e.celda),
                _p(_evidencia_dato(d.fuente, d.t), e.celda),
            ]
        )

    def sin_confianza(nombre: str, valor: str) -> None:
        filas.append(
            [
                _p(nombre, e.celda_titulo),
                _p_marcado(valor, e.celda),
                _p("—", e.celda),
                _p("", e.celda),
            ]
        )

    dato("Objetivo", r.objetivo)
    dato("Alcance", r.alcance)
    dato("Responsable", r.responsable)
    equipo = "<br/>".join(
        escape(x.nombre) + (f" — {escape(x.descripcion)}" if x.descripcion else "")
        for x in r.equipo_operacion
    )
    sin_confianza("Equipo de operación", equipo or "—")
    sin_confianza("Versión", escape(r.version or "1.0"))
    personas = "<br/>".join(
        escape(p.nombre + (f" ({p.rol})" if p.rol else ""))
        + f" · {ETIQUETA_PARTICIPACION[p.participacion]} · {mmss(p.t)}"
        for p in r.personas
    )
    sin_confianza("Personas", personas or "—")
    dato("Lugar", r.lugar)
    dato("Horario o frecuencia", r.horario_frecuencia)
    sin_confianza("Duración total", _minutos(r.duracion_total_min))
    for riesgo in r.riesgos:
        texto = _con_asterisco(riesgo.descripcion, inferido(riesgo))
        if riesgo.paso is not None:
            texto += f'<br/><font size="7" color="#555555">Paso {riesgo.paso}</font>'
        if riesgo.control:
            texto += f"<br/>Control: {escape(riesgo.control)}"
        filas.append(
            [
                _p(f"Riesgo ({riesgo.nivel})", e.celda_titulo),
                _p_marcado(texto, e.celda),
                _p(ETIQUETA_CONFIANZA[riesgo.confianza], e.celda),
                _p(_evidencia_dato(riesgo.fuente, riesgo.t), e.celda),
            ]
        )
    if not r.riesgos:
        sin_confianza("Riesgos", "—")
    for falla in r.en_caso_de_falla:
        texto = _con_asterisco(f"{falla.situacion} → {falla.accion}", inferido(falla))
        filas.append(
            [
                _p("En caso de falla", e.celda_titulo),
                _p_marcado(texto, e.celda),
                _p(ETIQUETA_CONFIANZA[falla.confianza], e.celda),
                _p(_evidencia_dato(falla.fuente, falla.t), e.celda),
            ]
        )
    if not r.en_caso_de_falla:
        sin_confianza("En caso de falla", "—")
    anchos = [3.6 * cm, 0, 2.0 * cm, 2.6 * cm]
    anchos[1] = ANCHO_UTIL - sum(anchos)
    return [_seccion(2, SECCIONES_SOP[0], e), _tabla(filas, anchos)]


def _procedimiento(sop: SOP, e: _Estilos) -> list[Flowable]:
    filas: list[list[Any]] = [
        [
            _p(x, e.celda_titulo)
            for x in (
                "N.º",
                "Nombre",
                "Descripción",
                "Responsable",
                "Equipo",
                "Puntos de validación",
                "Tiempo",
            )
        ]
    ]
    for p in sop.pasos:
        inferidos = set(p.campos_inferidos)
        nombre = _con_asterisco(p.nombre, "nombre" in inferidos)
        if p.t_inicio is not None:
            nombre += f'<br/><font size="7" color="#555555">Video {mmss(p.t_inicio)}</font>'
        equipo = "<br/>".join(_con_asterisco(x, item_inferido(p, "equipo", x)) for x in p.equipo)
        puntos = "<br/>".join(
            f"{CASILLA} " + _con_asterisco(x, item_inferido(p, "puntos_validacion", x))
            for x in p.puntos_validacion
        )
        filas.append(
            [
                _p(str(p.numero), e.celda),
                _p_marcado(nombre, e.celda),
                _p_marcado(_con_asterisco(p.descripcion, "descripcion" in inferidos), e.celda),
                _p_marcado(_con_asterisco(p.responsable, "responsable" in inferidos), e.celda),
                _p_marcado(equipo or "—", e.celda),
                _p_marcado(puntos or "—", e.celda),
                _p_marcado(
                    _con_asterisco(
                        _minutos(p.tiempo_esperado_min), "tiempo_esperado_min" in inferidos
                    ),
                    e.celda,
                ),
            ]
        )
    anchos = [0.9 * cm, 2.9 * cm, 0, 2.4 * cm, 2.4 * cm, 3.6 * cm, 1.6 * cm]
    anchos[2] = ANCHO_UTIL - sum(anchos)
    return [
        _seccion(3, SECCIONES_SOP[1], e),
        _tabla(filas, anchos),
        _p(LEYENDA_ASTERISCO, e.chico),
    ]


def _claves(sop: SOP, e: _Estilos) -> list[Flowable]:
    partes: list[Flowable] = [_seccion(4, SECCIONES_SOP[2], e), _p("Puntos clave", e.celda_titulo)]
    if not sop.puntos_clave:
        partes.append(_p("Ninguno.", e.texto))
    for punto in sop.puntos_clave:
        partes.append(
            _p_marcado(f"{mmss(punto.t)} · {_con_asterisco(punto.texto, inferido(punto))}", e.texto)
        )
    partes += [Spacer(1, 6), _p("Palabras clave", e.celda_titulo), Spacer(1, 3)]
    if not sop.palabras_clave:
        return [*partes, _p("Ninguna.", e.texto)]
    filas: list[list[Any]] = [
        [_p(x, e.celda_titulo) for x in ("Palabra clave", "Categoría", "Menciones")]
    ]
    for palabra in sop.palabras_clave:
        filas.append(
            [
                _p(palabra.termino, e.celda),
                _p(ETIQUETA_CATEGORIA.get(palabra.categoria, palabra.categoria), e.celda),
                _p(str(palabra.menciones), e.celda),
            ]
        )
    partes.append(_tabla(filas, [8 * cm, 4 * cm, 3 * cm]))
    return partes
