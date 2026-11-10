"""Partes puras de `scripts/medir_afinidad.py`: tipo de video según la anotación, criterio de
aceptación e informe.

La medición de verdad necesita Whisper, Ollama y los videos: se lanza a mano (ADR-020).
"""

import sys
from pathlib import Path

from sopvid.contrato import SOP, PasoSOP

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_afinidad as ma  # noqa: E402  (la ruta se ajusta arriba)

SOP_TRES = SOP(
    titulo="Inventado",
    pasos=[PasoSOP(numero=n, nombre=f"Paso {n}", responsable="Técnico") for n in range(1, 4)],
)
ANOTACION_MISMO = {"pasos": [{"sop": None}, {"sop": 1}, {"sop": 2}, {"sop": 3}]}
ANOTACION_DISTINTO = {"pasos": [{"sop": 1}, {"sop": 2, "esperado_persona": "Distinto"}, {"sop": 3}]}
ANOTACION_OTRO = {"pasos": [{"sop": None}, {"sop": None}]}


def _fila(paso: int, estado: str | None) -> dict:
    fila = {"estado": "Cumple", "paso_sop": paso}
    if estado is not None:
        fila["responsable"] = {"estado": estado}
    return fila


def _corrida(valor: int | None, filas: list[dict], *, detenida: bool = False, falta: int = 0,
             roles: list[dict] | None = None) -> dict:  # fmt: skip
    return {
        "afinidad": None if valor is None else {"valor": valor},
        "detenida": detenida,
        "validacion": {
            "filas": filas,
            "conteo": {"Falta": falta},
            "roles": roles if roles is not None else
            [{"estado": "presente", "con_pasos": True}],
        },
    }  # fmt: skip


def test_tipo_segun_la_anotacion() -> None:
    assert ma.tipo_de(ANOTACION_MISMO) == "mismo"
    assert ma.tipo_de(ANOTACION_DISTINTO) == "distinto"
    assert ma.tipo_de(ANOTACION_OTRO) == "otro_procedimiento"


def test_criterio_mismo_procedimiento() -> None:
    bien = _corrida(80, [_fila(1, "coincide"), _fila(2, "no_identificado")])
    assert ma.criterio("mismo", bien, ANOTACION_MISMO, SOP_TRES, 60) == (True, [])
    pasa, motivos = ma.criterio(
        "mismo",
        _corrida(50, [_fila(1, "distinto")], roles=[{"estado": "ausente", "con_pasos": True}]),
        ANOTACION_MISMO,
        SOP_TRES,
        60,
    )
    assert not pasa and len(motivos) == 3


def test_un_rol_sin_pasos_ausente_no_falla_el_criterio() -> None:
    roles = [{"estado": "presente", "con_pasos": True}, {"estado": "ausente", "con_pasos": False}]
    corrida = _corrida(80, [_fila(1, "coincide")], roles=roles)
    assert ma.criterio("mismo", corrida, ANOTACION_MISMO, SOP_TRES, 60)[0]


def test_criterio_distinto_exige_exactamente_los_pasos_anotados() -> None:
    filas = [_fila(1, "coincide"), _fila(2, "distinto"), _fila(3, "coincide")]
    assert ma.criterio("distinto", _corrida(70, filas), ANOTACION_DISTINTO, SOP_TRES, 60)[0]
    filas[2] = _fila(3, "distinto")
    pasa, motivos = ma.criterio("distinto", _corrida(70, filas), ANOTACION_DISTINTO, SOP_TRES, 60)
    assert not pasa and "[2, 3]" in motivos[0]


def test_criterio_otro_procedimiento() -> None:
    bien = _corrida(20, [], detenida=True, falta=3)
    assert ma.criterio("otro_procedimiento", bien, ANOTACION_OTRO, SOP_TRES, 60) == (True, [])
    mal = _corrida(70, [], detenida=False, falta=1)
    pasa, motivos = ma.criterio("otro_procedimiento", mal, ANOTACION_OTRO, SOP_TRES, 60)
    assert not pasa and len(motivos) == 3
