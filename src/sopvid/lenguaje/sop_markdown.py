"""Convierte un SOP de referencia en Markdown o TXT al esquema `SOP` (RF-03), con código y sin LLM.

El texto sigue la plantilla fija de docs/contrato/plantilla_sop.md: "# Título" y "## Pasos" son
obligatorios; resumen, roles, equipo, riesgos y "en caso de falla" son opcionales. En TXT, el
título es la primera línea no vacía y cada sección va sola en su línea ("Pasos:"). Secciones y
claves se comparan sin mayúsculas, acentos ni puntuación, con sinónimos.

Lo que no aparece queda en None o []: nada se inventa. Todo dato leído lleva fuente "documento"
y confianza "alta", salvo el responsable de un paso que no lo trae: se hereda del resumen con
confianza "media" (y "responsable" en `campos_inferidos`) o, si tampoco hay, queda
`NO_IDENTIFICADO` con confianza "baja".

Los errores (`ErrorSOP`) y las advertencias citan números de paso y de línea, nunca texto del SOP
(puede ser material del cliente). El log solo registra conteos.
"""

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from sopvid.contrato import SOP, Confianza, Dato, Elemento, Falla, PasoSOP, Resumen, Riesgo
from sopvid.texto import NO_IDENTIFICADO, normalizar

logger = logging.getLogger(__name__)

TipoAdvertencia = Literal[
    "numeracion",
    "clave_desconocida",
    "seccion_desconocida",
    "tiempos",
    "infinitivo",
    "valor_invalido",
]

TOLERANCIA_TIEMPOS = 0.20  # la suma de los pasos puede alejarse ±20 % de la duración total
_TERMINACIONES_INFINITIVO = ("ar", "er", "ir", "arse", "erse", "irse")
_FORMATO_PASOS = (
    'una sección "## Pasos" (o "Pasos:" en TXT) con subtítulos "### 1. Nombre" o '
    '"### Paso 1: Nombre", o con una lista "1. Nombre"'
)

# Claves ya pasadas por _clave() → nombre interno.
_SECCIONES = {
    "resumen": "resumen",
    "roles": "roles",
    "equipo": "equipo",
    "equipo de operacion": "equipo",
    "riesgos": "riesgos",
    "en caso de falla": "fallas",
    "pasos": "pasos",
    "procedimiento": "pasos",
}
_CLAVES_RESUMEN = {
    "objetivo": "objetivo",
    "alcance": "alcance",
    "responsable": "responsable",
    "lugar": "lugar",
    "horario": "horario_frecuencia",
    "frecuencia": "horario_frecuencia",
    "horario frecuencia": "horario_frecuencia",
    "duracion total": "duracion_total_min",
    "duracion total min": "duracion_total_min",
    "duracion": "duracion_total_min",
    "duracion min": "duracion_total_min",
}
_CLAVES_PASO = {
    "responsable": "responsable",
    "equipo": "equipo",
    "validacion": "puntos_validacion",
    "puntos de validacion": "puntos_validacion",
    "tiempo": "tiempo_esperado_min",
    "tiempo min": "tiempo_esperado_min",
    "duracion": "tiempo_esperado_min",
    "duracion min": "tiempo_esperado_min",
}
_NIVELES = ("alto", "medio", "bajo")

_COMENTARIO = re.compile(r"<!--.*?-->", re.DOTALL)
_TITULO = re.compile(r"#(?!#)(?:\s+(.*))?")
_SECCION_MD = re.compile(r"#{1,2}(?!#)(?:\s+(.*))?")
_SUBTITULO_PASO = re.compile(r"###(?!#)(?:\s+(.*))?")
_NUMERO_SUBTITULO = re.compile(r"(?:paso\s+)?(\d+)(?:\s*[.:)\-–]\s*|\s+|$)(.*)", re.IGNORECASE)
_ITEM_PASO = re.compile(r"(?:paso\s+)?(\d+)\s*[.:)](?:\s+(.*))?", re.IGNORECASE)
_VINETA = re.compile(r"[-*+]\s+(.*)")
_SEPARADOR_LISTA = re.compile(r";|(?<!\d),|,(?!\d)")  # la coma decimal ("0,5") no separa
_MINUTOS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:min|mins|minutos?)?\.?", re.IGNORECASE)
_MARCADOR_RIESGO = re.compile(r"\.?\s*\b(paso|control)\s*:\s*", re.IGNORECASE)
_ENTERO = re.compile(r"\d+")


class ErrorSOP(ValueError):  # noqa: N818 (nombre fijado en la especificación de RF-03)
    """El texto no sigue la plantilla: sin título, sin pasos o con un paso sin nombre."""


@dataclass(frozen=True)
class Advertencia:
    """Aviso que no detiene la conversión. `tipo` es estable para agruparlas (RF-04)."""

    tipo: TipoAdvertencia
    linea: int | None
    mensaje: str

    def __str__(self) -> str:
        donde = f" (línea {self.linea})" if self.linea is not None else ""
        return f"{self.tipo}{donde}: {self.mensaje}"


@dataclass
class ResultadoConversion:
    sop: SOP
    advertencias: list[Advertencia] = field(default_factory=list)


@dataclass
class _Seccion:
    clave: str  # nombre interno, "preambulo" (antes de la primera sección) o "ignorada"
    lineas: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class _PasoLeido:
    linea: int
    numero: int | None
    nombre: str
    descripcion: list[str] = field(default_factory=list)
    responsable: str | None = None
    equipo: list[str] = field(default_factory=list)
    puntos_validacion: list[str] = field(default_factory=list)
    tiempo_esperado_min: float | None = None


@dataclass
class _RiesgoLeido:
    linea: int
    nivel: str
    descripcion: str
    paso: int | None
    control: str


class _Avisos(list[Advertencia]):
    def agregar(self, tipo: TipoAdvertencia, linea: int | None, mensaje: str) -> None:
        self.append(Advertencia(tipo, linea, mensaje))


def convertir_sop(texto: str) -> ResultadoConversion:
    """Convierte el texto de un SOP en Markdown o TXT al esquema `SOP`.

    Lanza `ErrorSOP` si no hay título, no hay pasos o un paso no tiene nombre. Lo demás que no
    sigue la plantilla se ignora o se corrige (renumerar) y queda en `advertencias`.
    """
    avisos = _Avisos()
    titulo, secciones = _dividir(_lineas(texto), avisos)

    datos_resumen: dict[str, Dato | float] = {}
    roles: list[Elemento] = []
    equipo: list[Elemento] = []
    riesgos: list[_RiesgoLeido] = []
    fallas: list[Falla] = []
    lineas_pasos: list[tuple[int, str]] = []
    for s in secciones:
        if s.clave in ("preambulo", "resumen"):
            _leer_resumen(s.lineas, datos_resumen, avisos)
        elif s.clave == "roles":
            roles += _leer_elementos(s.lineas, avisos)
        elif s.clave == "equipo":
            equipo += _leer_elementos(s.lineas, avisos)
        elif s.clave == "riesgos":
            riesgos += _leer_riesgos(s.lineas, avisos)
        elif s.clave == "fallas":
            fallas += _leer_fallas(s.lineas, avisos)
        elif s.clave == "pasos":
            lineas_pasos += s.lineas

    leidos = _leer_pasos(lineas_pasos, avisos)
    if not leidos:
        raise ErrorSOP(f"El SOP no tiene pasos: se espera {_FORMATO_PASOS}.")
    mapa = _renumerar(leidos, avisos)

    resumen = Resumen(
        **datos_resumen,
        roles=roles,
        equipo_operacion=equipo,
        riesgos=[_riesgo(r, mapa, avisos) for r in riesgos],
        en_caso_de_falla=fallas,
    )
    pasos = [_paso(n, p, resumen.responsable.valor) for n, p in enumerate(leidos, start=1)]
    _revisar_tiempos(pasos, resumen.duracion_total_min, avisos)
    _revisar_infinitivos(leidos, avisos)

    sop = SOP(titulo=titulo, resumen=resumen, pasos=pasos)
    advertencias = sorted(avisos, key=lambda a: (a.linea is None, a.linea or 0))
    logger.info("SOP convertido: %d pasos, %d advertencias", len(pasos), len(advertencias))
    return ResultadoConversion(sop, advertencias)


# ── Líneas, título y secciones ───────────────────────────────────────────────────────────────


def _clave(texto: str) -> str:
    """Forma comparable de una sección o clave: sin acentos, mayúsculas ni puntuación."""
    return " ".join(normalizar(texto).split())


def _lineas(texto: str) -> list[tuple[int, str]]:
    """(número de línea, línea sin espacios a los lados), sin BOM, con LF y sin comentarios HTML.

    Los comentarios se cambian por tantos saltos de línea como tenían, para no mover los números.
    """
    texto = texto.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    texto = _COMENTARIO.sub(lambda m: "\n" * m.group().count("\n"), texto)
    return [(n, linea.strip()) for n, linea in enumerate(texto.split("\n"), start=1)]


def _sin_vineta(linea: str) -> str:
    m = _VINETA.fullmatch(linea)
    return m.group(1) if m else linea


def _dividir(lineas: list[tuple[int, str]], avisos: _Avisos) -> tuple[str, list[_Seccion]]:
    """Separa el título y agrupa el resto de las líneas no vacías por sección."""
    markdown = any(_TITULO.fullmatch(linea) for _, linea in lineas)
    titulo: str | None = None
    secciones = [_Seccion("preambulo")]
    for n, linea in lineas:
        if not linea:
            continue
        if titulo is None:
            if markdown:
                m = _TITULO.fullmatch(linea)
                if m is None:
                    avisos.agregar("clave_desconocida", n, "texto antes del título; se ignoró")
                    continue
                titulo = (m.group(1) or "").strip()
            elif not _abre_algo(linea, markdown):
                titulo = linea
            if not titulo:
                break
            continue

        nombre = _nombre_de_seccion(linea, markdown)
        if nombre is None:
            secciones[-1].lineas.append((n, linea))
            continue
        clave = _SECCIONES.get(_clave(nombre))
        if clave is None:
            avisos.agregar("seccion_desconocida", n, "sección desconocida; se ignoró su contenido")
        secciones.append(_Seccion(clave or "ignorada"))

    if not titulo:
        raise ErrorSOP(
            'El SOP no tiene título: la primera línea debe ser "# Título" en Markdown, '
            "o el título solo en TXT."
        )
    return titulo, secciones


def _abre_algo(linea: str, markdown: bool) -> bool:
    """True si la línea abre una sección, un paso o una viñeta: no puede ser el título en TXT."""
    return bool(
        _nombre_de_seccion(linea, markdown) is not None
        or _ITEM_PASO.fullmatch(linea)
        or _VINETA.fullmatch(linea)
    )


def _nombre_de_seccion(linea: str, markdown: bool) -> str | None:
    """Nombre de la sección si la línea la abre: "## Nombre" o, en TXT, "Nombre:" conocido."""
    if m := _SECCION_MD.fullmatch(linea):
        return m.group(1) or ""
    if markdown or not linea.endswith(":") or _VINETA.fullmatch(linea):
        return None
    nombre = linea[:-1]
    return nombre if _clave(nombre) in _SECCIONES else None


# ── Resumen, roles, equipo, riesgos y fallas ─────────────────────────────────────────────────


def _leer_resumen(
    lineas: Sequence[tuple[int, str]], datos: dict[str, Dato | float], avisos: _Avisos
) -> None:
    for n, linea in lineas:
        clave, separador, valor = _sin_vineta(linea).partition(":")
        campo = _CLAVES_RESUMEN.get(_clave(clave)) if separador else None
        if campo is None:
            avisos.agregar("clave_desconocida", n, "clave desconocida en el resumen; se ignoró")
            continue
        valor = valor.strip()
        if not valor:
            continue
        if campo == "duracion_total_min":
            minutos = _minutos(valor, n, avisos, "la duración total")
            if minutos is not None:
                datos[campo] = minutos
        else:
            datos[campo] = Dato(valor=valor, confianza="alta", fuente="documento")


def _leer_elementos(lineas: Sequence[tuple[int, str]], avisos: _Avisos) -> list[Elemento]:
    elementos = []
    for n, linea in lineas:
        nombre, _, descripcion = _sin_vineta(linea).partition(":")
        if not nombre.strip():
            avisos.agregar("valor_invalido", n, "elemento sin nombre; se ignoró")
            continue
        elementos.append(Elemento(nombre=nombre.strip(), descripcion=descripcion.strip()))
    return elementos


def _leer_riesgos(lineas: Sequence[tuple[int, str]], avisos: _Avisos) -> list[_RiesgoLeido]:
    riesgos = []
    for n, linea in lineas:
        nivel, separador, resto = _sin_vineta(linea).partition(":")
        nivel = _clave(nivel)
        if not separador or nivel not in _NIVELES:
            avisos.agregar(
                "valor_invalido", n, "el nivel del riesgo debe ser Alto, Medio o Bajo; se ignoró"
            )
            continue
        partes = _MARCADOR_RIESGO.split(resto)
        paso: int | None = None
        control = ""
        for marcador, valor in zip(partes[1::2], partes[2::2], strict=True):
            valor = valor.strip()
            if not valor:
                continue
            if marcador.lower() == "control":
                control = valor
            elif _ENTERO.fullmatch(valor.rstrip(". ")):
                paso = int(valor.rstrip(". "))
            else:
                avisos.agregar(
                    "valor_invalido", n, "el paso del riesgo no es un número; quedó vacío"
                )
        riesgos.append(_RiesgoLeido(n, nivel, partes[0].strip(), paso, control))
    return riesgos


def _leer_fallas(lineas: Sequence[tuple[int, str]], avisos: _Avisos) -> list[Falla]:
    fallas = []
    for n, linea in lineas:
        situacion, separador, accion = _sin_vineta(linea).partition(":")
        if not situacion.strip():
            avisos.agregar("valor_invalido", n, "falla sin situación; se ignoró")
            continue
        if not separador:
            avisos.agregar("valor_invalido", n, 'falla sin "Situación: acción"; quedó sin acción')
        fallas.append(Falla(situacion=situacion.strip(), accion=accion.strip()))
    return fallas


def _riesgo(r: _RiesgoLeido, mapa: dict[int, int], avisos: _Avisos) -> Riesgo:
    """Traduce el paso citado al número nuevo; si no existe o está repetido, lo conserva."""
    paso = r.paso
    if paso is not None:
        if paso in mapa:
            paso = mapa[paso]
        else:
            avisos.agregar(
                "valor_invalido",
                r.linea,
                f"el riesgo cita el paso {paso}, que no existe o está repetido; se conservó",
            )
    return Riesgo(descripcion=r.descripcion, nivel=r.nivel, paso=paso, control=r.control)


# ── Pasos ────────────────────────────────────────────────────────────────────────────────────


def _leer_pasos(lineas: Sequence[tuple[int, str]], avisos: _Avisos) -> list[_PasoLeido]:
    """Pasos con subtítulos "### …" o, si no hay ninguno, como lista numerada "1. …"."""
    con_subtitulos = any(_SUBTITULO_PASO.fullmatch(linea) for _, linea in lineas)
    pasos: list[_PasoLeido] = []
    for n, linea in lineas:
        inicio = _inicio_de_paso(linea, con_subtitulos)
        if inicio is not None:
            numero, nombre = inicio
            if not nombre:
                k = len(pasos) + 1
                raise ErrorSOP(
                    f"El paso {k} (línea {n}) no tiene nombre: se espera "
                    f'"### {k}. Nombre", "### Paso {k}: Nombre" o "{k}. Nombre".'
                )
            pasos.append(_PasoLeido(n, numero, nombre))
            continue
        if not pasos:
            avisos.agregar(
                "clave_desconocida",
                n,
                "texto en la sección de pasos antes del primer paso; se ignoró",
            )
            continue

        paso = pasos[-1]
        m = _VINETA.fullmatch(linea)
        if m is None or ":" not in m.group(1):
            paso.descripcion.append(m.group(1) if m else linea)
            continue
        clave, _, valor = m.group(1).partition(":")
        campo = _CLAVES_PASO.get(_clave(clave))
        valor = valor.strip()
        if campo is None:
            avisos.agregar(
                "clave_desconocida", n, f"clave desconocida en el paso {len(pasos)}; se ignoró"
            )
        elif campo == "responsable":
            paso.responsable = valor or paso.responsable
        elif campo == "tiempo_esperado_min":
            paso.tiempo_esperado_min = _minutos(
                valor, n, avisos, f"el tiempo del paso {len(pasos)}"
            )
        else:
            getattr(paso, campo).extend(_lista(valor))
    return pasos


def _inicio_de_paso(linea: str, con_subtitulos: bool) -> tuple[int | None, str] | None:
    """(número o None, nombre) si la línea abre un paso; None si no."""
    if con_subtitulos:
        m = _SUBTITULO_PASO.fullmatch(linea)
        if m is None:
            return None
        texto = (m.group(1) or "").strip()
        con_numero = _NUMERO_SUBTITULO.fullmatch(texto)
        if con_numero is None:
            return None, texto
        return int(con_numero.group(1)), con_numero.group(2).strip()
    m = _ITEM_PASO.fullmatch(linea)
    return (int(m.group(1)), (m.group(2) or "").strip()) if m else None


def _renumerar(pasos: list[_PasoLeido], avisos: _Avisos) -> dict[int, int]:
    """Avisa dónde se rompe la secuencia 1, 2, 3… y devuelve el mapa número original → nuevo.

    Los números originales repetidos quedan fuera del mapa: no se sabe a cuál de los pasos se
    refieren.
    """
    previo = 0
    for nuevo, p in enumerate(pasos, start=1):
        if p.numero is None:
            avisos.agregar("numeracion", p.linea, f"el paso {nuevo} no tiene número; se numeró")
        elif p.numero != previo + 1:
            avisos.agregar(
                "numeracion",
                p.linea,
                f"se esperaba el paso {previo + 1} y llegó el {p.numero}; "
                f"se renumeró 1 a {len(pasos)}",
            )
        previo = p.numero if p.numero is not None else nuevo
    veces = Counter(p.numero for p in pasos if p.numero is not None)
    return {
        p.numero: nuevo
        for nuevo, p in enumerate(pasos, start=1)
        if p.numero is not None and veces[p.numero] == 1
    }


def _paso(numero: int, p: _PasoLeido, responsable_resumen: str | None) -> PasoSOP:
    confianza: Confianza = "alta"
    inferidos: list[str] = []
    responsable = p.responsable
    if responsable is None and responsable_resumen:
        responsable, confianza, inferidos = responsable_resumen, "media", ["responsable"]
    elif responsable is None:
        responsable, confianza = NO_IDENTIFICADO, "baja"
    return PasoSOP(
        numero=numero,
        nombre=p.nombre,
        descripcion=" ".join(p.descripcion),
        responsable=responsable,
        equipo=p.equipo,
        puntos_validacion=p.puntos_validacion,
        tiempo_esperado_min=p.tiempo_esperado_min,
        confianza=confianza,
        campos_inferidos=inferidos,
    )


def _revisar_tiempos(pasos: Sequence[PasoSOP], total: float | None, avisos: _Avisos) -> None:
    """Solo si hay duración total y todos los pasos tienen tiempo: una suma parcial engaña."""
    tiempos = [p.tiempo_esperado_min for p in pasos]
    if total is None or any(t is None for t in tiempos):
        return
    suma = sum(t for t in tiempos if t is not None)
    if abs(suma - total) > TOLERANCIA_TIEMPOS * total + 1e-9:
        avisos.agregar(
            "tiempos",
            None,
            f"los pasos suman {suma:g} min y la duración total es {total:g} min "
            f"(más de ±{TOLERANCIA_TIEMPOS:.0%})",
        )


def _revisar_infinitivos(pasos: Sequence[_PasoLeido], avisos: _Avisos) -> None:
    for numero, p in enumerate(pasos, start=1):
        palabras = _clave(p.nombre).split()
        if not palabras or not palabras[0].endswith(_TERMINACIONES_INFINITIVO):
            avisos.agregar(
                "infinitivo", p.linea, f"el nombre del paso {numero} no empieza con un infinitivo"
            )


# ── Valores ──────────────────────────────────────────────────────────────────────────────────


def _lista(valor: str) -> list[str]:
    return [x.strip() for x in _SEPARADOR_LISTA.split(valor) if x.strip()]


def _minutos(valor: str, linea: int, avisos: _Avisos, que: str) -> float | None:
    """Minutos con punto o coma decimal ("0,5" = 0.5); vacío o inválido → None."""
    if not valor:
        return None
    m = _MINUTOS.fullmatch(valor)
    if m is None:
        avisos.agregar("valor_invalido", linea, f"{que} no es un número de minutos; quedó vacío")
        return None
    return float(m.group(1).replace(",", "."))
