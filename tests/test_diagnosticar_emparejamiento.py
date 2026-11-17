"""Partes puras de `scripts/diagnosticar_emparejamiento.py --variantes-texto` (#11).

La medición de verdad lee las segmentaciones de la base y usa MiniLM: se lanza a mano. Aquí, con
el vectorizador por palabras y pasos inventados, se prueba que cada variante arma la matriz que
dice, que la cascada del script reproduce `emparejar` sin juez, la verdad por tramos y el conteo
de lo que empeora o mejora respecto de la variante actual.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

from sopvid.contrato import SOP, PasoSOP, PasoVideo
from sopvid.lenguaje import emparejamiento as emp
from sopvid.plataforma import config

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import diagnosticar_emparejamiento as de  # noqa: E402  (la ruta se ajusta arriba)

from dobles import embedder_palabras  # noqa: E402


@pytest.fixture(autouse=True)
def umbrales(monkeypatch):
    monkeypatch.setenv("UMBRAL_BAJO", "0.55")
    monkeypatch.setenv("UMBRAL_ALTO", "0.75")
    monkeypatch.setenv("UMBRAL_FUSION", "0.55")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _paso(numero: int, nombre: str, descripcion: str, cita: str, t: float = 0.0) -> PasoVideo:
    return PasoVideo(
        numero=numero,
        nombre=nombre,
        descripcion=descripcion,
        responsable="Operador",
        t_inicio=t,
        t_fin=t + 5,
        cita=cita,
        fuente="audio",
        confianza="alta",
    )


SOP_PRUEBA = SOP(
    titulo="Cambio de filtro",
    pasos=[
        PasoSOP(
            numero=1, nombre="Cerrar la válvula", descripcion="Girar la manija", responsable="O"
        ),
        PasoSOP(
            numero=2, nombre="Abrir la carcasa", descripcion="Aflojar el vaso", responsable="O"
        ),
    ],
)
PASOS = [
    _paso(1, "Cierre", "cerrar la válvula", "close the valve now", t=0),
    _paso(2, "Carcasa", "abrir la carcasa", "aflojo el vaso con la llave", t=5),
]


@pytest.fixture
def vec(tmp_path):
    e = embedder_palabras(tmp_path)
    return e, de.Vectores(e)


def test_texto_sin_cita_y_cita():
    paso = _paso(1, "Cierre", "cerrar la válvula", "  close   the valve ")
    assert de.texto_sin_cita(paso) == "Cierre. cerrar la válvula"
    assert de.texto_cita(paso) == "close the valve"
    assert emp.texto_para_embeber(paso) == "Cierre. cerrar la válvula. close the valve"


def test_cada_variante_arma_su_matriz(vec):
    e, v = vec
    v_sop = v([emp.texto_para_embeber(p) for p in SOP_PRUEBA.pasos])
    con = emp.similitud(v_sop, e.embed([emp.texto_para_embeber(p) for p in PASOS]))
    sin = emp.similitud(v_sop, e.embed([de.texto_sin_cita(p) for p in PASOS]))

    def m(variante: str, idioma: str = "es") -> np.ndarray:
        return de.matriz_variante(variante, v_sop, PASOS, idioma, v)

    np.testing.assert_allclose(m("a"), con, atol=1e-6)
    np.testing.assert_allclose(m("b"), sin, atol=1e-6)
    np.testing.assert_allclose(m("d", "es"), con, atol=1e-6)
    np.testing.assert_allclose(m("d", "en"), sin, atol=1e-6)
    np.testing.assert_allclose(m("e"), np.maximum(con, sin), atol=1e-6)
    np.testing.assert_allclose(m("f", "es"), con, atol=1e-6)
    np.testing.assert_allclose(m("f", "en"), np.maximum(con, sin), atol=1e-6)
    # c con peso 0 sería b; con peso > 0 la cita en inglés aleja el paso 1 del SOP (no comparte
    # palabras) menos que en a, porque pesa menos que nombre + descripción.
    assert m("b")[0, 0] >= m("c0.20")[0, 0] >= m("c0.50")[0, 0]
    with pytest.raises(ValueError):
        m("z")


def test_la_cascada_del_script_reproduce_emparejar_sin_juez(vec):
    e, v = vec
    v_sop = v([emp.texto_para_embeber(p) for p in SOP_PRUEBA.pasos])
    corrida = de.cascada_variante(
        SOP_PRUEBA, PASOS, lambda pasos: de.matriz_variante("a", v_sop, pasos, "es", v)
    )
    assert de.mismo_resultado(corrida.resultado, emp.emparejar(SOP_PRUEBA, PASOS, e))
    assert corrida.matriz.shape == (2, len(corrida.resultado.pasos_video))


def _tramos() -> list[de.Tramo]:
    return [
        de.Tramo(0, 5, "Cerrar", 1),
        de.Tramo(5, 10, "Abrir", 2),
        de.Tramo(10, 15, "Cierre", None),
    ]


def test_verdad_con_el_sop_de_referencia():
    verdad = de.Verdad.de(SOP_PRUEBA, _tramos(), None, False)
    assert verdad.ref_sop == [1, 2]
    assert verdad.correcto(0, PASOS[0]) and not verdad.correcto(1, PASOS[0])
    assert verdad.presente(1, PASOS)
    assert not verdad.presente(1, PASOS[:1])


def test_verdad_con_un_sop_generado_de_la_misma_grabacion():
    generado = SOP(
        titulo="Generado",
        pasos=[
            PasoSOP(numero=1, nombre="A", responsable="O", t_inicio=0, t_fin=2),
            PasoSOP(numero=2, nombre="B", responsable="O", t_inicio=2.5, t_fin=4.5),
            PasoSOP(numero=3, nombre="C", responsable="O"),  # sin tiempos (agregado a mano)
        ],
    )
    verdad = de.Verdad.de(generado, _tramos(), _tramos(), True)
    assert verdad.ref_sop == [1, 1, None]
    tarde = _paso(1, "x", "y", "z", t=3).model_copy(update={"t_fin": 4.9})
    # Los dos pasos del SOP caen en el tramo 1, pero solo el que se encima en el tiempo vale.
    assert not verdad.correcto(0, tarde) and verdad.correcto(1, tarde)
    assert not verdad.correcto(2, tarde)
    # De otra grabación: basta con el mismo tramo.
    otra = de.Verdad.de(generado, _tramos(), _tramos(), False)
    assert otra.correcto(0, tarde) and otra.correcto(1, tarde)


def _fila(etiqueta: str, zona: str, correcto: bool) -> dict:
    return {"etiqueta": etiqueta, "zona": zona, "par_correcto": correcto}


def test_comparar_con_a_cuenta_graves_y_mejoras_por_rango():
    base = {
        "filas": [
            _fila("bien", "aceptado", True),
            _fila("juez", "gris", True),
            _fila("mal", "sin pareja", False),
            _fila("bien", "sin pareja", False),
        ],
        "fusion": [[1], [2]],
        "citas_fusion": ["x", "y"],
        "pares_llm": 1,
    }
    otra = {
        "filas": [
            _fila("bien", "aceptado", True),
            _fila("juez✗", "gris", False),  # par correcto en gris → equivocado en gris: grave
            _fila("bien", "aceptado", True),  # Falta fabricado que se arregla: mejora
            _fila("juez✗", "gris", False),  # ausente que ahora va al juez con par equivocado
        ],
        "fusion": [[1], [2]],
        "citas_fusion": ["x", "z"],
        "pares_llm": 2,
    }
    comp = de.comparar_con_a(base, otra)
    assert comp["graves"] == 2
    assert comp["mejoras"] == 1
    assert comp["transiciones"] == {"juez→juez✗": 1, "mal→bien": 1, "bien→juez✗": 1}
    assert comp["equivocados_suben"] == 2
    assert comp["cambios_zona"] == 2
    assert comp["citas_representante_distintas"] == 1
    assert comp["delta_pares_llm"] == 1


def test_caidas_por_cita_solo_las_mayores_al_umbral():
    caso = {
        "nombre": "e",
        "variantes": {
            "a": {
                "filas": [
                    {"paso_sop": 1, "coseno_correcto": 0.30},
                    {"paso_sop": 2, "coseno_correcto": 0.80},
                ]
            },
            "b": {
                "filas": [
                    {"paso_sop": 1, "coseno_correcto": 0.75},
                    {"paso_sop": 2, "coseno_correcto": 0.90},
                ]
            },
        },
    }
    assert de.caidas_por_cita([caso]) == [{"caso": "e", "paso_sop": 1, "a": 0.30, "b": 0.75}]
