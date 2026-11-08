"""Detección de GPU y plan de dispositivos por etapa (ADR-018), sin GPU ni nvidia-smi reales."""

import logging
import subprocess

import pytest

from sopvid.plataforma.config import Settings
from sopvid.plataforma.hardware import (
    CONSULTA_GPU,
    GPU,
    Hardware,
    detectar,
    planear,
    registrar,
)

RTX = GPU(nombre="NVIDIA GeForce RTX 2070 SUPER", vram_mb=8192)
CON_GPU = Hardware(gpus=(RTX,), nucleos=16)
SIN_GPU = Hardware(gpus=(), nucleos=8, motivo_sin_gpu="nvidia-smi no está en el PATH")


def ajustes(**cambios) -> Settings:
    """Settings con los dispositivos explícitos: el .env de cada equipo puede traer otros."""
    explicitos = {
        "whisper_dispositivo": "auto",
        "whisper_compute_type": "auto",
        "llm_dispositivo": "auto",
    }
    return Settings(**(explicitos | cambios))


@pytest.fixture(autouse=True)
def _sin_cuda_visible(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def smi(salida: str):
    llamadas = []

    def ejecutar(argumentos):
        llamadas.append(argumentos)
        return salida

    ejecutar.llamadas = llamadas
    return ejecutar


def falla(exc: Exception):
    def ejecutar(argumentos):
        raise exc

    return ejecutar


def eleccion(dispositivo: str, compute_type: str):
    return lambda d, c: (dispositivo, compute_type)


# ── detectar ─────────────────────────────────────────────────────────────────────────────────


def test_detectar_lee_nombre_y_vram_de_cada_gpu():
    ejecutar = smi("NVIDIA GeForce RTX 2070 SUPER, 8192\nNVIDIA T4, 15360\n\n")

    hardware = detectar(ejecutar)

    assert hardware.gpus == (RTX, GPU("NVIDIA T4", 15360))
    assert hardware.gpu == RTX
    assert hardware.nucleos >= 1
    assert hardware.motivo_sin_gpu is None
    assert ejecutar.llamadas == [CONSULTA_GPU]


def test_detectar_nombre_con_comas_toma_la_ultima_como_vram():
    assert detectar(smi("GPU, edición rara, 4096")).gpu == GPU("GPU, edición rara", 4096)


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("nvidia-smi"),
        subprocess.TimeoutExpired("nvidia-smi", 5),
        subprocess.CalledProcessError(9, "nvidia-smi"),
    ],
)
def test_detectar_sin_nvidia_smi_cuenta_como_sin_gpu(exc):
    hardware = detectar(falla(exc))

    assert hardware.gpu is None
    assert type(exc).__name__ in hardware.motivo_sin_gpu


def test_detectar_salida_ilegible_o_vacia_cuenta_como_sin_gpu():
    assert detectar(smi("no hay driver")).gpu is None
    assert detectar(smi("")).motivo_sin_gpu == "nvidia-smi no listó ninguna GPU"


@pytest.mark.parametrize("valor", ["", " ", "-1"])
def test_cuda_visible_devices_vacio_oculta_la_gpu(monkeypatch, valor):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", valor)
    ejecutar = smi("NVIDIA GeForce RTX 2070 SUPER, 8192")

    hardware = detectar(ejecutar)

    assert hardware.gpu is None
    assert "CUDA_VISIBLE_DEVICES" in hardware.motivo_sin_gpu
    assert ejecutar.llamadas == []


def test_cuda_visible_devices_con_indice_no_oculta(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert detectar(smi("NVIDIA GeForce RTX 2070 SUPER, 8192")).gpu == RTX


# ── planear ──────────────────────────────────────────────────────────────────────────────────


def test_con_gpu_y_todo_en_auto_acelera_sin_avisos():
    plan = planear(ajustes(), CON_GPU, eleccion("cuda", "float16"))

    assert (plan.transcripcion, plan.compute_type, plan.llm, plan.embedder) == (
        "cuda",
        "float16",
        "auto",
        "cpu",
    )
    assert plan.acelera
    assert plan.avisos == ()
    assert plan.como_dict() == {
        "gpu": {"nombre": RTX.nombre, "vram_mb": 8192},
        "transcripcion": "cuda/float16",
        "llm": "auto",
        "embedder": "cpu",
        "avisos": [],
    }


def test_sin_gpu_todo_en_cpu_sin_avisos():
    plan = planear(ajustes(), SIN_GPU, eleccion("cpu", "int8"))

    assert (plan.gpu, plan.transcripcion, plan.compute_type) == (None, "cpu", "int8")
    assert not plan.acelera
    assert plan.avisos == ()
    assert plan.como_dict()["gpu"] is None


def test_avisa_si_hay_gpu_pero_ctranslate2_no_la_ve():
    plan = planear(ajustes(whisper_dispositivo="auto"), CON_GPU, eleccion("cpu", "int8"))

    [aviso] = plan.avisos
    assert "ctranslate2 no la ve" in aviso and RTX.nombre in aviso


def test_avisa_si_whisper_pide_cuda_y_no_hay_gpu():
    plan = planear(ajustes(whisper_dispositivo="cuda"), SIN_GPU, eleccion("cuda", "float16"))

    assert any("WHISPER_DISPOSITIVO=cuda" in a for a in plan.avisos)


def test_avisa_si_el_compute_type_de_gpu_se_cambia_en_cpu():
    # .env con el perfil GPU (float16) y WHISPER_DISPOSITIVO=cpu en la terminal.
    ajuste = ajustes(whisper_dispositivo="cpu", whisper_compute_type="float16")
    plan = planear(ajuste, CON_GPU, eleccion("cpu", "int8"))

    assert (plan.transcripcion, plan.compute_type) == ("cpu", "int8")
    assert any("WHISPER_COMPUTE_TYPE=float16" in a and "int8" in a for a in plan.avisos)


def test_llm_en_cpu_con_gpu_avisa_y_no_cuenta_como_aceleracion_de_gemma():
    plan = planear(ajustes(llm_dispositivo="cpu"), CON_GPU, eleccion("cpu", "int8"))

    assert plan.llm == "cpu"
    assert any("LLM_DISPOSITIVO=cpu" in a for a in plan.avisos)
    assert not plan.acelera  # ni Whisper ni Gemma usan la GPU


def test_planear_no_lanza_si_no_se_puede_resolver_whisper():
    def rota(d, c):
        raise ImportError("sin ctranslate2")

    plan = planear(ajustes(), SIN_GPU, rota)

    assert (plan.transcripcion, plan.compute_type) == ("cpu", "int8")
    assert any("ImportError" in a for a in plan.avisos)


def test_registrar_deja_el_plan_y_un_warning_por_aviso(caplog):
    plan = planear(ajustes(llm_dispositivo="cpu"), CON_GPU, eleccion("cuda", "float16"))

    with caplog.at_level(logging.INFO, logger="sopvid.plataforma.hardware"):
        registrar(plan)

    info = [r for r in caplog.records if r.levelno == logging.INFO]
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(info) == 1 and RTX.nombre in info[0].getMessage()
    assert "solo CPU" in info[0].getMessage()
    assert len(avisos) == 1 and "LLM_DISPOSITIVO=cpu" in avisos[0].getMessage()


def test_registrar_sin_gpu_dice_el_motivo(caplog):
    plan = planear(ajustes(), SIN_GPU, eleccion("cpu", "int8"))

    with caplog.at_level(logging.INFO, logger="sopvid.plataforma.hardware"):
        registrar(plan, SIN_GPU.motivo_sin_gpu)

    mensaje = caplog.records[0].getMessage()
    assert "sin GPU (nvidia-smi no está en el PATH)" in mensaje
    assert "todo en CPU" in mensaje
