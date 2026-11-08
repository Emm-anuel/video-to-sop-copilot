"""Partes puras de `scripts/medir_contexto.py`: comparación CPU contra GPU e informe.

La medición de verdad necesita Ollama (y Whisper, en la ruta completa): se lanza a mano. Las
fichas de aquí son inventadas.
"""

import sys
from pathlib import Path

from sopvid.contrato import Contexto, Dato, Elemento, Persona

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_contexto as mc  # noqa: E402  (la ruta se ajusta arriba)


def _ficha(rol: str = "Técnico", lugar: str | None = "Línea de enjuague", equipo: str = "Cubeta"):
    return Contexto(
        actividad=Dato(valor="Cambio de cartucho", confianza="alta", fuente="audio", t=1.0),
        lugar=(
            Dato(valor=lugar, confianza="alta", fuente="audio", t=1.0)
            if lugar
            else Contexto().lugar
        ),
        personas=[Persona(rol=rol, participacion="participa", t=1.0, cita="soy el técnico")],
        equipos=[Elemento(nombre="Guantes"), Elemento(nombre=equipo)],
    ).model_dump(mode="json")


def _corrida(config: str, ficha: dict, **kwargs) -> mc.Corrida:
    c = mc.Corrida("video_a", config, 1, "analisis", generado=True, ficha=ficha, **kwargs)
    c.segundos_etapas = {"contexto": c.segundos_contexto}
    return c


def test_fichas_iguales_no_tienen_diferencias():
    comp = mc.comparar(_ficha(), _ficha())
    assert comp["mismas_personas"]
    assert all(d["mismo_valor"] for d in comp["datos"].values())
    assert comp["equipos_solo"] == [[], []]


def test_diferencias_en_personas_datos_y_equipos():
    comp = mc.comparar(_ficha(), _ficha(rol="Supervisor", lugar=None, equipo="Trapo"))
    assert not comp["mismas_personas"]
    assert comp["datos"]["lugar"] == {
        "con_valor": [True, False],
        "fuente": ["audio", "inferido"],
        "mismo_valor": False,
    }
    assert comp["equipos_comunes"] == 1
    assert comp["equipos_solo"] == [["cubeta"], ["trapo"]]


def test_comparaciones_solo_entre_fichas_generadas_de_la_misma_entrada():
    gpu, cpu = _corrida("gpu", _ficha()), _corrida("cpu", _ficha(rol="Supervisor"))
    [comp] = mc.comparaciones([gpu, cpu])
    assert (comp["video"], comp["entrada"], comp["mismas_personas"]) == (
        "video_a",
        "analisis",
        False,
    )
    cpu.generado = False
    assert mc.comparaciones([gpu, cpu]) == []


def test_informe_con_aviso_si_el_primer_token_pasa_de_120_s():
    corridas = [
        _corrida("gpu", _ficha(), primer_token_s=8.0, segundos_contexto=12.0),
        _corrida("cpu", _ficha(), primer_token_s=130.0, segundos_contexto=150.0),
    ]
    datos = {
        "fecha": "2026-11-07 23:59",
        "git": {"commit": "abc", "rama": "feat/contexto", "cambios_sin_commit": 0},
        "llm": "gemma4:e4b-it-q4_K_M",
        "gpu": None,
        "comparaciones": mc.comparaciones(corridas),
    }
    texto = mc.informe(datos, corridas)
    assert "| video_a | analisis | cpu | 1 | — | desconocido |" in texto
    assert "mismas personas" in texto
    assert "pasó de 120 s en video_a/cpu" in texto
