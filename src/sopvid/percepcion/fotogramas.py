"""Descripción opcional de imágenes del video con Gemma 4 (RF-11, ADR-024).

Apagada por defecto (`FOTOGRAMAS_DESCRIBIR=false`; `analizar_imagenes` de POST /videos gana sobre
la configuración). Encendida, corre después de la transcripción y antes de la ficha de contexto,
en la misma carga de Gemma (Whisper ya soltó la memoria, ADR-014 y ADR-018), y la ficha y el SOP
generado reciben los fotogramas como evidencia visual (`[f=N]`, `contexto.py` y `sop_generado.py`,
que no cambian). Sin GPU describe igual, más lento: solo se avisa antes con la estimación.

Cuántas y cuáles:
- N = los pasos del SOP (modo validar) o la duración por `PASOS_POR_MIN` (modo generar), entre
  `FOTOGRAMAS_MIN` y `FOTOGRAMAS_MAX` (tope de 20, ADR-002). La ficha no pone un tope propio:
  numera todos los fotogramas que recibe, así que el tope vive aquí.
- Repartidas de forma pareja: el centro de N tramos iguales del video. Una por paso exigiría
  segmentar antes, y la ficha va primero.
- JPEG de `FOTOGRAMAS_LADO_PX` en `media/videos/<id>/fotogramas/fNN.jpg`; `Fotograma.archivo`
  es esa ruta relativa a la carpeta del video.

La llamada va por lotes de `FOTOGRAMAS_LOTE` imágenes (en el mensaje del usuario, en orden), en
flujo (`ClienteLLM.chat_en_flujo`, tope `LLM_TIMEOUT_FOTOGRAMAS_S` por lote), con el JSON
restringido a lo que el modelo escribe: `i` (la posición en el lote), `descripcion`, `equipos`,
`personas` (un conteo), `texto_visible` y `riesgos`. Temperatura 0 y `SEMILLA` las pone el cliente;
hasta `MAX_INTENTOS` llamadas por lote si el JSON no es del esquema o faltan imágenes, como el juez.

Por código, nunca por el LLM (regla 4): el `t` y el `archivo` de cada fotograma, el orden por `t`
y el descarte de índices que no son de una imagen del lote (o repetidos) y de descripciones
vacías. Un lote que falla sus intentos (o se corta por tiempo) no entra y los demás siguen; si
Ollama no responde, los lotes que faltan no se piden. En los dos casos el resultado lleva el aviso
"imagenes_incompletas" (vuelve provisional el reporte, ADR-019). Nunca lanza por el LLM ni por
ffmpeg: el análisis sigue sin las imágenes que falten. Los logs solo llevan conteos.
"""

import base64
import logging
import math
import re
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sopvid.contrato import Analisis, Aviso, Fotograma, Imagenes
from sopvid.lenguaje.juez import Prompt, leer_prompt, texto_del_prompt
from sopvid.lenguaje.llm import (
    ClienteLLM,
    LLMError,
    LLMRespuestaInvalida,
    LLMTiempoExcedido,
    RespuestaLLM,
)
from sopvid.percepcion.medios import ErrorMedios, extraer_cuadros, imagen_visible
from sopvid.percepcion.miniaturas import aviso_sin_imagen
from sopvid.percepcion.segmentacion import _sin_refs
from sopvid.plataforma.config import Settings, get_settings
from sopvid.texto import VACIOS, comparable, limpiar

logger = logging.getLogger(__name__)

PROMPT = "fotogramas_v1"  # archivo en lenguaje/prompts/; un prompt nuevo es un archivo nuevo
MAX_INTENTOS = 3  # una llamada más dos reintentos, como el juez
# Frases de ejemplo que algún prompt tuvo en la regla de riesgos y que Gemma llegó a copiar tal
# cual (video E, 11 nov): un riesgo que las repite es una observación inventada (RNF-06) y se
# descarta por código, aunque el prompt ya no las traiga.
RIESGOS_DE_EJEMPLO = frozenset(
    {comparable("falta de guantes o lentes cuando la tarea los pide a la vista")}
)
# Rellenos que el modelo escribe en lugar de dejar la lista vacía (A–E, 11 nov: "Ninguno visible").
_RIESGOS_VACIOS = VACIOS | {
    comparable(t)
    for t in (
        "ninguno visible", "ninguna visible", "no se ve ninguno", "no se observan",
        "no se observan riesgos", "sin riesgos", "sin riesgos visibles", "no hay riesgos visibles",
    )
}  # fmt: skip
CARPETA = "fotogramas"
_MARCADORES = {
    "sistema": frozenset(),
    "usuario": frozenset({"n"}),
    "correccion": frozenset({"motivo"}),
}

# Por qué faltan imágenes: Ollama no respondió, un lote se cortó por tiempo, no dio un JSON
# válido con todas sus imágenes en los intentos, o ffmpeg no pudo sacar el cuadro.
MotivoFotogramas = Literal[
    "llm_no_disponible",
    "memoria_insuficiente",
    "tiempo_excedido",
    "respuesta_invalida",
    "extraccion",
]
# Lo que Ollama (llama.cpp) dice cuando el modelo con las imágenes no cabe en la VRAM o en la RAM.
_ERROR_DE_MEMORIA = re.compile(
    r"out of memory|cudamalloc|requires more system memory|insufficient memory|oom", re.I
)
Modo = Literal["validar", "generar"]
# Recibe la fracción de la etapa ya hecha (0 a 1), para el avance.
AlAvanzarFraccion = Callable[[float], None]
# (hechas, total): cuántas de las imágenes sacadas ya pasaron por Gemma; se llama antes del avance.
AlContar = Callable[[int, int], None]


# ── Respuesta del LLM ────────────────────────────────────────────────────────────────────────
# Solo lo que el modelo puede ver. Nada de tiempos ni archivos. Sin docstrings: Pydantic los
# pondría en el esquema que va a Ollama.


class _Libre(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ImagenLibre(_Libre):
    i: int = Field(ge=1)
    descripcion: str
    equipos: list[str]
    personas: int = Field(ge=0)
    texto_visible: list[str]
    riesgos: list[str]


class _LoteFotogramas(_Libre):
    imagenes: list[_ImagenLibre]


_ESQUEMA_BASE: dict[str, Any] = _sin_refs(_LoteFotogramas.model_json_schema())
TITULO_ESQUEMA = _ESQUEMA_BASE["title"]


def esquema_lote(n: int) -> dict[str, Any]:
    """El esquema de la respuesta para un lote de `n` imágenes: `i` de 1 a `n`."""
    esquema = _sin_refs(_LoteFotogramas.model_json_schema())
    esquema["properties"]["imagenes"]["items"]["properties"]["i"]["maximum"] = n
    return esquema


@cache
def cargar_prompt(version: str = PROMPT) -> Prompt:
    """Lee `prompts/<version>.md` (secciones sistema, usuario y correccion)."""
    return leer_prompt(version, texto_del_prompt(version), _MARCADORES)


# ── Cuántas y cuándo ─────────────────────────────────────────────────────────────────────────


def cuantas_imagenes(
    modo: Modo, pasos_sop: int | None, duracion_s: float, settings: Settings | None = None
) -> int:
    """N: los pasos del SOP en modo validar (si se saben) o la duración por `PASOS_POR_MIN`,
    acotado a [`FOTOGRAMAS_MIN`, `FOTOGRAMAS_MAX`]."""
    s = settings or get_settings()
    if modo == "validar" and pasos_sop:
        n = pasos_sop
    else:
        n = round(max(duracion_s, 0.0) / 60 * s.pasos_por_min)
    return max(s.fotogramas_min, min(s.fotogramas_max, n))


def tiempos_parejos(n: int, duracion_s: float) -> list[float]:
    """El centro de `n` tramos iguales del video, en segundos (a milisegundos)."""
    if n <= 0 or duracion_s <= 0:
        return []
    return [round((k + 0.5) * duracion_s / n, 3) for k in range(n)]


# ── Resultado ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResultadoFotogramas:
    """Las imágenes descritas y cómo se obtuvieron.

    `pedidas` es N; `fotogramas`, las que se describieron, ordenadas por `t`. `sin_imagen`: el
    video no tiene imagen visible y no se llamó al modelo. `lotes_fallidos` cuenta los lotes que
    no dieron ninguna imagen válida y `motivo` dice por qué faltan imágenes (la primera causa).
    Los tokens suman todas las llamadas que respondieron (None si ninguna).
    """

    fotogramas: list[Fotograma] = field(default_factory=list)
    pedidas: int = 0
    sin_imagen: bool = False
    lotes: int = 0
    lotes_fallidos: int = 0
    llamadas: int = 0
    motivo: MotivoFotogramas | None = None
    tokens_entrada: int | None = None
    tokens_salida: int | None = None
    segundos: float = 0.0
    prompt: str = PROMPT
    # El lote con que se terminó si un error de memoria obligó a bajarlo (None: el configurado).
    lote_degradado: int | None = None

    @property
    def descritas(self) -> int:
        return len(self.fotogramas)

    @property
    def incompletas(self) -> bool:
        return not self.sin_imagen and self.descritas < self.pedidas


def avisos_fotogramas(resultado: "ResultadoFotogramas | None") -> list[Aviso]:
    """ "sin_imagen" (informativo) o "imagenes_incompletas", sin texto del video."""
    if resultado is None:
        return []
    if resultado.sin_imagen:
        return [aviso_sin_imagen()]
    if resultado.incompletas:
        faltan = resultado.pedidas - resultado.descritas
        return [
            Aviso(
                tipo="imagenes_incompletas",
                detalle=f"{faltan} de {resultado.pedidas} imágenes sin describir: "
                f"{resultado.motivo or 'respuesta_invalida'}",
            )
        ]
    return []


def imagenes_de(resultado: "ResultadoFotogramas | None", analisis: Analisis) -> Imagenes:
    """El bloque `imagenes` de los metadatos: lo que se usó de verdad. Sin `resultado` (opción
    apagada o al repetir con las imágenes guardadas), las que trae el análisis."""
    if resultado is None:
        return Imagenes(descritas=bool(analisis.fotogramas), cantidad=len(analisis.fotogramas))
    return Imagenes(
        descritas=bool(resultado.fotogramas),
        cantidad=len(resultado.fotogramas),
        tokens_entrada=resultado.tokens_entrada,
        tokens_salida=resultado.tokens_salida,
    )


# ── Descripción ──────────────────────────────────────────────────────────────────────────────


@dataclass
class _Cuadro:
    t: float
    archivo: str  # relativo a la carpeta del video
    ruta: Path


@dataclass
class _Cuenta:
    llamadas: int = 0
    tokens_entrada: int | None = None
    tokens_salida: int | None = None

    def sumar(self, respuesta: RespuestaLLM) -> None:
        for campo, clave in (
            ("tokens_entrada", "prompt_eval_count"),
            ("tokens_salida", "eval_count"),
        ):
            valor = respuesta.metricas.get(clave)
            if valor is not None:
                setattr(self, campo, (getattr(self, campo) or 0) + valor)


def describir_fotogramas(
    video: Path,
    carpeta_video: Path,
    duracion_s: float,
    n: int,
    llm: ClienteLLM,
    *,
    settings: Settings | None = None,
    al_avanzar: AlAvanzarFraccion | None = None,
    al_contar: AlContar | None = None,
    version: str = PROMPT,
    reloj: Callable[[], float] = time.monotonic,
) -> ResultadoFotogramas:
    """Saca `n` cuadros repartidos de forma pareja y los describe con Gemma por lotes.

    Nunca lanza por el LLM ni por ffmpeg (ver el docstring del módulo). Sin imagen visible no
    llama al modelo y devuelve `sin_imagen=True`. `al_contar(hechas, total)` da la cuenta exacta
    para la pantalla de avance (RF-08): (0, total) al sacar los cuadros y después de cada lote,
    antes de `al_avanzar`; sin imagen, (0, 0).
    """
    s = settings or get_settings()
    inicio = reloj()
    avanzar = al_avanzar or (lambda fraccion: None)
    contar = al_contar or (lambda hechas, total: None)

    def terminar(**kwargs: Any) -> ResultadoFotogramas:
        resultado = ResultadoFotogramas(
            pedidas=n, prompt=version, segundos=round(reloj() - inicio, 2), **kwargs
        )
        _registrar(video, resultado)
        return resultado

    try:
        visible = imagen_visible(video, duracion_s)
    except ErrorMedios as exc:
        logger.warning("Imágenes de %s: no se pudo revisar la imagen (%s)", video.name, exc)
        visible = False
    if not visible:
        contar(0, 0)
        return terminar(sin_imagen=True)

    cuadros, motivo = _extraer(video, carpeta_video, tiempos_parejos(n, duracion_s), s)
    contar(0, len(cuadros))
    prompt = cargar_prompt(version)
    cuenta = _Cuenta()
    fotogramas: list[Fotograma] = []
    tamano, degradado = s.fotogramas_lote, None
    lotes = fallidos = hechos = 0
    while hechos < len(cuadros):
        lote = cuadros[hechos : hechos + tamano]
        descritos, motivo_lote = _describir_lote(lote, llm, prompt, s, cuenta)
        if motivo_lote == "memoria_insuficiente" and degradado is None and tamano > 1:
            # El lote no cupo (VRAM o RAM): se reintenta una vez con la mitad, y los que siguen
            # van con ese tamaño. FOTOGRAMAS_LOTE es la palanca para equipos con menos memoria.
            degradado = tamano = max(1, tamano // 2)
            logger.warning(
                "Imágenes de %s: sin memoria con %d imágenes por llamada; se reintenta con %d "
                "(baja FOTOGRAMAS_LOTE en este equipo)",
                video.name,
                len(lote),
                tamano,
            )
            continue
        lotes += 1
        hechos += len(lote)
        fotogramas.extend(descritos)
        if motivo_lote is not None:
            motivo = motivo or motivo_lote
            fallidos += not descritos
            if motivo_lote in ("llm_no_disponible", "memoria_insuficiente"):
                restantes = math.ceil((len(cuadros) - hechos) / tamano)
                logger.warning(
                    "Imágenes de %s: %s; %d lotes sin pedir", video.name, motivo_lote, restantes
                )
                fallidos += restantes
                lotes += restantes
                break
        contar(hechos, len(cuadros))
        avanzar(hechos / len(cuadros))
    fotogramas.sort(key=lambda f: f.t)
    return terminar(
        fotogramas=fotogramas,
        lotes=lotes,
        lotes_fallidos=fallidos,
        lote_degradado=degradado,
        llamadas=cuenta.llamadas,
        motivo=motivo if len(fotogramas) < n else None,
        tokens_entrada=cuenta.tokens_entrada,
        tokens_salida=cuenta.tokens_salida,
    )


def _extraer(
    video: Path, carpeta_video: Path, tiempos: Sequence[float], s: Settings
) -> tuple[list[_Cuadro], MotivoFotogramas | None]:
    """Los JPEG `fotogramas/fNN.jpg`, en una sola llamada a ffmpeg; la carpeta se vacía antes
    (son de este proceso)."""
    carpeta = carpeta_video / CARPETA
    shutil.rmtree(carpeta, ignore_errors=True)
    pedidos = [(t, f"{CARPETA}/f{numero:02d}.jpg") for numero, t in enumerate(tiempos, start=1)]
    try:
        hechos = set(
            extraer_cuadros(
                video,
                [(t, carpeta_video / relativo) for t, relativo in pedidos],
                s.fotogramas_lado_px,
            )
        )
    except ErrorMedios as exc:
        logger.warning("Imágenes de %s: %s", video.name, exc)
        hechos = set()
    cuadros = [
        _Cuadro(t=t, archivo=relativo, ruta=carpeta_video / relativo)
        for t, relativo in pedidos
        if carpeta_video / relativo in hechos
    ]
    motivo: MotivoFotogramas | None = "extraccion" if len(cuadros) < len(pedidos) else None
    if motivo:
        logger.warning("Imágenes de %s: %d sin extraer", video.name, len(pedidos) - len(cuadros))
    return cuadros, motivo


def _describir_lote(
    lote: Sequence[_Cuadro],
    llm: ClienteLLM,
    prompt: Prompt,
    s: Settings,
    cuenta: _Cuenta,
) -> tuple[list[Fotograma], MotivoFotogramas | None]:
    """Las imágenes del lote que el modelo describió y, si faltan, por qué.

    Se reintenta si la respuesta no es un JSON del esquema o faltan imágenes; tras los intentos
    se queda el mejor intento (el que más imágenes válidas dio). Un corte por tiempo o un Ollama
    caído no se reintenta.
    """
    imagenes = [base64.b64encode(c.ruta.read_bytes()).decode("ascii") for c in lote]
    base: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.sistema},
        {"role": "user", "content": prompt.usuario.substitute(n=len(lote)), "images": imagenes},
    ]
    esquema = esquema_lote(len(lote))
    historial = list(base)
    mejor: dict[int, _ImagenLibre] = {}
    for intento in range(1, MAX_INTENTOS + 1):
        cuenta.llamadas += 1
        try:
            respuesta = llm.chat_en_flujo(
                historial,
                esquema=esquema,
                primer_token_s=s.llm_timeout_fotogramas_s,
                inactividad_s=s.llm_inactividad_s,
                tope_s=s.llm_timeout_fotogramas_s,
            )
        except LLMTiempoExcedido:
            return _fotogramas(lote, mejor), "tiempo_excedido"
        except LLMRespuestaInvalida:
            correccion = "no devolviste un JSON válido"
        except LLMError as exc:
            # El mensaje es el de Ollama (sin texto del video): dice si fue falta de memoria.
            if _ERROR_DE_MEMORIA.search(str(exc)):
                logger.warning("Imágenes: Ollama sin memoria con %d imágenes", len(lote))
                return _fotogramas(lote, mejor), "memoria_insuficiente"
            logger.warning("Imágenes: LLM no disponible (%s)", type(exc).__name__)
            return _fotogramas(lote, mejor), "llm_no_disponible"
        else:
            cuenta.sumar(respuesta)
            try:
                libre = _LoteFotogramas.model_validate(respuesta.datos)
            except ValidationError as exc:
                correccion = _resumen_errores(exc)
            else:
                validas = _validas(libre, len(lote))
                if len(validas) > len(mejor):
                    mejor = validas
                if len(mejor) == len(lote):
                    return _fotogramas(lote, mejor), None
                faltan = [i for i in range(1, len(lote) + 1) if i not in validas]
                correccion = "faltan las imágenes " + ", ".join(map(str, faltan))
        logger.warning(
            "Imágenes: respuesta inválida (intento %d de %d): %s", intento, MAX_INTENTOS, correccion
        )
        historial = [
            *base,
            {"role": "user", "content": prompt.correccion.substitute(motivo=correccion)},
        ]
    return _fotogramas(lote, mejor), "respuesta_invalida"


def _validas(libre: _LoteFotogramas, n: int) -> dict[int, _ImagenLibre]:
    """Por código (regla 4): solo índices de una imagen del lote, el primero si se repite, y con
    descripción."""
    validas: dict[int, _ImagenLibre] = {}
    for imagen in libre.imagenes:
        if 1 <= imagen.i <= n and imagen.i not in validas and limpiar(imagen.descripcion):
            validas[imagen.i] = imagen
    return validas


def _fotogramas(lote: Sequence[_Cuadro], validas: dict[int, _ImagenLibre]) -> list[Fotograma]:
    """Los `Fotograma` del contrato: `t` y `archivo` del código; lo demás, limpio, del modelo."""
    fotogramas = []
    for i, imagen in sorted(validas.items()):
        cuadro = lote[i - 1]
        fotogramas.append(
            Fotograma(
                t=cuadro.t,
                archivo=cuadro.archivo,
                descripcion=limpiar(imagen.descripcion),
                equipos=_lista(imagen.equipos),
                personas=imagen.personas,
                texto_visible=_lista(imagen.texto_visible),
                riesgos=_riesgos(imagen.riesgos),
            )
        )
    return fotogramas


def _riesgos(valores: Sequence[str]) -> list[str]:
    """Los riesgos sin vacíos ni repetidos, sin rellenos ("Ninguno visible") y sin los que copian
    una frase de ejemplo del prompt."""
    return [
        r
        for r in _lista(valores)
        if comparable(r) not in _RIESGOS_VACIOS
        and not any(e in comparable(r) for e in RIESGOS_DE_EJEMPLO)
    ]


def _lista(valores: Sequence[str]) -> list[str]:
    """Sin vacíos ni repetidos, en su orden."""
    vistos: set[str] = set()
    limpios = []
    for valor in valores:
        if (limpio := limpiar(valor)) and limpio not in vistos:
            vistos.add(limpio)
            limpios.append(limpio)
    return limpios


def _resumen_errores(exc: ValidationError) -> str:
    """Campos y tipos de error de Pydantic, sin los valores."""
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'respuesta'}: {e['type']}" for e in exc.errors()
    )


def _registrar(video: Path, r: ResultadoFotogramas) -> None:
    por_imagen = r.segundos / r.descritas if r.descritas else math.nan
    logger.info(
        "Imágenes de %s (%s): %s%d de %d descritas en %d lotes (%d fallidos), %d llamadas; "
        "%s tokens de entrada, %s de salida; %.1f s (%.1f s por imagen)",
        video.name,
        r.prompt,
        "sin imagen; " if r.sin_imagen else "",
        r.descritas,
        r.pedidas,
        r.lotes,
        r.lotes_fallidos,
        r.llamadas,
        r.tokens_entrada,
        r.tokens_salida,
        r.segundos,
        por_imagen,
    )
