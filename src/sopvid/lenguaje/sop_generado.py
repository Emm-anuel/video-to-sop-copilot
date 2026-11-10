"""SOP generado desde el video (RF-22 a RF-25, RF-27; SOP V1.0 §6; ADR-023).

En modo "No tengo SOP", con el análisis, la ficha de contexto (RF-12) y los pasos del video (RF-13,
extraídos sin SOP, regla 5), arma un `SOP` en español con el mismo esquema que el de referencia.
Gemma solo redacta valores y copia citas; el código pone todo lo demás (regla 4):

1. **Agrupar** (`sop_generado_agrupar_v1`): Gemma recibe los pasos del video numerados con su
   narración y responde qué pasos del video forman cada paso del SOP (números consecutivos) y
   cuáles quedan fuera (presentación, cierre, preguntas del entrevistador, comentarios). Sin SOP
   no hay fusión (ADR-013) y `gemma4:e4b` sobre-segmenta: sin agrupar, un SOP tendría el doble de
   pasos. Si falla, un paso del SOP por paso del video.
2. **Pasos** (`sop_generado_pasos_v1`, por lotes de `PASOS_POR_LOTE`): nombre en infinitivo,
   descripción, y equipo y puntos de validación con su cita. Número, tiempos, responsable (la
   ficha, `personas.quien_hizo`) y tiempo esperado (`tiempos.duracion_narrada` o la medida de
   ADR-021) los pone el código.

Evidencia (RF-25, `_Evidencias`): una cita que aparece en la transcripción (primero en el tramo del
paso, luego en todo el video; `contexto.ubicar_cita`: 2–3 palabras, confianza media; 4–25, alta)
da fuente "audio" y el segundo de su segmento; si no, un fotograma que existe da "visual"; sin
evidencia, "inferido", confianza baja y el campo en `campos_inferidos`. Las citas se guardan en el
idioma original: son evidencia.

Fallas (criterio de ADR-019): `generar_sop` nunca lanza por el LLM. Lo que falló queda en la
advertencia `sop_incompleto` y el SOP sale con lo que se pudo; nunca sin pasos. Sin pasos del video
lanza `SinPasosDelVideo`.

Cada llamada va en flujo (`ClienteLLM.chat_en_flujo`) con el corte por inactividad, temperatura 0 y
`SEMILLA` (las fija el cliente), y se reintenta hasta `MAX_INTENTOS` solo si la respuesta no es un
JSON del esquema (o, en la agrupación, si no cubre cada paso una vez). Un corte por tiempo o un
Ollama caído no se reintenta. Los logs y las advertencias llevan conteos, números de paso y
motivos, nunca texto del video.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from sopvid.contrato import (
    SOP,
    Analisis,
    AvisoConversion,
    Confianza,
    Contexto,
    Dato,
    Elemento,
    Evidencia,
    FuenteSOP,
    GeneracionSOP,
    LlamadaLLM,
    MotivoLlamada,
    PasoFuera,
    PasoSOP,
    PasoVideo,
    Persona,
    Resumen,
    Segmento,
    TipoFuera,
)
from sopvid.lenguaje.emparejamiento import Embedder
from sopvid.lenguaje.juez import Prompt, leer_prompt, narracion_de, texto_del_prompt
from sopvid.lenguaje.llm import (
    ClienteLLM,
    LLMError,
    LLMRespuestaInvalida,
    LLMTiempoExcedido,
    tokens_por_segundo,
)
from sopvid.lenguaje.personas import (
    ComparadorRoles,
    Quien,
    confianza_del_rol,
    es_responsable_conocido,
    forma_base,
    quien_hizo,
)
from sopvid.lenguaje.sop_markdown import empieza_con_infinitivo
from sopvid.lenguaje.tiempos import duracion_narrada, fin_del_paso, segmentos_del_tramo
from sopvid.percepcion.contexto import PALABRAS_CITA, ubicar_cita
from sopvid.percepcion.segmentacion import _sin_refs
from sopvid.plataforma.config import get_settings
from sopvid.texto import NO_IDENTIFICADO, VACIOS, comparable, limpiar, recortar_palabras

logger = logging.getLogger(__name__)

PROMPT_AGRUPAR = "sop_generado_agrupar_v1"  # archivos en lenguaje/prompts/; uno nuevo por versión
PROMPT_PASOS = "sop_generado_pasos_v1"
MAX_INTENTOS = 3  # una llamada más dos reintentos si la respuesta no es un JSON del esquema
PASOS_POR_LOTE = 8  # pasos del SOP por llamada de redacción
VERSION_SOP = "1.0"  # §6: el SOP generado nace en la versión 1.0
TITULO_MAX = 300  # como `sops.titulo`
_RANGO_CONFIANZA: dict[Confianza, int] = {"baja": 0, "media": 1, "alta": 2}
# Lo que el modelo escribe a veces en lugar de dejar vacío un valor.
_VACIOS = VACIOS | {"no se menciona", "no mencionado", "no se dice", "no especificado", "n/a"}
# Separadores de la plantilla Markdown (ADR-015): un valor de lista que los lleve no vuelve igual.
_SEPARADORES = str.maketrans({",": " ", ";": " ", ":": " "})


class SinPasosDelVideo(ValueError):  # noqa: N818 (nombre de dominio)
    """No hay pasos del video de donde sacar los pasos del SOP: nunca se genera un SOP vacío."""


# ── Respuestas del LLM ───────────────────────────────────────────────────────────────────────
# Solo valores y citas: ningún tiempo, fuente, confianza, conteo ni número de paso del SOP. La
# cita va antes del valor para que el valor se apoye en ella. Sin docstrings: Pydantic los
# pondría en el esquema que va a Ollama.


class _Libre(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Grupo(_Libre):
    pasos_video: list[int]


class _Fuera(_Libre):
    paso_video: int
    tipo: TipoFuera


class _Agrupacion(_Libre):
    grupos: list[_Grupo]
    fuera: list[_Fuera]


class _Item(_Libre):
    cita: str
    valor: str


class _ItemVisual(_Item):
    f: int | None = Field(default=None, ge=1)


class _PasoLibre(_Libre):
    numero: int
    nombre: str
    descripcion: str
    equipo: list[_Item]
    puntos_validacion: list[_Item]


class _PasoVisual(_PasoLibre):
    equipo: list[_ItemVisual]  # type: ignore[assignment]
    puntos_validacion: list[_ItemVisual]  # type: ignore[assignment]


ESQUEMA_AGRUPAR: dict[str, Any] = _sin_refs(_Agrupacion.model_json_schema())
ESQUEMA_PASOS: dict[str, Any] = _sin_refs(TypeAdapter(list[_PasoLibre]).json_schema())
ESQUEMA_PASOS_FOTOGRAMAS: dict[str, Any] = _sin_refs(TypeAdapter(list[_PasoVisual]).json_schema())

_MARCADORES_AGRUPAR = {
    "sistema": frozenset(),
    "usuario": frozenset({"idioma", "pasos"}),
    "correccion": frozenset({"motivo"}),
}
_MARCADORES_PASOS = {
    "sistema": frozenset(),
    "sistema_fotogramas": frozenset(),
    "usuario": frozenset({"idioma", "ficha", "pasos"}),
    "usuario_fotogramas": frozenset({"fotogramas"}),
    "correccion": frozenset({"motivo"}),
}


@cache
def cargar_prompt(version: str) -> Prompt:
    """Lee `prompts/<version>.md` con los marcadores de su etapa."""
    marcadores = _MARCADORES_AGRUPAR if "agrupar" in version else _MARCADORES_PASOS
    return leer_prompt(version, texto_del_prompt(version), marcadores)


class RespuestaInvalida(ValueError):  # noqa: N818 (nombre de dominio)
    """La respuesta no cumple las reglas de su etapa. El mensaje solo lleva números y motivos."""


# ── Resultado ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SOPGenerado:
    """El SOP, sus advertencias (para `sops.advertencias`) y cómo se generó (`sops.generacion`)."""

    sop: SOP
    advertencias: list[AvisoConversion]
    generacion: GeneracionSOP


# ── Llamadas al LLM ──────────────────────────────────────────────────────────────────────────

T = TypeVar("T")


@dataclass
class _Plazos:
    """Plazos de una generación: el tope vale para todas sus llamadas juntas."""

    primer_token_s: float
    inactividad_s: float
    tope_s: float
    reloj: Callable[[], float]
    inicio: float = 0.0

    def restante(self) -> float:
        return self.tope_s - (self.reloj() - self.inicio)


def _llamar(
    llm: ClienteLLM,
    etapa: Literal["agrupar", "pasos", "resumen", "claves"],
    prompt: Prompt,
    mensajes: list[dict[str, str]],
    esquema: dict[str, Any],
    convertir: Callable[[Any], T],
    plazos: _Plazos,
) -> tuple[T | None, LlamadaLLM]:
    """Pide `mensajes` con `esquema` y convierte la respuesta, con hasta `MAX_INTENTOS`.

    Reintenta solo si el modelo no dio un JSON válido o si `convertir` lo rechaza
    (`ValidationError` o `RespuestaInvalida`): el reintento manda los mensajes de base y la
    corrección del prompt con el motivo (campos y tipos de error, nunca texto), sin la respuesta
    anterior. Un corte por tiempo o un Ollama caído terminan la llamada sin reintentar. Nunca
    lanza por el LLM: sin respuesta válida devuelve None y el motivo en la `LlamadaLLM`.
    """
    inicio = plazos.reloj()
    historial = list(mensajes)

    def fallida(motivo: MotivoLlamada, intentos: int) -> tuple[None, LlamadaLLM]:
        logger.warning("SOP generado, %s: sin respuesta válida (%s)", etapa, motivo)
        return None, LlamadaLLM(
            etapa=etapa,
            prompt=prompt.version,
            ok=False,
            motivo=motivo,
            intentos=intentos,
            segundos=round(plazos.reloj() - inicio, 2),
        )

    for intento in range(1, MAX_INTENTOS + 1):
        restante = plazos.restante()
        if restante <= 0:
            return fallida("tiempo_excedido", intento - 1)
        try:
            respuesta = llm.chat_en_flujo(
                historial,
                esquema=esquema,
                primer_token_s=plazos.primer_token_s,
                inactividad_s=plazos.inactividad_s,
                tope_s=restante,
            )
        except LLMTiempoExcedido:
            return fallida("tiempo_excedido", intento)
        except LLMRespuestaInvalida:
            motivo = "no devolviste un JSON válido"
        except LLMError as exc:
            logger.warning("SOP generado, %s: LLM no disponible (%s)", etapa, type(exc).__name__)
            return fallida("llm_no_disponible", intento)
        else:
            try:
                valor = convertir(respuesta.datos)
            except ValidationError as exc:
                motivo = _resumen_errores(exc)
            except RespuestaInvalida as exc:
                motivo = str(exc)
            else:
                llamada = LlamadaLLM(
                    etapa=etapa,
                    prompt=prompt.version,
                    ok=True,
                    intentos=intento,
                    segundos=round(plazos.reloj() - inicio, 2),
                    tokens_entrada=respuesta.metricas.get("prompt_eval_count"),
                    tokens_salida=respuesta.metricas.get("eval_count"),
                    tokens_por_s=_redondear(tokens_por_segundo(respuesta.metricas)),
                    primer_token_s=_redondear(respuesta.primer_token_s),
                )
                logger.info(
                    "SOP generado, %s (intento %d): %s tokens de salida, %s tokens/s, %.1f s",
                    etapa,
                    intento,
                    llamada.tokens_salida,
                    llamada.tokens_por_s,
                    llamada.segundos,
                )
                return valor, llamada
        logger.warning(
            "SOP generado, %s: respuesta inválida (intento %d de %d): %s",
            etapa,
            intento,
            MAX_INTENTOS,
            motivo,
        )
        correccion = prompt.correccion.substitute(motivo=motivo)
        historial = [*mensajes, {"role": "user", "content": correccion}]
    return fallida("respuesta_invalida", MAX_INTENTOS)


def _mensajes(prompt: Prompt, analisis: Analisis, **valores: str) -> list[dict[str, str]]:
    """Sistema y usuario del prompt; las secciones de fotogramas solo si el análisis los trae."""
    sistema = prompt.sistema
    usuario = prompt.usuario.substitute(idioma=analisis.idioma.codigo, **valores)
    if analisis.fotogramas and "sistema_fotogramas" in prompt.extras:
        sistema += "\n\n" + prompt.extras["sistema_fotogramas"].substitute()
        usuario += "\n\n" + prompt.extras["usuario_fotogramas"].substitute(
            fotogramas=_fotogramas(analisis)
        )
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def _fotogramas(analisis: Analisis) -> str:
    """Un fotograma por línea, sin su tiempo (como en la ficha de contexto)."""
    lineas = []
    for n, f in enumerate(analisis.fotogramas, start=1):
        partes = [limpiar(f.descripcion) or "(sin descripción)"]
        if equipos := [e for x in f.equipos if (e := limpiar(x))]:
            partes.append("equipos: " + "; ".join(equipos))
        if visible := [e for x in f.texto_visible if (e := limpiar(x))]:
            partes.append("texto visible: " + "; ".join(visible))
        lineas.append(f"[f={n}] " + " | ".join(partes))
    return "\n".join(lineas)


# ── 1. Agrupar los pasos del video ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Agrupacion:
    """Qué pasos del video (números desde 1) forman cada paso del SOP y cuáles quedan fuera."""

    grupos: list[list[int]]
    fuera: list[PasoFuera] = field(default_factory=list)
    metodo: Literal["llm", "uno_a_uno"] = "llm"


def uno_a_uno(pasos_video: Sequence[PasoVideo]) -> Agrupacion:
    """Respaldo: cada paso del video es un paso del SOP y ninguno queda fuera."""
    return Agrupacion([[p.numero] for p in pasos_video], [], "uno_a_uno")


def validar_agrupacion(datos: Any, n_pasos: int) -> Agrupacion:
    """Valida la respuesta de la agrupación: cada paso del video (1 a `n_pasos`) aparece una sola
    vez, en un grupo o fuera; cada grupo es de pasos consecutivos y los grupos van en orden; hay
    al menos un grupo. Lanza `ValidationError` o `RespuestaInvalida` (se reintenta)."""
    r = _Agrupacion.model_validate(datos)
    grupos = [g.pasos_video for g in r.grupos if g.pasos_video]
    if not grupos:
        raise RespuestaInvalida("no hay ningún grupo: el procedimiento tiene al menos un paso")
    vistos = Counter([n for g in grupos for n in g] + [f.paso_video for f in r.fuera])
    fuera_de_rango = sorted(n for n in vistos if not 1 <= n <= n_pasos)
    if fuera_de_rango:
        raise RespuestaInvalida(f"pasos del video que no existen: {fuera_de_rango}")
    repetidos = sorted(n for n, veces in vistos.items() if veces > 1)
    if repetidos:
        raise RespuestaInvalida(f"pasos del video repetidos: {repetidos}")
    faltan = sorted(set(range(1, n_pasos + 1)) - set(vistos))
    if faltan:
        raise RespuestaInvalida(f"pasos del video sin grupo ni fuera: {faltan}")
    for g in grupos:
        if g != list(range(g[0], g[0] + len(g))):
            raise RespuestaInvalida(f"el grupo {g} no es de pasos consecutivos")
    if [g[0] for g in grupos] != sorted(g[0] for g in grupos):
        raise RespuestaInvalida("los grupos no van en el orden del video")
    fuera = sorted(
        (PasoFuera(paso_video=f.paso_video, tipo=f.tipo) for f in r.fuera),
        key=lambda f: f.paso_video,
    )
    return Agrupacion(grupos, fuera, "llm")


def _bloques_agrupar(pasos_video: Sequence[PasoVideo], analisis: Analisis) -> str:
    return "\n\n".join(
        f"[{p.numero}] {p.nombre}\n{_narracion(p, analisis) or '(sin narración)'}"
        for p in pasos_video
    )


def _narracion(paso: PasoVideo, analisis: Analisis) -> str:
    """Lo que se dijo durante el paso, sin tiempos ni números de segmento."""
    return narracion_de(paso, analisis.transcripcion) or " ".join(
        s.texto for s in segmentos_del_tramo(analisis.transcripcion, paso.t_inicio, paso.t_fin)
    )


# ── 2. Redactar los pasos ────────────────────────────────────────────────────────────────────


def _ficha_breve(contexto: Contexto | None) -> str:
    if contexto is None:
        return "(sin ficha de contexto)"
    partes = [
        f"{nombre}: {dato.valor}"
        for nombre, dato in (("actividad", contexto.actividad), ("lugar", contexto.lugar))
        if dato.valor
    ]
    return "; ".join(partes) or "(sin datos)"


def validar_lote(datos: Any) -> list[dict[str, Any]]:
    """La respuesta de un lote de redacción es una lista de objetos; cada paso se valida aparte
    (`_redaccion_de`), así que un paso inválido no tira a los demás (como en ADR-010)."""
    if not isinstance(datos, list) or not all(isinstance(x, dict) for x in datos):
        raise RespuestaInvalida("la respuesta debe ser una lista de objetos, uno por paso")
    return datos


def _redaccion_de(
    crudos: Sequence[dict[str, Any]], n_lote: int, con_fotogramas: bool
) -> dict[int, _PasoLibre]:
    """Los pasos válidos del lote por su número (1 a `n_lote`); el primero gana si se repite."""
    modelo = _PasoVisual if con_fotogramas else _PasoLibre
    validos: dict[int, _PasoLibre] = {}
    for crudo in crudos:
        try:
            paso = modelo.model_validate(crudo)
        except ValidationError:
            continue
        nuevo = 1 <= paso.numero <= n_lote and paso.numero not in validos
        if nuevo and limpiar(paso.nombre, _VACIOS):
            validos[paso.numero] = paso
    return validos


# ── Evidencia (RF-25) ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Ubicada:
    """Evidencia de un dato: la cita (en el idioma original), fuente, confianza y segundo."""

    cita: str
    fuente: FuenteSOP
    confianza: Confianza
    t: float | None


INFERIDA = Ubicada("", "inferido", "baja", None)


@dataclass
class _Evidencias:
    """Ubica las citas en la transcripción (o en un fotograma) y cuenta las que no aparecen."""

    analisis: Analisis
    sin_evidencia: int = 0

    def ubicar(self, cita: str, tramo: Sequence[Segmento] = (), f: int | None = None) -> Ubicada:
        """Una cita que aparece en el tramo (o, si no, en todo el video) da "audio" con el
        segundo de su segmento; si no, un fotograma que existe da "visual"; si no, inferida."""
        cita = recortar_palabras(limpiar(cita, _VACIOS), PALABRAS_CITA[1])
        if cita:
            ubicada = ubicar_cita(cita, tramo) if tramo else None
            ubicada = ubicada or ubicar_cita(cita, self.analisis.transcripcion)
            if ubicada is not None:
                return Ubicada(cita, "audio", ubicada[1], ubicada[0])
        fotogramas = self.analisis.fotogramas
        if f is not None and 1 <= f <= len(fotogramas):
            return Ubicada("", "visual", "media", fotogramas[f - 1].t)
        self.sin_evidencia += 1
        return INFERIDA


def _valor_lista(texto: str) -> str:
    """Un elemento de lista (equipo, validación, rol) sin los separadores de la plantilla."""
    return limpiar(limpiar(texto, _VACIOS).translate(_SEPARADORES), _VACIOS)


def clave_elemento(texto: str) -> str:
    """Para juntar elementos repetidos sin importar acentos, mayúsculas, plural ni género."""
    return " ".join(forma_base(p) for p in comparable(texto).split())


# ── Armado de un paso ────────────────────────────────────────────────────────────────────────


@dataclass
class _Armado:
    """Lo que el código pone en los pasos: tiempos, responsable, tiempo esperado y evidencia."""

    analisis: Analisis
    pasos_video: list[PasoVideo]
    contexto: Contexto | None
    comparador: ComparadorRoles
    evidencias: _Evidencias = field(init=False)
    _indice: dict[int, int] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.evidencias = _Evidencias(self.analisis)
        self._indice = {p.numero: i for i, p in enumerate(self.pasos_video)}

    @property
    def personas(self) -> list[Persona]:
        return list(self.contexto.personas) if self.contexto is not None else []

    def grupo(self, numeros: Sequence[int]) -> list[PasoVideo]:
        return [self.pasos_video[self._indice[n]] for n in numeros]

    def fin_medida(self, numeros: Sequence[int]) -> float:
        """Donde termina la medida del paso (ADR-021): en el inicio del siguiente paso del video,
        esté o no en el SOP; el último, al final del video."""
        return fin_del_paso(self.pasos_video, self._indice[numeros[-1]], self.analisis.duracion_s)

    def paso(self, numero: int, numeros: Sequence[int], redaccion: _PasoLibre | None) -> PasoSOP:
        grupo = self.grupo(numeros)
        t_inicio, t_fin = grupo[0].t_inicio, grupo[-1].t_fin
        fin = self.fin_medida(numeros)
        tramo = segmentos_del_tramo(self.analisis.transcripcion, t_inicio, fin)
        inferidos: list[str] = []
        evidencia: list[Evidencia] = []

        if redaccion is not None:
            nombre = limpiar(redaccion.nombre, _VACIOS)
            descripcion = limpiar(redaccion.descripcion, _VACIOS)
        else:  # sin redactar: lo que ya dijo la segmentación, marcado como inferido
            nombre = grupo[0].nombre
            descripcion = " ".join(d for p in grupo if (d := limpiar(p.descripcion, _VACIOS)))
            inferidos += ["nombre", "descripcion"]

        listas: dict[str, list[str]] = {"equipo": [], "puntos_validacion": []}
        for campo in ("equipo", "puntos_validacion"):
            items = getattr(redaccion, campo) if redaccion is not None else []
            vistos: set[str] = set()
            for item in items:
                valor = _valor_lista(item.valor)
                if not valor or (clave := clave_elemento(valor)) in vistos:
                    continue
                vistos.add(clave)
                ubicada = self.evidencias.ubicar(item.cita, tramo, getattr(item, "f", None))
                listas[campo].append(valor)
                evidencia.append(_evidencia(campo, valor, ubicada))  # type: ignore[arg-type]
                if ubicada.fuente == "inferido" and campo not in inferidos:
                    inferidos.append(campo)

        responsable, ubicada = self.responsable(grupo)
        evidencia.append(_evidencia("responsable", responsable, ubicada))
        if ubicada.fuente == "inferido":
            inferidos.append("responsable")

        minutos, ubicada = self.tiempo(t_inicio, fin)
        evidencia.append(_evidencia("tiempo_esperado_min", f"{minutos:g}", ubicada))
        if ubicada.fuente == "inferido":
            inferidos.append("tiempo_esperado_min")

        cita, fuente, confianza = _evidencia_del_paso(grupo)
        if redaccion is None:
            confianza = "baja"
        return PasoSOP(
            numero=numero,
            nombre=nombre,
            descripcion=descripcion,
            responsable=responsable,
            equipo=listas["equipo"],
            puntos_validacion=listas["puntos_validacion"],
            tiempo_esperado_min=minutos,
            t_inicio=t_inicio,
            t_fin=t_fin,
            confianza=confianza,
            campos_inferidos=inferidos,
            cita=cita,
            fuente=fuente,
            evidencia=evidencia,
        )

    def quien(self, grupo: Sequence[PasoVideo]) -> Quien:
        """Quién hizo el paso con la regla de ADR-020, sobre cada paso del video del grupo: el
        primero que identifica a una persona; si ninguno, el primero con un rol."""
        personas = self.personas
        participantes = [p for p in personas if p.participacion == "participa"]
        encontrados = [
            quien_hizo(
                p.responsable,
                p,
                personas,
                participantes,
                self.analisis.transcripcion,
                self.comparador,
            )
            for p in grupo
        ]
        return next(
            (q for q in encontrados if q.persona is not None),
            next((q for q in encontrados if q.rol_suelto), Quien()),
        )

    def responsable(self, grupo: Sequence[PasoVideo]) -> tuple[str, Ubicada]:
        """El rol de quien hizo el paso, nunca su nombre (LFPDPPP), con su evidencia.

        Si el rol que escribió la segmentación (en español) coincide con el de la persona, va
        ese; si no, el de la persona (ficha). La evidencia es la cita de la persona en la ficha
        (ya verificada contra la transcripción): confianza alta si el rol aparece en ella
        (`confianza_del_rol`), media si no (en un video en otro idioma el rol es una traducción:
        "technician" no es "técnico" palabra por palabra). Una persona vista en un fotograma es
        visual; un rol que nadie de la ficha respalda, o ninguno, es inferido.
        """
        q = self.quien(grupo)
        persona = q.persona
        if persona is None:
            return (q.rol_suelto or NO_IDENTIFICADO), INFERIDA
        rol = persona.rol
        if q.rol_suelto and (rol is None or self.comparador.coinciden(q.rol_suelto, rol)):
            rol = q.rol_suelto
        if not rol:
            return NO_IDENTIFICADO, INFERIDA
        if not persona.cita.strip():
            return rol, Ubicada("", "visual", "media", persona.t)
        confianza: Confianza = "alta" if confianza_del_rol(persona) == "alta" else "media"
        return rol, Ubicada(persona.cita, "audio", confianza, persona.t)

    def tiempo(self, t_inicio: float, fin: float) -> tuple[float, Ubicada]:
        """La duración narrada en el tramo, si se dice (gana siempre, §5.5); si no, la medida
        (ADR-021), inferida con confianza media."""
        narrada = duracion_narrada(self.analisis.transcripcion, t_inicio, fin)
        if narrada is not None:
            return round(narrada.minutos, 2), Ubicada(narrada.cita, "audio", "alta", narrada.t)
        return round(max(0.0, fin - t_inicio) / 60, 2), Ubicada("", "inferido", "media", None)


def _evidencia(campo: str, valor: str, ubicada: Ubicada) -> Evidencia:
    return Evidencia(
        campo=campo,  # type: ignore[arg-type]
        valor=valor,
        cita=ubicada.cita,
        fuente=ubicada.fuente,
        confianza=ubicada.confianza,
        t=ubicada.t,
    )


def _evidencia_del_paso(grupo: Sequence[PasoVideo]) -> tuple[str, FuenteSOP, Confianza]:
    """La mejor cita de los pasos del video del grupo (ya verificada por la segmentación)."""
    con_cita = [p for p in grupo if p.cita.strip()]
    if not con_cita:
        return "", "inferido", "baja"
    mejor = max(con_cita, key=lambda p: _RANGO_CONFIANZA[p.confianza])
    return mejor.cita, mejor.fuente, mejor.confianza


# ── Cuadro resumen: lo que sale de la ficha y de los pasos ───────────────────────────────────


def _dato_vacio() -> Dato:
    return Dato(valor=None, confianza="baja", fuente="inferido")


def _dato_de_ficha(dato: Dato | None) -> Dato:
    return dato.model_copy() if dato is not None and dato.valor else _dato_vacio()


def _responsable_resumen(pasos: Sequence[PasoSOP]) -> Dato:
    """El responsable del procedimiento: el rol que más pasos tiene (el primero si empatan), con
    la evidencia de su primer paso."""
    conocidos = [p for p in pasos if es_responsable_conocido(p.responsable)]
    if not conocidos:
        return _dato_vacio()
    veces = Counter(comparable(p.responsable) for p in conocidos)
    ganador = max(conocidos, key=lambda p: veces[comparable(p.responsable)])
    ev = next(e for e in ganador.evidencia if e.campo == "responsable")
    return Dato(
        valor=ganador.responsable, confianza=ev.confianza, fuente=ev.fuente, t=ev.t, cita=ev.cita
    )


def _roles(
    pasos: Sequence[PasoSOP], personas: Sequence[Persona], comparador: ComparadorRoles
) -> list[Elemento]:
    """Los roles de las personas de la ficha (y los de los pasos que nadie de la ficha tiene),
    sin repetir. Si el rol de una persona coincide (regla de ADR-020) con el responsable de un
    paso, va el del paso, que la segmentación redactó en español."""
    responsables = [p.responsable for p in pasos if es_responsable_conocido(p.responsable)]
    roles: list[str] = []
    for persona in personas:
        rol = persona.rol
        if rol and es_responsable_conocido(rol):
            roles.append(next((r for r in responsables if comparador.coinciden(r, rol)), rol))
    roles += [r for r in responsables if not any(comparador.coinciden(r, x) for x in roles)]
    vistos: set[str] = set()
    elementos = []
    for rol in roles:
        valor = _valor_lista(rol)
        if valor and (clave := clave_elemento(valor)) not in vistos:
            vistos.add(clave)
            elementos.append(Elemento(nombre=valor))
    return elementos


def _equipo_operacion(pasos: Sequence[PasoSOP], contexto: Contexto | None) -> list[Elemento]:
    """El equipo de los pasos y el de la ficha, sin repetir y en ese orden."""
    nombres = [e for p in pasos for e in p.equipo]
    if contexto is not None:
        nombres += [e.nombre for e in contexto.equipos]
    vistos: set[str] = set()
    elementos = []
    for nombre in nombres:
        valor = _valor_lista(nombre)
        if valor and (clave := clave_elemento(valor)) not in vistos:
            vistos.add(clave)
            elementos.append(Elemento(nombre=valor))
    return elementos


def titulo_de(propuesto: str | None, contexto: Contexto | None, video_id: int) -> str:
    """El título que propuso Gemma; si no, la actividad de la ficha; si no, uno genérico."""
    for opcion in (propuesto, contexto.actividad.valor if contexto else None):
        if titulo := limpiar(opcion, _VACIOS):
            return titulo[:TITULO_MAX]
    return f"Procedimiento del video {video_id}"


def resumen_por_codigo(
    pasos: Sequence[PasoSOP], contexto: Contexto | None, comparador: ComparadorRoles
) -> Resumen:
    """Lo del cuadro resumen que no se le pide a Gemma: lugar y horario (ficha), responsable,
    roles y personas, equipo de operación, duración total (suma de los pasos) y versión."""
    duraciones = [p.tiempo_esperado_min for p in pasos]
    total = round(sum(d for d in duraciones if d is not None), 2) if duraciones else None
    return Resumen(
        version=VERSION_SOP,
        responsable=_responsable_resumen(pasos),
        lugar=_dato_de_ficha(contexto.lugar if contexto else None),
        horario_frecuencia=_dato_de_ficha(contexto.horario_mencionado if contexto else None),
        duracion_total_min=total,
        equipo_operacion=_equipo_operacion(pasos, contexto),
        roles=_roles(pasos, contexto.personas if contexto else [], comparador),
        personas=list(contexto.personas) if contexto else [],
    )


# ── Orquestación ─────────────────────────────────────────────────────────────────────────────


def generar_sop(
    analisis: Analisis,
    pasos_video: Sequence[PasoVideo],
    llm: ClienteLLM,
    contexto: Contexto | None = None,
    *,
    embedder: Embedder | None = None,
    primer_token_s: float | None = None,
    inactividad_s: float | None = None,
    tope_s: float | None = None,
    al_avanzar: Callable[[str], None] | None = None,
    reloj: Callable[[], float] = time.monotonic,
) -> SOPGenerado:
    """Genera el SOP del video (ver el docstring del módulo).

    `pasos_video` son los de la segmentación, antes de fusionar (la guardada o una nueva).
    `contexto` es la ficha (None si no se generó). Los plazos que no se pasan salen de la
    configuración: `LLM_TIMEOUT_S` (primer token), `LLM_INACTIVIDAD_S` y `LLM_TIMEOUT_SOP_S`, el
    tope de toda la generación. `al_avanzar(etapa)` avisa cada llamada ("sop_pasos",
    "sop_resumen", "sop_claves"). Lanza `SinPasosDelVideo` si no hay pasos; nunca por el LLM.
    """
    if not pasos_video:
        raise SinPasosDelVideo(
            "No hay pasos del video para redactar el SOP: la transcripción quedó vacía o sin "
            "pasos. Revisa el audio y vuelve a generar."
        )
    settings = get_settings()
    plazos = _Plazos(
        primer_token_s=settings.llm_timeout_s if primer_token_s is None else primer_token_s,
        inactividad_s=settings.llm_inactividad_s if inactividad_s is None else inactividad_s,
        tope_s=settings.llm_timeout_sop_s if tope_s is None else tope_s,
        reloj=reloj,
        inicio=reloj(),
    )
    avanzar = al_avanzar or (lambda _etapa: None)
    pasos_video = list(pasos_video)
    advertencias: list[AvisoConversion] = []
    llamadas: list[LlamadaLLM] = []
    armado = _Armado(analisis, pasos_video, contexto, ComparadorRoles(embedder))

    avanzar("sop_pasos")
    agrupacion, llamada = _agrupar(analisis, pasos_video, llm, plazos)
    llamadas.append(llamada)
    if agrupacion.metodo == "uno_a_uno":
        advertencias.append(
            _incompleto(f"agrupación ({llamada.motivo}): un paso del SOP por paso del video")
        )

    pasos, llamadas_pasos, sin_redactar = _redactar(analisis, agrupacion, armado, llm, plazos)
    llamadas += llamadas_pasos
    if sin_redactar:
        advertencias.append(
            _incompleto(
                f"pasos sin redactar {sin_redactar}: llevan el nombre del paso del video y "
                "quedan como inferidos"
            )
        )
    for paso in pasos:
        if not empieza_con_infinitivo(paso.nombre):
            advertencias.append(
                AvisoConversion(
                    tipo="infinitivo",
                    mensaje=f"el nombre del paso {paso.numero} no empieza con un infinitivo",
                )
            )

    resumen = resumen_por_codigo(pasos, contexto, armado.comparador)
    sop = SOP(titulo=titulo_de(None, contexto, analisis.video_id), resumen=resumen, pasos=pasos)
    generacion = GeneracionSOP(
        video_id=analisis.video_id,
        modelo=llm.modelo,
        pasos_video=len(pasos_video),
        agrupacion=agrupacion.metodo,
        grupos=agrupacion.grupos,
        fuera=agrupacion.fuera,
        llamadas=llamadas,
        segundos=round(reloj() - plazos.inicio, 2),
    )
    logger.info(
        "SOP generado del video %d: %d pasos (de %d pasos del video, %d fuera), %d llamadas, "
        "%d datos sin evidencia, %d advertencias, %.1f s",
        analisis.video_id,
        len(pasos),
        len(pasos_video),
        len(agrupacion.fuera),
        len(llamadas),
        armado.evidencias.sin_evidencia,
        len(advertencias),
        generacion.segundos,
    )
    return SOPGenerado(sop, advertencias, generacion)


def _agrupar(
    analisis: Analisis, pasos_video: Sequence[PasoVideo], llm: ClienteLLM, plazos: _Plazos
) -> tuple[Agrupacion, LlamadaLLM]:
    prompt = cargar_prompt(PROMPT_AGRUPAR)
    mensajes = _mensajes(prompt, analisis, pasos=_bloques_agrupar(pasos_video, analisis))
    n = len(pasos_video)
    agrupacion, llamada = _llamar(
        llm,
        "agrupar",
        prompt,
        mensajes,
        ESQUEMA_AGRUPAR,
        lambda datos: validar_agrupacion(datos, n),
        plazos,
    )
    return agrupacion or uno_a_uno(pasos_video), llamada


def _redactar(
    analisis: Analisis,
    agrupacion: Agrupacion,
    armado: _Armado,
    llm: ClienteLLM,
    plazos: _Plazos,
) -> tuple[list[PasoSOP], list[LlamadaLLM], list[int]]:
    """Los pasos del SOP, redactados por lotes; los que no se redactaron, por número."""
    prompt = cargar_prompt(PROMPT_PASOS)
    con_fotogramas = bool(analisis.fotogramas)
    esquema = ESQUEMA_PASOS_FOTOGRAMAS if con_fotogramas else ESQUEMA_PASOS
    ficha = _ficha_breve(armado.contexto)
    pasos: list[PasoSOP] = []
    llamadas: list[LlamadaLLM] = []
    sin_redactar: list[int] = []
    grupos = agrupacion.grupos
    for desde in range(0, len(grupos), PASOS_POR_LOTE):
        lote = grupos[desde : desde + PASOS_POR_LOTE]
        bloques = "\n\n".join(
            f"Paso {k}\n"
            + "\n".join(_narracion(p, analisis) for p in armado.grupo(numeros)).strip()
            for k, numeros in enumerate(lote, start=1)
        )
        mensajes = _mensajes(prompt, analisis, ficha=ficha, pasos=bloques)
        crudos, llamada = _llamar(llm, "pasos", prompt, mensajes, esquema, validar_lote, plazos)
        llamadas.append(llamada)
        redactados = _redaccion_de(crudos or [], len(lote), con_fotogramas)
        for k, numeros in enumerate(lote, start=1):
            numero = desde + k
            redaccion = redactados.get(k)
            if redaccion is None:
                sin_redactar.append(numero)
            pasos.append(armado.paso(numero, numeros, redaccion))
    return pasos, llamadas, sin_redactar


def _incompleto(detalle: str) -> AvisoConversion:
    return AvisoConversion(tipo="sop_incompleto", mensaje=f"SOP incompleto: {detalle}")


def _resumen_errores(exc: ValidationError) -> str:
    """Campos y tipos de error, sin los valores (podrían traer texto del video)."""
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'respuesta'}: {e['type']}" for e in exc.errors()
    )


def _redondear(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 2)
