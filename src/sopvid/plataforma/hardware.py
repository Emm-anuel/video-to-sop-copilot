"""Hardware del equipo y dispositivo de cada etapa: CPU de base, GPU opcional (ADR-018).

Regla (RNF-07): la GPU cambia **dónde** corre cada modelo, nunca **cuál**. El mismo video da el
mismo resultado con o sin tarjeta de video; con GPU solo tarda menos.

- **Transcripción:** `elegir_dispositivo` de faster-whisper. Con `WHISPER_DISPOSITIVO=auto`,
  cuda si ctranslate2 ve una GPU NVIDIA; si cuda falla antes del primer segmento, repite en CPU.
- **LLM (Gemma 4 en Ollama):** con `LLM_DISPOSITIVO=auto`, Ollama usa la GPU si la ve; con
  `cpu`, el cliente pide `num_gpu=0` y Gemma corre solo en CPU. Dónde quedó de verdad se le
  pregunta a Ollama después de usarlo (`ClienteLLM.dispositivo_cargado`).
- **MiniLM:** siempre en CPU (ADR-012).

`detectar` lee la GPU con `nvidia-smi` y nunca lanza: sin el programa, sin driver o si tarda,
el equipo cuenta como sin GPU. `planear` combina eso con la configuración y deja avisos cuando
algo no cuadra (p. ej. hay GPU pero ctranslate2 no la ve). La API registra el plan al arrancar
y lo informa en `/health`. Se detecta una vez por proceso: la GPU no cambia mientras corre.
"""

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from sopvid.plataforma.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Tope de la consulta a nvidia-smi: responde en décimas de segundo, pero con el driver colgado
# puede no volver nunca.
PLAZO_NVIDIA_SMI_S = 5.0
CONSULTA_GPU = ["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]

# (argumentos de nvidia-smi) -> su salida estándar; lanza si no se pudo correr.
EjecutarNvidiaSmi = Callable[[list[str]], str]


@dataclass(frozen=True)
class GPU:
    nombre: str
    vram_mb: int


@dataclass(frozen=True)
class Hardware:
    """Lo que la API ve del equipo. `gpus` vacía = sin GPU NVIDIA utilizable."""

    gpus: tuple[GPU, ...]
    nucleos: int
    motivo_sin_gpu: str | None = None

    @property
    def gpu(self) -> GPU | None:
        """La primera GPU: la que usan faster-whisper y Ollama por defecto."""
        return self.gpus[0] if self.gpus else None


def nvidia_smi(argumentos: list[str]) -> str:
    ruta = shutil.which("nvidia-smi")
    if ruta is None:
        raise FileNotFoundError("nvidia-smi no está en el PATH")
    resultado = subprocess.run(
        [ruta, *argumentos],
        capture_output=True,
        text=True,
        timeout=PLAZO_NVIDIA_SMI_S,
        check=True,
    )
    return resultado.stdout


def detectar(ejecutar: EjecutarNvidiaSmi = nvidia_smi) -> Hardware:
    """GPU NVIDIA (nombre y VRAM) y núcleos de CPU. Nunca lanza.

    `CUDA_VISIBLE_DEVICES` vacío o "-1" en el entorno del proceso oculta las GPU a CUDA, así que
    aquí también cuenta como sin GPU, aunque `nvidia-smi` sí las vea.
    """
    nucleos = os.cpu_count() or 1
    visibles = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visibles is not None and visibles.strip() in ("", "-1"):
        return Hardware((), nucleos, "CUDA_VISIBLE_DEVICES oculta las GPU a este proceso")
    try:
        gpus = tuple(_interpretar(ejecutar(CONSULTA_GPU)))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return Hardware((), nucleos, f"nvidia-smi no respondió ({type(exc).__name__})")
    if not gpus:
        return Hardware((), nucleos, "nvidia-smi no listó ninguna GPU")
    return Hardware(gpus, nucleos)


def _interpretar(salida: str) -> list[GPU]:
    """Una GPU por línea `nombre, MiB` (CSV sin encabezado ni unidades)."""
    gpus = []
    for linea in salida.splitlines():
        if not linea.strip():
            continue
        nombre, vram = linea.rsplit(",", 1)
        gpus.append(GPU(nombre=nombre.strip(), vram_mb=int(vram.strip())))
    return gpus


@lru_cache
def get_hardware() -> Hardware:
    """El hardware de este proceso, detectado una sola vez."""
    return detectar()


# ── Plan de dispositivos por etapa ───────────────────────────────────────────────────────────

# (WHISPER_DISPOSITIVO, WHISPER_COMPUTE_TYPE) -> (dispositivo, compute_type) resueltos.
ElegirDispositivo = Callable[[str, str], tuple[str, str]]


@dataclass(frozen=True)
class PlanDispositivos:
    """Dónde va a correr cada etapa con esta configuración y este equipo.

    `transcripcion` es lo que resolvió faster-whisper ("cuda" o "cpu"); `llm` es la política
    ("auto": Ollama decide y usa la GPU si la ve; "cpu": se fuerza la CPU). Dónde corrió de
    verdad cada video queda en los metadatos de su reporte (`Dispositivos` del contrato).
    """

    gpu: GPU | None
    nucleos: int
    transcripcion: str
    compute_type: str
    llm: Literal["auto", "cpu"]
    embedder: Literal["cpu"] = "cpu"
    avisos: tuple[str, ...] = ()

    @property
    def acelera(self) -> bool:
        """True si alguna etapa va a usar la GPU."""
        return self.gpu is not None and (self.transcripcion == "cuda" or self.llm == "auto")

    def como_dict(self) -> dict[str, Any]:
        """Para `/health`: sin rutas ni datos del cliente."""
        return {
            "gpu": None
            if self.gpu is None
            else {"nombre": self.gpu.nombre, "vram_mb": self.gpu.vram_mb},
            "transcripcion": f"{self.transcripcion}/{self.compute_type}",
            "llm": self.llm,
            "embedder": self.embedder,
            "avisos": list(self.avisos),
        }


def _elegir_whisper(dispositivo: str, compute_type: str) -> tuple[str, str]:
    from sopvid.percepcion.transcripcion import elegir_dispositivo

    return elegir_dispositivo(dispositivo, compute_type)


def planear(
    settings: Settings | None = None,
    hardware: Hardware | None = None,
    elegir: ElegirDispositivo = _elegir_whisper,
) -> PlanDispositivos:
    """El plan de dispositivos y los avisos de lo que no cuadra. Nunca lanza."""
    settings = settings or get_settings()
    hardware = hardware or get_hardware()
    avisos: list[str] = []
    try:
        transcripcion, compute_type = elegir(
            settings.whisper_dispositivo, settings.whisper_compute_type
        )
    except Exception as exc:  # p. ej. ctranslate2 sin instalar: se informa, no se cae la API
        transcripcion, compute_type = "cpu", "int8"
        avisos.append(f"no se pudo resolver el dispositivo de Whisper ({type(exc).__name__})")

    gpu = hardware.gpu
    if settings.whisper_dispositivo == "cuda" and gpu is None:
        avisos.append("WHISPER_DISPOSITIVO=cuda pero no se detectó GPU: la transcripción fallará")
    if settings.whisper_dispositivo == "auto" and gpu is not None and transcripcion == "cpu":
        avisos.append(
            f"hay GPU ({gpu.nombre}) pero ctranslate2 no la ve: Whisper en CPU "
            "(¿falta el extra gpu del venv?)"
        )
    if gpu is not None and settings.llm_dispositivo == "cpu":
        avisos.append("LLM_DISPOSITIVO=cpu: Gemma no usa la GPU aunque exista")
    return PlanDispositivos(
        gpu=gpu,
        nucleos=hardware.nucleos,
        transcripcion=transcripcion,
        compute_type=compute_type,
        llm=settings.llm_dispositivo,
        avisos=tuple(avisos),
    )


@lru_cache
def get_plan_dispositivos() -> PlanDispositivos:
    """El plan de este proceso (dependencia de `/health`; las pruebas la sustituyen)."""
    return planear()


def registrar(plan: PlanDispositivos, motivo_sin_gpu: str | None = None) -> None:
    """Deja el plan en el log al arrancar, con un WARNING por cada aviso."""
    if plan.gpu is not None:
        equipo = f"GPU {plan.gpu.nombre} ({plan.gpu.vram_mb} MB)"
    else:
        equipo = f"sin GPU ({motivo_sin_gpu or 'no detectada'})"
    logger.info(
        "Dispositivos: %s, %d núcleos · Whisper %s/%s · Gemma %s · MiniLM %s%s",
        equipo,
        plan.nucleos,
        plan.transcripcion,
        plan.compute_type,
        "GPU si Ollama la ve" if plan.llm == "auto" else "solo CPU (num_gpu=0)",
        plan.embedder,
        "" if plan.acelera else " · todo en CPU",
    )
    for aviso in plan.avisos:
        logger.warning("Dispositivos: %s", aviso)
