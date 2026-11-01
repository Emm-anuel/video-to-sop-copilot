"""Pruebas de la lectura de la anotación en `scripts/calibrar_umbrales.py`.

Solo las funciones que no tocan modelos: los tramos anotados y la verdad esperada por paso del
SOP. La rejilla de umbrales necesita MiniLM (~470 MB) y videos reales, y se corre como script.
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import calibrar_umbrales as cal  # noqa: E402  (la ruta se ajusta arriba)

from apoyo import pasos_del_video  # noqa: E402


def _paso(numero: int, t_inicio: float, t_fin: float) -> object:
    return pasos_del_video(("uno",) * numero)[-1].model_copy(
        update={"numero": numero, "t_inicio": t_inicio, "t_fin": t_fin, "cita": f"cita {numero}"}
    )


ANOTACION = {
    "v": {
        "esperado": "prueba",
        "pasos": [
            {"t": 0.0, "nombre": "Intro", "sop": None},
            {"t": 5.0, "nombre": "Preparar", "sop": 1},
            {"t": 10.0, "nombre": "Cerrar", "sop": 2},
            {"t": 15.0, "nombre": "Limpiar", "sop": "extra"},
        ],
    }
}


def test_tramos_de_cierra_el_ultimo_con_la_duracion() -> None:
    tramos = cal.tramos_de(ANOTACION["v"], 20.0)

    bordes = [(t.inicio, t.fin) for t in tramos]
    assert bordes == [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0)]
    assert [t.sop for t in tramos] == [None, 1, 2, "extra"]


def test_tramo_mayor_gana_por_encime_no_por_el_inicio() -> None:
    tramos = cal.tramos_de(ANOTACION["v"], 20.0)
    # Un paso de 9.0 a 13.0 empieza en "Preparar" pero pasa 3 s en "Cerrar" y solo 1 s en el otro.
    paso = _paso(1, 9.0, 13.0)

    assert cal.tramo_mayor(paso, tramos).nombre == "Cerrar"
    assert cal.encime(paso, tramos[2]) == pytest.approx(3.0)
    assert cal.encime(paso, tramos[1]) == pytest.approx(1.0)


def test_esperado_ignora_intro_y_extra() -> None:
    tramos = cal.tramos_de(ANOTACION["v"], 20.0)
    pasos = [_paso(1, 0.0, 4.9), _paso(2, 5.0, 9.9), _paso(3, 10.0, 14.9), _paso(4, 15.0, 19.9)]

    esperado = cal.esperado_por_sop(pasos, tramos)  # type: ignore[arg-type]

    # Índices desde 0: el paso del SOP 1 es el segundo del video, el 2 el tercero.
    assert esperado == {0: 1, 1: 2}


def test_dos_pasos_en_el_mismo_tramo_del_sop_gana_el_que_mas_se_encima() -> None:
    """Sobre-segmentación (el caso de ADR-013): un solo paso esperado, el de más encime."""
    tramos = cal.tramos_de(ANOTACION["v"], 20.0)
    pasos = [_paso(1, 5.0, 7.0), _paso(2, 7.0, 10.0)]

    esperado = cal.esperado_por_sop(pasos, tramos)  # type: ignore[arg-type]

    assert esperado == {0: 1}


def test_sin_pasos_emparejados_no_hay_expectativas() -> None:
    tramos = cal.tramos_de(ANOTACION["v"], 20.0)
    pasos = [_paso(1, 0.0, 4.9), _paso(2, 15.0, 19.9)]

    assert cal.esperado_por_sop(pasos, tramos) == {}  # type: ignore[arg-type]
