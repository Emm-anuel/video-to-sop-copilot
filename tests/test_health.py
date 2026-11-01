import pytest
from sqlalchemy.exc import OperationalError

from sopvid.lenguaje.llm import ClienteLLM, get_cliente_llm
from sopvid.plataforma.config import get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.hardware import GPU, PlanDispositivos, get_plan_dispositivos

PLAN = PlanDispositivos(gpu=None, nucleos=4, transcripcion="cpu", compute_type="int8", llm="auto")
DISPOSITIVOS = {
    "gpu": None,
    "transcripcion": "cpu/int8",
    "llm": "auto",
    "embedder": "cpu",
    "avisos": [],
}


class LLMFalso:
    def __init__(self, disponible: bool):
        self._disponible = disponible
        self.timeouts = []

    def disponible(self, timeout_s=None):
        self.timeouts.append(timeout_s)
        return self._disponible


@pytest.fixture(autouse=True)
def plan_fijo(client):
    client.app.dependency_overrides[get_plan_dispositivos] = lambda: PLAN


@pytest.fixture
def llm_caido(client):
    falso = LLMFalso(disponible=False)
    client.app.dependency_overrides[get_cliente_llm] = lambda: falso
    return falso


def test_health_ok_con_base_real(client, llm_caido):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "llm": "no_disponible",
        "dispositivos": DISPOSITIVOS,
    }


def test_health_503_si_la_base_no_responde(client, llm_caido):
    class SesionCaida:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    client.app.dependency_overrides[get_session] = lambda: SesionCaida()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "db": "error",
        "llm": "no_disponible",
        "dispositivos": DISPOSITIVOS,
    }


def test_health_informa_llm_ok_y_usa_el_timeout_corto(client):
    falso = LLMFalso(disponible=True)
    client.app.dependency_overrides[get_cliente_llm] = lambda: falso

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["llm"] == "ok"
    assert falso.timeouts == [get_settings().llm_health_timeout_s]


def test_health_no_falla_si_el_llm_no_responde_de_verdad(client):
    # Puerto local cerrado: el cliente real debe contestar "no_disponible" sin excepción.
    def cliente_a_puerto_cerrado():
        with ClienteLLM("http://127.0.0.1:9", "gemma4:e2b-it-q4_K_M") as cliente:
            yield cliente

    client.app.dependency_overrides[get_cliente_llm] = cliente_a_puerto_cerrado

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["llm"] == "no_disponible"


def test_health_informa_la_gpu_y_los_avisos_del_plan(client, llm_caido):
    plan = PlanDispositivos(
        gpu=GPU("NVIDIA GeForce RTX 2070 SUPER", 8192),
        nucleos=16,
        transcripcion="cuda",
        compute_type="float16",
        llm="cpu",
        avisos=("LLM_DISPOSITIVO=cpu: Gemma no usa la GPU aunque exista",),
    )
    client.app.dependency_overrides[get_plan_dispositivos] = lambda: plan

    dispositivos = client.get("/health").json()["dispositivos"]

    assert dispositivos["gpu"] == {"nombre": "NVIDIA GeForce RTX 2070 SUPER", "vram_mb": 8192}
    assert (dispositivos["transcripcion"], dispositivos["llm"]) == ("cuda/float16", "cpu")
    assert dispositivos["avisos"] == list(plan.avisos)
