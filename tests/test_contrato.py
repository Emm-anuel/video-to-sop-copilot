"""Contrato del análisis de video y de los pasos del video (`sopvid.contrato`)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sopvid.contrato import Analisis, Fotograma, Idioma, Palabra, PasoVideo, esquema_analisis

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "tests" / "fixtures" / "analisis_ejemplo.json"
ESQUEMA = RAIZ / "docs" / "contrato" / "analisis.schema.json"
INICIOS_PASO = [4, 6, 9, 12, 17, 21]  # anotados a mano en tests/fixtures/README.md

PASO = {
    "numero": 1,
    "nombre": "Ponerse guantes y lentes",
    "descripcion": "La técnica se pone guantes de nitrilo y lentes de seguridad.",
    "responsable": "Técnica de mantenimiento",
    "t_inicio": 20.45,
    "t_fin": 31.64,
    "cita": "Primero me pongo los guantes de nitrilo y los lentes de seguridad.",
    "fuente": "audio",
    "confianza": "alta",
}


@pytest.fixture
def ejemplo() -> dict:
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def _falla(modelo, datos, texto: str) -> None:
    with pytest.raises(ValidationError, match=texto):
        modelo.model_validate(datos)


# ── El ejemplo ───────────────────────────────────────────────────────────────────────────────


def test_el_ejemplo_valida(ejemplo):
    a = Analisis.model_validate(ejemplo)

    assert a.version_contrato == 1
    assert a.idioma.codigo == "es"
    assert len(a.transcripcion) == 25
    assert all(s.palabras for s in a.transcripcion)
    assert len(a.fotogramas) == 4
    assert a.model_dump(mode="json") == ejemplo  # ida y vuelta sin perder ni agregar campos


def test_el_ejemplo_es_coherente(ejemplo):
    a = Analisis.model_validate(ejemplo)
    ids = [s.id for s in a.transcripcion]

    assert ids == list(range(1, len(ids) + 1))
    assert set(INICIOS_PASO) <= set(ids)
    assert a.transcripcion[-1].t_fin <= a.duracion_s
    assert all(f.t <= a.duracion_s for f in a.fotogramas)
    for s in a.transcripcion:
        assert " ".join(p.w for p in s.palabras) == s.texto
        assert s.palabras[0].t == s.t_inicio and s.palabras[-1].t_fin == s.t_fin


def test_listas_vacias_por_defecto_y_nunca_null(ejemplo):
    minimo = {k: v for k, v in ejemplo.items() if k != "fotogramas"}
    minimo["transcripcion"] = [{"id": 1, "t_inicio": 0.0, "t_fin": 1.0, "texto": "Hola."}]
    a = Analisis.model_validate(minimo)
    assert a.fotogramas == [] and a.transcripcion[0].palabras == []
    assert Fotograma(t=0, archivo="f.jpg", descripcion="x").model_dump()["riesgos"] == []

    _falla(Analisis, {**ejemplo, "fotogramas": None}, "fotogramas")
    con_null = copy.deepcopy(ejemplo)
    con_null["transcripcion"][0]["palabras"] = None
    _falla(Analisis, con_null, "palabras")


# ── Tiempos ──────────────────────────────────────────────────────────────────────────────────


def test_tiempos_invertidos_fallan(ejemplo):
    invertido = copy.deepcopy(ejemplo)
    s = invertido["transcripcion"][2]
    s["t_inicio"], s["t_fin"] = s["t_fin"], s["t_inicio"]
    _falla(Analisis, invertido, "menor que el inicio")

    _falla(Palabra, {"w": "hola", "t": 2.0, "t_fin": 1.0}, "menor que el inicio")
    _falla(PasoVideo, {**PASO, "t_inicio": 40.0, "t_fin": 30.0}, "menor que el inicio")


@pytest.mark.parametrize("valor", [-0.1, float("nan"), float("inf")])
def test_tiempos_negativos_o_no_finitos_fallan(valor):
    with pytest.raises(ValidationError):
        Palabra(w="hola", t=valor, t_fin=1.0)
    with pytest.raises(ValidationError):
        Fotograma(t=valor, archivo="f.jpg", descripcion="x")


def test_palabras_fuera_de_orden_fallan(ejemplo):
    datos = copy.deepcopy(ejemplo)
    palabras = datos["transcripcion"][0]["palabras"]
    palabras[0], palabras[1] = palabras[1], palabras[0]
    _falla(Analisis, datos, "palabras fuera de orden")


def test_segmentos_que_se_solapan_fallan(ejemplo):
    datos = copy.deepcopy(ejemplo)
    datos["transcripcion"][1]["t_inicio"] = datos["transcripcion"][0]["t_fin"] - 0.5
    _falla(Analisis, datos, "empieza .* antes de que termine")


def test_un_paso_de_un_instante_es_valido():
    assert PasoVideo.model_validate({**PASO, "t_fin": PASO["t_inicio"]}).t_fin == 20.45


# ── Ids de segmento ──────────────────────────────────────────────────────────────────────────


def test_ids_duplicados_fallan(ejemplo):
    datos = copy.deepcopy(ejemplo)
    datos["transcripcion"][4]["id"] = datos["transcripcion"][3]["id"]
    _falla(Analisis, datos, "duplicado: 4")


def test_ids_no_crecientes_fallan(ejemplo):
    datos = copy.deepcopy(ejemplo)
    datos["transcripcion"][3]["id"], datos["transcripcion"][4]["id"] = 5, 4
    _falla(Analisis, datos, "no crecientes: 5 → 4")


def test_los_errores_no_citan_la_transcripcion(ejemplo):
    datos = copy.deepcopy(ejemplo)
    datos["transcripcion"][4]["id"] = 4
    with pytest.raises(ValidationError) as exc:
        Analisis.model_validate(datos)
    mensajes = " ".join(e["msg"] for e in exc.value.errors())
    assert "guantes" not in mensajes and "lentes" not in mensajes


# ── Valores cerrados ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("confianza", [-0.01, 1.01, "alta"])
def test_confianza_de_idioma_invalida_falla(confianza):
    _falla(Idioma, {"codigo": "es", "confianza": confianza}, "confianza")


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("confianza", "muy alta"), ("confianza", 0.9), ("fuente", "llm"), ("numero", 0)],
)
def test_paso_con_valor_fuera_del_contrato_falla(campo, valor):
    _falla(PasoVideo, {**PASO, campo: valor}, campo)


def test_version_de_contrato_desconocida_falla(ejemplo):
    _falla(Analisis, {**ejemplo, "version_contrato": 2}, "version_contrato")


# ── Campos extra ─────────────────────────────────────────────────────────────────────────────


def test_campo_extra_en_la_raiz_falla(ejemplo):
    _falla(Analisis, {**ejemplo, "_comentario": "inventado"}, "_comentario")


@pytest.mark.parametrize(
    "ruta",
    [("idioma",), ("transcripcion", 0), ("transcripcion", 0, "palabras", 0), ("fotogramas", 0)],
)
def test_campo_extra_anidado_falla(ejemplo, ruta):
    datos = copy.deepcopy(ejemplo)
    nodo = datos
    for paso in ruta:
        nodo = nodo[paso]
    nodo["extra"] = 1
    _falla(Analisis, datos, "extra")


def test_campo_extra_en_paso_falla():
    _falla(PasoVideo, {**PASO, "t_inicio_llm": 999}, "t_inicio_llm")


# ── JSON Schema exportado ────────────────────────────────────────────────────────────────────


def test_el_esquema_exportado_coincide_con_el_modelo():
    exportado = json.loads(ESQUEMA.read_text(encoding="utf-8"))
    assert exportado == esquema_analisis(), "corre: python scripts/exportar_contrato.py"


def test_el_esquema_prohibe_extras_y_exige_la_transcripcion():
    esquema = esquema_analisis()
    assert esquema["additionalProperties"] is False
    assert {"video_id", "duracion_s", "idioma", "transcripcion"} <= set(esquema["required"])
    assert all(d["additionalProperties"] is False for d in esquema["$defs"].values())
