"""Afinidad de contexto: ¿el video es de este SOP? (RF-17, SOP V1.0 §5.2; ADR-020).

`afinidad` compara la ficha de contexto del video (RF-12) con el título, el objetivo, el alcance
y el equipo del SOP, solo con MiniLM y código (sin LLM), y devuelve un valor de 0 a 100 con una
explicación que arma el código. Como MiniLM corre siempre en CPU, el resultado depende solo de la
ficha y del SOP, no del dispositivo (RNF-07).

Componentes (ADR-020, sección 1), cada uno llevado a 0–100 con el mismo mapeo lineal
`mapear(c) = 100 · (c − AFINIDAD_COS_CERO) / (AFINIDAD_COS_CIEN − AFINIDAD_COS_CERO)`, recortado:

- global: el texto del SOP contra el texto del video;
- actividad: el título del SOP contra la actividad de la ficha (o el tema, si no hay actividad);
- objetivo: el objetivo del SOP contra el propósito de la ficha;
- equipos: porcentaje de los equipos del SOP cuyo mejor equipo de la ficha tiene coseno ≥
  `AFINIDAD_UMBRAL_EQUIPO` o comparte sus palabras (las de uno incluidas en las del otro).

La afinidad es el promedio de los componentes que se pudieron calcular, ponderado por `PESOS` y
por la evidencia del dato de la ficha (`FACTOR_EVIDENCIA`): un dato inferido pesa menos, pero no
empuja el valor hacia abajo. El lugar solo va en la explicación. Antes de vectorizar se quitan las
`PALABRAS_GENERICAS`, que comparten procedimientos distintos, y todo pasa a minúsculas: MiniLM
distingue mayúsculas ("Lentes de seguridad" ~ "lentes de seguridad" da 0.55).

Los logs llevan el valor y los componentes, nunca la explicación (lleva nombres del SOP).
"""

import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sopvid.contrato import SOP, Afinidad, Confianza, Contexto, Dato
from sopvid.lenguaje.emparejamiento import Embedder, get_embedder, similitud
from sopvid.plataforma.config import Settings, get_settings
from sopvid.texto import comparable

logger = logging.getLogger(__name__)

# Vocabulario de planta que comparten procedimientos distintos: por sí solo no dice que el video
# sea de este SOP (ADR-020). Formas de `comparable` (sin acentos ni mayúsculas), con plurales.
PALABRAS_GENERICAS = frozenset(
    {
        "linea", "lineas", "area", "areas", "maquina", "maquinas", "equipo", "equipos",
        "boton", "botones", "panel", "paneles", "planta", "plantas", "zona", "zonas",
        "estacion", "estaciones", "seccion", "secciones", "sistema", "sistemas",
        "unidad", "unidades",
    }
)  # fmt: skip
# Palabras vacías que pueden quedar sueltas en los bordes al quitar una genérica ("Línea de
# enjuague" → "enjuague").
_VACIAS = frozenset(
    {"de", "del", "la", "el", "los", "las", "lo", "en", "y", "a", "al", "con", "un", "una", "para"}
)

# Peso de cada componente (ADR-020). El lugar pesa 0: solo va en la explicación.
PESOS = {"global": 0.30, "actividad": 0.30, "objetivo": 0.20, "equipos": 0.20}
# Cuánto pesa un dato de la ficha según su evidencia; multiplica el peso, no el valor.
FACTOR_EVIDENCIA: dict[Confianza, float] = {"alta": 1.0, "media": 0.75, "baja": 0.5}
# Los equipos de la ficha no traen evidencia propia (el LLM los nombra sin cita).
FACTOR_EQUIPOS = 0.75
NOMBRES_EN_EXPLICACION = 3  # equipos en común que se nombran en la explicación


def sin_genericas(texto: str | None) -> str:
    """`texto` sin las palabras genéricas ni las palabras vacías que queden en los bordes; "" si
    no queda ninguna palabra con contenido."""
    tokens = [t for t in (texto or "").split() if comparable(t) not in PALABRAS_GENERICAS]
    while tokens and comparable(tokens[0]) in _VACIAS | {""}:
        tokens.pop(0)
    while tokens and comparable(tokens[-1]) in _VACIAS | {""}:
        tokens.pop()
    if not any(comparable(t) not in _VACIAS for t in tokens):
        return ""
    return re.sub(r"\s+([,.;:])", r"\1", " ".join(tokens)).strip(" ,.;:")


def palabras(texto: str) -> frozenset[str]:
    """Las palabras con contenido de `texto` (sin acentos, mayúsculas ni palabras vacías)."""
    return frozenset(p for p in comparable(texto).split() if p not in _VACIAS)


def incluidas(a: str, b: str) -> bool:
    """True si las palabras con contenido de uno están todas en el otro ("enjuague" en
    "enjuague, filtro de agua de entrada"; "cartucho" en "cartucho nuevo")."""
    pa, pb = palabras(a), palabras(b)
    return bool(pa) and bool(pb) and (pa <= pb or pb <= pa)


def mapear(coseno: float, settings: Settings | None = None) -> float:
    """El coseno llevado a 0–100 con el mapeo lineal de la configuración, recortado."""
    s = settings or get_settings()
    x = (coseno - s.afinidad_cos_cero) / (s.afinidad_cos_cien - s.afinidad_cos_cero)
    return 100 * min(1.0, max(0.0, x))


def factor(dato: Dato) -> float:
    """Peso relativo de un dato de la ficha según su evidencia: un inferido cuenta como baja."""
    return FACTOR_EVIDENCIA["baja" if dato.fuente == "inferido" else dato.confianza]


def equipos_del_sop(sop: SOP) -> list[str]:
    """`resumen.equipo_operacion`; si viene vacío, el equipo de los pasos sin repetir."""
    nombres = [e.nombre for e in sop.resumen.equipo_operacion]
    if not nombres:
        nombres = [e for p in sop.pasos for e in p.equipo]
    vistos: set[str] = set()
    unicos = []
    for n in nombres:
        if (clave := comparable(n)) and clave not in vistos:
            vistos.add(clave)
            unicos.append(n)
    return unicos


@dataclass(frozen=True)
class _Lado:
    """Un dato comparable: su texto sin genéricas y su factor de evidencia."""

    texto: str
    factor: float = 1.0
    inferido: bool = False


def _dato(dato: Dato) -> _Lado:
    return _Lado(sin_genericas(dato.valor), factor(dato), dato.fuente == "inferido")


def afinidad(
    sop: SOP,
    contexto: Contexto | None,
    embedder: Embedder | None = None,
    settings: Settings | None = None,
) -> Afinidad | None:
    """Afinidad 0–100 entre la ficha de contexto y el SOP (ADR-020), o None si no hay ficha o
    ningún componente se puede calcular. `bajo_umbral` es `valor < AFINIDAD_MIN`."""
    if contexto is None:
        return None
    s = settings or get_settings()
    embedder = embedder or get_embedder()

    titulo = _Lado(sin_genericas(sop.titulo))
    objetivo = _Lado(sin_genericas(sop.resumen.objetivo.valor))
    alcance = _Lado(sin_genericas(sop.resumen.alcance.valor))
    lugar_sop = _Lado(sin_genericas(sop.resumen.lugar.valor))
    eq_sop = [(n, t) for n in equipos_del_sop(sop) if (t := sin_genericas(n))]

    actividad = _dato(contexto.actividad)
    if not actividad.texto:  # sin actividad, el tema
        actividad = _dato(contexto.tema)
    tema = _dato(contexto.tema)
    proposito = _dato(contexto.proposito)
    lugar_video = _dato(contexto.lugar)
    eq_video = [t for e in contexto.equipos if (t := sin_genericas(e.nombre))]

    partes_sop = [x.texto for x in (titulo, objetivo, alcance) if x.texto]
    if eq_sop:
        partes_sop.append(", ".join(t for _, t in eq_sop))
    datos_video = [x for x in (_dato(contexto.actividad), tema, proposito) if x.texto]
    partes_video = [x.texto for x in datos_video]
    factores_video = [x.factor for x in datos_video]
    if eq_video:
        partes_video.append(", ".join(eq_video))
        factores_video.append(FACTOR_EQUIPOS)

    # Una sola llamada a MiniLM con todos los textos.
    textos: list[str] = []

    def indice(texto: str) -> int:
        textos.append(texto)
        return len(textos) - 1

    i_global = (indice(". ".join(partes_sop)), indice(". ".join(partes_video)))
    i_act = (indice(titulo.texto), indice(actividad.texto))
    i_obj = (indice(objetivo.texto), indice(proposito.texto))
    i_lugar = (indice(lugar_sop.texto), indice(lugar_video.texto))
    i_eq_sop = [indice(t) for _, t in eq_sop]
    i_eq_video = [indice(t) for t in eq_video]
    # MiniLM distingue mayúsculas ("Lentes de seguridad" ~ "lentes de seguridad" 0.55): todo
    # va en minúsculas.
    vectores = embedder.embed([t.lower() for t in textos])

    def coseno(par: tuple[int, int]) -> float:
        return float(similitud(vectores[par[0]], vectores[par[1]])[0, 0])

    componentes: dict[str, tuple[float, float]] = {}  # nombre → (valor 0–100, factor)
    frases: list[str] = []

    if partes_sop and partes_video:
        componentes["global"] = (
            mapear(coseno(i_global), s),
            sum(factores_video) / len(factores_video),
        )

    marca = " (dato inferido)"
    if not actividad.texto:
        frases.append("actividad no identificada en el video")
    elif titulo.texto:
        m = mapear(coseno(i_act), s)
        componentes["actividad"] = (m, actividad.factor)
        parecida = "parecida al" if m >= s.afinidad_min else "distinta del"
        frases.append(f"actividad {parecida} título" + (marca if actividad.inferido else ""))

    if not objetivo.texto:
        frases.append("objetivo no indicado en el SOP")
    elif not proposito.texto:
        frases.append("propósito no identificado en el video")
    else:
        m = mapear(coseno(i_obj), s)
        componentes["objetivo"] = (m, proposito.factor)
        parecido = "parecido al" if m >= s.afinidad_min else "distinto del"
        frases.append(f"propósito {parecido} objetivo" + (marca if proposito.inferido else ""))

    if not eq_sop:
        frases.append("el SOP no lista equipo")
    elif not eq_video:
        frases.append("equipos no identificados en el video")
    else:
        matriz = similitud(vectores[i_eq_sop], vectores[i_eq_video])
        comunes = [
            nombre
            for (nombre, texto), fila in zip(eq_sop, matriz, strict=True)
            if fila.max() >= s.afinidad_umbral_equipo or any(incluidas(texto, v) for v in eq_video)
        ]
        componentes["equipos"] = (100 * len(comunes) / len(eq_sop), FACTOR_EQUIPOS)
        frases.append(_frase_equipos(comunes, len(eq_sop)))

    frases.append(_frase_lugar(lugar_sop, lugar_video, lambda: mapear(coseno(i_lugar), s), s))

    if not componentes:
        logger.info("Afinidad: ningún componente comparable entre la ficha y el SOP")
        return None
    peso = {n: PESOS[n] * f for n, (_, f) in componentes.items()}
    valor = sum(peso[n] * m for n, (m, _) in componentes.items()) / sum(peso.values())
    entero = _redondear(valor)
    redondeados = {n: _redondear(m) for n, (m, _) in componentes.items()}
    logger.info("Afinidad %d (componentes %s)", entero, redondeados)
    return Afinidad(
        valor=entero,
        explicacion="; ".join(frases),
        bajo_umbral=entero < s.afinidad_min,
        componentes=redondeados,
    )


def _frase_equipos(comunes: Sequence[str], total: int) -> str:
    if not comunes:
        return "ningún equipo en común"
    nombres = ", ".join(comunes[:NOMBRES_EN_EXPLICACION])
    if len(comunes) > NOMBRES_EN_EXPLICACION:
        nombres += ", …"
    return f"{len(comunes)} de {total} equipos del SOP en el video ({nombres})"


def _frase_lugar(sop: _Lado, video: _Lado, valor: Callable[[], float], s: Settings) -> str:
    if not sop.texto:
        return "lugar no indicado en el SOP"
    if not video.texto:
        return "lugar no mencionado en el video"
    mismo = incluidas(sop.texto, video.texto) or valor() >= s.afinidad_min
    frase = "mismo lugar" if mismo else "lugar distinto"
    return frase + (" (dato inferido)" if video.inferido else "")


def _redondear(x: float) -> int:
    """Al entero más cercano, con los medios hacia arriba (no el redondeo bancario)."""
    return int(min(100, max(0, math.floor(x + 0.5))))


__all__ = [
    "FACTOR_EQUIPOS",
    "FACTOR_EVIDENCIA",
    "PALABRAS_GENERICAS",
    "PESOS",
    "afinidad",
    "equipos_del_sop",
    "incluidas",
    "factor",
    "mapear",
    "sin_genericas",
]
