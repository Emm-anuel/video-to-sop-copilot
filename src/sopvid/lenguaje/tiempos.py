"""Tiempos del reporte de validación (RF-16, SOP V1.0 §5.5; ADR-021). Solo código, sin LLM.

El LLM nunca calcula ni escribe un tiempo (regla 4 de CLAUDE.md): todo sale de la transcripción y
de los pasos del video, cuyos segundos ya son de la transcripción.

- `duracion_narrada`: la duración que dice el operador en el tramo de un paso ("tarda unos 5
  minutos", "wait for half an hour"), con su cita literal y su segundo. Solo cuenta una cantidad con
  unidad de tiempo precedida, en la misma cláusula, por un verbo o sustantivo de duración de una
  lista blanca (tardar, durar, esperar, dejar…; take, last, wait, let…). "durante", "por" y "for"
  no bastan solos: "mantengo presionado el botón durante tres segundos" no es lo que tarda el paso.
  Ante la duda no se usa y se cae al tiempo medido (ADR-021).
- `tiempo_de_paso`: la duración observada de un paso del video, ya fusionado (ADR-013): la
  narrada, si el operador la dice (gana siempre, §5.5); si no, la medida (t_fin − t_inicio, el
  tramo completo de la fusión).
- `comparar`: en_tiempo, excede, menor o sin_referencia, con la tolerancia de la configuración.
- `tiempos_por_paso`, `tiempo_total` y `comparar_horario`: lo que va al reporte.

Los logs solo llevan conteos, nunca texto de la transcripción ni del SOP.
"""

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sopvid.contrato import (
    ESTADOS_PAR,
    SOP,
    Contexto,
    EstadoTiempo,
    Horario,
    PasoVideo,
    ResultadoEmparejamiento,
    Segmento,
    TiempoFila,
    TiempoTotal,
)
from sopvid.lenguaje.emparejamiento import Embedder, similitud
from sopvid.texto import comparable, contiene_cita, limpiar

logger = logging.getLogger(__name__)

# Holgura para comparar segundos y límites de la tolerancia en flotante.
_EPS = 1e-9
# Palabras que puede haber entre el disparador y la cantidad ("tarda más o menos unos 5 minutos").
VENTANA_PALABRAS = 6

# ── Vocabulario ──────────────────────────────────────────────────────────────────────────────
# Todo se compara en minúsculas y sin acentos (`_normalizar_misma_longitud`).

# Unidad → minutos. Sin "s" ni "h" sueltas: chocan con otras palabras.
_UNIDADES: dict[str, float] = {
    **dict.fromkeys(("segundo", "segundos", "seg", "segs"), 1 / 60),
    **dict.fromkeys(("second", "seconds", "sec", "secs"), 1 / 60),
    **dict.fromkeys(("minuto", "minutos", "minute", "minutes", "min", "mins"), 1.0),
    **dict.fromkeys(("hora", "horas", "hour", "hours", "hr", "hrs"), 60.0),
}
_UNIDADES_HORA = frozenset(u for u, m in _UNIDADES.items() if m == 60.0)

_UNIDADES_ES = {
    "cero": 0,
    "uno": 1,
    "un": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}
_SIMPLES_ES = {
    **_UNIDADES_ES,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiun": 21,
    "veintiuno": 21,
    "veintiuna": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "cien": 100,
}
_DECENAS_ES = {
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}
_UNIDADES_EN = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_SIMPLES_EN = {
    **_UNIDADES_EN,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "hundred": 100,
}
_DECENAS_EN = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SIMPLES = {**_SIMPLES_ES, **_SIMPLES_EN, **_DECENAS_EN}
_DECENAS = {**_DECENAS_ES, **_DECENAS_EN}
# "a"/"an" valen 1 solo justo antes de la unidad ("a minute"): también son preposición
# ("de 5 a 10").
_ARTICULO_UNO = frozenset({"a", "an"})

# Disparadores: verbos y sustantivos de duración (lista blanca, ADR-021).
_DISPARADOR = re.compile(
    r"^(?:"
    # español
    r"tard\w*|demor\w*|esper\w*|aguard\w*|repos\w*|duracion"
    r"|dur(?:a|as|an|amos|o|e|en|ar|ara|aria|aron|ando|ado|ada)"
    r"|tom(?:a|as|an|amos|o|ar|ara|aria|aron|ando)"
    r"|llev(?:a|as|an|amos|o|ar|ara|aria|aron|ando)"
    r"|dej(?:o|a|as|an|amos|e|en|ar|ara|aria|aron|ando)"
    # inglés
    r"|take|takes|took|taking|taken|last|lasts|lasted|lasting"
    r"|wait|waits|waited|waiting|let|lets|leave|leaves|left|leaving"
    r"|sit|sits|sitting|rest|rests|resting"
    r")$"
)
# Sustantivo después de la cantidad: "5 minutos de espera", "a 5-minute wait".
_SUSTANTIVO_DESPUES = frozenset({"espera", "reposo", "wait", "rest"})
# Conectores de un rango ("de 5 a 10", "5 to 10"); "y"/"and" solo después de "entre"/"between".
_RANGO = frozenset({"a", "o", "to", "or", "-"})
_RANGO_CON_ENTRE = frozenset({"y", "and"})
_ENTRE = frozenset({"entre", "between"})
# Unión de una cantidad compuesta: "un minuto y treinta segundos", "2 minutes and 30 seconds".
_UNION = frozenset({"y", "con", "and"})


# ── Tokens sobre el texto normalizado ────────────────────────────────────────────────────────


def _normalizar_misma_longitud(texto: str) -> str:
    """Minúsculas y sin acentos, carácter por carácter, con la misma longitud que `texto`: así
    un fragmento hallado en la copia se corta tal cual del original (la cita es literal)."""
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFD", c)[:1].lower()
        salida.append(base if len(base) == 1 else " ")
    return "".join(salida)


@dataclass(frozen=True)
class _Token:
    texto: str
    inicio: int
    fin: int

    @property
    def es_corte(self) -> bool:
        return self.texto in {".", ";", ":", "!", "?"}

    @property
    def es_palabra(self) -> bool:
        return self.texto[0].isalnum()


_RE_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|[a-z]+|[.;:!?]|[-–]")


def _tokens(normalizado: str) -> list[_Token]:
    return [
        _Token("-" if m.group() == "–" else m.group(), m.start(), m.end())
        for m in _RE_TOKEN.finditer(normalizado)
    ]


def _texto(tokens: Sequence[_Token], i: int) -> str | None:
    return tokens[i].texto if 0 <= i < len(tokens) else None


# ── Cantidades ───────────────────────────────────────────────────────────────────────────────


def _numero(tokens: Sequence[_Token], i: int) -> tuple[float, int] | None:
    """(valor, índice siguiente) de un número en cifra o en letra (0–99 y "cien"/"hundred")."""
    t = _texto(tokens, i)
    if t is None:
        return None
    if t[0].isdigit():
        return float(t.replace(",", ".")), i + 1
    if t in _DECENAS:
        valor = _DECENAS[t]
        # "treinta y cinco", "twenty-five", "twenty five"
        siguiente = _texto(tokens, i + 1)
        if siguiente in {"y", "-"} and _texto(tokens, i + 2) in {**_UNIDADES_ES, **_UNIDADES_EN}:
            unidad = _texto(tokens, i + 2)
            return valor + {**_UNIDADES_ES, **_UNIDADES_EN}[unidad], i + 3
        if siguiente in _UNIDADES_EN:
            return valor + _UNIDADES_EN[siguiente], i + 2
        return float(valor), i + 1
    if t in _SIMPLES:
        return float(_SIMPLES[t]), i + 1
    return None


def _cantidad(tokens: Sequence[_Token], i: int) -> tuple[float, int] | None:
    """Un número o un giro que vale un número: "un par de", "a couple of", "one and a half"."""
    t = _texto(tokens, i)
    if (
        t in {"un", "a"}
        and _texto(tokens, i + 1) in {"par", "couple"}
        and _texto(tokens, i + 2) in {"de", "of"}
    ):
        return 2.0, i + 3
    if t == "couple" and _texto(tokens, i + 1) == "of":
        return 2.0, i + 2
    numero = _numero(tokens, i)
    if numero is None:
        if t in _ARTICULO_UNO and _texto(tokens, i + 1) in _UNIDADES:
            return 1.0, i + 1
        return None
    valor, j = numero
    # "one and a half minutes", "uno y medio minutos"
    if _texto(tokens, j) in {"and", "y"}:
        if _texto(tokens, j + 1) == "a" and _texto(tokens, j + 2) == "half":
            return valor + 0.5, j + 3
        if _texto(tokens, j + 1) in {"medio", "media"}:
            return valor + 0.5, j + 2
    return valor, j


def _unidad(tokens: Sequence[_Token], j: int) -> tuple[str, int] | None:
    """La unidad en `j` (se permite un guion antes: "5-minute"), con el índice siguiente."""
    if _texto(tokens, j) == "-" and _texto(tokens, j + 1) in _UNIDADES:
        j += 1
    t = _texto(tokens, j)
    return (t, j + 1) if t in _UNIDADES else None


def _y_medio(tokens: Sequence[_Token], j: int) -> tuple[float, int]:
    """ "y medio", "y media", "and a half" después de la unidad: (0.5, siguiente) o (0, j)."""
    if _texto(tokens, j) == "y" and _texto(tokens, j + 1) in {"medio", "media"}:
        return 0.5, j + 2
    if (
        _texto(tokens, j) == "and"
        and _texto(tokens, j + 1) == "a"
        and _texto(tokens, j + 2) == "half"
    ):
        return 0.5, j + 3
    return 0.0, j


def _fraccion(tokens: Sequence[_Token], i: int) -> tuple[float, int] | None:
    """Giros sin número: "medio minuto", "media hora", "un cuarto de hora", "half an hour",
    "a quarter of an hour". (minutos, índice siguiente)."""
    t = _texto(tokens, i)
    if t in {"medio", "media"} and (u := _unidad(tokens, i + 1)):
        return 0.5 * _UNIDADES[u[0]], u[1]
    if t == "half":
        j = i + 2 if _texto(tokens, i + 1) in _ARTICULO_UNO else i + 1
        if u := _unidad(tokens, j):
            return 0.5 * _UNIDADES[u[0]], u[1]
    j = i + 1 if t in {"un", "a"} else i
    if _texto(tokens, j) in {"cuarto", "quarter"}:
        k = j + 1
        if _texto(tokens, k) in {"de", "of"}:
            k += 1
        if _texto(tokens, k) in _ARTICULO_UNO:
            k += 1
        if _texto(tokens, k) in _UNIDADES_HORA:
            return 15.0, k + 1
    return None


def _magnitud(tokens: Sequence[_Token], i: int) -> tuple[float, str, int] | None:
    """Una cantidad con su unidad, o un rango que da el punto medio: (minutos, unidad, siguiente).

    La unidad sirve para la cantidad compuesta ("un minuto y treinta segundos")."""
    if fraccion := _fraccion(tokens, i):
        minutos, j = fraccion
        return minutos, _texto(tokens, j - 1) or "", j
    cantidad = _cantidad(tokens, i)
    if cantidad is None:
        return None
    valor, j = cantidad
    # Rango: "5 a 10 minutos", "5-10", "5 to 10", "entre 5 y 10", "between 5 and 10".
    conector = _texto(tokens, j)
    if conector in _RANGO or (conector in _RANGO_CON_ENTRE and _texto(tokens, i - 1) in _ENTRE):
        segundo = _cantidad(tokens, j + 1)
        if segundo is not None and (u := _unidad(tokens, segundo[1])):
            unidad, k = u
            medio, k = _y_medio(tokens, k)
            return (
                (valor + segundo[0]) / 2 * _UNIDADES[unidad] + medio * _UNIDADES[unidad],
                unidad,
                k,
            )
    u = _unidad(tokens, j)
    if u is None:
        return None
    unidad, k = u
    medio, k = _y_medio(tokens, k)
    return (valor + medio) * _UNIDADES[unidad], unidad, k


def _expresion(tokens: Sequence[_Token], i: int) -> tuple[float, int] | None:
    """Una expresión de tiempo completa desde `i`: (minutos, índice siguiente), con la suma de
    una compuesta si la unidad que sigue es menor ("una hora y diez minutos")."""
    magnitud = _magnitud(tokens, i)
    if magnitud is None:
        return None
    minutos, unidad, j = magnitud
    if _texto(tokens, j) in _UNION and (otra := _magnitud(tokens, j + 1)):
        mas, unidad_menor, k = otra
        if _UNIDADES.get(unidad_menor, 0) < _UNIDADES.get(unidad, 0):
            return minutos + mas, k
    return minutos, j


def _disparador_antes(tokens: Sequence[_Token], i: int) -> int | None:
    """Índice del disparador más cercano antes de `i` en la misma cláusula y a lo más
    `VENTANA_PALABRAS` palabras de distancia, o None."""
    palabras = 0
    for k in range(i - 1, -1, -1):
        token = tokens[k]
        if token.es_corte:
            return None
        if not token.es_palabra:
            continue
        if _DISPARADOR.match(token.texto):
            return k
        palabras += 1
        if palabras > VENTANA_PALABRAS:
            return None
    return None


def duracion_en_texto(texto: str) -> tuple[float, str] | None:
    """(minutos, cita literal) de la primera duración narrada de `texto`, o None (ADR-021).

    La cita va del disparador al final de la expresión ("tarda unos 5 minutos"), o de la
    expresión al sustantivo ("5 minutos de espera"), cortada del texto original.
    """
    tokens = _tokens(_normalizar_misma_longitud(texto))
    i = 0
    while i < len(tokens):
        expresion = _expresion(tokens, i) if tokens[i].es_palabra else None
        if expresion is None:
            i += 1
            continue
        minutos, j = expresion
        disparador = _disparador_antes(tokens, i)
        if disparador is not None:
            return minutos, texto[tokens[disparador].inicio : tokens[j - 1].fin].strip()
        # "5 minutos de espera", "a 5-minute wait"
        k = j + 1 if _texto(tokens, j) == "de" else j
        if _texto(tokens, k) in _SUSTANTIVO_DESPUES:
            return minutos, texto[tokens[i].inicio : tokens[k].fin].strip()
        i = j
    return None


# ── Duración de un paso ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DuracionNarrada:
    """Lo que dice el operador que tarda algo en el tramo de un paso: `cita` es el fragmento
    literal de la transcripción y `t`, el inicio de su segmento (regla 4)."""

    minutos: float
    cita: str
    t: float


def segmentos_del_tramo(
    transcripcion: Sequence[Segmento], t_inicio: float, t_fin: float
) -> list[Segmento]:
    """Los segmentos que empiezan dentro de `[t_inicio, t_fin)`, en orden; un paso de un solo
    segmento sin duración (t_inicio == t_fin) se queda con el suyo."""
    return sorted(
        (
            s
            for s in transcripcion
            if t_inicio - _EPS <= s.t_inicio
            and (s.t_inicio < t_fin or s.t_inicio <= t_inicio + _EPS)
        ),
        key=lambda s: (s.t_inicio, s.id),
    )


def duracion_narrada(
    transcripcion: Sequence[Segmento], t_inicio: float, t_fin: float
) -> DuracionNarrada | None:
    """La duración narrada más cercana al inicio del tramo, o None (regla en ADR-021)."""
    for segmento in segmentos_del_tramo(transcripcion, t_inicio, t_fin):
        hallada = duracion_en_texto(segmento.texto)
        if hallada is not None and contiene_cita(segmento.texto, hallada[1]):
            return DuracionNarrada(hallada[0], hallada[1], segmento.t_inicio)
    return None


def comparar(esperado_min: float | None, observado_min: float, tolerancia: float) -> EstadoTiempo:
    """en_tiempo dentro de ±`tolerancia` × esperado (inclusive); excede arriba; menor abajo.
    Sin esperado (o esperado ≤ 0), sin_referencia."""
    if esperado_min is None or esperado_min <= 0:
        return "sin_referencia"
    margen = tolerancia * esperado_min
    if observado_min > esperado_min + margen + _EPS:
        return "excede"
    if observado_min < esperado_min - margen - _EPS:
        return "menor"
    return "en_tiempo"


def tiempo_de_paso(
    paso: PasoVideo,
    esperado_min: float | None,
    transcripcion: Sequence[Segmento],
    tolerancia: float,
) -> TiempoFila:
    """La duración observada del paso del video (ya fusionado) frente al esperado del SOP.

    Si el operador narra la duración, esa gana siempre (§5.5); si no, la medida: el tramo
    completo del paso (ADR-021). El observado se redondea a dos decimales antes de comparar: el
    estado cuadra con lo que se muestra.
    """
    narrada = duracion_narrada(transcripcion, paso.t_inicio, paso.t_fin)
    esperado = esperado_min if esperado_min is not None and esperado_min > 0 else None
    if narrada is not None:
        observado = round(narrada.minutos, 2)
        return TiempoFila(
            esperado_min=esperado,
            observado_min=observado,
            origen="narrado",
            estado=comparar(esperado, observado, tolerancia),
            cita=narrada.cita,
        )
    observado = round(max(0.0, paso.t_fin - paso.t_inicio) / 60, 2)
    return TiempoFila(
        esperado_min=esperado,
        observado_min=observado,
        origen="medido",
        estado=comparar(esperado, observado, tolerancia),
    )


def tiempos_por_paso(
    resultado: ResultadoEmparejamiento,
    sop: SOP,
    transcripcion: Sequence[Segmento],
    tolerancia: float,
) -> list[TiempoFila | None]:
    """El tiempo de cada resultado de la clasificación, en su orden: solo los pares (Cumple,
    Parcial, zona_gris, con o sin fuera de orden); Falta y Sobra, None."""
    tiempos: list[TiempoFila | None] = []
    for paso in resultado.clasificacion.pasos:
        if paso.estado not in ESTADOS_PAR or paso.indice_sop is None or paso.indice_video is None:
            tiempos.append(None)
            continue
        tiempos.append(
            tiempo_de_paso(
                resultado.pasos_video[paso.indice_video],
                sop.pasos[paso.indice_sop].tiempo_esperado_min,
                transcripcion,
                tolerancia,
            )
        )
    estados = Counter(f"{t.estado}/{t.origen}" for t in tiempos if t is not None)
    logger.info("Tiempos por paso: %s", dict(estados))
    return tiempos


def esperado_total(sop: SOP) -> float | None:
    """La duración total del SOP o, si no la trae, la suma de los esperados de los pasos cuando
    todos lo tienen (una suma parcial engañaría). None si no hay ninguna."""
    total = sop.resumen.duracion_total_min
    if total is not None and total > 0:
        return total
    esperados = [p.tiempo_esperado_min for p in sop.pasos]
    if esperados and all(e is not None for e in esperados):
        suma = sum(e for e in esperados if e is not None)
        return suma if suma > 0 else None
    return None


def tiempo_total(tiempos: Sequence[TiempoFila | None], sop: SOP, tolerancia: float) -> TiempoTotal:
    """La suma de lo observado en los pares (Falta y Sobra no suman) frente al total del SOP."""
    observado = round(sum(t.observado_min for t in tiempos if t is not None), 2)
    esperado = esperado_total(sop)
    return TiempoTotal(
        esperado_min=esperado,
        observado_min=observado,
        estado=comparar(esperado, observado, tolerancia),
    )


# ── Horario ──────────────────────────────────────────────────────────────────────────────────

_SIN_CONVERTIR = frozenset({"un", "una", "uno", "a", "an"})
_ALTERNATIVAS = re.compile(
    r"\s*;\s*|\s*,\s*(?:o|or)\s+|\s+(?:o|or)\s+(?=(?:cuando|when|si|if)\b)", re.IGNORECASE
)


def numeros_a_cifras(texto: str) -> str:
    """`texto` en forma comparable con los números en letra escritos en cifra ("cada tres
    meses" → "cada 3 meses"). Artículos como "un" o "a" se dejan."""
    tokens = _tokens(comparable(texto))
    salida: list[str] = []
    i = 0
    while i < len(tokens):
        numero = None if tokens[i].texto in _SIN_CONVERTIR else _numero(tokens, i)
        if numero is None:
            salida.append(tokens[i].texto)
            i += 1
            continue
        valor, i = numero
        salida.append(f"{valor:g}")
    return " ".join(salida)


def _contenida(a: str, b: str) -> bool:
    """`a` en `b` como palabras completas; si `a` es una sola palabra, solo si son iguales."""
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a.split()) >= 2 and f" {a} " in f" {b} "


def _cita_en(transcripcion: Sequence[Segmento], t: float) -> str:
    """El texto del segmento que empieza en `t` (literal de la transcripción), o ""."""
    for s in transcripcion:
        if abs(s.t_inicio - t) <= 1e-6:
            return " ".join(s.texto.split())
    return ""


def comparar_horario(
    sop: SOP,
    contexto: Contexto | None,
    transcripcion: Sequence[Segmento],
    embedder: Embedder,
    umbral: float,
) -> Horario:
    """El horario o la frecuencia del SOP frente al que menciona el video (§5.5, ADR-021).

    Sin horario en el SOP, sin_referencia; el SOP lo define y la ficha no lo trae con su segundo
    (uno inferido no es evidencia), no_mencionado. Si están los dos, coincide si una alternativa
    del SOP ("cada tres meses, o cuando…") está contenida en lo dicho o al revés, con los números
    en cifra, o si el coseno MiniLM en minúsculas llega a `umbral`; si no, distinto. Sin fechas.
    """
    esperado = limpiar(sop.resumen.horario_frecuencia.valor) or None
    dato = contexto.horario_mencionado if contexto is not None else None
    observado = limpiar(dato.valor) if dato is not None and dato.t is not None else ""
    t = dato.t if observado and dato is not None else None
    cita = _cita_en(transcripcion, t) if t is not None else ""
    base = {"esperado": esperado, "observado": observado or None, "t": t, "cita": cita}
    if esperado is None:
        return Horario(estado="sin_referencia", **base)
    if not observado:
        return Horario(estado="no_mencionado", **base)
    alternativas = [a for a in _ALTERNATIVAS.split(esperado) if a.strip()] or [esperado]
    dicho = numeros_a_cifras(observado)
    if any(
        _contenida(numeros_a_cifras(a), dicho) or _contenida(dicho, numeros_a_cifras(a))
        for a in alternativas
    ):
        return Horario(estado="coincide", **base)
    vectores = embedder.embed([observado.lower(), *(a.lower() for a in alternativas)])
    coseno = float(similitud(vectores[:1], vectores[1:]).max())
    return Horario(estado="coincide" if coseno >= umbral else "distinto", **base)
