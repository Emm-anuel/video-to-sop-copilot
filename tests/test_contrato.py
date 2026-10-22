"""Contratos del análisis de video, de los pasos del video y del SOP (`sopvid.contrato`)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sopvid.contrato import (
    SOP,
    Analisis,
    Dato,
    Fotograma,
    Fusion,
    Idioma,
    Palabra,
    Par,
    PasoSOP,
    PasoVideo,
    esquema_analisis,
    esquema_sop,
)

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "tests" / "fixtures" / "analisis_ejemplo.json"
DIR_ESQUEMAS = RAIZ / "docs" / "contrato"
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

# SOP inventado "Cambio del cartucho del filtro de agua" (tests/fixtures/README.md), solo título y
# pasos: lo mínimo que exige el contrato.
SOP_MINIMO = {
    "titulo": "Cambio del cartucho del filtro de agua",
    "pasos": [
        {"numero": 1, "nombre": "Ponerse guantes y lentes", "responsable": "Técnica"},
        {"numero": 2, "nombre": "Cerrar la llave de paso", "responsable": "Técnica"},
        {"numero": 3, "nombre": "Liberar la presión", "responsable": "Técnica"},
    ],
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


# ── SOP ──────────────────────────────────────────────────────────────────────────────────────


def _sop(**cambios) -> dict:
    return {**copy.deepcopy(SOP_MINIMO), **cambios}


def test_sop_minimo_valida_con_valores_por_defecto():
    s = SOP.model_validate(SOP_MINIMO)

    assert s.version_contrato == 1
    assert [p.numero for p in s.pasos] == [1, 2, 3]
    assert s.resumen.objetivo == Dato(valor=None, confianza="alta", fuente="documento", t=None)
    assert s.resumen.duracion_total_min is None
    paso = s.pasos[0]
    assert paso.descripcion == "" and paso.tiempo_esperado_min is None
    assert paso.t_inicio is None and paso.t_fin is None and paso.confianza == "alta"
    assert SOP.model_validate(s.model_dump(mode="json")) == s  # ida y vuelta


def test_numeracion_de_pasos_con_hueco_falla():
    datos = _sop()
    datos["pasos"][1]["numero"] = 3
    datos["pasos"][2]["numero"] = 4
    _falla(SOP, datos, "se esperaba el paso 2 y llegó el 3")


@pytest.mark.parametrize("numeros", [[2, 3, 4], [1, 1, 2], [1, 3, 2]])
def test_numeracion_que_no_es_1_2_3_falla(numeros):
    datos = _sop()
    for paso, n in zip(datos["pasos"], numeros, strict=True):
        paso["numero"] = n
    _falla(SOP, datos, "numeración de pasos")


def test_sop_sin_pasos_falla():
    _falla(SOP, _sop(pasos=[]), "pasos")
    _falla(SOP, {"titulo": SOP_MINIMO["titulo"]}, "pasos")


def test_sop_sin_titulo_falla():
    _falla(SOP, _sop(titulo=""), "titulo")


def test_el_error_de_numeracion_no_cita_el_sop():
    datos = _sop()
    datos["pasos"][1]["numero"] = 5
    with pytest.raises(ValidationError) as exc:
        SOP.model_validate(datos)
    mensajes = " ".join(e["msg"] for e in exc.value.errors())
    assert "numeración" in mensajes
    assert all(p["nombre"] not in mensajes for p in datos["pasos"])
    assert SOP_MINIMO["titulo"] not in mensajes and "Técnica" not in mensajes


def test_tiempos_del_paso_sop():
    base = SOP_MINIMO["pasos"][0]
    assert PasoSOP.model_validate({**base, "t_inicio": 20.45}).t_fin is None  # solo uno: válido
    assert PasoSOP.model_validate({**base, "t_inicio": 20.45, "t_fin": 31.64}).t_fin == 31.64
    _falla(PasoSOP, {**base, "t_inicio": 31.64, "t_fin": 20.45}, "menor que el inicio")
    _falla(PasoSOP, {**base, "t_inicio": -1.0}, "t_inicio")


def test_fuente_documento_vale_en_el_sop_pero_no_en_el_video():
    assert Dato(valor="Cambiar el cartucho", fuente="documento").fuente == "documento"
    _falla(PasoVideo, {**PASO, "fuente": "documento"}, "fuente")


def test_listas_vacias_del_sop_salen_vacias_y_nunca_null():
    dump = SOP.model_validate(SOP_MINIMO).model_dump(mode="json")

    assert dump["puntos_clave"] == [] and dump["palabras_clave"] == []
    for campo in ("equipo_operacion", "roles", "riesgos", "en_caso_de_falla"):
        assert dump["resumen"][campo] == []
    for campo in ("equipo", "puntos_validacion", "campos_inferidos"):
        assert dump["pasos"][0][campo] == []

    _falla(SOP, _sop(puntos_clave=None), "puntos_clave")
    datos = _sop()
    datos["pasos"][0]["equipo"] = None
    _falla(SOP, datos, "equipo")


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("confianza", "muy alta"), ("fuente", "llm"), ("t", -1.0)],
)
def test_dato_con_valor_fuera_del_contrato_falla(campo, valor):
    _falla(Dato, {campo: valor}, campo)


def test_campo_extra_en_la_raiz_del_sop_falla():
    _falla(SOP, _sop(_comentario="inventado"), "_comentario")


@pytest.mark.parametrize("ruta", [("resumen",), ("resumen", "objetivo"), ("pasos", 0)])
def test_campo_extra_anidado_en_el_sop_falla(ruta):
    datos = _sop(resumen={"objetivo": {"valor": "Cambiar el cartucho"}})
    nodo = datos
    for paso in ruta:
        nodo = nodo[paso]
    nodo["extra"] = 1
    _falla(SOP, datos, "extra")


# ── Registro de la fusión (ADR-013) ──────────────────────────────────────────────────────────

FUSION = {
    "numero": 2,
    "originales": [2, 3],
    "paso_sop": 2,
    "citas": ["Desenrosco el vaso del filtro", "Saco el cartucho usado"],
    "similitudes": [0.64, 0.77],
}


def test_fusion_valida():
    assert Fusion.model_validate(FUSION).originales == [2, 3]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("originales", []), ("originales", [3, 2]), ("originales", [2, 2]), ("citas", ["una"])],
)
def test_fusion_con_listas_invalidas_falla(campo, valor):
    with pytest.raises(ValidationError):
        Fusion.model_validate({**FUSION, campo: valor})


def test_fusion_sin_responsables_distintos_los_deja_vacios():
    assert Fusion.model_validate(FUSION).responsables_distintos == []


@pytest.mark.parametrize("distintos", [["Técnica"], ["Técnica", "Técnica"]])
def test_fusion_con_responsables_distintos_invalidos_falla(distintos):
    _falla(Fusion, {**FUSION, "responsables_distintos": distintos}, "responsables_distintos")


def test_fusion_con_similitud_fuera_de_rango_falla():
    _falla(Fusion, {**FUSION, "similitudes": [0.64, 1.5]}, "similitudes")


def test_el_error_de_la_fusion_no_cita_el_texto():
    with pytest.raises(ValidationError) as exc:
        Fusion.model_validate({**FUSION, "similitudes": [0.64]})
    mensajes = " ".join(e["msg"] for e in exc.value.errors())
    assert "1 similitudes" in mensajes
    assert all(c not in mensajes for c in FUSION["citas"])


# ── Par del algoritmo húngaro (ADR-012) ──────────────────────────────────────────────────────


def test_par_valida():
    par = Par(indice_sop=0, indice_video=3, similitud=0.82)
    assert (par.indice_sop, par.indice_video, par.similitud) == (0, 3, 0.82)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("indice_sop", -1), ("indice_video", -1), ("similitud", 1.01), ("similitud", float("nan"))],
)
def test_par_fuera_del_contrato_falla(campo, valor):
    datos = {"indice_sop": 0, "indice_video": 0, "similitud": 0.5, campo: valor}
    _falla(Par, datos, campo)


def test_campo_extra_en_par_falla():
    _falla(Par, {"indice_sop": 0, "indice_video": 0, "similitud": 0.5, "extra": 1}, "extra")


# ── JSON Schema exportado ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("archivo", "esquema"),
    [("analisis.schema.json", esquema_analisis), ("sop.schema.json", esquema_sop)],
)
def test_el_esquema_exportado_coincide_con_el_modelo(archivo, esquema):
    exportado = json.loads((DIR_ESQUEMAS / archivo).read_text(encoding="utf-8"))
    assert exportado == esquema(), "corre: python scripts/exportar_contrato.py"


def test_el_esquema_prohibe_extras_y_exige_la_transcripcion():
    esquema = esquema_analisis()
    assert esquema["additionalProperties"] is False
    assert {"video_id", "duracion_s", "idioma", "transcripcion"} <= set(esquema["required"])
    assert all(d["additionalProperties"] is False for d in esquema["$defs"].values())


def test_el_esquema_sop_prohibe_extras_y_exige_titulo_y_pasos():
    esquema = esquema_sop()
    assert esquema["additionalProperties"] is False
    assert set(esquema["required"]) == {"titulo", "pasos"}
    assert esquema["properties"]["pasos"]["minItems"] == 1
    assert all(d["additionalProperties"] is False for d in esquema["$defs"].values())
