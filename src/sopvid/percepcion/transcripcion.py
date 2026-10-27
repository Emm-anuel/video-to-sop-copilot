"""Idioma (RF-09) y transcripción con tiempo por frase y por palabra (RF-10) con faster-whisper.

`TranscriptorWhisper` corre el modelo localmente (costo cero, ADR-011), con decodificación
reproducible (RNF-07): temperatura 0 sin respaldo, beam fijo y sin condicionar en el texto
previo, que con temperatura 0 puede entrar en bucles de repetición. Cada segmento se normaliza
a las reglas del contrato (`Segmento` de sopvid/contrato.py) en cuanto sale y se entrega a un
callback; `escritor_txt` lo usa para escribir el TXT mientras avanza.

El modelo se carga en cada `transcribir` y se libera al terminar: en 8 GB de VRAM no cabe junto
a Gemma 4 (ADR-014). Los logs solo llevan conteos, tiempos e idioma, nunca texto transcrito.
"""

import gc
import importlib.util
import logging
import math
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

from sopvid.contrato import Idioma, Palabra, Segmento
from sopvid.percepcion.medios import MedioInvalido
from sopvid.plataforma.config import Settings, get_settings

logger = logging.getLogger(__name__)

BEAM = 5
DECIMALES = 3
# Lo que se usa al caer a CPU, sea cual sea WHISPER_COMPUTE_TYPE (float16 no corre en CPU).
COMPUTE_TYPE_CPU = "int8"
# Re-corte de la transcripción (`resegmentar`): silencio que por sí solo cierra un segmento,
# signos que cierran una frase y mínimo de palabras de un segmento (los fragmentos se unen).
PAUSA_CORTE_S = 1.5
FIN_DE_FRASE = (".", "?", "!", "…")
MIN_PALABRAS_SEGMENTO = 2

AlSegmento = Callable[[Segmento], None]
# (modelo, dispositivo, compute_type, carpeta de caché) -> objeto con `transcribe`, como
# `faster_whisper.WhisperModel`. Las pruebas inyectan uno simulado.
FabricaModelo = Callable[[str, str, str, Path], Any]


@dataclass(frozen=True)
class Transcripcion:
    """Resultado de `transcribir`. `dispositivo` y `compute_type` son con los que corrió."""

    idioma: Idioma
    segmentos: list[Segmento]
    duracion_s: float
    modelo: str
    dispositivo: str
    compute_type: str
    segundos: float
    respaldo_cpu: bool = False


class Transcriptor(Protocol):
    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion: ...


class TranscriptorWhisper:
    """Transcriptor con faster-whisper; modelo, dispositivo y caché salen de la configuración."""

    def __init__(self, settings: Settings | None = None, fabrica: FabricaModelo | None = None):
        self.settings = settings or get_settings()
        self._fabrica = fabrica or _cargar_whisper

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        """Transcribe `audio`. Con `idioma` (ISO 639-1) se fuerza y queda fijado a mano.

        `al_segmento` recibe cada segmento ya normalizado en cuanto sale. Con dispositivo
        "auto", si cuda falla antes del primer segmento se repite en CPU.
        """
        if not audio.is_file():
            raise MedioInvalido(f"{audio.name}: el archivo no existe")
        codigo = idioma.strip().lower() if idioma and idioma.strip() else None
        modelo = self.settings.whisper_modelo
        dispositivo, compute_type = elegir_dispositivo(
            self.settings.whisper_dispositivo, self.settings.whisper_compute_type
        )
        inicio = time.perf_counter()
        segmentos: list[Segmento] = []
        respaldo = False
        try:
            info = self._correr(audio, codigo, dispositivo, compute_type, segmentos, al_segmento)
        except (RuntimeError, OSError) as exc:
            puede_caer = self.settings.whisper_dispositivo == "auto" and dispositivo == "cuda"
            if not puede_caer or segmentos:
                raise
            logger.warning(
                "Whisper %s: cuda falló antes del primer segmento (%s: %s); se repite en CPU "
                "(%s). El tiempo de esta corrida no sirve para RNF-01.",
                modelo,
                type(exc).__name__,
                exc,
                COMPUTE_TYPE_CPU,
            )
            dispositivo, compute_type, respaldo = "cpu", COMPUTE_TYPE_CPU, True
            info = self._correr(audio, codigo, dispositivo, compute_type, segmentos, al_segmento)
        segundos = time.perf_counter() - inicio

        if codigo:
            idioma_final = Idioma(codigo=codigo, confianza=1.0, fijado_a_mano=True)
        else:
            confianza = min(max(float(info.language_probability), 0.0), 1.0)
            idioma_final = Idioma(codigo=info.language, confianza=round(confianza, 4))
        duracion = _t(info.duration)
        logger.info(
            "Transcripción: %d segmentos y %d palabras de %.1f s de audio en %.1f s "
            "(%s en %s/%s; idioma %s %.2f%s)",
            len(segmentos),
            sum(len(s.palabras) for s in segmentos),
            duracion,
            segundos,
            modelo,
            dispositivo,
            compute_type,
            idioma_final.codigo,
            idioma_final.confianza,
            ", fijado a mano" if idioma_final.fijado_a_mano else "",
        )
        return Transcripcion(
            idioma=idioma_final,
            segmentos=segmentos,
            duracion_s=duracion,
            modelo=modelo,
            dispositivo=dispositivo,
            compute_type=compute_type,
            segundos=round(segundos, 2),
            respaldo_cpu=respaldo,
        )

    def _correr(
        self,
        audio: Path,
        codigo: str | None,
        dispositivo: str,
        compute_type: str,
        segmentos: list[Segmento],
        al_segmento: AlSegmento | None,
    ) -> Any:
        """Carga el modelo, agrega los segmentos normalizados a `segmentos` y lo libera."""
        modelo = self._fabrica(
            self.settings.whisper_modelo,
            dispositivo,
            compute_type,
            self.settings.whisper_cache_path,
        )
        crudos = None
        try:
            crudos, info = modelo.transcribe(
                str(audio),
                language=codigo,
                word_timestamps=True,
                vad_filter=True,
                temperature=0.0,
                beam_size=BEAM,
                condition_on_previous_text=False,
            )
            for segmento in _normalizar_flujo(crudos):
                segmentos.append(segmento)
                if al_segmento is not None:
                    al_segmento(segmento)
            return info
        finally:
            # El generador de segmentos también apunta al modelo: se sueltan los dos para que
            # ctranslate2 libere la memoria (y la VRAM) antes de la siguiente etapa.
            crudos = modelo = None
            gc.collect()
            logger.debug("Whisper liberado (%s)", dispositivo)


def normalizar(crudos: Iterable[Any]) -> list[Segmento]:
    """Segmentos de faster-whisper (`start`, `end`, `text`, `words`) según las reglas del contrato.

    Ids seguidos desde 0; texto sin espacios sobrantes y sin segmentos vacíos; tiempos ≥ 0 y en
    milisegundos; un segmento que empieza antes de que termine el anterior se recorta a su fin;
    palabras en orden, dentro de su segmento y con fin ≥ inicio.
    """
    return list(_normalizar_flujo(crudos))


def resegmentar(segmentos: Sequence[Segmento]) -> list[Segmento]:
    """Vuelve a cortar la transcripción por frases y pausas, con los tiempos por palabra.

    Whisper agrupa por ventanas de audio, no por frases: con habla real deja segmentos de 30 s
    que juntan dos pasos y marca las pausas largas solo con una coma, o corta a media frase
    ("Ahora | retiro la carcasa"). Como el LLM elige las fronteras de paso entre segmentos
    (ADR-010), un segmento que mezcla dos pasos ya no se puede separar. Aquí se juntan las
    palabras de todos los segmentos y se corta después de un fin de frase (`FIN_DE_FRASE`) o en
    un silencio ≥ `PAUSA_CORTE_S`; una coma sola no corta. Un fragmento de menos de
    `MIN_PALABRAS_SEGMENTO` palabras ("Siguiente.", un "Ahora" dicho antes de la pausa) se une
    al segmento siguiente, y si es el último, al anterior.

    Ningún tiempo nuevo (regla 4): cada segmento va del inicio de su primera palabra al fin de
    la última, y su texto son sus palabras. Ids seguidos desde 0. Si algún segmento no trae
    palabras que reproduzcan su texto, o si los segmentos se enciman, se devuelven sin cambios.
    """
    if not segmentos or not all(_palabras_cubren_texto(s) for s in segmentos):
        return list(segmentos)
    if any(b.t_inicio < a.t_fin for a, b in pairwise(segmentos)):
        return list(segmentos)  # fuera del contrato: que lo rechace la validación, no ocultarlo
    palabras = [p for s in segmentos for p in s.palabras]
    grupos: list[list[Palabra]] = [[]]
    for actual, siguiente in zip(palabras, [*palabras[1:], None], strict=True):
        grupos[-1].append(actual)
        if siguiente is not None and (
            _cierra_frase(actual.w) or siguiente.t - actual.t_fin >= PAUSA_CORTE_S
        ):
            grupos.append([])
    resultado: list[Segmento] = []
    fin_anterior = 0.0
    for id_, grupo in enumerate(_unir_fragmentos(grupos)):
        t_inicio = max(grupo[0].t, fin_anterior)
        t_fin = max(grupo[-1].t_fin, t_inicio)
        resultado.append(
            Segmento(
                id=id_,
                t_inicio=t_inicio,
                t_fin=t_fin,
                texto=" ".join(p.w for p in grupo),
                palabras=grupo,
            )
        )
        fin_anterior = t_fin
    logger.info("Transcripción re-cortada: %d → %d segmentos", len(segmentos), len(resultado))
    return resultado


def _palabras_cubren_texto(segmento: Segmento) -> bool:
    return " ".join(p.w for p in segmento.palabras).split() == segmento.texto.split()


def _cierra_frase(palabra: str) -> bool:
    return palabra.rstrip("\"'”»)").endswith(FIN_DE_FRASE)


def _unir_fragmentos(grupos: list[list[Palabra]]) -> list[list[Palabra]]:
    unidos: list[list[Palabra]] = []
    pendiente: list[Palabra] = []
    for grupo in grupos:
        # Se mide el fragmento solo, sin lo pendiente: dos fragmentos seguidos no forman
        # un segmento ("Listo. Siguiente."), van juntos al siguiente.
        if len(grupo) < MIN_PALABRAS_SEGMENTO:
            pendiente += grupo
            continue
        unidos.append(pendiente + grupo)
        pendiente = []
    if pendiente:
        if unidos:
            unidos[-1].extend(pendiente)
        else:
            unidos.append(pendiente)
    return unidos


def _normalizar_flujo(crudos: Iterable[Any]) -> Iterator[Segmento]:
    siguiente_id = 0
    fin_anterior = 0.0
    for crudo in crudos:
        texto = " ".join(str(crudo.text).split())
        if not texto:
            continue
        t_inicio = max(_t(crudo.start), fin_anterior)
        t_fin = max(_t(crudo.end), t_inicio)
        yield Segmento(
            id=siguiente_id,
            t_inicio=t_inicio,
            t_fin=t_fin,
            texto=texto,
            palabras=_normalizar_palabras(crudo.words or [], t_inicio, t_fin),
        )
        siguiente_id += 1
        fin_anterior = t_fin


def _normalizar_palabras(crudas: Iterable[Any], t_inicio: float, t_fin: float) -> list[Palabra]:
    palabras: list[Palabra] = []
    t_previo = t_inicio
    for cruda in crudas:
        w = " ".join(str(cruda.word).split())
        if not w:
            continue
        # No decreciente en vez de reordenar: así el orden de las palabras sigue al del texto.
        t = min(max(_t(cruda.start), t_previo), t_fin)
        palabras.append(Palabra(w=w, t=t, t_fin=min(max(_t(cruda.end), t), t_fin)))
        t_previo = t
    return palabras


def _t(valor: Any) -> float:
    """Tiempo finito, ≥ 0 y redondeado a milisegundos."""
    try:
        segundos = float(valor)
    except (TypeError, ValueError):
        return 0.0
    return round(segundos, DECIMALES) if math.isfinite(segundos) and segundos > 0 else 0.0


@contextmanager
def escritor_txt(ruta: Path) -> Iterator[AlSegmento]:
    """Abre el TXT de la transcripción y da un callback que agrega cada segmento al momento.

    Una línea por segmento, `[mm:ss] texto`, con flush tras cada una para que el TXT se pueda
    leer o descargar mientras avanza (RF-10).
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as archivo:

        def escribir(segmento: Segmento) -> None:
            archivo.write(f"[{marca_tiempo(segmento.t_inicio)}] {segmento.texto}\n")
            archivo.flush()

        yield escribir


def marca_tiempo(segundos: float) -> str:
    """`mm:ss` (truncado al segundo); los minutos pueden pasar de 59."""
    total = int(segundos)
    return f"{total // 60:02d}:{total % 60:02d}"


def elegir_dispositivo(dispositivo: str, compute_type: str) -> tuple[str, str]:
    """Resuelve "auto": cuda si ctranslate2 ve una GPU; float16 en cuda e int8 en cpu."""
    if dispositivo == "auto":
        dispositivo = "cuda" if _gpus_cuda() > 0 else "cpu"
    if compute_type == "auto":
        compute_type = "float16" if dispositivo == "cuda" else COMPUTE_TYPE_CPU
    return dispositivo, compute_type


def _gpus_cuda() -> int:
    import ctranslate2

    try:
        return ctranslate2.get_cuda_device_count()
    except RuntimeError:
        return 0


def _cargar_whisper(modelo: str, dispositivo: str, compute_type: str, cache: Path) -> Any:
    if dispositivo == "cuda":
        _registrar_dll_nvidia()
    from faster_whisper import WhisperModel

    inicio = time.perf_counter()
    cargado = WhisperModel(
        modelo, device=dispositivo, compute_type=compute_type, download_root=str(cache)
    )
    logger.info(
        "Whisper %s cargado en %s/%s en %.1f s",
        modelo,
        dispositivo,
        compute_type,
        time.perf_counter() - inicio,
    )
    return cargado


def _registrar_dll_nvidia() -> None:
    """En Windows, hace visibles las DLL de los wheels nvidia-* del extra "gpu".

    ctranslate2 solo registra su propia carpeta: cuBLAS (`cublas64_12.dll`) y las partes de
    cuDNN 9 que carga su `cudnn64_9.dll` quedan en `site-packages/nvidia/*/bin`. Se agregan con
    `os.add_dll_directory` y al PATH (el cargador de cuDNN busca con el orden clásico).
    """
    if sys.platform != "win32":
        return
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return
    ruta = os.environ.get("PATH", "")
    for base in spec.submodule_search_locations:
        for paquete in ("cublas", "cudnn"):
            carpeta = Path(base) / paquete / "bin"
            if carpeta.is_dir():
                os.add_dll_directory(str(carpeta))
                if str(carpeta) not in ruta.split(os.pathsep):
                    ruta = str(carpeta) + os.pathsep + ruta
    os.environ["PATH"] = ruta
