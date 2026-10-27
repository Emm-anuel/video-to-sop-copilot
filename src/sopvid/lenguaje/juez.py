"""Juez Gemma 4 de la zona gris (ADR-012, punto 3).

Un par SOP–video con coseno MiniLM entre `UMBRAL_BAJO` y `UMBRAL_ALTO` queda en "zona_gris"
tras `clasificar`. El juez lee el paso del SOP, el paso del video y la narración de ese paso, y
decide *Cumple*, *Parcial* o "no_corresponde", con una justificación corta y una cita.

- `Juez` es la interfaz (como `Emparejador`): cualquier objeto con `juzgar` sirve, y sin juez
  la cascada queda como antes. `JuezGemma` la cumple con el cliente de `llm.py` (salida
  restringida por JSON Schema, temperatura 0 y `SEMILLA`).
- El prompt vive en `prompts/<PROMPT>.md`, versionado; no en el código.
- La cita se verifica con código contra la narración del paso (regla 4 de CLAUDE.md, igual
  que RF-13): debe aparecer tal cual. El juez nunca ve ni escribe tiempos, y el coseno no va
  en el prompt para no sesgarlo.
- Si la respuesta no es válida (JSON roto, cita inventada), se reintenta hasta
  `MAX_INTENTOS`. Si aun así no hay respuesta válida, o si Ollama no responde, el par queda en
  zona_gris con un `Juicio` de respaldo: nunca se inventa un estado.
- `aplicar_juez` aplica las decisiones a una `Clasificacion`: "no_corresponde" rompe el par en
  un Falta (paso del SOP) y un Sobra (paso del video).

Los mensajes de error y de log nunca llevan texto de la transcripción ni del SOP (pueden ser
material del cliente): solo campos, tipos de error y conteos.
"""

import logging
import string
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from sopvid.contrato import (
    ESTADOS,
    RESULTADOS_JUEZ,
    Clasificacion,
    Juicio,
    MotivoRespaldo,
    PasoSOP,
    PasoVideo,
    ResultadoJuez,
    ResultadoPaso,
    Segmento,
    Veredicto,
)
from sopvid.lenguaje.llm import ClienteLLM, LLMError, LLMRespuestaInvalida
from sopvid.texto import contar_palabras, contiene_cita, recortar_palabras

logger = logging.getLogger(__name__)

PROMPT = "juez_zona_gris_v1"  # archivo en prompts/; un prompt nuevo es un archivo nuevo
MAX_INTENTOS = 3  # una llamada más dos reintentos si la respuesta no es válida
PALABRAS_CITA = (4, 15)  # igual que la cita de los pasos del video (RF-13)
MAX_JUSTIFICACION = 300  # caracteres; una más larga se recorta en una frontera de palabra

# Secciones del archivo del prompt y los marcadores que debe usar cada una.
_MARCADORES: dict[str, frozenset[str]] = {
    "sistema": frozenset(),
    "usuario": frozenset(
        {
            "sop_nombre",
            "sop_descripcion",
            "sop_puntos",
            "sop_equipo",
            "video_nombre",
            "video_descripcion",
            "narracion",
        }
    ),
    "correccion": frozenset({"motivo"}),
}


class Juez(Protocol):
    """Interfaz del juez de la zona gris: decide sobre un par y devuelve un `Juicio`.

    `narracion` es lo que dijo el operador durante el paso del video (`narracion_de`), sin
    tiempos. Nunca lanza por un problema del LLM: en ese caso devuelve un juicio de respaldo.
    """

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio: ...


# ── Prompt versionado ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Prompt:
    """Prompt del juez leído de su archivo: el mensaje de sistema y dos plantillas."""

    version: str
    sistema: str
    usuario: string.Template
    correccion: string.Template


@cache
def cargar_prompt(version: str = PROMPT) -> Prompt:
    """Lee `prompts/<version>.md` del paquete (ver `leer_prompt`)."""
    archivo = resources.files("sopvid.lenguaje") / "prompts" / f"{version}.md"
    return leer_prompt(version, archivo.read_text(encoding="utf-8"))


def leer_prompt(version: str, texto: str) -> Prompt:
    """Separa las secciones `## sistema`, `## usuario` y `## correccion` de `texto`.

    Lo que va antes de la primera sección es documentación y se ignora. Falla si falta o sobra
    una sección, o si una plantilla no usa exactamente sus marcadores (`$nombre`).
    """
    secciones: dict[str, list[str]] = {}
    actual: list[str] | None = None
    for linea in texto.splitlines():
        if linea.startswith("## "):
            nombre = linea[3:].strip()
            if nombre in secciones:
                raise ValueError(f"prompt {version}: la sección {nombre!r} está repetida")
            actual = secciones[nombre] = []
        elif actual is not None:
            actual.append(linea)
    if set(secciones) != set(_MARCADORES):
        raise ValueError(
            f"prompt {version}: se esperaban las secciones {sorted(_MARCADORES)} "
            f"y hay {sorted(secciones)}"
        )
    cuerpo = {nombre: "\n".join(lineas).strip() for nombre, lineas in secciones.items()}
    for nombre, esperados in _MARCADORES.items():
        plantilla = string.Template(cuerpo[nombre])
        if not plantilla.is_valid() or set(plantilla.get_identifiers()) != esperados:
            raise ValueError(
                f"prompt {version}: la sección {nombre!r} debe usar los marcadores "
                f"{sorted(esperados)}"
            )
    return Prompt(
        version=version,
        sistema=cuerpo["sistema"],
        usuario=string.Template(cuerpo["usuario"]),
        correccion=string.Template(cuerpo["correccion"]),
    )


def construir_mensajes(
    prompt: Prompt, paso_sop: PasoSOP, paso_video: PasoVideo, narracion: str
) -> list[dict[str, str]]:
    """Mensajes de sistema y de usuario para un par. Solo van este paso del SOP y este paso
    del video: ni el resto del SOP, ni tiempos, ni el coseno."""
    usuario = prompt.usuario.substitute(
        sop_nombre=_linea(paso_sop.nombre),
        sop_descripcion=_linea(paso_sop.descripcion, "(ninguna)"),
        sop_puntos=_lista(paso_sop.puntos_validacion),
        sop_equipo=_lista(paso_sop.equipo),
        video_nombre=_linea(paso_video.nombre),
        video_descripcion=_linea(paso_video.descripcion, "(ninguna)"),
        narracion=narracion,
    )
    return [{"role": "system", "content": prompt.sistema}, {"role": "user", "content": usuario}]


def _linea(texto: str, vacio: str = "(ninguno)") -> str:
    return " ".join(texto.split()) or vacio


def _lista(elementos: Sequence[str]) -> str:
    return "; ".join(e for x in elementos if (e := _linea(x, ""))) or "(ninguno)"


# ── Narración del paso ───────────────────────────────────────────────────────────────────────


def narracion_de(paso_video: PasoVideo, transcripcion: Sequence[Segmento]) -> str:
    """Lo que dijo el operador durante `paso_video`, cortado por palabra y sin tiempos.

    Toma las palabras de la transcripción cuyo inicio cae dentro del paso: `t_inicio ≤ t <
    t_fin`, más una palabra de duración 0 justo en `t_fin` (cae entera dentro). Una palabra con
    duración que empieza justo donde el paso termina es del paso siguiente: Whisper suele dar
    palabras contiguas. Cortar por palabra y no por segmento evita que un segmento que cruza la
    frontera entre dos pasos deje entrar texto del vecino, que el juez podría citar. Un segmento
    sin tiempos por palabra solo cuenta si cae entero dentro del paso.
    """
    inicio, fin = paso_video.t_inicio, paso_video.t_fin
    palabras: list[str] = []
    for segmento in transcripcion:
        if segmento.palabras:
            palabras += [
                p.w
                for p in segmento.palabras
                if inicio <= p.t and (p.t < fin or p.t == p.t_fin == fin)
            ]
        elif inicio <= segmento.t_inicio and segmento.t_fin <= fin:
            palabras += segmento.texto.split()
    return " ".join(palabras)


# ── Respuesta del LLM ────────────────────────────────────────────────────────────────────────


class _RespuestaJuez(BaseModel):
    """Lo que devuelve el LLM. La cita va primero, para que el veredicto se apoye en ella."""

    model_config = ConfigDict(extra="forbid")

    cita: str
    justificacion: str
    veredicto: Veredicto


ESQUEMA_JUEZ: dict[str, Any] = _RespuestaJuez.model_json_schema()


class RespuestaInvalida(ValueError):  # noqa: N818 (nombre de dominio)
    """La respuesta del juez no pasa las reglas del dominio. El mensaje solo trae campos,
    tipos de error y conteos, nunca texto de la transcripción ni del SOP."""


@dataclass(frozen=True)
class Decision:
    """Respuesta válida del juez, con la cita ya verificada contra la narración."""

    veredicto: Veredicto
    justificacion: str
    cita: str


def validar_respuesta(datos: Any, narracion: str) -> Decision:
    """Valida la respuesta del LLM contra el esquema y las reglas del dominio.

    La cita, con los espacios colapsados, se recorta a `PALABRAS_CITA[1]` palabras (el
    recorte de una cita literal sigue siendo literal), debe tener al menos `PALABRAS_CITA[0]`
    (o toda la narración si es más corta) y debe aparecer tal cual en `narracion`. La
    justificación no puede ir vacía; si pasa de `MAX_JUSTIFICACION` caracteres, se recorta.
    """
    try:
        respuesta = _RespuestaJuez.model_validate(datos)
    except ValidationError as exc:
        raise RespuestaInvalida(_resumen_errores(exc)) from None
    maximo = PALABRAS_CITA[1]
    cita = recortar_palabras(" ".join(respuesta.cita.split()), maximo)
    minimo = min(PALABRAS_CITA[0], contar_palabras(narracion))
    if (n := contar_palabras(cita)) < minimo:
        raise RespuestaInvalida(f"la cita tiene {n} palabras y debe tener de {minimo} a {maximo}")
    if not contiene_cita(narracion, cita):
        raise RespuestaInvalida("la cita no aparece tal cual en la narración del paso")
    justificacion = _recortar_justificacion(respuesta.justificacion)
    if not justificacion:
        raise RespuestaInvalida("la justificación está vacía")
    return Decision(respuesta.veredicto, justificacion, cita)


def _resumen_errores(exc: ValidationError) -> str:
    """Campos y tipos de error de Pydantic, sin los valores (podrían traer texto citado)."""
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'respuesta'}: {e['type']}" for e in exc.errors()
    )


def _recortar_justificacion(texto: str) -> str:
    limpio = " ".join(texto.split())
    if len(limpio) <= MAX_JUSTIFICACION:
        return limpio
    corte = limpio.rfind(" ", 0, MAX_JUSTIFICACION)
    return limpio[: corte if corte > 0 else MAX_JUSTIFICACION].rstrip(" ,;:") + "…"


def respaldo(
    similitud: float, motivo: MotivoRespaldo, intentos: int = 0, prompt: str = PROMPT
) -> Juicio:
    """Juicio de respaldo: el juez no pudo decidir y el par queda en zona_gris (sin revisar)."""
    return Juicio(
        origen="respaldo", similitud=similitud, prompt=prompt, intentos=intentos, motivo=motivo
    )


# ── Juez con Gemma 4 ─────────────────────────────────────────────────────────────────────────


class JuezGemma:
    """`Juez` con el LLM local de `llm.py` (Gemma 4 por configuración, ADR-006).

    La salida se restringe con `ESQUEMA_JUEZ`; temperatura 0 y semilla `SEMILLA` las fija el
    cliente. No guarda estado entre llamadas: si Ollama está caído, cada llamada lo vuelve a
    intentar (`aplicar_juez` es quien deja de llamarlo durante una corrida). Sin `prompt`, usa
    el de `PROMPT`.
    """

    def __init__(self, llm: ClienteLLM, prompt: Prompt | None = None) -> None:
        self._llm = llm
        self.prompt = prompt or cargar_prompt()

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio:
        """Decide sobre el par, con hasta `MAX_INTENTOS` llamadas.

        Se reintenta si el modelo no devolvió JSON válido o si la respuesta no pasa
        `validar_respuesta`: cada reintento agrega la respuesta anterior (si se pudo leer) y un
        mensaje de corrección con el motivo. Si Ollama no responde o rechaza la petición, no se
        reintenta aquí (el cliente ya reintentó el transporte): respaldo "llm_no_disponible".
        Sin narración no hay qué citar: respaldo "sin_narracion", sin llamar al LLM.
        """
        version = self.prompt.version
        if not narracion.split():
            return respaldo(similitud, "sin_narracion", 0, version)
        historial = construir_mensajes(self.prompt, paso_sop, paso_video, narracion)
        for intento in range(1, MAX_INTENTOS + 1):
            anterior: str | None = None
            try:
                respuesta = self._llm.chat(historial, esquema=ESQUEMA_JUEZ)
            except LLMRespuestaInvalida:
                motivo = "no devolviste un JSON válido"
            except LLMError as exc:
                logger.warning("Juez: LLM no disponible o con error (%s)", type(exc).__name__)
                return respaldo(similitud, "llm_no_disponible", intento, version)
            else:
                try:
                    decision = validar_respuesta(respuesta.datos, narracion)
                except RespuestaInvalida as exc:
                    motivo, anterior = str(exc), respuesta.texto
                else:
                    return Juicio(
                        origen="llm",
                        veredicto=decision.veredicto,
                        justificacion=decision.justificacion,
                        cita=decision.cita,
                        similitud=similitud,
                        prompt=version,
                        modelo=respuesta.modelo,
                        intentos=intento,
                    )
            logger.warning(
                "Juez: respuesta inválida (intento %d de %d): %s", intento, MAX_INTENTOS, motivo
            )
            if anterior is not None:
                historial.append({"role": "assistant", "content": anterior})
            historial.append(
                {"role": "user", "content": self.prompt.correccion.substitute(motivo=motivo)}
            )
        return respaldo(similitud, "respuesta_invalida", MAX_INTENTOS, version)


# ── Aplicar el juez a una clasificación ──────────────────────────────────────────────────────


def aplicar_juez(
    clasificacion: Clasificacion,
    pasos_sop: Sequence[PasoSOP],
    pasos_video: Sequence[PasoVideo],
    transcripcion: Sequence[Segmento],
    juez: Juez,
) -> Clasificacion:
    """Pasa cada par en zona_gris por `juez` y aplica su decisión.

    - Cumple o Parcial: el par toma ese estado y lleva el `Juicio`.
    - no_corresponde: el par se rompe en un Falta (paso del SOP) y un Sobra (paso del video,
      con su tiempo y su cita), los dos con el `Juicio`.
    - respaldo: el par sigue en zona_gris con el `Juicio` de respaldo ("sin revisar").

    Si un juicio llega con motivo "llm_no_disponible", los pares que siguen en esta misma
    llamada no se envían al juez: reciben ese respaldo con `intentos=0` (evita esperar el
    timeout de Ollama una vez por par). Ese estado vive solo en esta llamada; la siguiente
    vuelve a intentar con el LLM.

    `pasos_video` son los que se emparejaron (los fusionados de `emparejar`) y `transcripcion`
    la del mismo video. Devuelve una clasificación nueva con el resumen del juez y sin marcas
    de orden: después hay que correr `orden` (lo hace `emparejar`), que revisa también los
    Parcial.
    """
    caido: Juicio | None = None
    por_sop: list[ResultadoPaso] = []
    sobran: list[ResultadoPaso] = []
    for paso in clasificacion.pasos:
        datos = paso.model_dump() | {
            "fuera_de_orden": False,
            "posicion_esperada": None,
            "posicion_observada": None,
        }
        if paso.estado != "zona_gris":
            (sobran if paso.estado == "Sobra" else por_sop).append(
                ResultadoPaso.model_validate(datos)
            )
            continue
        assert paso.indice_sop is not None and paso.indice_video is not None
        assert paso.similitud is not None
        if caido is not None:
            juicio = caido.model_copy(update={"similitud": paso.similitud, "intentos": 0})
        else:
            video = pasos_video[paso.indice_video]
            narracion = narracion_de(video, transcripcion)
            juicio = juez.juzgar(pasos_sop[paso.indice_sop], video, paso.similitud, narracion)
            if juicio.motivo == "llm_no_disponible":
                caido = juicio
        if juicio.origen == "respaldo":
            por_sop.append(ResultadoPaso.model_validate(datos | {"juicio": juicio}))
        elif juicio.veredicto == "no_corresponde":
            por_sop.append(ResultadoPaso(estado="Falta", indice_sop=paso.indice_sop, juicio=juicio))
            sobran.append(
                ResultadoPaso.model_validate(
                    datos
                    | {"estado": "Sobra", "indice_sop": None, "similitud": None, "juicio": juicio}
                )
            )
        else:
            por_sop.append(
                ResultadoPaso.model_validate(datos | {"estado": juicio.veredicto, "juicio": juicio})
            )

    pasos = por_sop + sorted(sobran, key=lambda p: p.indice_video or 0)  # orden del video
    resumen_juez = _resumen_juez(pasos)
    conteo = dict.fromkeys(ESTADOS, 0)
    for p in pasos:
        conteo[p.estado] += 1
    resumen = clasificacion.resumen.model_dump() | {
        "conteo": conteo,
        "fuera_de_orden": 0,
        "juez": resumen_juez,
    }
    logger.info("Juez de la zona gris: %s", resumen_juez)
    return Clasificacion.model_validate({"pasos": pasos, "resumen": resumen})


def _resumen_juez(pasos: Sequence[ResultadoPaso]) -> dict[ResultadoJuez, int]:
    """Qué decidió el juez en cada par: un par roto cuenta una vez (por su Falta)."""
    conteo = dict.fromkeys(RESULTADOS_JUEZ, 0)
    for p in pasos:
        if p.estado == "zona_gris":
            conteo["respaldo"] += 1
        elif p.juicio is not None and p.juicio.veredicto is not None and p.estado != "Sobra":
            conteo[p.juicio.veredicto] += 1
    return conteo
