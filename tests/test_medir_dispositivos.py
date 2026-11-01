"""Partes puras de `scripts/medir_dispositivos.py`: criterio de la anotación, estimado y tabla.

La corrida de verdad necesita Whisper, Ollama y los videos A y B: se lanza a mano (ADR-018).
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sopvid.contrato import SOP, PasoSOP
from sopvid.plataforma.config import Settings

RAIZ = Path(__file__).resolve().parents[1]

SOP_SEIS = SOP(
    titulo="Inventado",
    pasos=[PasoSOP(numero=n, nombre=f"Paso {n}", responsable="Técnico") for n in range(1, 7)],
)
# Como la de B: faltan 2 y 6 y hay un paso agregado entre 74 y 86 s.
ANOTACION_B = {
    "pasos": [
        {"sop": None, "t": 3.5},
        {"sop": 1, "t": 17.0},
        {"sop": 3, "t": 31.7},
        {"sop": 4, "t": 49.9},
        {"sop": "extra", "t": 74.1},
        {"sop": 5, "t": 85.9},
        {"sop": None, "t": 111.0},
    ]
}


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "medir_dispositivos", RAIZ / "scripts" / "medir_dispositivos.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    # Las dataclasses del script buscan su módulo en sys.modules al crearse.
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _fila(estado, indice_sop=None, t=None, marco=None):
    return SimpleNamespace(estado=estado, indice_sop=indice_sop, t_inicio=t, marco_operador=marco)


def _guardado(filas, cumplimiento):
    clasificacion = SimpleNamespace(pasos=filas)
    return SimpleNamespace(
        resultado=SimpleNamespace(clasificacion=clasificacion), cumplimiento=cumplimiento
    )


def test_esperado_sale_de_la_anotacion(script):
    esperado = script.esperado_de(ANOTACION_B, SOP_SEIS, 115.0)

    assert esperado.falta == {2, 6}
    assert esperado.extras == ((74.1, 85.9),)


def test_criterio_de_b_pasa_con_las_falta_exactas_y_el_sobra_en_su_tramo(script):
    esperado = script.esperado_de(ANOTACION_B, SOP_SEIS, 115.0)
    filas = [
        _fila("Cumple", 0, 17.0),
        _fila("Falta", 1),
        _fila("Cumple", 2, 32.0),
        _fila("Cumple", 3, 50.0),
        _fila("Cumple", 4, 86.0),
        _fila("Falta", 5),
        _fila("Sobra", t=74.5),
        _fila("Sobra", t=3.5, marco="intro"),
    ]

    resultado = script.criterio(_guardado(filas, 66.7), SOP_SEIS, esperado, Settings())

    assert resultado == {
        "pasa": True,
        "falta_obtenida": [2, 6],
        "falta_esperada": [2, 6],
        "extras_encontrados": "1/1",
    }


def test_criterio_no_pasa_si_el_sobra_es_la_intro_o_falta_otro_paso(script):
    esperado = script.esperado_de(ANOTACION_B, SOP_SEIS, 115.0)
    solo_intro = [_fila("Falta", 1), _fila("Falta", 5), _fila("Sobra", t=74.5, marco="intro")]
    otra_falta = [_fila("Falta", 1), _fila("Falta", 2), _fila("Sobra", t=74.5)]

    assert not script.criterio(_guardado(solo_intro, 66.7), SOP_SEIS, esperado, Settings())["pasa"]
    assert not script.criterio(_guardado(otra_falta, 66.7), SOP_SEIS, esperado, Settings())["pasa"]


def test_sin_falta_esperada_exige_verde(script):
    anotacion = {"pasos": [{"sop": n, "t": 10.0 * n} for n in range(1, 7)]}
    esperado = script.esperado_de(anotacion, SOP_SEIS, 70.0)
    filas = [_fila("Cumple", i, 10.0 * (i + 1)) for i in range(6)]
    ajustes = Settings(semaforo_verde=90, semaforo_amarillo=70)

    assert script.criterio(_guardado(filas, 100.0), SOP_SEIS, esperado, ajustes)["pasa"]
    assert not script.criterio(_guardado(filas, 83.3), SOP_SEIS, esperado, ajustes)["pasa"]


def test_estimado_de_10_minutos_es_lineal(script):
    corrida = script.Corrida("cpu", "small", "video_a", duracion_video_s=120.0, total_s=60.0)

    assert corrida.tiempo_real == 0.5
    assert corrida.estimado_10_min_s == 300.0


def test_tabla_marca_si_cpu_y_gpu_dan_resultados_distintos(script):
    def corrida(config, pct):
        return script.Corrida(
            config,
            "small",
            "video_a",
            duracion_video_s=120.0,
            total_s=60.0,
            dispositivos={"transcripcion": "cpu", "llm": config},
            compute_type="int8",
            cumplimiento=pct,
            semaforo="verde",
            conteo={"Cumple": 6},
            criterio={"pasa": True},
        )

    equipo = {
        "fecha": "2026-10-27",
        "cpu": "CPU de prueba",
        "nucleos": 8,
        "ram_gb": 32.0,
        "gpu": None,
        "llm_model": "falso",
    }

    igual = script.tabla([corrida("cpu", 100.0), corrida("gpu", 100.0)], equipo)
    distinto = script.tabla([corrida("cpu", 100.0), corrida("gpu", 83.3)], equipo)

    assert "video_a, Whisper small: igual entre corridas" in igual
    assert "DISTINTO (2 resultados)" in distinto
    assert "| 5.0 min | no cumple |" in igual  # 300 s justo: la meta es menos de 5 min
