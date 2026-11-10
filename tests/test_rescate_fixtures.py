"""Regresión del rescate de un Falta (ADR-022) con segmentaciones reales, sin LLM ni MiniLM.

`tests/fixtures/rescate.json` (de `scripts/grabar_rescate.py`) trae, de los videos del equipo A y
B: las segmentaciones de Gemma que dejaban el paso 6 de A en Falta (83.33 %, amarillo) y un caso
adversario (B, que omite el paso 6, con fragmentos de A que se le parecen: "purgo el aire" sin
abrir la llave ni revisar fugas). Los vectores de MiniLM y los juicios de Gemma están grabados:
si el código pide un texto o una entrada del juez que no está, la prueba falla y pide regrabar.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sopvid.contrato import Juicio, PasoSOP, PasoVideo, Segmento
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.reporte import porcentaje
from sopvid.lenguaje.sop_markdown import convertir_sop

RAIZ = Path(__file__).resolve().parents[1]
DATOS = json.loads((RAIZ / "tests" / "fixtures" / "rescate.json").read_text(encoding="utf-8"))
SOP = convertir_sop((RAIZ / "tests" / "fixtures" / "sop_filtro_agua.md").read_text("utf-8")).sop
REGRABAR = "el código cambió lo que pide: corre scripts/grabar_rescate.py (ADR-022)"


def _cargar_grabar():
    import importlib.util

    ruta = RAIZ / "scripts" / "grabar_rescate.py"
    spec = importlib.util.spec_from_file_location("grabar_rescate", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


GRABAR = _cargar_grabar()


class VectorizadorGrabado:
    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        try:
            return np.stack(
                [GRABAR.texto_a_vector(DATOS["vectores"][GRABAR.huella(t)]) for t in sentences]
            )
        except KeyError:
            pytest.fail(f"texto sin vector grabado; {REGRABAR}")


class JuezGrabado:
    def __init__(self) -> None:
        self.llamadas: list[int] = []

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio:
        clave = GRABAR.clave_juez(paso_sop, paso_video, narracion)
        if clave not in DATOS["juicios"]:
            pytest.fail(f"entrada del juez sin juicio grabado; {REGRABAR}")
        self.llamadas.append(paso_sop.numero)
        return Juicio.model_validate({**DATOS["juicios"][clave], "similitud": similitud})


@pytest.fixture
def embedder(tmp_path: Path) -> emp.Embedder:
    vectorizador = VectorizadorGrabado()
    return emp.Embedder("grabado", tmp_path, cargador=lambda m, c: vectorizador)


def _emparejar(caso: dict[str, Any], embedder: emp.Embedder, juez: JuezGrabado):
    pasos = [PasoVideo.model_validate(p) for p in caso["pasos_video"]]
    transcripcion = [
        Segmento.model_validate(s) for s in caso.get("transcripcion", DATOS["transcripcion_a"])
    ]
    return emp.emparejar(SOP, pasos, embedder, juez=juez, transcripcion=transcripcion)


CASOS_A = sorted(c for c in DATOS["casos"] if c.startswith("a_"))


def test_hay_cuatro_casos_de_a_que_daban_amarillo() -> None:
    assert len(CASOS_A) == 4
    assert all(DATOS["casos"][c]["antes"] == 83.33 for c in CASOS_A)


@pytest.mark.parametrize("caso", CASOS_A)
def test_a_que_daba_amarillo_queda_verde_con_el_paso_6_rescatado(
    caso: str, embedder: emp.Embedder
) -> None:
    juez = JuezGrabado()
    r = _emparejar(DATOS["casos"][caso], embedder, juez)
    assert porcentaje(r) >= 90  # verde
    estados = {
        p.indice_sop + 1: p.estado for p in r.clasificacion.pasos if p.indice_sop is not None
    }
    assert "Falta" not in estados.values()
    seis = next(p for p in r.clasificacion.pasos if p.indice_sop == 5)
    assert seis.estado in ("Cumple", "Parcial")
    fusion = r.fusiones[seis.indice_video]
    # Se armó con varios fragmentos y el juez lo confirmó (ADR-022, condición a).
    assert fusion.rescate is True and len(fusion.originales) >= 2
    assert seis.juicio is not None and seis.juicio.origen == "llm"
    assert r.clasificacion.resumen.rescatados == 1
    # El tramo rescatado empieza en "abro la llave de paso" (110.0 s, el inicio anotado a mano).
    assert r.pasos_video[seis.indice_video].t_inicio == pytest.approx(110.0)


def test_b_adversario_el_paso_6_omitido_sigue_en_falta(embedder: emp.Embedder) -> None:
    juez = JuezGrabado()
    r = _emparejar(DATOS["casos"]["b_adversario"], embedder, juez)
    faltas = sorted(p.indice_sop + 1 for p in r.clasificacion.pasos if p.estado == "Falta")
    assert faltas == [2, 6]
    assert r.clasificacion.resumen.rescatados == 0
    assert not any(f.rescate for f in r.fusiones)
    assert porcentaje(r) == pytest.approx(200 / 3)
