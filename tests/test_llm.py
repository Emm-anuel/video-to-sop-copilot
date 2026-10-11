"""Cliente LLM con Ollama simulado (httpx.MockTransport): no requiere Ollama ni GPU."""

import json
import time

import httpx
import pytest

from sopvid.lenguaje.llm import (
    SEMILLA,
    ClienteLLM,
    LLMError,
    LLMNoDisponible,
    LLMRespuestaInvalida,
)
from sopvid.plataforma.config import Settings

MODELO = "gemma4:e2b-it-q4_K_M"
ESQUEMA = {
    "type": "object",
    "properties": {"respuesta": {"type": "string"}},
    "required": ["respuesta"],
}


def respuesta_chat(contenido: str, **extra) -> httpx.Response:
    cuerpo = {
        "model": MODELO,
        "message": {"role": "assistant", "content": contenido},
        "done": True,
        "done_reason": "stop",
        "total_duration": 900,
        "load_duration": 100,
        "prompt_eval_count": 20,
        "prompt_eval_duration": 300,
        "eval_count": 10,
        "eval_duration": 500,
    }
    cuerpo.update(extra)
    return httpx.Response(200, json=cuerpo)


def cliente_con(manejador, **kwargs) -> ClienteLLM:
    return ClienteLLM(
        "http://ollama.test:11434/",
        MODELO,
        timeout_s=5,
        num_ctx=8192,
        transport=httpx.MockTransport(manejador),
        **kwargs,
    )


def test_chat_envia_esquema_opciones_deterministas_y_think_apagado():
    peticiones = []

    def manejador(request):
        peticiones.append(request)
        return respuesta_chat('{"respuesta": "hola"}')

    with cliente_con(manejador) as cliente:
        r = cliente.chat([{"role": "user", "content": "di hola"}], esquema=ESQUEMA)

    (peticion,) = peticiones
    assert peticion.url == "http://ollama.test:11434/api/chat"
    cuerpo = json.loads(peticion.content)
    assert cuerpo["model"] == MODELO
    assert cuerpo["stream"] is False
    assert cuerpo["think"] is False
    assert cuerpo["format"] == ESQUEMA
    assert cuerpo["options"] == {"num_ctx": 8192, "temperature": 0, "seed": SEMILLA}
    assert r.datos == {"respuesta": "hola"}
    assert r.razon_fin == "stop"
    assert r.metricas["eval_count"] == 10
    assert r.metricas["load_duration"] == 100


def test_chat_sin_esquema_no_manda_format_ni_interpreta_json():
    cuerpos = []

    def manejador(request):
        cuerpos.append(json.loads(request.content))
        return respuesta_chat("texto libre")

    with cliente_con(manejador) as cliente:
        r = cliente.chat([{"role": "user", "content": "resume"}])

    assert "format" not in cuerpos[0]
    assert r.texto == "texto libre"
    assert r.datos is None


@pytest.mark.parametrize(
    ("del_cliente", "en_llamada", "esperado"),
    [(True, None, True), (False, True, True), (True, False, False)],
)
def test_think_es_configurable(del_cliente, en_llamada, esperado):
    cuerpos = []

    def manejador(request):
        cuerpos.append(json.loads(request.content))
        return respuesta_chat("ok")

    with cliente_con(manejador, think=del_cliente) as cliente:
        cliente.chat([{"role": "user", "content": "x"}], think=en_llamada)

    assert cuerpos[0]["think"] is esperado


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("lento"), httpx.ConnectError("caído"), httpx.ReadError("corte")]
)
def test_reintenta_una_vez_ante_timeout_o_error_de_red(error):
    llamadas = []

    def manejador(request):
        llamadas.append(request)
        if len(llamadas) == 1:
            raise error
        return respuesta_chat('{"respuesta": "segunda"}')

    with cliente_con(manejador) as cliente:
        r = cliente.chat([{"role": "user", "content": "x"}], esquema=ESQUEMA)

    assert len(llamadas) == 2
    assert r.datos == {"respuesta": "segunda"}


def test_dos_timeouts_seguidos_dan_llm_no_disponible():
    llamadas = []

    def manejador(request):
        llamadas.append(request)
        raise httpx.ReadTimeout("lento")

    with cliente_con(manejador) as cliente, pytest.raises(LLMNoDisponible):
        cliente.chat([{"role": "user", "content": "x"}])

    assert len(llamadas) == 2


@pytest.mark.parametrize("status", [404, 500, 503])
def test_modelo_ausente_o_error_del_servidor_no_se_reintenta(status):
    llamadas = []

    def manejador(request):
        llamadas.append(request)
        return httpx.Response(status, json={"error": "model not found"})

    with cliente_con(manejador) as cliente, pytest.raises(LLMNoDisponible, match=str(status)):
        cliente.chat([{"role": "user", "content": "x"}])

    assert len(llamadas) == 1


def test_peticion_rechazada_da_llm_error_sin_reintento():
    llamadas = []

    def manejador(request):
        llamadas.append(request)
        return httpx.Response(400, json={"error": "invalid format"})

    with cliente_con(manejador) as cliente, pytest.raises(LLMError) as info:
        cliente.chat([{"role": "user", "content": "x"}])

    assert not isinstance(info.value, LLMNoDisponible | LLMRespuestaInvalida)
    assert len(llamadas) == 1


def test_json_roto_con_esquema_da_respuesta_invalida_sin_filtrar_el_texto():
    secreto = '{"respuesta": "dato del cliente'  # JSON truncado

    cliente = cliente_con(lambda r: respuesta_chat(secreto, done_reason="length"))
    with cliente, pytest.raises(LLMRespuestaInvalida, match="done_reason=length") as info:
        cliente.chat([{"role": "user", "content": "x"}], esquema=ESQUEMA)

    assert "dato del cliente" not in str(info.value)


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(200, text="no es json"),
        httpx.Response(200, json={"done": True}),
        httpx.Response(200, json={"message": {"content": None}}),
    ],
)
def test_cuerpo_mal_formado_da_respuesta_invalida(respuesta):
    with cliente_con(lambda r: respuesta) as cliente, pytest.raises(LLMRespuestaInvalida):
        cliente.chat([{"role": "user", "content": "x"}])


def test_las_excepciones_de_httpx_no_escapan():
    def manejador(request):
        raise httpx.UnsupportedProtocol("raro")

    with cliente_con(manejador) as cliente, pytest.raises(LLMNoDisponible):
        cliente.chat([{"role": "user", "content": "x"}])


def tags(*nombres: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in nombres]})


def test_disponible_si_el_modelo_esta_descargado_y_usa_el_timeout_dado():
    timeouts = []

    def manejador(request):
        assert request.url.path == "/api/tags"
        timeouts.append(request.extensions["timeout"])
        return tags("qwen3:8b-q4_K_M", MODELO)

    with cliente_con(manejador) as cliente:
        assert cliente.disponible(timeout_s=2) is True

    assert timeouts[0]["connect"] == 2
    assert timeouts[0]["read"] == 2


def test_no_disponible_si_falta_el_modelo():
    with cliente_con(lambda r: tags("qwen3:8b-q4_K_M")) as cliente:
        assert cliente.disponible() is False


def test_nombre_sin_etiqueta_equivale_a_latest():
    t = httpx.MockTransport(lambda r: tags("gemma4:latest"))
    with ClienteLLM("http://ollama.test:11434", "gemma4", transport=t) as cliente:
        assert cliente.disponible() is True


@pytest.mark.parametrize(
    "manejador",
    [
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("caído")),
        lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("lento")),
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, text="<html>"),
        lambda r: httpx.Response(200, json={"otra": "cosa"}),
    ],
)
def test_disponible_nunca_lanza(manejador):
    with cliente_con(manejador) as cliente:
        assert cliente.disponible(timeout_s=0.1) is False


def test_disponible_respeta_el_plazo_aunque_la_red_ignore_los_timeouts():
    # Simula la resolución DNS de un nombre inexistente en Docker Desktop (~4 s), que los
    # timeouts de httpx no cubren.
    def manejador(request):
        time.sleep(1.5)
        return tags(MODELO)

    with cliente_con(manejador) as cliente:
        inicio = time.perf_counter()
        assert cliente.disponible(timeout_s=0.2) is False
        assert time.perf_counter() - inicio < 1.0


def test_desde_settings_toma_las_variables_llm():
    settings = Settings(
        llm_base_url="http://ollama:11434",
        llm_model="qwen3:8b-q4_K_M",
        llm_timeout_s=30,
        llm_num_ctx=4096,
    )
    with ClienteLLM.desde_settings(settings) as cliente:
        assert cliente.base_url == "http://ollama:11434"
        assert cliente.modelo == "qwen3:8b-q4_K_M"
        assert cliente.timeout_s == 30
        assert cliente.num_ctx == 4096
        assert cliente.think is False
