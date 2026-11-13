"""Parte pura de `scripts/medir_s5.py`: unir tandas intercaladas de la misma fase.

La medición de verdad necesita la GPU, Ollama y los videos del equipo: se lanza a mano. Las
tandas de aquí son inventadas.
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

medir_s5 = pytest.importorskip("medir_s5")


def _tanda(inicio: str, videos: list[str], repro: dict | None = None, segundos: float = 100.0):
    return {
        "fase": "gpu",
        "inicio": inicio,
        "fin": inicio.replace("T10", "T11"),
        "segundos_fase": segundos,
        "reproducibilidad": repro,
        "corridas": [{"video": v, "n": 1, "pasa": True} for v in videos],
    }


def test_una_sola_tanda_queda_igual():
    t = _tanda("2026-11-13T10:00:00", ["video_a"])
    assert medir_s5.unir_tandas([t]) == [t]


def test_tandas_se_unen_en_orden_y_se_renumeran_por_video():
    segunda = _tanda("2026-11-13T10:30:00", ["video_a", "video_b"], segundos=50.0)
    primera = _tanda(
        "2026-11-13T10:00:00", ["video_a", "video_b", "video_e"], repro={"regeneradas": [1]}
    )
    (unida,) = medir_s5.unir_tandas([segunda, primera])
    assert [(c["video"], c["n"], c["tanda"]) for c in unida["corridas"]] == [
        ("video_a", 1, 1),
        ("video_b", 1, 1),
        ("video_e", 1, 1),
        ("video_a", 2, 2),
        ("video_b", 2, 2),
    ]
    assert unida["repeticiones"] == {"video_a": 2, "video_b": 2, "video_e": 1}
    assert unida["reproducibilidad"] == {"regeneradas": [1]}
    assert unida["segundos_fase"] == 150.0
    assert unida["inicio"] == "2026-11-13T10:00:00"
    assert unida["fin"] == segunda["fin"]
    assert [t["videos"] for t in unida["tandas"]] == [
        ["video_a", "video_b", "video_e"],
        ["video_a", "video_b"],
    ]


def test_fases_distintas_no_se_mezclan():
    gpu = _tanda("2026-11-13T10:00:00", ["video_a"])
    cpu = {**_tanda("2026-11-13T12:00:00", ["video_a"]), "fase": "cpu"}
    assert [f["fase"] for f in medir_s5.unir_tandas([gpu, cpu])] == ["gpu", "cpu"]
