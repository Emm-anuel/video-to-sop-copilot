"""Funciones puras de `scripts/medir_sop_generado.py` (sin Ollama ni Whisper)."""

import json
import sys
from pathlib import Path

import pytest

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


TRAMOS = {1: (10.0, 30.0), 2: (30.0, 50.0), 3: (50.0, 70.0)}


def test_un_paso_correcto_por_tramos_cae_dentro_de_un_solo_paso_de_referencia():
    assert medir.paso_del_tramo(12.0, 29.0, TRAMOS) == 1
    assert medir.paso_del_tramo(9.5, 30.8, TRAMOS) == 1  # tolerancia de 1 s en cada borde
    assert medir.paso_del_tramo(20.0, 45.0, TRAMOS) is None  # mezcla los pasos 1 y 2
    assert medir.paso_del_tramo(0.0, 8.0, TRAMOS) is None  # la presentación
    assert medir.paso_del_tramo(29.5, 30.5, TRAMOS) == 2  # cabe en dos: gana el punto medio


def test_varios_pasos_en_un_mismo_paso_de_referencia_cuentan_y_el_orden_se_respeta():
    pasos = [(10.0, 15.0), (15.0, 29.0), (31.0, 49.0), (12.0, 20.0), (50.0, 69.0), (20.0, 60.0)]
    assert medir.correctos_por_tramos(pasos, TRAMOS) == [
        (1, True),
        (1, True),  # más detallado que la referencia: no se castiga
        (2, True),
        (1, False),  # vuelve a un paso anterior
        (3, True),
        (None, False),  # mezcla pasos de referencia
    ]


# ── SOP editado en el editor (RF-26, ADR-025) ───────────────────────────────────────────────

SOP_EDITADO = {
    "titulo": "x",
    "pasos": [
        {"numero": 1, "nombre": "Cerrar la llave", "responsable": "T", "t_inicio": 10, "t_fin": 49},
        {"numero": 2, "nombre": "Anotar", "responsable": "T"},
    ],
}


def test_un_paso_agregado_a_mano_sin_tiempos_no_cae_en_ningun_tramo():
    assert medir.correctos_por_tramos([(12.0, 29.0), (None, None)], TRAMOS) == [
        (1, True),
        (None, False),
    ]
    assert medir._tramo({"t_inicio": None, "t_fin": None}) == "sin tiempos"
    assert medir._tramo({"t_inicio": 10.0, "t_fin": 49.0}) == "10.0–49.0"


@pytest.mark.parametrize(
    "contenido",
    [
        SOP_EDITADO,  # el SOP del contrato
        {"id": 42, "codigo": "SOP-0042", "sop": SOP_EDITADO},  # GET /sops/{id}
        {"sop": SOP_EDITADO, "advertencias": [], "generacion": {}},  # archivo de una corrida
    ],
)
def test_el_sop_editado_se_lee_de_un_json(tmp_path, contenido):
    ruta = tmp_path / "editado.json"
    ruta.write_text(json.dumps(contenido), "utf-8")
    sop = medir.leer_sop_editado(str(ruta))
    assert [p.nombre for p in sop.pasos] == ["Cerrar la llave", "Anotar"]


def test_el_sop_editado_se_lee_por_sop_id(monkeypatch):
    class Fila:
        contenido = SOP_EDITADO

    class Sesion:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, modelo, sop_id):
            return Fila() if sop_id == 42 else None

    monkeypatch.setattr(medir, "get_sessionmaker", lambda: Sesion)
    assert len(medir.leer_sop_editado("42").pasos) == 2
    with pytest.raises(SystemExit, match="no existe"):
        medir.leer_sop_editado("7")
    with pytest.raises(SystemExit, match="ni un archivo"):
        medir.leer_sop_editado("no_existe.json")


def test_sop_editado_espera_clave_y_origen():
    assert medir.ediciones(["video_e=42", "video_a=sop.json"]) == {
        "video_e": "42",
        "video_a": "sop.json",
    }
    with pytest.raises(SystemExit):
        medir.ediciones(["42"])
