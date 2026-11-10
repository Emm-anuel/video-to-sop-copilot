"""Personas del video frente al SOP (RF-15, SOP V1.0 §5.4; ADR-020).

Dos revisiones, solo con MiniLM y código (sin LLM), sobre las personas de la ficha de contexto
(RF-12), que ya traen su segundo y su cita verificados contra la transcripción (regla 4):

- `emparejar_roles`: cada rol del SOP es *presente* (una persona con ese rol participa),
  *mencionado* (solo se le nombra) o *ausente*.
- `asignar_responsables`: para cada paso emparejado, el responsable del SOP *coincide* con quien
  lo hizo en el video, es *distinto* o *no_identificado*. Se comparan roles, no nombres.

Cuándo dos roles coinciden (`ComparadorRoles`, ADR-020 sección 3): cada rol se parte en núcleo
(la primera palabra sin artículo, en su forma base sin plural ni género: "técnica" → "tecnic") y
complemento (lo que va después del primer "de"). Coinciden si los núcleos tienen la misma forma
base o coseno ≥ `UMBRAL_ROL` y, cuando los dos traen complemento, los complementos comparten sus
palabras (uno incluido en el otro) o tienen coseno ≥ `UMBRAL_ROL_COMPLEMENTO`. La descripción del
rol no cuenta: con MiniLM baja el coseno del mismo rol a 0.62.

"Distinto" exige una persona identificada y distinguible: con nombre, o en una ficha con dos o
más personas que participan. Con un solo narrador sin nombre la diferencia de rol se ve en los
roles (el del SOP, ausente), nunca paso por paso. Ningún nombre sale de otro lado que no sea la
ficha.

Los logs llevan conteos, nunca nombres ni roles.
"""

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from sopvid.contrato import (
    ESTADOS_PAR,
    SOP,
    Confianza,
    Contexto,
    Elemento,
    Fusion,
    PasoVideo,
    Persona,
    ResponsableFila,
    ResultadoEmparejamiento,
    RolReporte,
    Segmento,
)
from sopvid.lenguaje.emparejamiento import Embedder, get_embedder, similitud
from sopvid.lenguaje.juez import narracion_de
from sopvid.plataforma.config import Settings, get_settings
from sopvid.texto import NO_IDENTIFICADO, VACIOS, comparable, contiene_cita, limpiar

logger = logging.getLogger(__name__)

ARTICULOS = frozenset({"el", "la", "los", "las", "un", "una", "unos", "unas"})
_CONECTORES = frozenset({"de", "del"})
_FUERA_DEL_COMPLEMENTO = ARTICULOS | _CONECTORES | {"y", "e", "en", "a", "al", "o"}
# Lo que significa "no se sabe quién" en un responsable (además de los vacíos comunes).
_SIN_RESPONSABLE = VACIOS | {comparable(NO_IDENTIFICADO), "desconocido", "no se sabe"}


# ── Roles: núcleo y complemento ──────────────────────────────────────────────────────────────


def forma_base(palabra: str) -> str:
    """La palabra sin acentos, sin plural y sin la vocal final de género ("técnicas" → "tecnic",
    "supervisores" → "supervisor", "jefa" → "jef"). Es un recorte de terminaciones, no un
    lematizador (ADR-020, limitaciones)."""
    p = comparable(palabra)
    if len(p) > 4 and p.endswith("es") and p[-3] in "rlndzj":
        p = p[:-2]
    elif len(p) > 3 and p.endswith("s"):
        p = p[:-1]
    if len(p) > 3 and p[-1] in "aoe":
        p = p[:-1]
    return p


@dataclass(frozen=True)
class Rol:
    """Un rol partido en núcleo y complemento. `nucleo` y `complemento` van en minúsculas con
    sus acentos (para MiniLM); `*_base`, en forma base (para comparar por palabras)."""

    nucleo: str
    nucleo_base: str
    complemento: str = ""
    complemento_base: frozenset[str] = field(default_factory=frozenset)
    completo: str = ""  # forma comparable, sin artículos


def partir_rol(texto: str | None) -> Rol | None:
    """El rol partido (ver `Rol`), o None si no tiene ninguna palabra fuera de los artículos."""
    tokens = [t for t in re.findall(r"\w+", (texto or "").lower()) if comparable(t)]
    while tokens and comparable(tokens[0]) in ARTICULOS:
        tokens.pop(0)
    if not tokens:
        return None
    nucleo, resto = tokens[0], tokens[1:]
    complemento: list[str] = []
    for i, t in enumerate(resto):
        if comparable(t) in _CONECTORES:
            complemento = [x for x in resto[i + 1 :] if comparable(x) not in _FUERA_DEL_COMPLEMENTO]
            break
    return Rol(
        nucleo=nucleo,
        nucleo_base=forma_base(nucleo),
        complemento=" ".join(complemento),
        complemento_base=frozenset(forma_base(x) for x in complemento),
        completo=" ".join(comparable(t) for t in tokens),
    )


@dataclass(frozen=True)
class Comparacion:
    coinciden: bool
    similitud: float  # la menor de las que se compararon; 1.0 si fueron iguales


class ComparadorRoles:
    """Compara roles con la regla de ADR-020 (ver el docstring del módulo). Guarda los vectores
    de MiniLM de cada texto para no vectorizar dos veces el mismo núcleo o complemento."""

    def __init__(self, embedder: Embedder | None = None, settings: Settings | None = None):
        self._embedder = embedder
        self._settings = settings or get_settings()
        self._vectores: dict[str, np.ndarray] = {}

    def _coseno(self, a: str, b: str) -> float:
        faltan = [t for t in dict.fromkeys((a, b)) if t not in self._vectores]
        if faltan:
            self._embedder = self._embedder or get_embedder()
            for texto, vector in zip(faltan, self._embedder.embed(faltan), strict=True):
                self._vectores[texto] = vector
        return float(similitud(self._vectores[a], self._vectores[b])[0, 0])

    def comparar(self, a: str | None, b: str | None) -> Comparacion | None:
        """Si los roles `a` y `b` coinciden, con su similitud; None si alguno está vacío."""
        ra, rb = partir_rol(a), partir_rol(b)
        if ra is None or rb is None:
            return None
        if ra.completo == rb.completo:
            return Comparacion(True, 1.0)
        s = self._settings
        nucleo = 1.0 if ra.nucleo_base == rb.nucleo_base else self._coseno(ra.nucleo, rb.nucleo)
        if nucleo < s.umbral_rol:
            return Comparacion(False, nucleo)
        if not ra.complemento_base or not rb.complemento_base:
            return Comparacion(True, nucleo)
        ca, cb = ra.complemento_base, rb.complemento_base
        incluidas = ca <= cb or cb <= ca
        complemento = 1.0 if incluidas else self._coseno(ra.complemento, rb.complemento)
        return Comparacion(complemento >= s.umbral_rol_complemento, min(nucleo, complemento))

    def coinciden(self, a: str | None, b: str | None) -> bool:
        comparacion = self.comparar(a, b)
        return comparacion is not None and comparacion.coinciden


# ── Roles del SOP entre las personas del video ──────────────────────────────────────────────


def es_responsable_conocido(responsable: str | None) -> bool:
    """False si el responsable está vacío o dice que no se sabe ("No identificado")."""
    clave = comparable(limpiar(responsable))
    return bool(clave) and clave not in _SIN_RESPONSABLE


def roles_del_sop(sop: SOP) -> list[Elemento]:
    """`resumen.roles`; si viene vacío, los responsables distintos de los pasos (sin "No
    identificado")."""
    if sop.resumen.roles:
        return list(sop.resumen.roles)
    vistos: set[str] = set()
    roles = []
    for paso in sop.pasos:
        clave = comparable(paso.responsable)
        if es_responsable_conocido(paso.responsable) and clave not in vistos:
            vistos.add(clave)
            roles.append(Elemento(nombre=paso.responsable))
    return roles


def mostrar(persona: Persona) -> str:
    """ "Nombre (rol)" si la persona tiene nombre; si no, el rol (o "No identificado")."""
    if persona.nombre != NO_IDENTIFICADO:
        return f"{persona.nombre} ({persona.rol})" if persona.rol else persona.nombre
    return persona.rol or NO_IDENTIFICADO


def confianza_del_rol(persona: Persona) -> Confianza:
    """ "alta" si el núcleo del rol aparece en la cita de la persona; "media" si salió de un
    fotograma (sin cita); "baja" si el rol no está en su cita (lo infirió el LLM)."""
    if not persona.cita.strip():
        return "media"
    rol = partir_rol(persona.rol)
    if rol is None:
        return "baja"
    en_cita = {forma_base(p) for p in comparable(persona.cita).split()}
    return "alta" if rol.nucleo_base in en_cita else "baja"


def emparejar_roles(
    roles_sop: Sequence[Elemento],
    personas: Sequence[Persona],
    embedder: Embedder | None = None,
    *,
    responsables: Sequence[str] | None = None,
    comparador: ComparadorRoles | None = None,
) -> list[RolReporte]:
    """Cada rol del SOP entre las personas de la ficha (§5.4, RF-15).

    Entre las personas cuyo rol coincide se elige la que participa, después la de mayor
    similitud y después la que aparece antes. Presente si participa, mencionado si solo se le
    nombra (con su `t` y su `cita`); ausente si no hay ninguna. `responsables` son los de los
    pasos del SOP: un rol que no coincide con ninguno lleva `con_pasos=False` y su ausencia no
    cuenta como diferencia (ADR-020). Sin `responsables`, todos llevan `con_pasos=True`.
    """
    comparador = comparador or ComparadorRoles(embedder)
    reporte = []
    for rol in roles_sop:
        con_pasos = responsables is None or any(
            comparador.coinciden(rol.nombre, r) for r in responsables
        )
        candidatos = []
        for persona in personas:
            comparacion = comparador.comparar(rol.nombre, persona.rol)
            if comparacion is not None and comparacion.coinciden:
                candidatos.append((persona, comparacion.similitud))
        if not candidatos:
            reporte.append(RolReporte(rol=rol.nombre, estado="ausente", con_pasos=con_pasos))
            continue
        persona, sim = min(
            candidatos, key=lambda c: (c[0].participacion != "participa", -c[1], c[0].t)
        )
        reporte.append(
            RolReporte(
                rol=rol.nombre,
                estado="presente" if persona.participacion == "participa" else "mencionado",
                t=persona.t,
                cita=persona.cita,
                persona=mostrar(persona),
                similitud=round(sim, 4),
                confianza=confianza_del_rol(persona),
                con_pasos=con_pasos,
            )
        )
    estados = Counter(r.estado for r in reporte)
    logger.info("Roles del SOP: %s", dict(estados))
    return reporte


# ── Responsable de cada paso emparejado ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Quien:
    """Quién hizo el paso: una persona de la ficha, un rol suelto o los dos; `camino` dice cómo
    se encontró (para la nota del reporte)."""

    persona: Persona | None = None
    rol_suelto: str | None = None
    camino: str = ""


def asignar_responsables(
    resultado: ResultadoEmparejamiento,
    sop: SOP,
    contexto: Contexto | None,
    transcripcion: Sequence[Segmento],
    pasos_originales: Sequence[PasoVideo] = (),
    embedder: Embedder | None = None,
    *,
    comparador: ComparadorRoles | None = None,
) -> list[ResponsableFila | None]:
    """El responsable de cada resultado de la clasificación, en su orden (§5.4, RF-15).

    Solo los pares (Cumple, Parcial, zona_gris, con o sin fuera de orden) llevan uno; Falta y
    Sobra, None. En un paso fusionado (ADR-013) cuenta el **original citado**, el más parecido al
    paso del SOP, que ya aporta el nombre, la cita y el segundo de la fila: su responsable (el del
    paso fusionado) y, si hay que buscar nombres en la narración, solo su tramo
    (`pasos_originales` son los pasos del video antes de fusionar; sin ellos, el tramo del paso
    fusionado). Así la persona queda coherente con la evidencia que muestra la fila (decidido el
    8 nov tras el video C, ADR-020).
    Quién hizo el paso, en orden (ADR-020 sección 4): el `responsable` del paso si es el nombre
    de una persona de la ficha o un rol que coincide con el de una sola; si viene vacío, el único
    nombre de la ficha que aparece en la narración del paso; si la ficha tiene una sola persona
    que participa, esa (narrador único).
    """
    comparador = comparador or ComparadorRoles(embedder)
    personas = list(contexto.personas) if contexto is not None else []
    participantes = [p for p in personas if p.participacion == "participa"]
    distinguibles = len(participantes) >= 2
    por_numero = {p.numero: p for p in pasos_originales}
    filas: list[ResponsableFila | None] = []
    for paso in resultado.clasificacion.pasos:
        if paso.estado not in ESTADOS_PAR or paso.indice_sop is None or paso.indice_video is None:
            filas.append(None)
            continue
        esperado = sop.pasos[paso.indice_sop].responsable
        paso_video = resultado.pasos_video[paso.indice_video]
        fusion = resultado.fusiones[paso.indice_video]
        notas: list[str] = []
        tramo = _original_citado(paso_video, fusion, por_numero)
        if fusion.responsables_distintos:
            notas.append(
                f"paso fusionado con {len(fusion.responsables_distintos)} responsables "
                f"({', '.join(fusion.responsables_distintos)}); se tomó el del original citado"
            )
        if not es_responsable_conocido(esperado):
            filas.append(
                ResponsableFila(
                    esperado=esperado or NO_IDENTIFICADO,
                    estado="no_identificado",
                    nota="; ".join([*notas, "el SOP no indica responsable"]),
                )
            )
            continue
        quien = quien_hizo(
            paso_video.responsable, tramo, personas, participantes, transcripcion, comparador
        )
        filas.append(_estado(esperado, quien, distinguibles, notas, comparador))
    estados = Counter(f.estado for f in filas if f is not None)
    logger.info("Responsables por paso: %s", dict(estados))
    return filas


def _original_citado(
    paso: PasoVideo, fusion: Fusion, por_numero: dict[int, PasoVideo]
) -> PasoVideo:
    """El paso original cuya cita lleva el paso fusionado (el representante de ADR-013); sin
    fusión o sin los originales, el mismo paso."""
    if len(fusion.originales) == 1:
        return paso
    for numero, cita in zip(fusion.originales, fusion.citas, strict=True):
        if cita == paso.cita and (original := por_numero.get(numero)) is not None:
            return original
    return paso


def quien_hizo(
    responsable: str,
    paso: PasoVideo,
    personas: Sequence[Persona],
    participantes: Sequence[Persona],
    transcripcion: Sequence[Segmento],
    comparador: ComparadorRoles,
) -> Quien:
    """Quién hizo `paso` (ADR-020 sección 4): el `responsable` que escribió el LLM si es el nombre
    de una persona de la ficha o un rol que coincide con el de una sola; si viene vacío, el único
    nombre de la ficha que aparece en la narración del paso; si la ficha tiene una sola persona
    que participa (`participantes`), esa. La usan el reporte (`asignar_responsables`) y el SOP
    generado (ADR-023)."""
    con_nombre = [p for p in personas if p.nombre != NO_IDENTIFICADO]
    rol_suelto = None
    if es_responsable_conocido(responsable):
        r = limpiar(responsable)
        por_nombre = [p for p in con_nombre if contiene_cita(r, p.nombre)]
        if len(por_nombre) == 1:
            return Quien(persona=por_nombre[0], camino="responsable del paso (nombre)")
        por_rol = [p for p in personas if p.rol and comparador.coinciden(r, p.rol)]
        if len(por_rol) == 1:
            return Quien(persona=por_rol[0], rol_suelto=r, camino="responsable del paso (rol)")
        rol_suelto = r
    else:
        narracion = narracion_de(paso, transcripcion)
        nombrados = {
            comparable(p.nombre): p for p in con_nombre if contiene_cita(narracion, p.nombre)
        }
        if len(nombrados) == 1:
            [persona] = nombrados.values()
            return Quien(persona=persona, camino="nombre en la narración del paso")
    if len(participantes) == 1:
        return Quien(persona=participantes[0], rol_suelto=rol_suelto, camino="narrador único")
    return Quien(rol_suelto=rol_suelto, camino="rol del responsable del paso" if rol_suelto else "")


def _estado(
    esperado: str,
    quien: Quien,
    distinguibles: bool,
    notas: list[str],
    comparador: ComparadorRoles,
) -> ResponsableFila:
    persona = quien.persona
    # Primero el rol de la persona; después el rol suelto que escribió el LLM.
    candidatos = [(persona.rol, persona)] if persona is not None and persona.rol else []
    if quien.rol_suelto:
        candidatos.append((quien.rol_suelto, None))
    mejor = None
    for rol, de_persona in candidatos:
        comparacion = comparador.comparar(esperado, rol)
        if comparacion is None:
            continue
        if comparacion.coinciden:
            observado = mostrar(de_persona) if de_persona is not None else rol
            return _fila(esperado, observado, "coincide", comparacion.similitud, quien, notas)
        if de_persona is not None and mejor is None:
            mejor = comparacion
    if persona is not None and persona.rol and mejor is not None:
        if persona.nombre != NO_IDENTIFICADO or distinguibles:
            return _fila(esperado, mostrar(persona), "distinto", mejor.similitud, quien, notas)
        notas.append("un solo narrador sin nombre: la diferencia de rol se ve en los roles")
    elif persona is not None and not persona.rol:
        notas.append("la persona no tiene rol en la ficha")
    elif quien.rol_suelto:
        notas.append("el rol del responsable no corresponde a nadie de la ficha")
    return _fila(esperado, None, "no_identificado", None, quien, notas)


def _fila(
    esperado: str,
    observado: str | None,
    estado: str,
    sim: float | None,
    quien: Quien,
    notas: list[str],
) -> ResponsableFila:
    partes = ([quien.camino] if quien.camino else []) + notas
    return ResponsableFila(
        esperado=esperado,
        observado=observado,
        estado=estado,  # type: ignore[arg-type]
        similitud=None if sim is None else round(sim, 4),
        nota="; ".join(partes),
    )
