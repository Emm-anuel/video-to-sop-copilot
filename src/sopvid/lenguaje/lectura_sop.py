"""Lectura del SOP de referencia (RF-01, RF-02, RF-03) y su conversión al esquema `SOP`.

Dos piezas:

1. `extraer_texto` saca el texto del archivo, sin LLM:
   - Markdown y TXT: UTF-8 (con o sin BOM), tal cual.
   - PDF (pdfplumber): página por página, en orden de lectura. Las líneas que se partieron por
     el ancho de la página se vuelven a unir; las tablas se cambian por líneas legibles en el
     lugar donde estaban (`lineas_tabla`). Un PDF sin texto (escaneado) es un error: el OCR es
     la propuesta PR-10, fuera de alcance.
   - Word (python-docx): el cuerpo en orden de documento, párrafos y tablas intercalados. Los
     estilos de encabezado se vuelven "#", "##"…, y las listas de Word llevan su viñeta o su
     número ("- ", "1. "), que en el XML no vienen como texto.
2. `convertir_documento` convierte el texto en dos caminos (ADR-015), igual para los cuatro
   formatos:
   a) `convertir_sop` (plantilla y código). Si no falla y no ignoró texto, ese es el resultado:
      un Word que sigue la plantilla sale igual que un .md (`metodo="plantilla"`). Un .md o .txt
      que no la sigue ya no es un error: pasa al camino b.
   b) Si no, Gemma 4 (`convertir_con_llm`): prompt versionado `prompts/<PROMPT>.md`, salida
      restringida a `ESQUEMA_SOP_LIBRE`, temperatura 0 y `SEMILLA` (las fija el cliente), hasta
      `MAX_INTENTOS` como el juez. Cada paso trae `cita_origen`, un fragmento del documento
      (`PALABRAS_CITA_ORIGEN`); el código la verifica con `contiene_cita` y, si no aparece, deja
      la advertencia `paso_sin_evidencia` (el nombre queda libre: puede resumir). El código
      numera los pasos, pone `fuente="documento"` y hereda el responsable del resumen como
      `convertir_sop`. El LLM no ve ni escribe tiempos del video (regla 4): un SOP cargado no
      los tiene.

Si Ollama no responde, `convertir_documento` lanza `LLMNoDisponible` antes de convertir nada
(la API responde 503, ADR-019). Los errores, las advertencias y el log citan números de paso o
de página, tipos de error y conteos; nunca texto del documento (puede ser material del cliente).
"""

import io
import logging
import math
import re
import statistics
import time
import zipfile
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Literal

import docx
import pdfplumber
from docx.document import Document as DocumentoWord
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sopvid.contrato import SOP, Confianza, Dato, Elemento, Falla, PasoSOP, Resumen, Riesgo
from sopvid.lenguaje.juez import Prompt, RespuestaInvalida, leer_prompt, texto_del_prompt
from sopvid.lenguaje.llm import (
    ClienteLLM,
    LLMNoDisponible,
    LLMRespuestaInvalida,
    LLMTiempoExcedido,
)
from sopvid.lenguaje.sop_markdown import (
    ErrorSOP,
    ResultadoConversion,
    _Avisos,
    _revisar_tiempos,
    convertir_sop,
    empieza_con_infinitivo,
)
from sopvid.percepcion.segmentacion import _sin_refs
from sopvid.plataforma.config import Settings
from sopvid.texto import (
    NO_IDENTIFICADO,
    comparable,
    contar_palabras,
    contiene_cita,
    limpiar,
    recortar_palabras,
)

logger = logging.getLogger(__name__)

EXTENSIONES_TEXTO = (".md", ".txt")
EXTENSIONES_DOCUMENTO = (".pdf", ".docx")
EXTENSIONES = EXTENSIONES_TEXTO + EXTENSIONES_DOCUMENTO

MENSAJE_UTF8 = "el archivo debe estar en UTF-8"
MENSAJE_ESCANEADO = (
    "El PDF no tiene texto seleccionable; parece escaneado. Súbelo en Word, TXT o Markdown."
)
MENSAJE_PDF_ILEGIBLE = "El PDF está dañado o protegido y no se pudo leer."
MENSAJE_WORD_ILEGIBLE = (
    "El archivo de Word está dañado o no es un .docx (los .doc antiguos no se leen; guárdalo "
    "como .docx)."
)
MENSAJE_WORD_VACIO = "El archivo de Word no tiene texto."
# Un .docx es un zip: más de esto descomprimido se rechaza sin abrirlo (zip bomb).
MAX_DESCOMPRIMIDO = 200 * 1024 * 1024

PROMPT = "sop_texto_libre_v3"  # archivo en prompts/; un prompt nuevo es un archivo nuevo
MAX_INTENTOS = 3  # una llamada más dos reintentos si la respuesta no es válida
PALABRAS_CITA_ORIGEN = (4, 25)  # largo de la cita de cada paso; una más larga se recorta
# Estimación del contexto (`contexto_necesario`): ~3.5 caracteres por token en español, y la
# salida JSON repite el documento (cita, descripción) con sus claves: con Gemma 4 y el Word en
# prosa salió 2.8 veces los tokens del texto (1829 por 657, docs/adr/datos/sop/prosa-v2-…).
CARACTERES_POR_TOKEN = 3.5
SALIDA_POR_TOKEN_DE_TEXTO = 3.0
SALIDA_FIJA = 512  # título, resumen y claves del JSON aunque el texto sea corto
MENSAJE_DEMASIADO_LARGO = (
    "El documento es demasiado largo; divídelo o usa la plantilla (docs/contrato/plantilla_sop.md)."
)
# Advertencias de `convertir_sop` que dicen que se ignoró texto: con alguna, la plantilla no
# se reconoció del todo y el documento pasa al LLM para no perder pasos.
_TEXTO_IGNORADO = frozenset({"clave_desconocida", "seccion_desconocida"})


class ErrorLectura(ValueError):  # noqa: N818 (nombre de dominio)
    """No se pudo sacar texto del archivo. El mensaje es para el usuario y no cita el archivo."""


class ErrorConversionLLM(ValueError):  # noqa: N818
    """El LLM respondió, pero ninguna de sus `MAX_INTENTOS` respuestas fue un SOP válido."""


class DocumentoDemasiadoLargo(ErrorConversionLLM):
    """El documento no cabe en la ventana de contexto más grande permitida; no se llama al LLM."""


# ── Extracción de texto ──────────────────────────────────────────────────────────────────────


def extraer_texto(datos: bytes, extension: str) -> str:
    """Texto del SOP según su extensión (".md", ".txt", ".pdf" o ".docx", sin distinguir
    mayúsculas). Lanza `ErrorLectura` si el archivo no se puede leer o no trae texto."""
    extension = extension.lower()
    if extension in EXTENSIONES_TEXTO:
        try:
            return datos.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ErrorLectura(MENSAJE_UTF8) from None
    if extension == ".pdf":
        return _texto_pdf(datos)
    if extension == ".docx":
        return _texto_docx(datos)
    raise ValueError(f"extensión no soportada: {extension!r}")


def lineas_tabla(filas: Sequence[Sequence[str | None]]) -> list[str]:
    """Una tabla como líneas legibles, una por fila, sin filas vacías.

    - Dos columnas: "clave: valor" (tablas de datos como "Objetivo | …" o "1 | Cerrar…").
    - Tres o más con la primera fila completa (encabezado): "Encabezado: valor | …" por fila,
      sin las celdas vacías. Así cada fila de una tabla de pasos se lee sola.
    - Si no: las celdas no vacías separadas por " | ".
    """
    limpias = [[" ".join((c or "").split()) for c in fila] for fila in filas]
    limpias = [f for f in limpias if any(f)]
    if not limpias:
        return []
    if all(len(f) == 2 for f in limpias):
        return [f"{a}: {b}" if a and b else a or b for a, b in limpias]
    encabezado = limpias[0]
    if len(limpias) > 1 and len(encabezado) >= 3 and all(encabezado):
        return [
            " | ".join(f"{h}: {v}" for h, v in zip(encabezado, fila, strict=False) if v)
            for fila in limpias[1:]
        ]
    return [" | ".join(c for c in fila if c) for fila in limpias]


# ── PDF ──────────────────────────────────────────────────────────────────────────────────────

# Una línea que abre algo (viñeta, número, encabezado) nunca continúa a la anterior.
_ABRE_LINEA = re.compile(r"(?:[-*+•▪◦]\s|\d+[.):]\s|#|paso\s+\d)", re.IGNORECASE)


def _texto_pdf(datos: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(datos)) as pdf:
            paginas = [_texto_pagina(p) for p in pdf.pages]
    except Exception as exc:  # pdfminer lanza de todo con un PDF roto o cifrado
        logger.info("PDF ilegible (%s)", type(exc).__name__)
        raise ErrorLectura(MENSAJE_PDF_ILEGIBLE) from None
    texto = "\n\n".join(p for p in paginas if p.strip())
    if not texto.strip():
        raise ErrorLectura(MENSAJE_ESCANEADO)
    logger.info("PDF leído: %d páginas, %d con texto", len(paginas), sum(map(bool, paginas)))
    return texto


def _texto_pagina(pagina: Any) -> str:
    """Bloques de la página (párrafos y tablas) ordenados de arriba abajo."""
    tablas = pagina.find_tables()
    cajas = [t.bbox for t in tablas]
    lineas = [
        linea
        for linea in pagina.extract_text_lines(strip=True)
        if linea["text"].strip() and not any(_dentro(linea, caja) for caja in cajas)
    ]
    bloques: list[tuple[float, list[str]]] = [
        (linea["top"], [texto]) for linea, texto in _unir_lineas_partidas(lineas)
    ]
    bloques += [(t.bbox[1], lineas_tabla(t.extract())) for t in tablas]
    bloques.sort(key=lambda b: b[0])
    return "\n".join(texto for _, textos in bloques for texto in textos)


def _dentro(linea: dict[str, Any], caja: tuple[float, float, float, float]) -> bool:
    x0, arriba, x1, abajo = caja
    cx = (linea["x0"] + linea["x1"]) / 2
    cy = (linea["top"] + linea["bottom"]) / 2
    return x0 <= cx <= x1 and arriba <= cy <= abajo


def _unir_lineas_partidas(lineas: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """Une cada línea que el PDF partió por el ancho de la página con la que sigue.

    Una línea continúa a la anterior si la anterior llega casi al margen derecho del texto, la
    separación vertical es menor que media línea y la nueva no abre una viñeta, un número o un
    encabezado. Devuelve (primera línea del párrafo, texto unido).
    """
    if not lineas:
        return []
    derecha = max(linea["x1"] for linea in lineas)
    izquierda = min(linea["x0"] for linea in lineas)
    holgura = 0.12 * (derecha - izquierda)
    alto = statistics.median(linea["bottom"] - linea["top"] for linea in lineas)
    unidas: list[tuple[dict[str, Any], str]] = []
    previa: dict[str, Any] | None = None
    for linea in lineas:
        texto = linea["text"].strip()
        continua = (
            previa is not None
            and previa["x1"] >= derecha - holgura
            and 0 <= linea["top"] - previa["bottom"] < 0.5 * alto
            and not _ABRE_LINEA.match(texto)
            and not unidas[-1][1].endswith(":")
        )
        if continua:
            primera, anterior = unidas[-1]
            unidas[-1] = (primera, f"{anterior} {texto}")
        else:
            unidas.append((linea, texto))
        previa = linea
    return unidas


# ── Word ─────────────────────────────────────────────────────────────────────────────────────

_ESTILO_ENCABEZADO = re.compile(r"(?:heading|t[ií]tulo|encabezado)\s*([1-9])", re.IGNORECASE)
_ESTILO_TITULO = frozenset({"title", "título", "titulo"})
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


@cache
def _xpath(expresion: str) -> etree.XPath:
    return etree.XPath(expresion, namespaces=_NS)


def _xp(elemento: Any, expresion: str, **variables: str) -> list[str]:
    """Valores de `expresion` (con el prefijo w:) en `elemento`; los `$nombre` van como
    variables de XPath, nunca pegados al texto de la expresión."""
    return [str(x) for x in _xpath(expresion)(elemento, **variables)]


def _texto_docx(datos: bytes) -> str:
    try:
        _revisar_zip(datos)
        lineas = _lineas_docx(docx.Document(io.BytesIO(datos)))
    except ErrorLectura:
        raise
    except Exception as exc:  # zip roto, XML roto, tipo de contenido que no es .docx…
        logger.info("Word ilegible (%s)", type(exc).__name__)
        raise ErrorLectura(MENSAJE_WORD_ILEGIBLE) from None
    texto = "\n".join(lineas)
    if not texto.strip():
        raise ErrorLectura(MENSAJE_WORD_VACIO)
    logger.info("Word leído: %d líneas", len(lineas))
    return texto


def _revisar_zip(datos: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPRIMIDO:
            raise ErrorLectura(MENSAJE_WORD_ILEGIBLE)


def _lineas_docx(documento: DocumentoWord) -> list[str]:
    """El cuerpo en orden de documento: `iter_inner_content` intercala párrafos y tablas (no
    solo `paragraphs`). Encabezados, pies y cuadros de texto no se leen."""
    numeracion = _Numeracion(documento)
    lineas: list[str] = []
    for bloque in documento.iter_inner_content():
        if isinstance(bloque, Table):
            lineas += lineas_tabla(_filas_docx(bloque))
        elif linea := _linea_parrafo(bloque, numeracion):
            lineas.append(linea)
    return lineas


def _linea_parrafo(parrafo: Paragraph, numeracion: "_Numeracion") -> str:
    texto = parrafo.text.strip()
    if not texto:
        return ""
    prefijo = numeracion.prefijo(parrafo)
    nivel = _nivel_encabezado(parrafo)
    if nivel is not None:
        return " ".join(x for x in ("#" * nivel, prefijo.strip(), texto) if x)
    return f"{prefijo}{texto}"


def _nivel_encabezado(parrafo: Paragraph) -> int | None:
    """1 para el título y "Heading 1"; n para "Heading n" (o "Título n" en Word en español)."""
    nombre = (parrafo.style.name if parrafo.style is not None else "") or ""
    if nombre.strip().lower() in _ESTILO_TITULO:
        return 1
    if m := _ESTILO_ENCABEZADO.fullmatch(nombre.strip()):
        return int(m.group(1))
    nivel = _xp(parrafo._p, "./w:pPr/w:outlineLvl/@w:val")
    if nivel and nivel[0].isdigit() and int(nivel[0]) < 9:
        return int(nivel[0]) + 1
    return None


def _filas_docx(tabla: Table) -> list[list[str]]:
    """Texto de cada fila; una celda combinada (que python-docx repite) cuenta una vez."""
    filas = []
    for fila in tabla.rows:
        celdas: list[str] = []
        previa = None
        for celda in fila.cells:
            if celda._tc is not previa:
                celdas.append(celda.text)
            previa = celda._tc
        filas.append(celdas)
    return filas


@dataclass
class _Numeracion:
    """Viñetas y números de las listas de Word, que el XML guarda como formato, no como texto.

    Cada párrafo de lista apunta a una numeración (`numId`) y un nivel (`ilvl`), en el párrafo o
    en su estilo ("List Number"). Los contadores van por `numId`, como en Word: una lista sigue
    contando aunque haya párrafos en medio, y al subir de nivel se reinician los de abajo.
    """

    documento: DocumentoWord
    _contadores: dict[str, list[int]] = field(default_factory=dict)
    _numeracion: Any = None

    def __post_init__(self) -> None:
        try:
            self._numeracion = self.documento.part.numbering_part.element
        except (KeyError, NotImplementedError):
            self._numeracion = None

    def prefijo(self, parrafo: Paragraph) -> str:
        """ "- " para una viñeta, "n. " para un número (con sangría por nivel) o ""."""
        num_id, nivel = self._num_pr(parrafo)
        if num_id is None or num_id == "0" or self._numeracion is None:
            return ""
        formato, inicio = self._formato(num_id, nivel)
        sangria = "  " * nivel
        if formato == "bullet":
            return f"{sangria}- "
        if formato == "none":
            return ""
        contadores = self._contadores.setdefault(num_id, [0] * 9)
        if contadores[nivel] == 0:
            contadores[nivel] = inicio - 1
        contadores[nivel] += 1
        for abajo in range(nivel + 1, 9):
            contadores[abajo] = 0
        return f"{sangria}{contadores[nivel]}. "

    def _num_pr(self, parrafo: Paragraph) -> tuple[str | None, int]:
        num_id = _xp(parrafo._p, "./w:pPr/w:numPr/w:numId/@w:val")
        nivel = _xp(parrafo._p, "./w:pPr/w:numPr/w:ilvl/@w:val")
        estilo = parrafo.style
        while not num_id and estilo is not None:
            num_id = _xp(estilo.element, "./w:pPr/w:numPr/w:numId/@w:val")
            nivel = nivel or _xp(estilo.element, "./w:pPr/w:numPr/w:ilvl/@w:val")
            estilo = estilo.base_style
        n = int(nivel[0]) if nivel and nivel[0].isdigit() else 0
        return (num_id[0] if num_id else None), min(max(n, 0), 8)

    def _formato(self, num_id: str, nivel: int) -> tuple[str, int]:
        """(numFmt, inicio) del nivel; "decimal" y 1 si la numeración no lo dice."""
        abstracto = _xp(
            self._numeracion, "./w:num[@w:numId=$num]/w:abstractNumId/@w:val", num=num_id
        )
        if not abstracto:
            return "decimal", 1
        lvl = _xpath("./w:abstractNum[@w:abstractNumId=$abs]/w:lvl[@w:ilvl=$nivel]")(
            self._numeracion, abs=abstracto[0], nivel=str(nivel)
        )
        if not lvl:
            return "decimal", 1
        formato = _xp(lvl[0], "./w:numFmt/@w:val")
        inicio = _xp(lvl[0], "./w:start/@w:val")
        return (
            formato[0] if formato else "decimal",
            int(inicio[0]) if inicio and inicio[0].isdigit() else 1,
        )


# ── Conversión en dos caminos ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AjustesConversion:
    """Plazos y ventanas de la conversión con el LLM (variables LLM_* de `Settings`)."""

    plazo_s: float = 2.0  # revisar que Ollama responda (LLM_HEALTH_TIMEOUT_S)
    num_ctx: int = 8192  # ventana del cliente (LLM_NUM_CTX)
    num_ctx_max: int = 16384  # ventana para documentos largos (LLM_NUM_CTX_SOP)
    inactividad_s: float = 60.0  # sin un token nuevo (LLM_INACTIVIDAD_S)
    tope_s: float = 900.0  # toda la conversión, con sus reintentos (LLM_TIMEOUT_SOP_S)

    @classmethod
    def desde_settings(cls, s: Settings) -> "AjustesConversion":
        return cls(
            plazo_s=s.llm_health_timeout_s,
            num_ctx=s.llm_num_ctx,
            num_ctx_max=s.llm_num_ctx_sop,
            inactividad_s=s.llm_inactividad_s,
            tope_s=s.llm_timeout_sop_s,
        )


def convertir_documento(
    texto: str,
    fabrica_llm: Callable[[], AbstractContextManager[ClienteLLM]],
    *,
    ajustes: AjustesConversion | None = None,
    candado: Callable[[], AbstractContextManager[object]] = nullcontext,
) -> ResultadoConversion:
    """Convierte el texto del SOP (de cualquier formato): plantilla primero, Gemma 4 si no
    (ADR-015).

    Solo el camino del LLM toma `candado` (el de modelo pesado, ADR-014; puede lanzar si no se
    libera a tiempo) y crea el cliente (`fabrica_llm` da un context manager: un `ClienteLLM`, o
    `nullcontext(cliente)` para uno que no se debe cerrar). Antes de convertir se revisa que
    Ollama responda y tenga el modelo (`ajustes.plazo_s`); si no, `LLMNoDisponible` sin haber
    hecho nada.
    Al terminar, con o sin error, se le pide a Ollama que suelte el modelo (ADR-014, ADR-019).
    Lanza `LLMError` si Ollama se cae durante la conversión, `LLMTiempoExcedido` si pasa de
    `ajustes.tope_s` y `ErrorConversionLLM` si no logró una respuesta válida.

    Contexto: si `contexto_necesario` pasa de `num_ctx` (la ventana del cliente, `LLM_NUM_CTX`),
    cada petición pide `num_ctx_max` (`LLM_NUM_CTX_SOP`); si tampoco cabe,
    `DocumentoDemasiadoLargo` antes de tomar el candado o llamar al LLM.
    """
    try:
        resultado = convertir_sop(texto)
    except ErrorSOP as exc:
        logger.info("SOP sin plantilla (%s); se convierte con el LLM", type(exc).__name__)
    else:
        ignorado = sum(a.tipo in _TEXTO_IGNORADO for a in resultado.advertencias)
        if not ignorado:
            return resultado
        logger.info("La plantilla ignoró %d bloques de texto; se convierte con el LLM", ignorado)

    ajustes = ajustes or AjustesConversion()
    prompt = cargar_prompt()
    necesario = contexto_necesario(texto, prompt)
    if necesario > ajustes.num_ctx_max:
        logger.info("Documento de ~%d tokens: no cabe en %d", necesario, ajustes.num_ctx_max)
        raise DocumentoDemasiadoLargo(MENSAJE_DEMASIADO_LARGO)
    ventana = ajustes.num_ctx_max if necesario > ajustes.num_ctx else None
    if ventana is not None:
        logger.info("Documento de ~%d tokens: se pide num_ctx=%d", necesario, ventana)

    with candado(), fabrica_llm() as llm:
        if not llm.disponible(ajustes.plazo_s):
            raise LLMNoDisponible("Ollama no responde o no tiene el modelo")
        try:
            return convertir_con_llm(
                texto,
                llm,
                prompt,
                num_ctx=ventana,
                inactividad_s=ajustes.inactividad_s,
                tope_s=ajustes.tope_s,
            )
        finally:
            llm.descargar()


# ── Respuesta del LLM ────────────────────────────────────────────────────────────────────────

# Esquema recortado (v3): fuera lo que el código ya pone o casi siempre salía vacío. Con v2,
# en los dos documentos de prueba la confianza de cada paso y de cada dato salió siempre "alta",
# `campos_inferidos` siempre vacío y `equipo_operacion` repetía, sin descripción, el equipo de
# los pasos. Ahora la confianza sale de la evidencia (`_paso`, `_dato`) y el equipo de operación
# es la unión del de los pasos (`_equipo_operacion`).


class _Libre(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ElementoLibre(_Libre):
    nombre: str
    descripcion: str


class _RiesgoLibre(_Libre):
    descripcion: str
    nivel: Literal["alto", "medio", "bajo"] | None
    paso: int | None
    control: str


class _FallaLibre(_Libre):
    situacion: str
    accion: str


class _ResumenLibre(_Libre):
    objetivo: str | None
    alcance: str | None
    responsable: str | None
    lugar: str | None
    horario_frecuencia: str | None
    duracion_total_min: float | None = Field(ge=0)
    roles: list[_ElementoLibre]
    riesgos: list[_RiesgoLibre]
    en_caso_de_falla: list[_FallaLibre]


class _PasoLibre(_Libre):
    # La cita va primero: el nombre y la descripción se apoyan en ella.
    cita_origen: str
    nombre: str
    descripcion: str
    responsable: str | None
    equipo: list[str]
    puntos_validacion: list[str]
    tiempo_esperado_min: float | None = Field(ge=0)


# Lo que devuelve el LLM: el SOP del contrato sin lo que pone el código (números de paso, fuente,
# versión) ni lo que un SOP cargado no tiene (tiempos del video, personas, puntos y palabras
# clave). Sin docstrings en estos modelos: Pydantic los pondría en el esquema que va a Ollama.
class _SOPLibre(_Libre):
    titulo: str
    resumen: _ResumenLibre
    pasos: list[_PasoLibre]


ESQUEMA_SOP_LIBRE: dict[str, Any] = _sin_refs(_SOPLibre.model_json_schema())
_MARCADORES = {
    "sistema": frozenset(),
    "usuario": frozenset({"texto"}),
    "correccion": frozenset({"motivo"}),
}
_RANGO_CONFIANZA: dict[Confianza, int] = {"baja": 0, "media": 1, "alta": 2}


@cache
def cargar_prompt(version: str = PROMPT) -> Prompt:
    """Lee `prompts/<version>.md` del paquete, con las secciones del juez y sus marcadores."""
    return leer_prompt(version, texto_del_prompt(version), _MARCADORES)


def estimar_tokens(texto: str) -> int:
    """Tokens aproximados de `texto` (`CARACTERES_POR_TOKEN`); basta para elegir la ventana."""
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


def contexto_necesario(texto: str, prompt: Prompt) -> int:
    """Tokens que necesita la conversión más larga: los mensajes con el documento, la salida
    estimada y una corrección (cada reintento manda solo la última, sin respuestas anteriores)."""
    mensajes = sum(estimar_tokens(m["content"]) for m in construir_mensajes(prompt, texto))
    salida = math.ceil(SALIDA_POR_TOKEN_DE_TEXTO * estimar_tokens(texto)) + SALIDA_FIJA
    correccion = estimar_tokens(prompt.correccion.template) + 50  # el motivo
    return mensajes + salida + correccion


def construir_mensajes(prompt: Prompt, texto: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": prompt.sistema},
        {"role": "user", "content": prompt.usuario.substitute(texto=texto.strip())},
    ]


def convertir_con_llm(
    texto: str,
    llm: ClienteLLM,
    prompt: Prompt | None = None,
    *,
    num_ctx: int | None = None,
    inactividad_s: float = 60.0,
    tope_s: float = 900.0,
) -> ResultadoConversion:
    """Convierte con el LLM, con hasta `MAX_INTENTOS` llamadas (con `num_ctx` si se da).

    Cada llamada va en flujo (`ClienteLLM.chat_en_flujo`): corta tras `inactividad_s` sin un
    token, y `tope_s` vale para toda la conversión (cada intento recibe lo que queda). Un corte
    por tiempo no se reintenta: `LLMTiempoExcedido` ("La conversión pasó de N s") o
    `LLMNoDisponible`.

    Se reintenta si el modelo no devolvió JSON válido o si la respuesta no pasa
    `validar_respuesta`: cada reintento manda los mensajes iniciales y solo la corrección con el
    último motivo, sin la respuesta anterior (puede ser tan larga como el documento y no cabría
    en el contexto). Un `LLMError` de transporte o de Ollama sale tal cual (el cliente ya
    reintentó). Sin respuesta válida, `ErrorConversionLLM`.
    """
    prompt = prompt or cargar_prompt()
    base = construir_mensajes(prompt, texto)
    historial = list(base)
    inicio = time.monotonic()
    for intento in range(1, MAX_INTENTOS + 1):
        restante = tope_s - (time.monotonic() - inicio)
        try:
            if restante <= 0:
                raise LLMTiempoExcedido("sin tiempo para otro intento")
            respuesta = llm.chat_en_flujo(
                historial,
                esquema=ESQUEMA_SOP_LIBRE,
                num_ctx=num_ctx,
                inactividad_s=inactividad_s,
                tope_s=restante,
            )
        except LLMTiempoExcedido:
            logger.warning("SOP con el LLM: pasó de %g s (intento %d)", tope_s, intento)
            raise LLMTiempoExcedido(
                f"La conversión pasó de {tope_s:g} s; súbelo con la plantilla o en partes."
            ) from None
        except LLMRespuestaInvalida:
            motivo = "no devolviste un JSON válido"
        else:
            try:
                resultado = validar_respuesta(respuesta.datos, texto)
            except RespuestaInvalida as exc:
                motivo = str(exc)
            else:
                logger.info(
                    "SOP convertido con el LLM (%s, intento %d): %d pasos, %d advertencias",
                    prompt.version,
                    intento,
                    len(resultado.sop.pasos),
                    len(resultado.advertencias),
                )
                return resultado
        logger.warning(
            "SOP con el LLM: respuesta inválida (intento %d de %d): %s",
            intento,
            MAX_INTENTOS,
            motivo,
        )
        correccion = prompt.correccion.substitute(motivo=motivo)
        historial = [*base, {"role": "user", "content": correccion}]
    raise ErrorConversionLLM(
        f"El LLM no logró convertir el documento en {MAX_INTENTOS} intentos. Súbelo con la "
        "plantilla (docs/contrato/plantilla_sop.md) o en Markdown."
    )


def validar_respuesta(datos: Any, texto: str) -> ResultadoConversion:
    """Valida la respuesta del LLM y arma el `SOP` (`metodo="llm"`).

    Inválida (se reintenta) si no cumple el esquema, si el título está vacío o si no hay pasos
    o uno no tiene nombre. Lo demás se corrige y queda en las advertencias: un paso sin evidencia
    (`cita_origen` que no aparece en `texto` o con menos de `PALABRAS_CITA_ORIGEN[0]` palabras),
    un nombre que no empieza con un infinitivo, un riesgo sin nivel o que cita un paso que no
    existe, y tiempos que no suman la duración total. La cita no viaja en el `SOP`.
    """
    try:
        r = _SOPLibre.model_validate(datos)
    except ValidationError as exc:
        raise RespuestaInvalida(_resumen_errores(exc)) from None
    titulo = " ".join(r.titulo.split())
    if not titulo:
        raise RespuestaInvalida("el título está vacío")
    if not r.pasos:
        raise RespuestaInvalida("no hay pasos")
    for n, p in enumerate(r.pasos, start=1):
        if not p.nombre.strip():
            raise RespuestaInvalida(f"el paso {n} no tiene nombre")

    avisos = _Avisos()
    resumen = _resumen(r.resumen, r.pasos, texto, avisos)
    evidencia = [cita_verificada(p.cita_origen, texto) for p in r.pasos]
    pasos = [
        _paso(n, p, resumen.responsable.valor, con_evidencia)
        for n, (p, con_evidencia) in enumerate(zip(r.pasos, evidencia, strict=True), start=1)
    ]
    for paso, con_evidencia in zip(pasos, evidencia, strict=True):
        if not con_evidencia:
            avisos.agregar(
                "paso_sin_evidencia",
                None,
                f"la cita del paso {paso.numero} no aparece tal cual en el documento; revísalo",
            )
        if not empieza_con_infinitivo(paso.nombre):
            avisos.agregar(
                "infinitivo", None, f"el nombre del paso {paso.numero} no empieza con un infinitivo"
            )
    _revisar_tiempos(pasos, resumen.duracion_total_min, avisos)
    sop = SOP(titulo=titulo, resumen=resumen, pasos=pasos)
    return ResultadoConversion(sop, list(avisos), metodo="llm")


def cita_verificada(cita: str, texto: str) -> bool:
    """True si la cita, recortada a `PALABRAS_CITA_ORIGEN[1]` palabras (el recorte de una cita
    literal sigue siendo literal), tiene al menos `PALABRAS_CITA_ORIGEN[0]` (o todo el texto, si
    es más corto) y aparece tal cual en `texto`, normalizada (`contiene_cita`)."""
    minimo, maximo = PALABRAS_CITA_ORIGEN
    recortada = recortar_palabras(" ".join(cita.split()), maximo)
    if contar_palabras(recortada) < min(minimo, contar_palabras(texto)):
        return False
    return contiene_cita(texto, recortada)


def _resumen_errores(exc: ValidationError) -> str:
    """Campos y tipos de error de Pydantic, sin los valores (podrían traer texto del SOP)."""
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'respuesta'}: {e['type']}" for e in exc.errors()
    )


# Lo que el modelo escribe a veces en lugar de dejar el campo vacío (con el JSON compacto de v3
# salía ["null"] en listas vacías) se trata como vacío (`sopvid.texto.VACIOS`).
_limpio = limpiar


def _lista(elementos: Iterable[str]) -> list[str]:
    return [e for x in elementos if (e := _limpio(x))]


def _dato(valor: str | None, texto: str) -> Dato:
    """Dato del resumen: "alta" si está tal cual en el documento, "media" si el modelo lo juntó
    o lo resumió. Vacío, sin dato."""
    valor = _limpio(valor)
    if not valor:
        return Dato()
    confianza: Confianza = "alta" if contiene_cita(texto, valor) else "media"
    return Dato(valor=valor, confianza=confianza, fuente="documento")


def _equipo_operacion(pasos: Sequence[_PasoLibre]) -> list[Elemento]:
    """El equipo de todos los pasos, sin repetir (comparado normalizado) y en orden de aparición."""
    vistos: set[str] = set()
    equipo = []
    for p in pasos:
        for nombre in _lista(p.equipo):
            if (clave := comparable(nombre)) not in vistos:
                vistos.add(clave)
                equipo.append(Elemento(nombre=nombre))
    return equipo


def _resumen(r: _ResumenLibre, pasos: Sequence[_PasoLibre], texto: str, avisos: _Avisos) -> Resumen:
    n_pasos = len(pasos)
    riesgos = []
    for i, x in enumerate((x for x in r.riesgos if _limpio(x.descripcion)), start=1):
        nivel = x.nivel
        if nivel is None:
            nivel = "medio"
            avisos.agregar(
                "valor_invalido",
                None,
                f'el riesgo {i} no trae nivel en el documento; quedó "medio"',
            )
        paso = x.paso
        if paso is not None and not 1 <= paso <= n_pasos:
            avisos.agregar(
                "valor_invalido",
                None,
                f"el riesgo {i} cita el paso {paso}, que no existe; quedó vacío",
            )
            paso = None
        riesgos.append(
            Riesgo(
                descripcion=_limpio(x.descripcion),
                nivel=nivel,
                paso=paso,
                control=_limpio(x.control),
            )
        )
    return Resumen(
        objetivo=_dato(r.objetivo, texto),
        alcance=_dato(r.alcance, texto),
        responsable=_dato(r.responsable, texto),
        lugar=_dato(r.lugar, texto),
        horario_frecuencia=_dato(r.horario_frecuencia, texto),
        duracion_total_min=r.duracion_total_min,
        roles=_elementos(r.roles),
        equipo_operacion=_equipo_operacion(pasos),
        riesgos=riesgos,
        en_caso_de_falla=[
            Falla(situacion=_limpio(f.situacion), accion=_limpio(f.accion))
            for f in r.en_caso_de_falla
            if _limpio(f.situacion)
        ],
    )


def _elementos(elementos: Sequence[_ElementoLibre]) -> list[Elemento]:
    return [
        Elemento(nombre=_limpio(e.nombre), descripcion=_limpio(e.descripcion))
        for e in elementos
        if _limpio(e.nombre)
    ]


def _paso(
    numero: int, p: _PasoLibre, responsable_resumen: str | None, con_evidencia: bool
) -> PasoSOP:
    """Confianza "alta" si la cita se verificó y "baja" si no. El responsable que falta se
    hereda del resumen (confianza "media" a lo más) o queda `NO_IDENTIFICADO` ("baja"), igual
    que en `convertir_sop`."""
    inferidos: list[str] = []
    confianza: Confianza = "alta" if con_evidencia else "baja"
    responsable = _limpio(p.responsable)
    if responsable == NO_IDENTIFICADO:
        responsable = ""
    if not responsable and responsable_resumen:
        responsable = responsable_resumen
        inferidos.append("responsable")
        confianza = min(confianza, "media", key=_RANGO_CONFIANZA.__getitem__)
    elif not responsable:
        responsable, confianza = NO_IDENTIFICADO, "baja"
    return PasoSOP(
        numero=numero,
        nombre=_limpio(p.nombre),
        descripcion=_limpio(p.descripcion),
        responsable=responsable,
        equipo=_lista(p.equipo),
        puntos_validacion=_lista(p.puntos_validacion),
        tiempo_esperado_min=p.tiempo_esperado_min,
        confianza=confianza,
        campos_inferidos=inferidos,
    )
