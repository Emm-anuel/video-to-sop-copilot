"""Partes puras de `scripts/medir_reproducibilidad.py` (RNF-07): qué se compara, el rango y el
informe. La medición de verdad necesita Ollama y un video: se lanza a mano."""

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_reproducibilidad as mr  # noqa: E402  (la ruta se ajusta arriba)

from sopvid.contrato import ResultadoValidacion  # noqa: E402


def _ejemplo() -> ResultadoValidacion:
    spec = importlib.util.spec_from_file_location(
        "ejemplo", RAIZ / "scripts" / "ejemplo_reporte.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.construir_validacion(caido=False)


def test_comparable_ignora_segundos_y_la_marca_de_reuso() -> None:
    a = _ejemplo()
    b = a.model_copy(
        update={
            "metadatos": a.metadatos.model_copy(
                update={"segundos": {"emparejamiento": 99.0}, "segmentacion_reusada": True}
            )
        }
    )
    assert mr.huella(mr.comparable(a)) == mr.huella(mr.comparable(b))
    c = a.model_copy(update={"cumplimiento": a.cumplimiento - 1})
    assert mr.huella(mr.comparable(a)) != mr.huella(mr.comparable(c))


def test_rango() -> None:
    assert mr.rango([91.67, 100.0, 91.67]) == "91.67–100.00 %"
    assert mr.rango([66.67, 66.67]) == "66.67 %"
    assert mr.rango([]) == "—"


def test_informe_y_veredicto() -> None:
    corrida = {
        "repeticion": 1,
        "cumplimiento": 100.0,
        "semaforo": "verde",
        "conteo": {},
        "rescatados": 0,
        "pasos_video": 14,
        "huella": "abc",
        "regeneradas": [{"huella": "abc", "reusada": True}, {"huella": "abc", "reusada": True}],
        "identicas": True,
    }
    otra = {**corrida, "repeticion": 2, "cumplimiento": 91.67, "pasos_video": 17}
    datos = {
        "fecha": "2026-11-09T12:00:00",
        "git": {"commit": "abc", "cambios_sin_commit": 0},
        "sop": "sop.md",
        "modelos": {},
        "videos": [{"video": "video_a", "corridas": [corrida, otra]}],
    }
    texto = mr.informe(datos)
    assert "| video_a | 2 | 91.67–100.00 % | {'verde': 2} | {14: 1, 17: 1} | 4/4 |" in texto
    assert mr.todas_identicas(datos)
    otra["identicas"] = False
    assert not mr.todas_identicas(datos)
