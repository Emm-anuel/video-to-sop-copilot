"""Funciones puras de `scripts/medir_sop_generado.py` (sin Ollama ni Whisper)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import medir_sop_generado as medir  # noqa: E402

from sopvid.contrato import SOP  # noqa: E402

ANOTACION = {
    "pasos": [
        {"sop": None, "nombre": "Intro", "t": 0.0},
        {"sop": 1, "nombre": "Uno", "t": 10.0},
        {"sop": 2, "nombre": "Dos", "t": 30.0},
        {"sop": None, "nombre": "Cierre", "t": 50.0},
    ]
}


def test_los_tramos_anotados_van_hasta_el_siguiente_segundo_anotado():
    assert medir.tramos_anotados(ANOTACION, 60.0) == {1: (10.0, 30.0), 2: (30.0, 50.0)}


def test_un_paso_generado_se_compara_como_paso_del_video_con_sus_tiempos():
    sop = SOP.model_validate(
        {
            "titulo": "x",
            "pasos": [
                {
                    "numero": 1,
                    "nombre": "Cerrar la llave",
                    "responsable": "Técnico",
                    "t_inicio": 12.0,
                    "t_fin": 20.0,
                    "cita": "cierro la llave",
                    "fuente": "audio",
                    "confianza": "alta",
                },
                {"numero": 2, "nombre": "Anotar", "responsable": "Técnico"},
            ],
        }
    )
    uno, dos = medir.como_paso_video(sop)
    assert (uno.t_inicio, uno.t_fin, uno.cita, uno.fuente) == (
        12.0,
        20.0,
        "cierro la llave",
        "audio",
    )
    # Un paso sin tiempos ni evidencia (p. ej. editado a mano) entra como inferido en 0 s.
    assert (dos.t_inicio, dos.fuente) == (0.0, "inferido")


def test_la_completitud_cuenta_lo_que_quedo_lleno():
    sop = SOP.model_validate(
        {"titulo": "x", "pasos": [{"numero": 1, "nombre": "Cerrar", "responsable": "T"}]}
    )
    c = medir.completitud(sop)
    assert (c["pasos"], c["pasos_en_infinitivo"], c["objetivo"], c["riesgos"]) == (1, 1, None, 0)


def test_la_cobertura_cuenta_cada_paso_de_referencia_cumplido_en_orden_una_vez():
    def fila(ref, estado, fuera=False):
        return {"referencia": ref, "estado": estado, "fuera_de_orden": fuera}

    filas = [
        fila(1, "Cumple"),
        fila(None, "Sobra"),
        fila(2, "Parcial"),
        fila(3, "Cumple", fuera=True),  # fuera de orden: no cuenta
        fila(4, "zona_gris"),  # sin decidir: no cuenta
        fila(2, "Cumple"),  # repetido: cuenta una vez
    ]
    assert medir.cobertura_en_orden(filas) == [1, 2]
