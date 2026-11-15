"""Texto vectorizado del paso del video (ADR-026, #11): `EMPAREJAR_TEXTO` y `SOP_IDIOMA`.

Con `max_si_otro_idioma`, un video cuya transcripción no está en el idioma del SOP toma, en cada
par, el mayor coseno entre el paso con su cita y sin ella; en el mismo idioma (o sin idioma) el
cálculo es exactamente el de `cita`. Todo con vectorizadores falsos y pasos inventados, salvo la
prueba lenta, que usa MiniLM real con el caso del paso 6 del video E (grabado por el equipo,
`tests/fixtures/emparejamiento_e.json`).
"""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dobles import JuezFalso, embedder_palabras  # noqa: I001  (de tests/, como en las demás)
from sopvid.contrato import SOP, PasoSOP, PasoVideo, Segmento
from sopvid.lenguaje import emparejamiento as emp
from sopvid.plataforma import config

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def modo(monkeypatch):
    """Fija EMPAREJAR_TEXTO y SOP_IDIOMA (y los umbrales por defecto) sin leer el `.env`."""

    def fijar(valor: str, sop_idioma: str = "es") -> None:
        monkeypatch.setenv("EMPAREJAR_TEXTO", valor)
        monkeypatch.setenv("SOP_IDIOMA", sop_idioma)
        monkeypatch.setenv("UMBRAL_BAJO", "0.55")
        monkeypatch.setenv("UMBRAL_ALTO", "0.75")
        monkeypatch.setenv("UMBRAL_FUSION", "0.55")
        config.get_settings.cache_clear()

    yield fijar
    config.get_settings.cache_clear()


# ── Configuración ────────────────────────────────────────────────────────────────────────────


def test_valores_por_defecto(monkeypatch):
    monkeypatch.delenv("EMPAREJAR_TEXTO", raising=False)
    monkeypatch.delenv("SOP_IDIOMA", raising=False)
    settings = config.Settings(_env_file=None)
    assert settings.emparejar_texto == "max_si_otro_idioma"
    assert settings.sop_idioma == "es"


def test_se_leen_del_entorno_y_rechazan_un_valor_sin_nombre(monkeypatch):
    monkeypatch.setenv("EMPAREJAR_TEXTO", "cita")
    monkeypatch.setenv("SOP_IDIOMA", "en")
    settings = config.Settings(_env_file=None)
    assert (settings.emparejar_texto, settings.sop_idioma) == ("cita", "en")
    monkeypatch.setenv("EMPAREJAR_TEXTO", "sin_cita")
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


@pytest.mark.parametrize(
    ("valor", "sop_idioma", "idioma", "esperado"),
    [
        ("max_si_otro_idioma", "es", "en", True),
        ("max_si_otro_idioma", "es", "es", False),
        ("max_si_otro_idioma", "es", "ES", False),
        ("max_si_otro_idioma", "es", "es-MX", False),
        ("max_si_otro_idioma", "es", None, False),
        ("max_si_otro_idioma", "es", "", False),
        ("max_si_otro_idioma", "en", "es", True),
        ("cita", "es", "en", False),
    ],
)
def test_cita_en_otro_idioma(modo, valor, sop_idioma, idioma, esperado):
    modo(valor, sop_idioma)
    assert emp.cita_en_otro_idioma(idioma) is esperado


def test_texto_sin_cita():
    paso = _paso(1, "Cierre", "cierro la valvula", "I close the valve")
    assert emp.texto_sin_cita(paso) == "Cierre. cierro la valvula"
    assert emp.texto_para_embeber(paso) == "Cierre. cierro la valvula. I close the valve"


# ── Cada valor arma el coseno esperado ───────────────────────────────────────────────────────


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


SOP_DOS = SOP(
    titulo="Cambio de filtro",
    pasos=[
        PasoSOP(numero=1, nombre="Cerrar valvula", descripcion="cerrar valvula", responsable="O"),
        PasoSOP(numero=2, nombre="Abrir carcasa", descripcion="aflojar vaso", responsable="O"),
    ],
)
# Citas en inglés: con la bolsa de palabras no comparten nada con el SOP y diluyen el vector.
VIDEO_EN = [
    _paso(1, "Cerrar valvula", "cerrar valvula", "now I close the shut-off valve slowly", t=0),
    _paso(2, "Abrir carcasa", "aflojar vaso", "I loosen the bowl with the housing wrench", t=6),
]


def _coseno(embedder: emp.Embedder, a: str, b: str) -> float:
    v = embedder.embed([a, b])
    return float(emp.similitud(v[:1], v[1:])[0, 0])


def test_cita_usa_el_texto_con_cita_aunque_el_video_este_en_otro_idioma(modo, tmp_path):
    modo("cita")
    e = embedder_palabras(tmp_path)
    r = emp.emparejar(SOP_DOS, VIDEO_EN, e, idioma="en")
    uno = next(p for p in r.clasificacion.pasos if p.indice_sop == 0)
    esperado = _coseno(
        e, emp.texto_para_embeber(SOP_DOS.pasos[0]), emp.texto_para_embeber(VIDEO_EN[0])
    )
    assert uno.similitud == pytest.approx(esperado, abs=1e-6)


def test_max_si_otro_idioma_toma_el_mayor_coseno_con_y_sin_cita(modo, tmp_path):
    modo("max_si_otro_idioma")
    e = embedder_palabras(tmp_path)
    r = emp.emparejar(SOP_DOS, VIDEO_EN, e, idioma="en")
    for i in range(2):
        paso = next(p for p in r.clasificacion.pasos if p.indice_sop == i)
        texto_sop = emp.texto_para_embeber(SOP_DOS.pasos[i])
        con = _coseno(e, texto_sop, emp.texto_para_embeber(VIDEO_EN[i]))
        sin = _coseno(e, texto_sop, emp.texto_sin_cita(VIDEO_EN[i]))
        assert sin > con  # la cita en inglés hunde el coseno con el texto con cita
        assert paso.similitud == pytest.approx(max(con, sin), abs=1e-6)
        assert paso.estado == "Cumple"
    # Con la cita, el mismo video no llega a UMBRAL_ALTO.
    modo("cita")
    con_cita = emp.emparejar(SOP_DOS, VIDEO_EN, e, idioma="en")
    assert all(p.estado != "Cumple" for p in con_cita.clasificacion.pasos)


def test_fusionar_tambien_toma_el_mayor_en_otro_idioma(modo, tmp_path):
    modo("max_si_otro_idioma")
    e = embedder_palabras(tmp_path)
    partes = [
        _paso(1, "Cerrar valvula", "", "first I grab the red handle", t=0),
        _paso(2, "Cerrar valvula", "", "and turn it fully right now", t=6),
    ]
    # Con la cita en inglés cada parte queda bajo UMBRAL_FUSION; sin ella, las dos lo pasan.
    assert len(emp.fusionar(SOP_DOS.pasos, partes, e, idioma="es")[0]) == 2
    (unido,), (registro,) = emp.fusionar(SOP_DOS.pasos, partes, e, idioma="en")
    assert registro.originales == [1, 2]
    assert unido.cita in (partes[0].cita, partes[1].cita)  # regla 4: una cita original


# ── En el mismo idioma, exactamente lo mismo que con la cita ─────────────────────────────────


VIDEO_ES = [
    _paso(1, "Cerrar valvula", "cerrar valvula", "cierro la valvula de paso", t=0),
    _paso(2, "Limpiar mesa", "limpiar mesa", "limpio la mesa", t=6),
    _paso(3, "Abrir carcasa", "aflojar", "aflojo el vaso con la llave", t=12),
]
SEGMENTOS_ES = [
    Segmento(id=i, t_inicio=p.t_inicio, t_fin=p.t_fin, texto=p.cita) for i, p in enumerate(VIDEO_ES)
]


def _sin_tiempos(r: emp.ResultadoEmparejamiento) -> dict:
    """El resultado sin `segundos_juez`, que es un tiempo medido y cambia entre corridas."""
    datos = r.model_dump()
    datos["clasificacion"]["resumen"]["segundos_juez"] = None
    return datos


@pytest.mark.parametrize("idioma", ["es", "es-MX", None])
def test_video_en_espanol_da_el_mismo_resultado_con_los_dos_valores(modo, tmp_path, idioma):
    e = embedder_palabras(tmp_path)
    modo("cita")
    con_cita = emp.emparejar(
        SOP_DOS, VIDEO_ES, e, juez=JuezFalso(), transcripcion=SEGMENTOS_ES, idioma=idioma
    )
    modo("max_si_otro_idioma")
    con_max = emp.emparejar(
        SOP_DOS, VIDEO_ES, e, juez=JuezFalso(), transcripcion=SEGMENTOS_ES, idioma=idioma
    )
    assert _sin_tiempos(con_max) == _sin_tiempos(con_cita)


def test_en_el_mismo_idioma_no_se_vectoriza_el_texto_sin_cita(modo, tmp_path):
    modo("max_si_otro_idioma")
    pedidos: list[str] = []

    class Registro:
        def encode(self, sentences: list[str], **kwargs: object) -> np.ndarray:
            pedidos.extend(sentences)
            return embedder_palabras(tmp_path)._cargador("", tmp_path).encode(sentences)

    e = emp.Embedder("registro", tmp_path, cargador=lambda m, c: Registro())
    emp.emparejar(SOP_DOS, VIDEO_ES, e, idioma="es")
    textos_sop = {emp.texto_para_embeber(p) for p in SOP_DOS.pasos}
    sin_cita = {emp.texto_sin_cita(p) for p in VIDEO_ES} - textos_sop
    assert sin_cita
    assert not sin_cita & set(pedidos)
    pedidos.clear()
    emp.emparejar(SOP_DOS, VIDEO_ES, e, idioma="en")
    assert sin_cita <= set(pedidos)


# ── MiniLM real: el paso 6 del video E (#11) ─────────────────────────────────────────────────


def _par_e(identificador: str) -> tuple[SOP, PasoVideo]:
    datos = json.loads((RAIZ / "tests" / "fixtures" / "emparejamiento_e.json").read_text("utf-8"))
    par = next(p for p in datos["pares"] if p["id"] == identificador)
    sop = SOP(titulo="E", pasos=[PasoSOP(numero=1, responsable="Técnico", **par["sop"])])
    paso = PasoVideo(
        numero=1,
        responsable="Técnico",
        t_inicio=133.76,
        t_fin=145.88,
        cita=par["citas"]["whisper"],
        fuente="audio",
        confianza="alta",
        **par["video"],
    )
    return sop, paso


@pytest.mark.lento
def test_minilm_real_el_paso_6_de_e_deja_de_fabricar_falta_y_sobra(modo):
    """#11: con la cita en inglés, 0.307 (bajo UMBRAL_BAJO: Falta + Sobra); con
    max_si_otro_idioma, 0.755 (aceptado sin juez). El margen sobre UMBRAL_ALTO es de 0.005
    (ADR-026: no se mueve el umbral por eso)."""
    sop, paso = _par_e("e6")
    e = emp.Embedder()

    modo("cita")
    antes = emp.emparejar(sop, [paso], e, idioma="en").clasificacion
    assert [p.estado for p in antes.pasos] == ["Falta", "Sobra"]

    modo("max_si_otro_idioma")
    despues = emp.emparejar(sop, [paso], e, idioma="en").clasificacion
    assert [p.estado for p in despues.pasos] == ["Cumple"]
    assert despues.pasos[0].similitud == pytest.approx(0.755, abs=0.005)
    assert despues.pasos[0].cita == paso.cita  # la evidencia sigue siendo la de Whisper

    # Si el video estuviera en español, nada cambia respecto de la cita.
    mismo = emp.emparejar(sop, [paso], e, idioma="es").clasificacion
    assert [p.estado for p in mismo.pasos] == ["Falta", "Sobra"]
