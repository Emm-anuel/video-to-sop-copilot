"""Segmentación en pasos con LLM simulado (httpx.MockTransport): no requiere Ollama ni GPU."""

import json
import logging
import re
from pathlib import Path

import httpx
import pytest

from sopvid.lenguaje.llm import ClienteLLM
from sopvid.percepcion.segmentacion import (
    PropuestaInvalida,
    construir_mensajes,
    empieza_con_marcador,
    f1_fronteras,
    segmentar,
    segmentar_heuristica,
    validar_propuesta,
)

FIXTURES = Path(__file__).parent / "fixtures" / "transcripciones"
ETIQUETAS = {"maquina": "cortadora", "area": "conversión", "proceso": "cambio de cuchilla"}

SEGMENTOS = [
    {"id": 1, "t_inicio": 0.0, "t_fin": 4.0, "texto": "Hoy vamos a cambiar la cuchilla."},
    {"id": 2, "t_inicio": 4.5, "t_fin": 8.0, "texto": "Primero apagamos la máquina."},
    {"id": 3, "t_inicio": 8.4, "t_fin": 12.0, "texto": "Se pone el candado en el gabinete."},
    {"id": 4, "t_inicio": 16.0, "t_fin": 20.0, "texto": "La guarda tiene cuatro perillas."},
    {"id": 5, "t_inicio": 20.3, "t_fin": 24.0, "texto": "Se levanta con las dos manos."},
    {"id": 6, "t_inicio": 24.5, "t_fin": 28.0, "texto": "Después se monta la cuchilla nueva."},
    {"id": 7, "t_inicio": 28.2, "t_fin": 31.0, "texto": "Ahora, ojo con el filo."},
]


def cliente_que_responde(contenido: str | None = None, *, error: Exception | None = None):
    def manejador(request):
        if error is not None:
            raise error
        return httpx.Response(
            200,
            json={"model": "falso", "message": {"role": "assistant", "content": contenido}},
        )

    return ClienteLLM("http://ollama.test:11434", "falso", transport=httpx.MockTransport(manejador))


# ── Camino LLM y validación ──────────────────────────────────────────────────────────────────


def test_los_tiempos_salen_de_los_segmentos_aunque_el_llm_invente_uno():
    respuesta = json.dumps(
        [
            {"segmento_id": 2, "titulo": "Apagar y bloquear", "t_inicio": 999},
            {"segmento_id": 4, "titulo": " Retirar la guarda "},
            {"segmento_id": 6, "titulo": "Montar la cuchilla"},
        ]
    )
    with cliente_que_responde(respuesta) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "llm"
    assert r.motivo_respaldo is None
    assert [(p.segmento_id, p.t_inicio, p.titulo) for p in r.pasos] == [
        (2, 4.5, "Apagar y bloquear"),
        (4, 16.0, "Retirar la guarda"),
        (6, 24.5, "Montar la cuchilla"),
    ]


@pytest.mark.parametrize(
    ("datos", "motivo"),
    [
        ([{"segmento_id": 2, "titulo": "a"}, {"segmento_id": 99, "titulo": "b"}], "no existe"),
        ([{"segmento_id": 4, "titulo": "a"}, {"segmento_id": 2, "titulo": "b"}], "no creciente"),
        ([{"segmento_id": 2, "titulo": "a"}, {"segmento_id": 2, "titulo": "b"}], "duplicado"),
        ([], "al menos un paso"),
        ({"pasos": []}, "al menos un paso"),
        ([{"segmento_id": "2", "titulo": "a"}], "entero"),
        ([{"segmento_id": True, "titulo": "a"}], "entero"),
        ([{"segmento_id": 2, "titulo": "  "}], "título"),
        (["2"], "objeto"),
    ],
)
def test_validacion_rechaza_propuestas_invalidas(datos, motivo):
    with pytest.raises(PropuestaInvalida, match=motivo):
        validar_propuesta(datos, SEGMENTOS)


def test_propuesta_invalida_cae_a_la_heuristica_y_registra_el_camino(caplog):
    respuesta = json.dumps([{"segmento_id": 2, "titulo": "a"}, {"segmento_id": 99, "titulo": "b"}])
    with caplog.at_level(logging.INFO), cliente_que_responde(respuesta) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "heuristica"
    assert "inválida" in r.motivo_respaldo and "99" in r.motivo_respaldo
    assert r.pasos == segmentar_heuristica(SEGMENTOS)
    assert "heurística" in caplog.text


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("caído"), httpx.ReadTimeout("lento")], ids=["red", "timeout"]
)
def test_llm_caido_cae_a_la_heuristica(error):
    with cliente_que_responde(error=error) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "heuristica"
    assert "LLMNoDisponible" in r.motivo_respaldo


def test_json_roto_cae_a_la_heuristica():
    with cliente_que_responde('[{"segmento_id": 2, "tit') as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "heuristica"
    assert "LLMRespuestaInvalida" in r.motivo_respaldo


def test_sin_cliente_usa_la_heuristica():
    r = segmentar(SEGMENTOS, ETIQUETAS, None)
    assert r.metodo == "heuristica"
    assert r.motivo_respaldo == "sin cliente LLM"


def test_el_prompt_lleva_ids_y_etiquetas_pero_ningun_tiempo():
    mensajes = construir_mensajes(SEGMENTOS, ETIQUETAS)
    usuario = mensajes[1]["content"]

    assert "[4] La guarda tiene cuatro perillas." in usuario
    assert "maquina=cortadora" in usuario
    for s in SEGMENTOS:
        for t in (s["t_inicio"], s["t_fin"]):
            assert not re.search(rf"(?<![\d.]){re.escape(str(t))}(?![\d])", usuario)


def test_por_defecto_prompt_v1_y_la_regla_de_aclaraciones_es_opcional():
    por_defecto = construir_mensajes(SEGMENTOS, ETIQUETAS)[1]["content"]
    v1 = construir_mensajes(SEGMENTOS, ETIQUETAS, regla_aclaraciones=False)[1]["content"]
    v2 = construir_mensajes(SEGMENTOS, ETIQUETAS, regla_aclaraciones=True)[1]["content"]

    assert por_defecto == v1  # v2 se probó en la Fase 4 y se descartó (ADR-010)
    assert "aclaraciones, advertencias" not in v1
    assert "aclaraciones, advertencias" in v2


# ── Heurística ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Primero apagamos la máquina.", True),
        ("Lo primero es preparar todo.", True),
        ("DESPUÉS se monta.", True),
        ("Ahora, ojo con el filo.", True),
        ("A continuación se purga.", True),
        ("Se pone el candado y luego se purga.", False),  # marcador fuera de las primeras palabras
        ("Ahorita no.", False),  # no basta un prefijo
        ("La guarda tiene cuatro perillas.", False),
    ],
)
def test_marcadores_al_inicio_sin_acentos_ni_mayusculas(texto, esperado):
    assert empieza_con_marcador(texto) is esperado


def test_heuristica_combina_marcadores_y_pausas_con_separacion_minima():
    pasos = segmentar_heuristica(SEGMENTOS)

    # 2: "Primero"; 4: pausa de 4 s; 6: "Después"; 7 ("Ahora") queda a 1 segmento del 6.
    assert [p.segmento_id for p in pasos] == [2, 4, 6]
    assert [p.t_inicio for p in pasos] == [4.5, 16.0, 24.5]


def test_heuristica_sin_t_fin_solo_usa_marcadores():
    sin_fin = [{k: v for k, v in s.items() if k != "t_fin"} for s in SEGMENTOS]
    assert [p.segmento_id for p in segmentar_heuristica(sin_fin)] == [2, 6]


def test_heuristica_sin_candidatos_devuelve_un_solo_paso():
    planos = [{"id": i, "t_inicio": float(i), "texto": "Se aprieta el tornillo."} for i in (1, 2)]
    pasos = segmentar_heuristica(planos)
    assert [(p.segmento_id, p.t_inicio) for p in pasos] == [(1, 1.0)]


# ── Métrica ──────────────────────────────────────────────────────────────────────────────────


def test_f1_fronteras_a_mas_menos_un_segmento_uno_a_uno():
    r = f1_fronteras([5, 9, 12, 16], [5, 10, 15])

    assert r["tp"] == 3  # 5=5, 9~10, 16~15
    assert r["falsos_positivos"] == [12]
    assert r["no_detectados"] == []
    assert r["precision"] == 0.75 and r["recall"] == 1.0


def test_f1_un_predicho_no_cuenta_dos_veces():
    r = f1_fronteras([5], [4, 6])
    assert r["tp"] == 1
    assert r["no_detectados"] == [6]  # el empate se resuelve hacia el anterior


def test_f1_prefiere_la_coincidencia_exacta_al_etiquetar_el_sobrante():
    r = f1_fronteras([5, 6], [6])
    assert r["tp"] == 1
    assert r["falsos_positivos"] == [5]  # sobra el 5, no el 6 que coincide exacto


def test_f1_no_pierde_aciertos_en_una_cadena_desplazada():
    r = f1_fronteras([4, 5], [5, 6])
    assert r["tp"] == 2  # 4~5 y 5~6; fijar primero el 5 exacto dejaría solo 1
    assert r["falsos_positivos"] == [] and r["no_detectados"] == []


def test_f1_sin_predicciones():
    assert f1_fronteras([], [3])["f1"] == 0.0


# ── Fixtures ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("archivo", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_fixtures_bien_formados(archivo):
    fx = json.loads(archivo.read_text(encoding="utf-8"))
    ids = [s["id"] for s in fx["segmentos"]]

    assert "INVENTADA" in fx["descripcion"]  # nada del cliente (NDA)
    assert ids == list(range(1, len(ids) + 1))
    assert set(fx["inicios_paso"]) <= set(ids)
    assert fx["inicios_paso"] == sorted(set(fx["inicios_paso"]))
    assert all(s["t_inicio"] < s["t_fin"] for s in fx["segmentos"])
    segs = fx["segmentos"]
    assert all(a["t_fin"] <= b["t_inicio"] for a, b in zip(segs, segs[1:], strict=False))


def test_hay_una_transcripcion_sin_palabras_de_transicion():
    fx = json.loads((FIXTURES / "cambio_filtro_hidraulico.json").read_text(encoding="utf-8"))
    assert not any(empieza_con_marcador(s["texto"], 99) for s in fx["segmentos"])
