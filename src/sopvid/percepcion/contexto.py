"""Ficha de contexto del video con Gemma 4 (RF-12; SOP V1.0 §6).

Corre después de la transcripción (y, cuando existan, de los fotogramas, RF-11) y antes de los
pasos del video, en la misma ventana en que Gemma está cargado. La usan la afinidad y los roles
(RF-15, RF-17) y el SOP generado.

`generar_contexto` le da al modelo la transcripción por segmento con su número (`[s=N]`) y, solo
si el análisis trae fotogramas, cada fotograma con el suyo (`[f=N]`, desde 1 y por posición). El
modelo nunca ve el SOP (regla 5) ni tiempos: escribe valores y citas, y el código pone lo demás
(regla 4):

- Un dato con su cita en la transcripción: fuente "audio" y `t` = inicio del primer segmento
  donde aparece (o del primero de dos segmentos seguidos, si la frase cruza la frontera), con
  confianza "alta" si la cita tiene de 4 a 25 palabras y "media" si tiene 2 o 3 (el sustantivo
  solo, p. ej. "línea de enjuague": está, pero sin la frase que lo respalda). Uno sin esa cita
  pero con un fotograma que existe: "visual", "media" y el `t` del fotograma. Si no hay ninguna
  de las dos (o la cita tiene menos de 2 palabras): "inferido", "baja" y sin `t`. El resumen
  siempre es "inferido" con confianza "media", sin cita.
- Una persona necesita nombre o rol, y una cita verificada (o un fotograma que exista): sin eso
  no hay un segundo que ponerle (`Persona.t` es obligatorio) y se descarta.
- Los equipos son los que nombra el modelo más los de los fotogramas, sin repetir.

Sin fotogramas, ni el prompt ni el esquema los mencionan (no se gastan tokens en algo que no
existe): `ESQUEMA_CONTEXTO` no tiene el campo `f`, que solo trae `ESQUEMA_CONTEXTO_FOTOGRAMAS`.

La llamada va en flujo (`ClienteLLM.chat_en_flujo`) con los cortes de la conversión del SOP:
primer token en `LLM_TIMEOUT_S`, `LLM_INACTIVIDAD_S` sin tokens y un tope total
`LLM_TIMEOUT_CONTEXTO_S` que cubre los reintentos. Se reintenta solo si la respuesta no es un JSON
del esquema (hasta `MAX_INTENTOS`); un corte por tiempo o un Ollama caído no se reintenta. Nunca
lanza por el LLM: si falla, la ficha va vacía y `ResultadoContexto.motivo` dice por qué (ADR-019:
el procesamiento sigue y el reporte lleva el aviso "contexto_sin_generar"). Los logs solo llevan
conteos, nunca texto del video.
"""

import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cache
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sopvid.contrato import (
    Analisis,
    Aviso,
    Confianza,
    Contexto,
    Dato,
    Elemento,
    Fotograma,
    Participacion,
    Persona,
    Segmento,
)
from sopvid.lenguaje.juez import Prompt, leer_prompt, texto_del_prompt
from sopvid.lenguaje.llm import (
    ClienteLLM,
    LLMError,
    LLMRespuestaInvalida,
    LLMTiempoExcedido,
    tokens_por_segundo,
)
from sopvid.percepcion.segmentacion import _sin_refs
from sopvid.percepcion.transcripcion import aviso_transcripcion
from sopvid.plataforma.config import get_settings
from sopvid.texto import (
    NO_IDENTIFICADO,
    VACIOS,
    comparable,
    contar_palabras,
    contiene_cita,
    limpiar,
    recortar_palabras,
)

logger = logging.getLogger(__name__)

PROMPT = "contexto_v2"  # archivo en lenguaje/prompts/; un prompt nuevo es un archivo nuevo
MAX_INTENTOS = 3  # una llamada más dos reintentos si la respuesta no es un JSON del esquema
# Largo de la cita: menos que el mínimo no vale como evidencia; una más larga que el máximo se
# recorta. Desde `PALABRAS_CITA_ALTA` la confianza es "alta"; por debajo, "media".
PALABRAS_CITA = (2, 25)
PALABRAS_CITA_ALTA = 4
CARACTERES_POR_TOKEN = 3.5  # para avisar en el log si la entrada no cabe en `num_ctx`
SALIDA_ESTIMADA = 600  # tokens de una ficha (medido con A: ver docs/adr/datos/contexto/)

# Por qué la ficha quedó vacía.
MotivoContexto = Literal[
    "transcripcion_vacia", "llm_no_disponible", "tiempo_excedido", "respuesta_invalida"
]

# Además de los vacíos comunes, lo que el modelo escribe cuando un dato no se dice.
_VACIOS_CONTEXTO = VACIOS | {
    "no se menciona",
    "no mencionado",
    "no se dice",
    "no especificado",
    "desconocido",
    "no aplica",
}
_NOMBRES_VACIOS = _VACIOS_CONTEXTO | {comparable(NO_IDENTIFICADO), "anonimo", "sin nombre"}
_DATOS = ("actividad", "tema", "lugar", "horario_mencionado", "proposito")
_MARCADORES = {
    "sistema": frozenset(),
    "sistema_fotogramas": frozenset(),
    "usuario": frozenset({"idioma", "segmentos"}),
    "usuario_fotogramas": frozenset({"fotogramas"}),
    "correccion": frozenset({"motivo"}),
}


# ── Respuesta del LLM ────────────────────────────────────────────────────────────────────────
# Solo lo que el código no puede calcular: valores y citas. Nada de tiempos, fuente, confianza
# ni conteos. La cita va antes del valor para que el valor se apoye en ella. Sin docstrings:
# Pydantic los pondría en el esquema que va a Ollama.


class _Libre(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _DatoLibre(_Libre):
    cita: str
    valor: str | None


class _PersonaLibre(_Libre):
    cita: str
    nombre: str
    rol: str | None
    participacion: Participacion


class _ContextoLibre(_Libre):
    actividad: _DatoLibre
    tema: _DatoLibre
    lugar: _DatoLibre
    horario_mencionado: _DatoLibre
    proposito: _DatoLibre
    resumen: str | None
    personas: list[_PersonaLibre]
    equipos: list[str]


# Con fotogramas: lo mismo más `f`, el número del fotograma que respalda el dato o la persona.
class _DatoVisual(_DatoLibre):
    f: int | None = Field(default=None, ge=1)


class _PersonaVisual(_PersonaLibre):
    f: int | None = Field(default=None, ge=1)


class _ContextoVisual(_Libre):
    actividad: _DatoVisual
    tema: _DatoVisual
    lugar: _DatoVisual
    horario_mencionado: _DatoVisual
    proposito: _DatoVisual
    resumen: str | None
    personas: list[_PersonaVisual]
    equipos: list[str]


ESQUEMA_CONTEXTO: dict[str, Any] = _sin_refs(_ContextoLibre.model_json_schema())
ESQUEMA_CONTEXTO_FOTOGRAMAS: dict[str, Any] = _sin_refs(_ContextoVisual.model_json_schema())


def esquema_para(analisis: Analisis) -> dict[str, Any]:
    """El esquema de la salida: con el campo `f` solo si hay fotogramas."""
    return ESQUEMA_CONTEXTO_FOTOGRAMAS if analisis.fotogramas else ESQUEMA_CONTEXTO


# ── Prompt y entrada ─────────────────────────────────────────────────────────────────────────


@cache
def cargar_prompt(version: str = PROMPT) -> Prompt:
    """Lee `prompts/<version>.md`: las tres secciones de siempre más las de fotogramas."""
    return leer_prompt(version, texto_del_prompt(version), _MARCADORES)


def construir_mensajes(analisis: Analisis, prompt: Prompt | None = None) -> list[dict[str, str]]:
    """Mensajes de sistema y de usuario. Las secciones de fotogramas solo van si los hay."""
    prompt = prompt or cargar_prompt()
    sistema = prompt.sistema
    usuario = prompt.usuario.substitute(
        idioma=analisis.idioma.codigo, segmentos=_segmentos(analisis.transcripcion)
    )
    if analisis.fotogramas:
        sistema += "\n\n" + prompt.extras["sistema_fotogramas"].substitute()
        usuario += "\n\n" + prompt.extras["usuario_fotogramas"].substitute(
            fotogramas=_fotogramas(analisis.fotogramas)
        )
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def _segmentos(segmentos: Sequence[Segmento]) -> str:
    return "\n".join(
        f"[s={s.id}] {texto}" for s in segmentos if (texto := " ".join(s.texto.split()))
    )


def _fotogramas(fotogramas: Sequence[Fotograma]) -> str:
    """Un fotograma por línea, sin su tiempo: descripción, equipos, texto visible y personas."""
    lineas = []
    for n, f in enumerate(fotogramas, start=1):
        partes = [limpiar(f.descripcion) or "(sin descripción)"]
        if equipos := [e for x in f.equipos if (e := limpiar(x))]:
            partes.append("equipos: " + "; ".join(equipos))
        if visible := [e for x in f.texto_visible if (e := limpiar(x))]:
            partes.append("texto visible: " + "; ".join(visible))
        if f.personas:
            partes.append(f"personas: {f.personas}")
        lineas.append(f"[f={n}] " + " | ".join(partes))
    return "\n".join(lineas)


# ── Resultado ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResultadoContexto:
    """La ficha y cómo se obtuvo.

    `generado` es False si la ficha quedó vacía por una falla (`motivo`); entonces no se guarda
    en `videos.contexto`. Las métricas (`tokens_*`, `primer_token_s`, `tokens_por_s`) son las del
    intento válido, o None si no lo hubo; `segundos` es lo que tardó toda la etapa, con sus
    reintentos. `fotogramas` cuenta los que entraron al prompt. `citas_no_verificadas` cuenta los
    datos que se quedaron como inferidos porque su cita no aparece (o no traían) y
    `personas_descartadas`, las que no tenían nombre ni rol, o cita ni fotograma.
    """

    contexto: Contexto
    generado: bool
    motivo: MotivoContexto | None = None
    prompt: str = PROMPT
    modelo: str | None = None
    intentos: int = 0
    tokens_entrada: int | None = None
    tokens_salida: int | None = None
    primer_token_s: float | None = None
    tokens_por_s: float | None = None
    segundos: float = 0.0
    fotogramas: int = 0
    citas_no_verificadas: int = 0
    personas_descartadas: int = 0


def aviso_contexto(resultado: ResultadoContexto) -> Aviso | None:
    """El aviso "contexto_sin_generar" si la ficha quedó vacía (sin texto del video)."""
    if resultado.generado:
        return None
    intentos = f" tras {resultado.intentos} intentos" if resultado.intentos > 1 else ""
    return Aviso(
        tipo="contexto_sin_generar",
        detalle=f"ficha de contexto vacía: {resultado.motivo}{intentos}",
    )


# ── Generación ───────────────────────────────────────────────────────────────────────────────


def generar_contexto(
    analisis: Analisis,
    cliente_llm: ClienteLLM,
    *,
    primer_token_s: float | None = None,
    inactividad_s: float | None = None,
    tope_s: float | None = None,
    version: str = PROMPT,
    reloj: Callable[[], float] = time.monotonic,
) -> ResultadoContexto:
    """Pide la ficha a Gemma y la arma con la evidencia (ver el docstring del módulo).

    Los plazos que no se pasan salen de la configuración: `LLM_TIMEOUT_S` (primer token),
    `LLM_INACTIVIDAD_S` y `LLM_TIMEOUT_CONTEXTO_S` (tope total). `version` elige el prompt
    (para comparar versiones; en producción, `PROMPT`). Con la transcripción vacía no llama al
    modelo. Nunca lanza por el LLM: la falla queda en `motivo`.
    """
    settings = get_settings()
    primer = settings.llm_timeout_s if primer_token_s is None else primer_token_s
    inactividad = settings.llm_inactividad_s if inactividad_s is None else inactividad_s
    tope = settings.llm_timeout_contexto_s if tope_s is None else tope_s
    inicio = reloj()
    n_fotogramas = len(analisis.fotogramas)

    def vacio(motivo: MotivoContexto, intentos: int) -> ResultadoContexto:
        logger.warning(
            "Ficha de contexto del video %d sin generar: %s (%d intentos)",
            analisis.video_id,
            motivo,
            intentos,
        )
        return ResultadoContexto(
            Contexto(),
            generado=False,
            motivo=motivo,
            prompt=version,
            modelo=cliente_llm.modelo if intentos else None,
            intentos=intentos,
            segundos=round(reloj() - inicio, 2),
            fotogramas=n_fotogramas,
        )

    if not any(s.texto.strip() for s in analisis.transcripcion):
        return vacio("transcripcion_vacia", 0)

    prompt = cargar_prompt(version)
    base = construir_mensajes(analisis, prompt)
    _revisar_ventana(base, cliente_llm.num_ctx)
    esquema = esquema_para(analisis)
    modelo = _ContextoVisual if analisis.fotogramas else _ContextoLibre
    historial = list(base)
    for intento in range(1, MAX_INTENTOS + 1):
        restante = tope - (reloj() - inicio)
        if restante <= 0:
            return vacio("tiempo_excedido", intento - 1)
        try:
            respuesta = cliente_llm.chat_en_flujo(
                historial,
                esquema=esquema,
                primer_token_s=primer,
                inactividad_s=inactividad,
                tope_s=restante,
            )
        except LLMTiempoExcedido:
            return vacio("tiempo_excedido", intento)
        except LLMRespuestaInvalida:
            correccion = "no devolviste un JSON válido"
        except LLMError as exc:
            logger.warning("Ficha de contexto: LLM no disponible (%s)", type(exc).__name__)
            return vacio("llm_no_disponible", intento)
        else:
            try:
                libre = modelo.model_validate(respuesta.datos)
            except ValidationError as exc:
                correccion = _resumen_errores(exc)
            else:
                armado = _Armado(analisis)
                contexto = armado.contexto(libre)
                resultado = ResultadoContexto(
                    contexto,
                    generado=True,
                    prompt=version,
                    modelo=respuesta.modelo,
                    intentos=intento,
                    tokens_entrada=respuesta.metricas.get("prompt_eval_count"),
                    tokens_salida=respuesta.metricas.get("eval_count"),
                    primer_token_s=_redondear(respuesta.primer_token_s),
                    tokens_por_s=_redondear(tokens_por_segundo(respuesta.metricas)),
                    segundos=round(reloj() - inicio, 2),
                    fotogramas=n_fotogramas,
                    citas_no_verificadas=armado.citas_no_verificadas,
                    personas_descartadas=armado.personas_descartadas,
                )
                _registrar(analisis.video_id, resultado)
                return resultado
        logger.warning(
            "Ficha de contexto: respuesta inválida (intento %d de %d): %s",
            intento,
            MAX_INTENTOS,
            correccion,
        )
        correccion_usuario = prompt.correccion.substitute(motivo=correccion)
        historial = [*base, {"role": "user", "content": correccion_usuario}]
    return vacio("respuesta_invalida", MAX_INTENTOS)


def ubicar_cita(cita: str, segmentos: Sequence[Segmento]) -> tuple[float, Confianza] | None:
    """(`t_inicio` del primer segmento donde aparece la cita, confianza), o None.

    La cita se recorta a `PALABRAS_CITA[1]` palabras (el recorte de una cita literal sigue siendo
    literal) y necesita al menos `PALABRAS_CITA[0]`. Confianza "alta" desde `PALABRAS_CITA_ALTA`
    palabras y "media" por debajo. Si no aparece en ningún segmento solo, se busca en cada par de
    segmentos seguidos (una frase que `resegmentar` partió en dos) y vale el inicio del primero
    del par.
    """
    minimo, maximo = PALABRAS_CITA
    recortada = recortar_palabras(" ".join(cita.split()), maximo)
    n = contar_palabras(recortada)
    if n < minimo:
        return None
    confianza: Confianza = "alta" if n >= PALABRAS_CITA_ALTA else "media"
    for s in segmentos:
        if contiene_cita(s.texto, recortada):
            return s.t_inicio, confianza
    for a, b in pairwise(segmentos):
        if contiene_cita(f"{a.texto} {b.texto}", recortada):
            return a.t_inicio, confianza
    return None


@dataclass
class _Armado:
    """Arma el `Contexto` con la evidencia y cuenta lo que no la tuvo."""

    analisis: Analisis
    citas_no_verificadas: int = 0
    personas_descartadas: int = 0
    _personas: dict[tuple[str, str], Persona] = field(default_factory=dict)

    def contexto(self, r: _ContextoLibre | _ContextoVisual) -> Contexto:
        resumen = limpiar(r.resumen, _VACIOS_CONTEXTO)
        for p in r.personas:
            self._persona(p)
        return Contexto(
            **{campo: self._dato(getattr(r, campo)) for campo in _DATOS},
            resumen=(
                Dato(valor=resumen, confianza="media", fuente="inferido")
                if resumen
                else Contexto().resumen
            ),
            personas=list(self._personas.values()),
            equipos=self._equipos(r.equipos),
            avisos=[a for a in (aviso_transcripcion(self.analisis),) if a is not None],
        )

    def _evidencia(self, cita: str, f: int | None) -> tuple[float, str, Confianza] | None:
        """(t, fuente, confianza) de la cita en la transcripción o, si no, del fotograma."""
        if cita and (ubicada := ubicar_cita(cita, self.analisis.transcripcion)) is not None:
            t, confianza = ubicada
            return t, "audio", confianza
        fotogramas = self.analisis.fotogramas
        if f is not None and 1 <= f <= len(fotogramas):
            return fotogramas[f - 1].t, "visual", "media"
        return None

    def _dato(self, d: _DatoLibre) -> Dato:
        valor = limpiar(d.valor, _VACIOS_CONTEXTO)
        if not valor:
            return Contexto().actividad  # vacío: inferido, confianza baja
        evidencia = self._evidencia(limpiar(d.cita, _VACIOS_CONTEXTO), getattr(d, "f", None))
        if evidencia is None:
            self.citas_no_verificadas += 1
            return Dato(valor=valor, confianza="baja", fuente="inferido")
        t, fuente, confianza = evidencia
        return Dato(valor=valor, confianza=confianza, fuente=fuente, t=t)

    def _persona(self, p: _PersonaLibre) -> None:
        nombre = limpiar(p.nombre, _NOMBRES_VACIOS) or NO_IDENTIFICADO
        rol = limpiar(p.rol, _VACIOS_CONTEXTO) or None
        cita = recortar_palabras(limpiar(p.cita, _VACIOS_CONTEXTO), PALABRAS_CITA[1])
        evidencia = self._evidencia(cita, getattr(p, "f", None))
        if (nombre == NO_IDENTIFICADO and rol is None) or evidencia is None:
            self.personas_descartadas += 1
            return
        t, fuente, _ = evidencia
        # Con nombre, se identifica por él; sin nombre, por su rol.
        clave = (comparable(nombre), "") if nombre != NO_IDENTIFICADO else ("", comparable(rol))
        previa = self._personas.get(clave)
        if previa is None:
            self._personas[clave] = Persona(
                nombre=nombre,
                rol=rol,
                participacion=p.participacion,
                t=t,
                cita=cita if fuente == "audio" else "",
            )
            return
        # La misma persona otra vez: se queda la primera aparición, con el rol si le faltaba y
        # "participa" si en alguna aparición participa.
        self._personas[clave] = previa.model_copy(
            update={
                "rol": previa.rol or rol,
                "participacion": (
                    "participa"
                    if "participa" in (previa.participacion, p.participacion)
                    else "mencionado"
                ),
            }
        )

    def _equipos(self, nombrados: Sequence[str]) -> list[Elemento]:
        """Los que nombra el modelo y los de los fotogramas, sin repetir y en ese orden."""
        vistos: set[str] = set()
        equipos = []
        de_fotogramas = (e for f in self.analisis.fotogramas for e in f.equipos)
        for x in (*nombrados, *de_fotogramas):
            nombre = limpiar(x, _VACIOS_CONTEXTO)
            if nombre and (clave := comparable(nombre)) not in vistos:
                vistos.add(clave)
                equipos.append(Elemento(nombre=nombre))
        return equipos


def _revisar_ventana(mensajes: Sequence[dict[str, str]], num_ctx: int) -> None:
    """Avisa en el log si la entrada estimada más la ficha no caben en `num_ctx`. Se usa la
    ventana del cliente, la misma de la segmentación, para que Ollama no recargue el modelo."""
    entrada = sum(math.ceil(len(m["content"]) / CARACTERES_POR_TOKEN) for m in mensajes)
    if entrada + SALIDA_ESTIMADA > num_ctx:
        logger.warning(
            "Ficha de contexto: ~%d tokens de entrada más la ficha pueden no caber en num_ctx=%d",
            entrada,
            num_ctx,
        )


def _resumen_errores(exc: ValidationError) -> str:
    """Campos y tipos de error de Pydantic, sin los valores (podrían traer texto del video)."""
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'respuesta'}: {e['type']}" for e in exc.errors()
    )


def _redondear(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 2)


def _registrar(video_id: int, r: ResultadoContexto) -> None:
    c = r.contexto
    con_valor = sum(getattr(c, campo).valor is not None for campo in _DATOS)
    con_cita = sum(getattr(c, campo).fuente in ("audio", "visual") for campo in _DATOS)
    logger.info(
        "Ficha de contexto del video %d (%s, intento %d): %d de %d datos con valor, %d con "
        "evidencia; %d personas (%d descartadas), %d equipos, %d fotogramas; %s tokens de "
        "entrada, %s de salida, %.1f s",
        video_id,
        r.prompt,
        r.intentos,
        con_valor,
        len(_DATOS),
        con_cita,
        len(c.personas),
        r.personas_descartadas,
        len(c.equipos),
        r.fotogramas,
        r.tokens_entrada,
        r.tokens_salida,
        r.segundos,
    )
