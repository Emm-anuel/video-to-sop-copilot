"""Partes puras de `scripts/medir_whisper.py`: alineación por palabras y tramos que llegan a la
ficha o a los pasos. La medición de verdad necesita Whisper y Ollama: se lanza a mano. Los textos
son inventados."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_whisper as mw  # noqa: E402  (la ruta se ajusta arriba)


def test_alinear_cuenta_sustituciones_inserciones_y_borrados():
    ref = ["cambio", "el", "cartucho", "de", "la", "linea", "de", "enjuague"]
    assert mw.alinear(ref, ref) == (0, [])
    hip = ["cambio", "el", "cartucho", "de", "la", "clinica", "del", "jugue"]
    assert mw.alinear(ref, hip) == (3, [("linea de enjuague", "clinica del jugue")])
    assert mw.alinear(["a", "b"], ["a", "b", "c"]) == (1, [("", "c")])
    assert mw.alinear(["a", "b"], ["b"]) == (1, [("a", "")])


def test_un_tramo_afecta_si_una_palabra_nueva_aparece_aunque_el_valor_la_corrija():
    ref = ["cambio", "el", "cartucho", "de", "la", "linea", "de", "enjuague"]
    tramos = [("linea de enjuague", "clinica del jugue"), ("el", "un")]
    textos = {"lugar": "Clínica del jugo", "tema": "Mantenimiento", "paso 1": "Cambiar un cartucho"}

    # Cada palabra nueva cuenta donde aparezca: "clinica" en el lugar (Gemma corrigió "jugue"
    # por "jugo" en el valor) y "un" en el paso; "Mantenimiento" no trae ninguna.
    assert mw.afectados(tramos, set(ref), textos) == [
        {"referencia": "linea de enjuague", "whisper": "clinica del jugue", "en": ["lugar"]},
        {"referencia": "el", "whisper": "un", "en": ["paso 1"]},
    ]


def test_textos_de_la_ficha_y_de_los_pasos():
    dato = {"valor": None}
    ficha = {
        **{k: dato for k in ("actividad", "tema", "horario_mencionado", "proposito", "resumen")},
        "lugar": {"valor": "Clínica del jugo"},
        "personas": [{"nombre": "No identificado", "rol": "técnico", "cita": "soy el técnico"}],
        "equipos": [{"nombre": "guantes del tilo"}],
    }
    textos = mw.textos_de_la_ficha(ficha)
    assert textos["lugar"] == "Clínica del jugo"
    assert textos["persona 1"] == "No identificado técnico soy el técnico"
    assert textos["equipo guantes del tilo"] == "guantes del tilo"
    pasos = [{"numero": 2, "nombre": "Ponerse guantes", "descripcion": "", "cita": "del tilo"}]
    assert mw.textos_de_los_pasos(pasos) == {"paso 2": "Ponerse guantes  del tilo"}
