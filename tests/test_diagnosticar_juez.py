"""Partes puras de `scripts/diagnosticar_juez.py`: huella y comparación de las llamadas al juez.

El diagnóstico de verdad necesita Ollama y un video: se lanza a mano.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import diagnosticar_juez as dj  # noqa: E402  (la ruta se ajusta arriba)


def _llamada(paso: int, entrada: str, salida: str, veredicto: str | None = "Parcial") -> dict:
    return {
        "paso_sop": paso,
        "entrada": entrada,
        "salida": salida,
        "juicio": {"veredicto": veredicto, "motivo": None if veredicto else "llm_no_disponible"},
    }


def test_huella_estable_e_independiente_del_orden_de_las_claves() -> None:
    assert dj.huella({"a": 1, "b": [2]}) == dj.huella({"b": [2], "a": 1})
    assert dj.huella({"a": 1}) != dj.huella({"a": 2})
    assert len(dj.huella("x")) == 12


def test_comparar_separa_entradas_distintas_de_salidas_distintas() -> None:
    corridas = [
        {"repeticion": 1, "llamadas_juez": [_llamada(6, "e1", "s1")]},
        {"repeticion": 2, "llamadas_juez": [_llamada(6, "e2", "s2", "no_corresponde")]},
        {"repeticion": 3, "llamadas_juez": [_llamada(6, "e1", "s1"), _llamada(3, "e9", "s9")]},
        {"repeticion": 4, "llamadas_juez": []},
    ]
    filas = {f["paso_sop"]: f for f in dj.comparar(corridas)}
    assert filas[6]["corridas"] == [1, 2, 3]
    assert filas[6]["veredictos"] == [(1, "Parcial"), (2, "no_corresponde"), (3, "Parcial")]
    assert filas[6]["entradas_distintas"] == 2
    assert filas[6]["misma_entrada_salidas_distintas"] is False
    assert filas[3]["entradas_distintas"] == 1


def test_comparar_detecta_la_misma_entrada_con_salidas_distintas() -> None:
    corridas = [
        {"repeticion": 1, "llamadas_juez": [_llamada(6, "e1", "s1")]},
        {"repeticion": 2, "llamadas_juez": [_llamada(6, "e1", "s2", None)]},
    ]
    [fila] = dj.comparar(corridas)
    assert fila["misma_entrada_salidas_distintas"] is True
    assert fila["veredictos"] == [(1, "Parcial"), (2, "llm_no_disponible")]
