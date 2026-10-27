"""Contratos del análisis de video, de los pasos del video y del SOP (`sopvid.contrato`)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sopvid.contrato import (
    ESTADOS,
    RESULTADOS_JUEZ,
    SOP,
    Analisis,
    Clasificacion,
    Dato,
    Fotograma,
    Fusion,
    Idioma,
    Juicio,
    Palabra,
    Par,
    PasoSOP,
    PasoVideo,
    ResultadoEmparejamiento,
    ResultadoPaso,
    ResumenClasificacion,
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


# ── Clasificación por umbrales (ADR-012) ─────────────────────────────────────────────────────

CUMPLE = {
    "estado": "Cumple",
    "indice_sop": 0,
    "indice_video": 2,
    "similitud": 0.81,
    "t_inicio": 33.44,
    "cita": "Ahora cierro la llave de paso",
    "confianza": "alta",
}
SOBRA = {k: v for k, v in CUMPLE.items() if k not in ("indice_sop", "similitud")} | {
    "estado": "Sobra"
}
JUICIO = {
    "origen": "llm",
    "veredicto": "Parcial",
    "justificacion": "Cierra la llave, pero no confirma que el manómetro marque cero.",
    "cita": "Ahora cierro la llave de paso",
    "similitud": 0.62,
    "prompt": "juez_zona_gris_v1",
    "modelo": "falso",
    "intentos": 1,
}
RESPALDO = {
    "origen": "respaldo",
    "similitud": 0.62,
    "prompt": "juez_zona_gris_v1",
    "intentos": 0,
    "motivo": "llm_no_disponible",
}
PARCIAL = {**CUMPLE, "estado": "Parcial", "similitud": 0.62, "juicio": JUICIO}


def _conteo(**cambios: int) -> dict[str, int]:
    return dict.fromkeys(ESTADOS, 0) | cambios


@pytest.mark.parametrize(
    "datos",
    [
        CUMPLE,
        {**CUMPLE, "estado": "zona_gris", "similitud": 0.6},
        PARCIAL,
        SOBRA,
        {**SOBRA, "cita": "", "confianza": "baja"},
        {"estado": "Falta", "indice_sop": 3},
    ],
    ids=["cumple", "zona_gris", "parcial", "sobra", "sobra_sin_cita", "falta"],
)
def test_resultado_paso_valido(datos):
    assert ResultadoPaso.model_validate(datos).estado == datos["estado"]


@pytest.mark.parametrize(
    ("datos", "texto"),
    [
        ({**CUMPLE, "indice_video": None}, "índices"),
        ({**SOBRA, "indice_sop": 0}, "índices"),
        ({"estado": "Falta", "indice_sop": 0, "indice_video": 1}, "índices"),
        ({**CUMPLE, "similitud": None}, "similitud"),
        ({**SOBRA, "similitud": 0.4}, "similitud"),
        ({"estado": "Falta", "indice_sop": 0, "t_inicio": 3.0}, "Falta"),
        ({"estado": "Falta", "indice_sop": 0, "cita": "cierro"}, "Falta"),
        ({**SOBRA, "t_inicio": None}, "t_inicio"),
        ({**SOBRA, "cita": "", "confianza": "media"}, "baja"),
        ({**CUMPLE, "cita": "  ", "confianza": "alta"}, "baja"),
        ({**CUMPLE, "estado": "Fuera de orden"}, "estado"),
    ],
)
def test_resultado_paso_incoherente_falla(datos, texto):
    _falla(ResultadoPaso, datos, texto)


def test_el_error_del_resultado_no_cita_el_texto():
    with pytest.raises(ValidationError) as exc:
        ResultadoPaso.model_validate({**CUMPLE, "similitud": None})
    assert CUMPLE["cita"] not in str(exc.value)


def test_resumen_de_la_clasificacion_valido():
    resumen = ResumenClasificacion(
        conteo=_conteo(Cumple=3, zona_gris=1), pares=4, pares_llm=1, pct_pares_llm=25.0
    )
    assert resumen.pct_pares_llm == 25.0


@pytest.mark.parametrize(
    "datos",
    [
        {"conteo": {"Cumple": 1}, "pares": 1, "pares_llm": 0, "pct_pares_llm": 0.0},
        {"conteo": _conteo(zona_gris=1), "pares": 1, "pares_llm": 0, "pct_pares_llm": 0.0},
        {"conteo": _conteo(zona_gris=2), "pares": 1, "pares_llm": 2, "pct_pares_llm": 100.0},
        {"conteo": _conteo(zona_gris=1), "pares": 4, "pares_llm": 1, "pct_pares_llm": 0.25},
        {"conteo": _conteo(Cumple=-1), "pares": 0, "pares_llm": 0, "pct_pares_llm": 0.0},
    ],
    ids=["sin_todos_los_estados", "llm_distinto", "llm_mayor", "pct_mal", "negativo"],
)
def test_resumen_de_la_clasificacion_incoherente_falla(datos):
    with pytest.raises(ValidationError):
        ResumenClasificacion.model_validate(datos)


def test_clasificacion_con_resumen_que_no_cuadra_falla():
    resumen = {"conteo": _conteo(Cumple=2), "pares": 2, "pares_llm": 0, "pct_pares_llm": 0.0}
    _falla(Clasificacion, {"pasos": [CUMPLE], "resumen": resumen}, "Cumple")
    resumen["conteo"] = _conteo(Cumple=1)
    assert len(Clasificacion.model_validate({"pasos": [CUMPLE], "resumen": resumen}).pasos) == 1


# ── Marca de fuera de orden y resultado de emparejar (ADR-012) ───────────────────────────────

MARCA = {"fuera_de_orden": True, "posicion_esperada": 1, "posicion_observada": 2}


@pytest.mark.parametrize(
    "datos",
    [
        {**CUMPLE, **MARCA},
        {**CUMPLE, "estado": "zona_gris", "similitud": 0.6, **MARCA},
        {**PARCIAL, **MARCA},
    ],
    ids=["cumple", "zona_gris", "parcial"],
)
def test_cumple_parcial_y_zona_gris_pueden_ir_fuera_de_orden(datos):
    paso = ResultadoPaso.model_validate(datos)
    assert (paso.fuera_de_orden, paso.posicion_esperada, paso.posicion_observada) == (True, 1, 2)


@pytest.mark.parametrize(
    "datos",
    [
        {"estado": "Falta", "indice_sop": 0, **MARCA},
        {**SOBRA, **MARCA},
    ],
    ids=["falta", "sobra"],
)
def test_otros_estados_no_pueden_ir_fuera_de_orden(datos):
    _falla(ResultadoPaso, datos, "solo Cumple, Parcial y zona_gris")


@pytest.mark.parametrize(
    "cambios",
    [
        {"fuera_de_orden": True},
        {"fuera_de_orden": True, "posicion_esperada": 1},
        {"fuera_de_orden": True, "posicion_observada": 2},
        {"posicion_esperada": 1, "posicion_observada": 2},
        {"posicion_observada": 2},
    ],
    ids=["marca_sin_posiciones", "sin_observada", "sin_esperada", "posiciones_sin_marca", "una"],
)
def test_las_posiciones_van_si_y_solo_si_hay_marca(cambios):
    _falla(ResultadoPaso, {**CUMPLE, **cambios}, "posiciones")


def test_posicion_negativa_falla():
    _falla(ResultadoPaso, {**CUMPLE, **MARCA, "posicion_esperada": -1}, "posicion_esperada")


def test_clasificacion_con_fuera_de_orden_que_no_cuadra_falla():
    resumen = {"conteo": _conteo(Cumple=1), "pares": 1, "pares_llm": 0, "pct_pares_llm": 0.0}
    pasos = [{**CUMPLE, **MARCA}]
    _falla(Clasificacion, {"pasos": pasos, "resumen": resumen}, "fuera de orden")
    clasificacion = Clasificacion.model_validate(
        {"pasos": pasos, "resumen": {**resumen, "fuera_de_orden": 1}}
    )
    assert clasificacion.resumen.fuera_de_orden == 1
    assert clasificacion.resumen.conteo["Cumple"] == 1  # la marca no toca el conteo por estado


def _resultado_emparejamiento(**cambios) -> dict:
    paso_video = {**PASO, "numero": 1, "cita": CUMPLE["cita"], "t_inicio": 33.44, "t_fin": 40.0}
    datos = {
        "clasificacion": {
            "pasos": [{**CUMPLE, "indice_video": 0}],
            "resumen": {
                "conteo": _conteo(Cumple=1),
                "pares": 1,
                "pares_llm": 0,
                "pct_pares_llm": 0.0,
            },
        },
        "fusiones": [
            {**FUSION, "numero": 1, "originales": [1], "citas": ["c"], "similitudes": [0.8]}
        ],
        "pasos_video": [paso_video],
    }
    return datos | cambios


def test_resultado_emparejamiento_valido():
    resultado = ResultadoEmparejamiento.model_validate(_resultado_emparejamiento())
    assert resultado.clasificacion.pasos[0].indice_video == 0


def test_resultado_emparejamiento_sin_fusion_por_paso_falla():
    _falla(ResultadoEmparejamiento, _resultado_emparejamiento(fusiones=[]), "registros de fusión")


def test_resultado_emparejamiento_con_tiempo_ajeno_al_paso_del_video_falla():
    datos = _resultado_emparejamiento()
    datos["pasos_video"][0]["t_inicio"] = 30.0
    _falla(ResultadoEmparejamiento, datos, "regla 4")


def test_resultado_emparejamiento_con_indice_fuera_de_rango_falla():
    datos = _resultado_emparejamiento()
    datos["clasificacion"]["pasos"][0]["indice_video"] = 3
    _falla(ResultadoEmparejamiento, datos, "indice_video 3")


# ── Juez de la zona gris (ADR-012, punto 3) ──────────────────────────────────────────────────


def test_juicio_del_llm_y_de_respaldo_validan():
    assert Juicio.model_validate(JUICIO).veredicto == "Parcial"
    assert Juicio.model_validate(RESPALDO).veredicto is None


@pytest.mark.parametrize(
    "datos",
    [
        {**JUICIO, "veredicto": None},
        {**JUICIO, "cita": " "},
        {**JUICIO, "justificacion": ""},
        {**JUICIO, "motivo": "respuesta_invalida"},
        {**JUICIO, "intentos": 0},
        {**RESPALDO, "veredicto": "Cumple"},
        {**RESPALDO, "cita": "Ahora cierro la llave de paso"},
        {**RESPALDO, "motivo": None},
        {**RESPALDO, "motivo": "otro"},
        {**RESPALDO, "prompt": ""},
    ],
    ids=[
        "llm_sin_veredicto",
        "llm_sin_cita",
        "llm_sin_justificacion",
        "llm_con_motivo",
        "llm_sin_intentos",
        "respaldo_con_veredicto",
        "respaldo_con_cita",
        "respaldo_sin_motivo",
        "motivo_desconocido",
        "sin_prompt",
    ],
)
def test_juicio_incoherente_falla(datos):
    with pytest.raises(ValidationError):
        Juicio.model_validate(datos)


NO_CORRESPONDE = {**JUICIO, "veredicto": "no_corresponde"}


@pytest.mark.parametrize(
    "datos",
    [
        {**CUMPLE, "juicio": {**JUICIO, "veredicto": "Cumple"}},
        PARCIAL,
        {**CUMPLE, "estado": "zona_gris", "similitud": 0.62, "juicio": RESPALDO},
        {"estado": "Falta", "indice_sop": 0, "juicio": NO_CORRESPONDE},
        {**SOBRA, "juicio": NO_CORRESPONDE},
    ],
    ids=["cumple", "parcial", "zona_gris_respaldo", "falta_roto", "sobra_roto"],
)
def test_resultado_con_juicio_coherente_valida(datos):
    assert ResultadoPaso.model_validate(datos).juicio is not None


@pytest.mark.parametrize(
    ("datos", "texto"),
    [
        ({**PARCIAL, "juicio": None}, "Parcial"),
        ({**CUMPLE, "juicio": JUICIO}, "no concuerda"),
        ({**CUMPLE, "juicio": RESPALDO}, "no concuerda"),
        ({**CUMPLE, "estado": "zona_gris", "similitud": 0.6, "juicio": JUICIO}, "no concuerda"),
        ({**CUMPLE, "juicio": NO_CORRESPONDE}, "no concuerda"),
        ({"estado": "Falta", "indice_sop": 0, "juicio": RESPALDO}, "no concuerda"),
    ],
    ids=[
        "parcial_sin_juicio",
        "cumple_con_parcial",
        "cumple_con_respaldo",
        "zona_gris_con_veredicto",
        "cumple_no_corresponde",
        "falta_con_respaldo",
    ],
)
def test_resultado_con_juicio_incoherente_falla(datos, texto):
    _falla(ResultadoPaso, datos, texto)


def _juez(**cambios: int) -> dict[str, int]:
    return dict.fromkeys(RESULTADOS_JUEZ, 0) | cambios


def test_resumen_con_juez_cuenta_los_pares_que_fueron_al_llm():
    # 4 pares en zona gris: 1 Cumple, 1 Parcial, 1 roto (Falta + Sobra) y 1 sin revisar.
    resumen = ResumenClasificacion(
        conteo=_conteo(Cumple=1, Parcial=1, Falta=1, Sobra=1, zona_gris=1),
        pares=4,
        pares_llm=4,
        pct_pares_llm=100.0,
        juez=_juez(Cumple=1, Parcial=1, no_corresponde=1, respaldo=1),
        segundos_juez=12.5,
    )
    assert resumen.juez is not None and resumen.juez["respaldo"] == 1
    assert resumen.segundos_juez == 12.5


@pytest.mark.parametrize(
    ("juez", "zona_gris", "texto"),
    [
        (_juez(Cumple=1, Parcial=1, no_corresponde=1, respaldo=1), 2, "pares en respaldo"),
        (_juez(Cumple=1, Parcial=1, no_corresponde=1, respaldo=2), 2, "decidió 5"),
        ({"Cumple": 4}, 0, "todos sus resultados"),
    ],
    ids=["respaldo_distinto", "suma_distinta", "sin_todos"],
)
def test_resumen_con_juez_incoherente_falla(juez, zona_gris, texto):
    datos = {
        "conteo": _conteo(Cumple=1, Parcial=1, Falta=1, Sobra=1, zona_gris=zona_gris),
        "pares": 4,
        "pares_llm": 4,
        "pct_pares_llm": 100.0,
        "juez": juez,
        "segundos_juez": 12.5,
    }
    _falla(ResumenClasificacion, datos, texto)


@pytest.mark.parametrize(
    "cambios",
    [{"juez": None}, {"segundos_juez": None}],
    ids=["segundos_sin_juez", "juez_sin_segundos"],
)
def test_juez_y_sus_segundos_van_juntos(cambios):
    datos = {
        "conteo": _conteo(Cumple=1),
        "pares": 1,
        "pares_llm": 0,
        "pct_pares_llm": 0.0,
        "juez": _juez(),
        "segundos_juez": 0.0,
    }
    assert ResumenClasificacion.model_validate(datos).segundos_juez == 0.0
    _falla(ResumenClasificacion, datos | cambios, "van juntos")


def test_segundos_del_juez_negativos_fallan():
    datos = {
        "conteo": _conteo(Cumple=1),
        "pares": 1,
        "pares_llm": 0,
        "pct_pares_llm": 0.0,
        "juez": _juez(),
        "segundos_juez": -0.1,
    }
    _falla(ResumenClasificacion, datos, "segundos_juez")


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
