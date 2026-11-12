"""Estimación antes de procesar (`GET /videos/estimacion`, ADR-024) y dónde correría Gemma.

Sin GPU ni Ollama: el cliente del LLM es el doble de tests/dobles.py y el plan de dispositivos se
sustituye como en test_health.py.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dobles import SOP_PRUEBA, Entorno, OllamaFalso, guardar_sop
from sopvid.contrato import SOP, PasoSOP
from sopvid.lenguaje.llm import get_cliente_llm
from sopvid.plataforma.hardware import (
    GPU,
    PlanDispositivos,
    dispositivo_llm_probable,
    get_plan_dispositivos,
)
from sopvid.plataforma.modelos import Sop

SIN_GPU = PlanDispositivos(
    gpu=None, nucleos=8, transcripcion="cpu", compute_type="int8", llm="auto"
)
CON_GPU = PlanDispositivos(
    gpu=GPU("GPU de prueba", 8192), nucleos=8, transcripcion="cuda", compute_type="float16",
    llm="auto",
)  # fmt: skip


# ── Dónde correría Gemma ─────────────────────────────────────────────────────────────────────


def test_llm_dispositivo_cpu_manda_sin_preguntar() -> None:
    def no_preguntar() -> str:
        raise AssertionError("no debía preguntar a Ollama")

    assert dispositivo_llm_probable("cpu", GPU("x", 1), no_preguntar) == ("cpu", False)


def test_ollama_con_el_modelo_cargado_dice_donde_esta() -> None:
    assert dispositivo_llm_probable("auto", None, lambda: "gpu") == ("gpu", False)
    assert dispositivo_llm_probable("auto", GPU("x", 1), lambda: "cpu") == ("cpu", False)


def test_sin_modelo_cargado_usa_la_gpu_que_vio_la_api() -> None:
    assert dispositivo_llm_probable("auto", GPU("x", 1), lambda: "desconocido") == ("gpu", False)


def test_si_no_se_sabe_supone_cpu() -> None:
    def caido() -> str:
        raise RuntimeError("Ollama apagado")

    assert dispositivo_llm_probable("auto", None, lambda: "desconocido") == ("cpu", True)
    assert dispositivo_llm_probable("auto", None, caido) == ("cpu", True)


# ── El endpoint ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    entorno = Entorno(db_session, tmp_path)
    entorno.settings = entorno.settings.model_copy(
        update={"seg_imagen_gpu": 1.5, "seg_imagen_cpu": 15.0, "pasos_por_min": 2.2}
    )
    entorno.app.dependency_overrides[get_plan_dispositivos] = lambda: SIN_GPU
    apagado = OllamaFalso([], disponible=False)  # /api/ps no responde: no se sabe dónde
    entorno.app.dependency_overrides[get_cliente_llm] = apagado.cliente
    return entorno


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def test_modo_validar_usa_los_pasos_del_sop(client: TestClient, entorno: Entorno) -> None:
    sop = SOP(
        titulo="Seis pasos",
        pasos=[PasoSOP(numero=n, nombre=f"Paso {n}", responsable="Técnico") for n in range(1, 7)],
    )
    fila = guardar_sop(entorno.session, sop)
    r = client.get(
        "/videos/estimacion", params={"duracion_s": 135, "modo": "validar", "sop_id": fila.id}
    )
    assert r.status_code == 200
    datos = r.json()
    assert datos["imagenes_estimadas"] == 6
    assert (datos["segundos_extra_gpu"], datos["segundos_extra_cpu"]) == (9.0, 90.0)
    assert (datos["dispositivo"], datos["dispositivo_supuesto"]) == ("cpu", True)
    assert datos["aviso"] == (
        "No se pudo saber si hay GPU: describir 6 imágenes sumará ~9 s con GPU o ~2 min sin ella."
    )


def test_modo_validar_con_pocos_pasos_sube_al_minimo(client: TestClient, entorno: Entorno) -> None:
    fila = guardar_sop(entorno.session, SOP_PRUEBA)  # 3 pasos
    r = client.get(
        "/videos/estimacion", params={"duracion_s": 60, "modo": "validar", "sop_id": fila.id}
    )
    assert r.json()["imagenes_estimadas"] == 4


def test_modo_validar_con_el_sop_convirtiendose_usa_la_duracion(
    client: TestClient, entorno: Entorno
) -> None:
    fila = Sop(origen="cargado", archivo_original="", estado="convirtiendo")
    entorno.session.add(fila)
    entorno.session.commit()
    r = client.get(
        "/videos/estimacion", params={"duracion_s": 300, "modo": "validar", "sop_id": fila.id}
    )
    assert r.json()["imagenes_estimadas"] == 11  # 5 min × 2.2


def test_modo_generar_usa_la_duracion_con_tope_de_20(client: TestClient) -> None:
    corto = client.get("/videos/estimacion", params={"duracion_s": 227.3, "modo": "generar"})
    largo = client.get("/videos/estimacion", params={"duracion_s": 3600, "modo": "generar"})
    assert corto.json()["imagenes_estimadas"] == 8
    assert largo.json()["imagenes_estimadas"] == 20
    assert largo.json()["segundos_extra_cpu"] == 300.0


def test_con_gpu_detectada(client: TestClient, entorno: Entorno) -> None:
    entorno.app.dependency_overrides[get_plan_dispositivos] = lambda: CON_GPU
    datos = client.get("/videos/estimacion", params={"duracion_s": 600, "modo": "generar"}).json()
    assert (datos["dispositivo"], datos["dispositivo_supuesto"]) == ("gpu", False)
    assert datos["aviso"] == "Con GPU: describir 20 imágenes sumará ~30 s."


def test_con_el_modelo_cargado_en_ollama(client: TestClient, entorno: Entorno) -> None:
    ollama = OllamaFalso([])
    ollama.vram = 0  # /api/ps: cargado, nada en VRAM
    entorno.app.dependency_overrides[get_cliente_llm] = ollama.cliente
    entorno.app.dependency_overrides[get_plan_dispositivos] = lambda: CON_GPU
    datos = client.get("/videos/estimacion", params={"duracion_s": 600, "modo": "generar"}).json()
    assert (datos["dispositivo"], datos["dispositivo_supuesto"]) == ("cpu", False)
    assert datos["aviso"] == "Sin GPU: describir 20 imágenes sumará ~5 min."


def test_llm_dispositivo_cpu(client: TestClient, entorno: Entorno) -> None:
    entorno.settings = entorno.settings.model_copy(update={"llm_dispositivo": "cpu"})
    entorno.app.dependency_overrides[get_plan_dispositivos] = lambda: CON_GPU
    datos = client.get("/videos/estimacion", params={"duracion_s": 120, "modo": "generar"}).json()
    assert (datos["dispositivo"], datos["dispositivo_supuesto"]) == ("cpu", False)


def test_errores_de_parametros(client: TestClient) -> None:
    assert (
        client.get("/videos/estimacion", params={"duracion_s": 0, "modo": "generar"}).status_code
        == 422
    )
    assert (
        client.get("/videos/estimacion", params={"duracion_s": 60, "modo": "otro"}).status_code
        == 422
    )
    assert client.get("/videos/estimacion", params={"modo": "generar"}).status_code == 422
    r = client.get(
        "/videos/estimacion", params={"duracion_s": 60, "modo": "validar", "sop_id": 999999}
    )
    assert r.status_code == 404  # fmt: skip
