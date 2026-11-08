"""Partes puras de `scripts/medir_tiempos.py`: criterio según la anotación, tramos anotados,
explicación de un *excede* e informe.

La medición de verdad necesita Whisper, Ollama y los videos: se lanza a mano (ADR-021).
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_tiempos as mt  # noqa: E402  (la ruta se ajusta arriba)

# Anotación inventada con la forma de media/anotacion_ab.json.
ANOTACION_C = {
    "duracion_s": 100.0,
    "pasos": [
        {"sop": None, "nombre": "Intro", "t": 1.0},
        {"sop": 1, "nombre": "Uno", "t": 10.0, "esperado_tiempo": "Excede"},
        {"sop": 3, "nombre": "Tres", "t": 50.0},
        {"sop": 2, "nombre": "Dos", "t": 70.0},
        {"sop": None, "nombre": "Cierre", "t": 95.0},
    ],
}
ANOTACION_A = {
    "pasos": [
        {"sop": None, "t": 0.0},
        {"sop": 1, "t": 5.0},
        {"sop": "extra", "t": 20.0},
        {"sop": 2, "t": 30.0},
    ]
}


def _fila(paso: int, estado: str, **extra) -> dict:
    return {"paso_sop": paso, "tiempo": {"estado": estado, "origen": "medido", "cita": ""}, **extra}


def test_excede_esperados_segun_la_anotacion() -> None:
    assert mt.excede_esperados(ANOTACION_C) == [1]
    assert mt.excede_esperados(ANOTACION_A) is None


def test_tramos_anotados_hasta_lo_siguiente_o_el_final() -> None:
    assert mt.tramos_anotados(ANOTACION_C, 999.0) == {
        1: (10.0, 50.0),
        3: (50.0, 70.0),
        2: (70.0, 95.0),
    }
    # Un Sobra anotado ("extra") también corta el tramo; el último va al final del video.
    assert mt.tramos_anotados(ANOTACION_A, 40.0) == {1: (5.0, 20.0), 2: (30.0, 40.0)}


def test_criterio_exige_exactamente_los_excede_anotados() -> None:
    filas = [_fila(1, "excede"), _fila(2, "menor"), _fila(3, "en_tiempo")]
    assert mt.criterio([1], filas, True) == (True, [])
    filas.append(_fila(4, "excede"))
    pasa, motivos = mt.criterio([1], filas, True)
    assert not pasa and "[1, 4]" in motivos[0]
    assert mt.criterio([1], [_fila(1, "en_tiempo")], True)[0] is False


def test_sin_criterio_solo_informa_pero_la_corrida_debe_ser_valida() -> None:
    filas = [_fila(1, "excede")]
    assert mt.criterio(None, filas, True) == (True, [])
    pasa, motivos = mt.criterio(None, filas, False)
    assert not pasa and "no válida" in motivos[0]


def test_por_que_excede() -> None:
    fila = _fila(1, "excede", tramo=[2.0, 60.0], anotado=[10.0, 50.0], originales=[1, 2])
    notas = mt.por_que_excede(fila)
    assert notas[0] == "fusión de 2 pasos del video"
    assert "empieza 8.0 s antes" in notas[1]
    assert "termina 10.0 s después" in notas[2]
    sola = _fila(1, "excede", tramo=[10.0, 49.0], anotado=[10.0, 50.0], originales=[2])
    assert mt.por_que_excede(sola) == ["el paso duró más que lo esperado"]


def test_informe_y_codigo_de_salida() -> None:
    corrida = {
        "video": "video_c",
        "repeticion": 1,
        "cumplimiento": 75.0,
        "estados_tiempo": {"en_tiempo": 1, "menor": 1, "excede": 1},
        "total": {"esperado_min": 3.0, "observado_min": 2.5, "estado": "en_tiempo"},
        "horario": {"estado": "coincide"},
        "filas": [
            {
                **_fila(1, "excede"),
                "estado": "Cumple",
                "paso_video": 2,
                "fuera_de_orden": False,
                "tramo": [10.0, 80.0],
                "originales": [2],
                "anotado": [10.0, 82.0],
                "dif_inicio_s": 0.0,
                "dif_duracion_s": -2.0,
                "por_que": ["el paso duró más que lo esperado"],
            }
            | {
                "tiempo": {
                    "estado": "excede",
                    "origen": "medido",
                    "cita": "",
                    "observado_min": 1.17,
                }
            },
            {"estado": "Sobra", "paso_sop": None, "paso_video": 1, "fuera_de_orden": False},
        ],
        "valida": True,
        "pasa": True,
        "motivos": [],
    }
    datos = {
        "fecha": "2026-11-08T12:00:00",
        "git": {"commit": "abc", "cambios_sin_commit": 0},
        "sop": "tests/fixtures/sop_filtro_agua.md",
        "modelos": {},
        "umbrales": {"tolerancia_tiempo": 0.2},
        "corridas": [corrida],
    }
    texto = mt.informe(datos)
    assert (
        "| video_c · 1 | 75.0 | 1 / 1 / 1 | [1] | 2.50 / 3.00, en_tiempo | coincide | pasa |"
        in texto
    )
    assert "| 1 ↔ 2 | Cumple | 10.0–80.0 | [2] | 1.17 (medido) | excede | 10.0–82.0 |" in texto
    assert mt.codigo_salida([corrida]) == 0
    assert mt.codigo_salida([{**corrida, "pasa": False}]) == 1
    assert mt.codigo_salida([{**corrida, "valida": False, "pasa": False}]) == 2
