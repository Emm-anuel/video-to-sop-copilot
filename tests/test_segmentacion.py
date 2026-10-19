"""Segmentación en pasos con LLM simulado (httpx.MockTransport): no requiere Ollama ni GPU."""

import inspect
import json
import logging
import re
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter

from sopvid.contrato import Analisis, PasoVideo
from sopvid.lenguaje.llm import SEMILLA, ClienteLLM
from sopvid.percepcion.segmentacion import (
    ESQUEMA_FRONTERAS,
    ESQUEMA_PASOS,
    ESQUEMA_REDACCION,
    NO_IDENTIFICADO,
    RECORDATORIO_REDACCION,
    RECORDATORIO_SEGMENTOS,
    SISTEMA,
    PropuestaFrontera,
    PropuestaInvalida,
    RedaccionPaso,
    _construir_con_rangos,
    _texto_comparable,
    _validar_propuestas,
    _validar_redaccion,
    cargar_transcripcion_prueba,
    construir_mensajes,
    construir_mensajes_fronteras,
    construir_mensajes_redaccion,
    construir_pasos,
    empieza_con_marcador,
    f1_fronteras,
    normalizar_responsable,
    recortar_cita,
    rol_mencionado,
    segmentar,
    segmentar_con_llm,
    segmentar_heuristica,
    segmentos_de_inicio,
    verificar_cita,
)

FIXTURES = Path(__file__).parent / "fixtures" / "transcripciones"
ANALISIS_EJEMPLO = Path(__file__).parent / "fixtures" / "analisis_ejemplo.json"
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


def analisis_de(segmentos: list[dict], video_id: int = 1) -> Analisis:
    return Analisis(
        video_id=video_id,
        duracion_s=segmentos[-1]["t_fin"] if segmentos else 0.0,
        idioma={"codigo": "es", "confianza": 0.99},
        transcripcion=segmentos,
    )


ANALISIS = analisis_de(SEGMENTOS)


def propuesta(segmento_id, nombre="Paso", **campos) -> dict:
    """Un paso como lo devolvería el LLM, con los cinco campos de `PropuestaPaso`."""
    return {
        "segmento_id": segmento_id,
        "nombre": nombre,
        "descripcion": "Se hace algo.",
        "responsable": "Técnico",
        "cita": "una frase del segmento",
        **campos,
    }


def cliente_que_responde(
    contenido: str | None = None, *, error: Exception | None = None, peticiones: list | None = None
):
    def manejador(request):
        if peticiones is not None:
            peticiones.append(json.loads(request.content))
        if error is not None:
            raise error
        return httpx.Response(
            200,
            json={"model": "falso", "message": {"role": "assistant", "content": contenido}},
        )

    return ClienteLLM("http://ollama.test:11434", "falso", transport=httpx.MockTransport(manejador))


# ── Camino LLM y validación ──────────────────────────────────────────────────────────────────


def test_los_pasos_traen_los_campos_del_llm_y_los_tiempos_de_los_segmentos():
    respuesta = json.dumps(
        [
            propuesta(
                2,
                "Apagar y bloquear",
                descripcion="Se apaga la máquina y se bloquea el gabinete con candado.",
                responsable="Operador",
                cita="Primero apagamos la máquina.",
            ),
            propuesta(4, " Retirar la guarda ", responsable=""),
            propuesta(6, "Montar la cuchilla"),
        ]
    )
    with cliente_que_responde(respuesta) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert r.metodo == "llm"
    assert r.motivo_respaldo is None
    assert all(isinstance(p, PasoVideo) for p in r.pasos)
    assert segmentos_de_inicio(r.pasos, ANALISIS) == [2, 4, 6]
    assert [(p.numero, p.t_inicio, p.t_fin, p.nombre) for p in r.pasos] == [
        (1, 4.5, 12.0, "Apagar y bloquear"),
        (2, 16.0, 24.0, "Retirar la guarda"),
        (3, 24.5, 31.0, "Montar la cuchilla"),
    ]
    primero = r.pasos[0]
    assert primero.descripcion == "Se apaga la máquina y se bloquea el gabinete con candado."
    assert primero.responsable == "Operador"
    assert primero.cita == "Primero apagamos la máquina."
    assert r.pasos[1].responsable == NO_IDENTIFICADO  # vacío: nadie lo dice en el audio


def test_un_tiempo_escrito_por_el_llm_invalida_la_propuesta():
    respuesta = json.dumps([propuesta(2, t_inicio=999), propuesta(4)])
    with cliente_que_responde(respuesta) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert r.metodo == "heuristica"
    assert "t_inicio (extra_forbidden)" in r.motivo_respaldo


@pytest.mark.parametrize(
    ("datos", "motivo"),
    [
        ([propuesta(2), propuesta(99)], "no existe"),
        ([propuesta(4), propuesta(2)], "no creciente"),
        ([propuesta(2), propuesta(2)], "duplicado"),
        ([], "al menos un paso"),
        ({"pasos": []}, "al menos un paso"),
        ([propuesta("2")], r"segmento_id \(int_type\)"),
        ([propuesta(True)], r"segmento_id \(int_type\)"),
        ([propuesta(2, "  ")], r"nombre \(value_error\)"),
        ([{k: v for k, v in propuesta(2).items() if k != "cita"}], r"cita \(missing\)"),
        ([propuesta(2, descripcion=None)], r"descripcion \(string_type\)"),
        (["2"], "objeto"),
    ],
)
def test_validacion_rechaza_propuestas_invalidas(datos, motivo):
    with pytest.raises(PropuestaInvalida, match=motivo):
        construir_pasos(datos, ANALISIS)


def test_el_motivo_de_rechazo_no_copia_texto_de_la_transcripcion():
    cita = "Se pone el candado en el gabinete."
    with pytest.raises(PropuestaInvalida) as exc:
        construir_pasos([propuesta(2, nombre=cita, extra=cita, cita=1)], ANALISIS)
    assert "candado" not in str(exc.value)


def test_propuesta_invalida_cae_a_la_heuristica_y_registra_el_camino(caplog):
    respuesta = json.dumps([propuesta(2), propuesta(99)])
    with caplog.at_level(logging.INFO), cliente_que_responde(respuesta) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert r.metodo == "heuristica"
    assert "inválida" in r.motivo_respaldo and "99" in r.motivo_respaldo
    assert r.pasos == segmentar_heuristica(ANALISIS)
    assert "heurística" in caplog.text


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("caído"), httpx.ReadTimeout("lento")], ids=["red", "timeout"]
)
def test_llm_caido_cae_a_la_heuristica(error):
    with cliente_que_responde(error=error) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert r.metodo == "heuristica"
    assert "LLMNoDisponible" in r.motivo_respaldo
    assert r.intentos == 1  # el cliente reintenta la red una vez por dentro; aquí no se repite


def test_sin_cliente_usa_la_heuristica():
    r = segmentar(ANALISIS, None, ETIQUETAS)
    assert r.metodo == "heuristica"
    assert r.motivo_respaldo == "sin cliente LLM"
    assert r.intentos == 0


# ── Reintentos (RNF-07) ──────────────────────────────────────────────────────────────────────


def cliente_en_secuencia(respuestas: list, peticiones: list):
    """Cliente simulado que devuelve `respuestas` en orden: texto del modelo o código HTTP."""
    pendientes = iter(respuestas)

    def manejador(request):
        peticiones.append(json.loads(request.content))
        r = next(pendientes)
        if isinstance(r, int):
            return httpx.Response(r, json={"error": "falla del servidor"})
        return httpx.Response(
            200, json={"model": "falso", "message": {"role": "assistant", "content": r}}
        )

    return ClienteLLM("http://ollama.test:11434", "falso", transport=httpx.MockTransport(manejador))


VALIDA = json.dumps([propuesta(2), propuesta(4), propuesta(6)])
ID_INEXISTENTE = json.dumps([propuesta(2), propuesta(99)])
DUPLICADA = json.dumps([propuesta(2), propuesta(2)])
CON_TIEMPO = json.dumps([propuesta(2, t_inicio=4.5)])


def test_valida_al_primer_intento():
    peticiones = []
    with cliente_en_secuencia([VALIDA], peticiones) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert (r.metodo, r.intentos, len(peticiones)) == ("llm", 1, 1)
    assert segmentos_de_inicio(r.pasos, ANALISIS) == [2, 4, 6]


def test_invalida_y_luego_valida_reenvia_la_respuesta_y_el_error():
    peticiones = []
    with cliente_en_secuencia([ID_INEXISTENTE, VALIDA], peticiones) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert (r.metodo, r.intentos, r.motivo_respaldo) == ("llm", 2, None)
    assert segmentos_de_inicio(r.pasos, ANALISIS) == [2, 4, 6]

    primera, segunda = (p["messages"] for p in peticiones)
    assert segunda[:2] == primera  # mismo sistema y mismo prompt
    assert [m["role"] for m in segunda] == ["system", "user", "assistant", "user"]
    assert segunda[2]["content"] == ID_INEXISTENTE  # la respuesta anterior, tal cual
    correccion = segunda[3]["content"]
    assert "el segmento 99 no existe" in correccion
    assert "no escribas tiempos" in correccion
    for s in SEGMENTOS:  # el error no copia texto de la transcripción
        assert s["texto"] not in correccion
    for p in peticiones:  # misma decodificación determinista en cada llamada
        assert p["options"]["temperature"] == 0 and p["options"]["seed"] == SEMILLA
        assert p["format"] == ESQUEMA_PASOS


def test_el_error_de_esquema_se_resume_por_campo():
    peticiones = []
    with cliente_en_secuencia([CON_TIEMPO, VALIDA], peticiones) as llm:
        segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert "t_inicio (extra_forbidden)" in peticiones[1]["messages"][-1]["content"]


def test_tres_invalidas_caen_a_la_heuristica_con_el_ultimo_motivo(caplog):
    peticiones = []
    with (
        caplog.at_level(logging.WARNING),
        cliente_en_secuencia([ID_INEXISTENTE, CON_TIEMPO, DUPLICADA], peticiones) as llm,
    ):
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert (r.metodo, r.intentos, len(peticiones)) == ("heuristica", 3, 3)
    assert r.pasos == segmentar_heuristica(ANALISIS)
    assert "inválida" in r.motivo_respaldo
    assert "el segmento 2 está duplicado" in r.motivo_respaldo  # el último, no el primero
    assert "tras 3 intentos" in r.motivo_respaldo
    # La tercera llamada lleva las dos respuestas anteriores y sus dos correcciones.
    assert [m["role"] for m in peticiones[2]["messages"]] == ["system", "user"] + [
        "assistant",
        "user",
    ] * 2
    assert caplog.text.count("Respuesta del LLM inválida") == 3


def test_segmentar_con_llm_lanza_el_ultimo_motivo():
    with (
        cliente_en_secuencia([ID_INEXISTENTE] * 3, []) as llm,
        pytest.raises(PropuestaInvalida, match="99 no existe.*tras 3 intentos"),
    ):
        segmentar_con_llm(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)


def test_llm_no_disponible_va_directo_a_la_heuristica_sin_reintentos():
    peticiones = []
    with cliente_en_secuencia([500, VALIDA], peticiones) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert r.metodo == "heuristica"
    assert "LLMNoDisponible" in r.motivo_respaldo
    assert len(peticiones) == r.intentos == 1


def test_llm_que_se_cae_a_media_correccion_no_se_reintenta():
    peticiones = []
    with cliente_en_secuencia([ID_INEXISTENTE, 500, VALIDA], peticiones) as llm:
        r = segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    assert r.metodo == "heuristica"
    assert "LLMNoDisponible" in r.motivo_respaldo
    assert len(peticiones) == r.intentos == 2


def test_el_prompt_lleva_ids_y_etiquetas_pero_ningun_tiempo():
    mensajes = construir_mensajes(ANALISIS, ETIQUETAS)
    usuario = mensajes[1]["content"]

    assert "[4] La guarda tiene cuatro perillas." in usuario
    assert "maquina=cortadora" in usuario
    for s in SEGMENTOS:
        for t in (s["t_inicio"], s["t_fin"]):
            assert not re.search(rf"(?<![\d.]){re.escape(str(t))}(?![\d])", usuario)


def test_el_prompt_pide_los_campos_de_rf13_sin_sop():
    usuario = construir_mensajes(ANALISIS, ETIQUETAS)[1]["content"]

    for campo in ("segmento_id", "nombre", "descripcion", "responsable", "cita"):
        assert f"- {campo}:" in usuario
    assert f'"{NO_IDENTIFICADO}"' in usuario
    assert "de 4 a 15 palabras, sin parafrasear" in usuario
    assert "en español aunque la transcripción esté en otro idioma" in usuario
    assert "la cita se deja en el idioma original" in usuario
    assert "no escribas tiempos" in usuario
    assert "SOP" not in usuario  # la extracción nunca ve el SOP (sección 5.3)


def test_por_defecto_prompt_v1_y_la_regla_de_aclaraciones_es_opcional():
    por_defecto = construir_mensajes(ANALISIS, ETIQUETAS)[1]["content"]
    v1 = construir_mensajes(ANALISIS, ETIQUETAS, regla_aclaraciones=False)[1]["content"]
    v2 = construir_mensajes(ANALISIS, ETIQUETAS, regla_aclaraciones=True)[1]["content"]

    assert por_defecto == v1  # v2 se probó en la Fase 4 y se descartó (ADR-010)
    assert "aclaraciones, advertencias" not in v1
    assert "aclaraciones, advertencias" in v2


@pytest.mark.parametrize("etiquetas", [None, {}])
def test_las_etiquetas_son_opcionales(etiquetas):
    usuario = construir_mensajes(ANALISIS, etiquetas)[1]["content"]
    assert "Etiquetas" not in usuario
    assert usuario.startswith("Segmentos de la transcripción")

    peticiones = []
    with cliente_en_secuencia([VALIDA], peticiones) as llm:
        r = segmentar(ANALISIS, llm, dos_llamadas=False)
    assert r.metodo == "llm"
    assert "Etiquetas" not in peticiones[0]["messages"][1]["content"]


# ── Pasos del video (construir_pasos) ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def analisis() -> Analisis:
    return Analisis.model_validate_json(ANALISIS_EJEMPLO.read_text(encoding="utf-8"))


def test_construir_pasos_calcula_tiempos_desde_los_segmentos(analisis):
    propuestas = [
        propuesta(4, "Ponerse guantes y lentes", responsable="Técnica"),
        propuesta(12, "Retirar la carcasa"),
        propuesta(21, "Abrir la llave y revisar fugas", responsable=""),
    ]
    pasos = construir_pasos(propuestas, analisis)

    # Segmentos 4–11, 12–20 y 21–25 del fixture (tests/fixtures/README.md).
    assert [(p.numero, p.t_inicio, p.t_fin) for p in pasos] == [
        (1, 20.45, 73.56),
        (2, 74.76, 125.62),
        (3, 127.32, 156.29),
    ]
    assert [p.nombre for p in pasos] == [
        "Ponerse guantes y lentes",
        "Retirar la carcasa",
        "Abrir la llave y revisar fugas",
    ]
    assert [p.responsable for p in pasos] == ["Técnica", "Técnico", NO_IDENTIFICADO]
    assert all(isinstance(p, PasoVideo) for p in pasos)


def test_construir_pasos_guarda_el_rango_de_segmentos_fuera_de_paso_video(analisis):
    propuestas = [propuesta(4), propuesta(12), propuesta(21)]
    rangos = _construir_con_rangos(propuestas, analisis)

    assert [(r.primer_segmento, r.ultimo_segmento) for r in rangos] == [(4, 11), (12, 20), (21, 25)]
    assert "segmento" not in " ".join(PasoVideo.model_fields)


def test_un_solo_paso_abarca_hasta_el_final(analisis):
    (paso,) = construir_pasos([propuesta(1, "Todo el procedimiento")], analisis)
    assert (paso.numero, paso.t_inicio, paso.t_fin) == (1, 0.4, 156.29)


def test_construir_pasos_con_ids_no_consecutivos():
    analisis = Analisis(
        video_id=9,
        duracion_s=40.0,
        idioma={"codigo": "es", "confianza": 0.9},
        transcripcion=[
            {"id": i, "t_inicio": t, "t_fin": t + 5.0, "texto": "x"}
            for i, t in ((10, 0.0), (20, 10.0), (30, 20.0), (40, 30.0))
        ],
    )
    pasos = construir_pasos([propuesta(10), propuesta(30)], analisis)
    assert [(p.t_inicio, p.t_fin) for p in pasos] == [(0.0, 15.0), (20.0, 35.0)]


@pytest.mark.parametrize(
    ("ids", "motivo"),
    [
        ([4, 99], "el segmento 99 no existe"),
        ([4, 4], "el segmento 4 está duplicado"),
        ([12, 4], "orden no creciente: 12 → 4"),
    ],
    ids=["inexistente", "duplicado", "decreciente"],
)
def test_construir_pasos_rechaza_ids_invalidos(analisis, ids, motivo):
    with pytest.raises(PropuestaInvalida, match=motivo):
        construir_pasos([propuesta(i) for i in ids], analisis)


def test_construir_pasos_rechaza_propuestas_vacias_o_sin_nombre(analisis):
    with pytest.raises(PropuestaInvalida, match="al menos un paso"):
        construir_pasos([], analisis)
    with pytest.raises(PropuestaInvalida, match=r"nombre \(value_error\)"):
        construir_pasos([propuesta(4, " ")], analisis)


def test_ningun_tiempo_de_construir_pasos_sale_del_llm(analisis):
    with pytest.raises(PropuestaInvalida, match=r"t_inicio \(extra_forbidden\)"):
        construir_pasos([propuesta(4, t_inicio=1.0), propuesta(12)], analisis)

    pasos = construir_pasos([propuesta(4), propuesta(12), propuesta(21)], analisis)
    inicios = {s.t_inicio for s in analisis.transcripcion}
    fines = {s.t_fin for s in analisis.transcripcion}
    assert all(p.t_inicio in inicios and p.t_fin in fines for p in pasos)


# ── Verificación de citas (RNF-06) ───────────────────────────────────────────────────────────

PASO_1 = (4, 5)  # guantes y lentes: segmentos 4–5 del fixture


@pytest.mark.parametrize(
    ("cita", "rango", "esperado"),
    [
        # Exacta, copiada del segmento 4.
        (
            "Primero me pongo los guantes de nitrilo y los lentes de seguridad.",
            PASO_1,
            ("alta", "audio"),
        ),
        # Mayúsculas, acentos y puntuación distintos (segmento 9: "Después", "presión", "botón").
        ("DESPUES libero la PRESION con el boton rojo", (9, 11), ("alta", "audio")),
        # Sin el punto y coma del segmento 7.
        ("la tuberia asi sabemos que esta cerrada", (6, 8), ("alta", "audio")),
        # Cruza del segmento 4 al 5.
        ("los lentes de seguridad. Los lentes son obligatorios", PASO_1, ("alta", "audio")),
        # Está en la transcripción, pero en el paso 6 (segmento 21).
        ("abro la llave de paso despacio", PASO_1, ("media", "audio")),
        # Cruza la frontera del paso: final del segmento 11 e inicio del 12.
        ("un poco de agua. Con la llave de carcasa", (9, 11), ("media", "audio")),
        # Inventada.
        ("se aprieta el tornillo con el torquímetro", PASO_1, ("baja", "inferido")),
        # Palabra incompleta: no basta una subcadena de caracteres.
        ("los guantes de nitri", PASO_1, ("baja", "inferido")),
        # Vacía o solo puntuación.
        ("", PASO_1, ("baja", "inferido")),
        ("  ¿…?  ", PASO_1, ("baja", "inferido")),
    ],
    ids=[
        "exacta",
        "mayusculas_y_acentos",
        "sin_puntuacion",
        "cruza_dos_segmentos",
        "en_otro_paso",
        "cruza_frontera_de_paso",
        "inventada",
        "palabra_incompleta",
        "vacia",
        "solo_puntuacion",
    ],
)
def test_verificar_cita(analisis, cita, rango, esperado):
    assert verificar_cita(cita, analisis, rango) == esperado


def test_construir_pasos_usa_la_verificacion_de_citas_y_la_registra_sin_texto(analisis, caplog):
    propuestas = [
        propuesta(4, cita="me pongo los guantes de nitrilo"),
        propuesta(9, cita="Finalmente abro la llave de paso"),  # es del paso de la 21
        propuesta(21, cita="aprieto la contratuerca a mano"),  # inventada
    ]
    with caplog.at_level(logging.INFO, logger="sopvid.percepcion.segmentacion"):
        pasos = construir_pasos(propuestas, analisis)

    assert [(p.confianza, p.fuente) for p in pasos] == [
        ("alta", "audio"),
        ("media", "audio"),
        ("baja", "inferido"),
    ]
    assert "Citas verificadas en 3 pasos: alta=1, media=1, baja=1" in caplog.text
    for p in propuestas:
        assert p["cita"] not in caplog.text


# ── Responsable (ADR-008) ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("  operador   de turno ", "Operador de turno"),
        ("Operador CNC", "Operador CNC"),  # conserva siglas
        ("", NO_IDENTIFICADO),
        ("   ", NO_IDENTIFICADO),
        ("N/A", NO_IDENTIFICADO),
        ("Desconocido", NO_IDENTIFICADO),
        ("ninguno", NO_IDENTIFICADO),
        ("no identificado", NO_IDENTIFICADO),
        ("-", NO_IDENTIFICADO),
    ],
)
def test_normalizar_responsable(valor, esperado):
    assert normalizar_responsable(valor) == esperado


@pytest.mark.parametrize(
    ("responsable", "texto", "esperado"),
    [
        ("Operador", "El operador abre la válvula.", True),
        ("El operador de turno", "lo hace el OPERADOR", True),  # ignora artículo y mayúsculas
        ("Técnico", "soy Laura, técnica de mantenimiento", True),  # género
        ("Supervisora", "avisen a los supervisores", True),  # género y número
        ("Operador", "La operación se detiene.", False),  # otra palabra con la misma raíz corta
        ("Supervisor", "Se abre la llave de paso.", False),
    ],
)
def test_rol_mencionado(responsable, texto, esperado):
    assert rol_mencionado(responsable, texto) is esperado


# Cita exacta del segmento 4 (paso 1, segmentos 4–5), para partir de confianza "alta".
CITA_PASO_1 = "me pongo los guantes de nitrilo"


def _paso_1(analisis, responsable, cita=CITA_PASO_1):
    propuestas = [propuesta(4, cita=cita, responsable=responsable), propuesta(6)]
    return construir_pasos(propuestas, analisis)[0]


def test_rol_dicho_en_la_introduccion_no_baja_la_confianza(analisis):
    # "soy Laura, técnica de mantenimiento" está en el segmento 1, antes del primer paso.
    paso = _paso_1(analisis, "técnica de mantenimiento")
    assert (paso.responsable, paso.confianza, paso.fuente) == (
        "Técnica de mantenimiento",
        "alta",
        "audio",
    )


def test_rol_dicho_dentro_del_paso_no_baja_la_confianza(analisis):
    # "avisen al supervisor de turno" está en el segmento 8, dentro del paso 6–8.
    propuestas = [
        propuesta(4),
        propuesta(6, cita="cierro la llave de paso", responsable="Supervisor"),
    ]
    paso = construir_pasos(propuestas, analisis)[1]
    assert (paso.responsable, paso.confianza) == ("Supervisor", "alta")


def test_rol_dicho_solo_en_otro_paso_baja_la_confianza(analisis):
    # El supervisor se menciona en el paso 2 (segmento 8), no en el 3 ni en la introducción.
    propuestas = [
        propuesta(4),
        propuesta(6),
        propuesta(9, cita="libero la presión con el botón rojo", responsable="Supervisor"),
    ]
    paso = construir_pasos(propuestas, analisis)[2]
    assert (paso.responsable, paso.confianza) == ("Supervisor", "media")


@pytest.mark.parametrize(
    ("cita", "confianza_cita", "esperada"),
    [
        (CITA_PASO_1, "alta", "media"),
        ("abro la llave de paso despacio", "media", "baja"),  # cita de otro paso
        ("cita inventada por el modelo", "baja", "baja"),  # baja no baja más
    ],
)
def test_rol_inventado_se_conserva_y_baja_un_nivel(analisis, cita, confianza_cita, esperada):
    assert verificar_cita(cita, analisis, (4, 5))[0] == confianza_cita
    paso = _paso_1(analisis, "jefe de línea", cita=cita)
    assert paso.responsable == "Jefe de línea"
    assert paso.confianza == esperada
    assert paso.fuente == verificar_cita(cita, analisis, (4, 5))[1]  # la fuente no cambia


@pytest.mark.parametrize("responsable", ["", "  ", "desconocido", "No identificado"])
def test_responsable_vacio_o_no_identificado_no_baja_la_confianza(analisis, responsable):
    paso = _paso_1(analisis, responsable)
    assert (paso.responsable, paso.confianza) == (NO_IDENTIFICADO, "alta")


def test_el_log_cuenta_los_responsables_no_mencionados_sin_texto(analisis, caplog):
    propuestas = [
        propuesta(4, cita=CITA_PASO_1, responsable="Jefe de línea"),
        propuesta(6, responsable="Supervisor"),
    ]
    with caplog.at_level(logging.INFO, logger="sopvid.percepcion.segmentacion"):
        construir_pasos(propuestas, analisis)

    # Las citas se cuentan antes de ajustar por el responsable.
    assert "alta=1, media=0, baja=1; responsables no mencionados en el audio: 1" in caplog.text
    assert "Jefe" not in caplog.text and "Supervisor" not in caplog.text


# ── Esquema y petición a Ollama ──────────────────────────────────────────────────────────────

# Palabras clave de JSON Schema que Ollama convierte en gramática sin problemas.
CLAVES_ESQUEMA = {
    "type",
    "items",
    "properties",
    "required",
    "additionalProperties",
    "title",
    "description",
}


def _nodos(esquema: dict):
    yield esquema
    for clave, valor in esquema.items():
        if clave == "properties":
            for hijo in valor.values():
                yield from _nodos(hijo)
        elif isinstance(valor, dict):
            yield from _nodos(valor)


def test_el_esquema_de_ollama_es_plano_y_sale_de_propuesta_paso():
    assert "$ref" not in json.dumps(ESQUEMA_PASOS)
    for nodo in _nodos(ESQUEMA_PASOS):
        assert set(nodo) <= CLAVES_ESQUEMA, set(nodo) - CLAVES_ESQUEMA

    assert ESQUEMA_PASOS["type"] == "array"
    item = ESQUEMA_PASOS["items"]
    campos = ["segmento_id", "nombre", "descripcion", "responsable", "cita"]
    assert item["type"] == "object"
    assert item["additionalProperties"] is False
    assert item["required"] == campos
    assert {k: v["type"] for k, v in item["properties"].items()} == {
        "segmento_id": "integer",
        **dict.fromkeys(campos[1:], "string"),
    }


def test_la_peticion_lleva_el_esquema_temperatura_0_y_la_semilla():
    peticiones = []
    with cliente_que_responde(json.dumps([propuesta(2)]), peticiones=peticiones) as llm:
        segmentar(ANALISIS, llm, ETIQUETAS, dos_llamadas=False)

    (cuerpo,) = peticiones
    assert cuerpo["format"] == ESQUEMA_PASOS
    assert cuerpo["options"]["temperature"] == 0
    assert cuerpo["options"]["seed"] == SEMILLA


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
    pasos = segmentar_heuristica(ANALISIS)

    # 2: "Primero"; 4: pausa de 4 s; 6: "Después"; 7 ("Ahora") queda a 1 segmento del 6.
    assert segmentos_de_inicio(pasos, ANALISIS) == [2, 4, 6]
    assert [(p.numero, p.t_inicio, p.t_fin) for p in pasos] == [
        (1, 4.5, 12.0),
        (2, 16.0, 24.0),
        (3, 24.5, 31.0),
    ]


def test_heuristica_sin_pausas_solo_usa_marcadores():
    pasos = segmentar_heuristica(ANALISIS, pausa_min_s=float("inf"))
    assert segmentos_de_inicio(pasos, ANALISIS) == [2, 6]


def test_heuristica_sin_candidatos_devuelve_un_solo_paso():
    planos = analisis_de(
        [
            {"id": i, "t_inicio": float(i), "t_fin": i + 0.5, "texto": "Se aprieta el tornillo."}
            for i in (1, 2)
        ]
    )
    (paso,) = segmentar_heuristica(planos)
    assert (paso.numero, paso.t_inicio, paso.t_fin) == (1, 1.0, 2.5)


def test_heuristica_llena_los_campos_de_paso_video():
    primero, segundo, _ = segmentar_heuristica(ANALISIS)

    assert primero.nombre == "Primero apagamos la máquina."
    assert primero.descripcion == "Primero apagamos la máquina. Se pone el candado en el gabinete."
    assert primero.cita == "Primero apagamos la máquina."
    assert segundo.cita == "La guarda tiene cuatro perillas."
    for p in (primero, segundo):
        assert p.responsable == NO_IDENTIFICADO
        assert (p.fuente, p.confianza) == ("audio", "baja")


def test_heuristica_no_sube_la_confianza_aunque_la_cita_este_en_el_paso(analisis):
    pasos = segmentar_heuristica(analisis)
    rangos = segmentos_de_inicio(pasos, analisis)
    ultimo_id = analisis.transcripcion[-1].id
    fines = [i - 1 for i in rangos[1:]] + [ultimo_id]  # ids consecutivos en el fixture

    for p, inicio, fin in zip(pasos, rangos, fines, strict=True):
        assert verificar_cita(p.cita, analisis, (inicio, fin)) == ("alta", "audio")
        assert (p.fuente, p.confianza) == ("audio", "baja")


def test_heuristica_recorta_nombre_cita_y_descripcion():
    palabras = [f"palabra{i:02d}" for i in range(60)]  # 60 palabras de 9 caracteres
    largo = analisis_de([{"id": 1, "t_inicio": 0.0, "t_fin": 30.0, "texto": " ".join(palabras)}])
    (paso,) = segmentar_heuristica(largo)

    assert paso.nombre == " ".join(palabras[:8]) + "…"
    assert paso.cita == " ".join(palabras[:15])
    assert paso.descripcion.endswith("…")
    assert len(paso.descripcion) <= 301
    recortada = paso.descripcion.removesuffix("…").split()
    assert recortada == palabras[: len(recortada)]  # corta en palabra completa
    assert len(recortada) == 30  # 30 palabras con espacios = 299 caracteres; 31 = 309


def test_transcripcion_vacia_no_llama_al_llm():
    peticiones = []
    with cliente_en_secuencia([VALIDA], peticiones) as llm:
        r = segmentar(analisis_de([]), llm)

    assert (r.metodo, r.motivo_respaldo, r.pasos, r.intentos) == (
        "heuristica",
        "transcripción vacía",
        [],
        0,
    )
    assert peticiones == []


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


@pytest.mark.parametrize("archivo", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_cargar_transcripcion_prueba_sin_modificar_el_archivo(archivo):
    antes = archivo.read_bytes()
    a = cargar_transcripcion_prueba(archivo)
    fx = json.loads(antes.decode("utf-8"))

    assert archivo.read_bytes() == antes
    assert isinstance(a, Analisis)
    assert [s.model_dump(exclude={"palabras"}) for s in a.transcripcion] == fx["segmentos"]
    assert a.duracion_s == fx["segmentos"][-1]["t_fin"]
    assert (a.idioma.codigo, a.fotogramas) == ("es", [])
    assert set(fx["inicios_paso"]) <= {s.id for s in a.transcripcion}


@pytest.mark.parametrize("archivo", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_las_transcripciones_de_prueba_corren_por_segmentar(archivo):
    a = cargar_transcripcion_prueba(archivo)
    r = segmentar(a, None)

    assert r.metodo == "heuristica" and r.pasos
    assert r.pasos[-1].t_fin == a.transcripcion[-1].t_fin
    assert segmentos_de_inicio(r.pasos, a)[0] >= a.transcripcion[0].id


# ── Extracción de pasos sobre analisis_ejemplo.json (RF-13, de punta a punta) ───────────────

# Respuesta simulada del LLM sobre el fixture: los 6 inicios reales (tests/fixtures/README.md)
# con citas copiadas de sus segmentos y el rol que la narradora dice en la introducción.
PROPUESTA_EJEMPLO = [
    (4, "Ponerse guantes y lentes", "me pongo los guantes de nitrilo y los lentes de seguridad"),
    (6, "Cerrar la llave de paso", "cierro la llave de paso que está antes del filtro"),
    (9, "Liberar la presión", "libero la presión con el botón rojo"),
    (12, "Retirar la carcasa y el cartucho", "giro el vaso hacia la izquierda para aflojarlo"),
    (17, "Colocar el cartucho nuevo", "tomo el cartucho nuevo y le quito el plástico"),
    (21, "Abrir la llave y revisar fugas", "abro la llave de paso despacio"),
]
RESPUESTA_EJEMPLO = json.dumps(
    [
        propuesta(sid, nombre, cita=cita, responsable="Técnica de mantenimiento")
        for sid, nombre, cita in PROPUESTA_EJEMPLO
    ],
    ensure_ascii=False,
)
JSON_ROTO = '[{"segmento_id": 4, "nombre": "Ponerse'

# SOP de prueba INVENTADO, solo para comprobar que nunca llega al LLM (sección 5.3).
SOP_PRUEBA = [
    "SOP-FA-07 · Cambio del cartucho del filtro de agua",
    "Colocarse guantes de nitrilo y lentes de seguridad antes de iniciar",
    "Cerrar la válvula de aislamiento aguas arriba del filtro",
    "Despresurizar la carcasa mediante la válvula de purga superior",
    "Retirar el vaso y desechar el cartucho saturado",
    "Instalar el cartucho nuevo y apretar 1/4 de vuelta",
    "Restablecer el flujo y verificar ausencia de fugas durante 2:00 min",
]


def _extraer(analisis, respuestas):
    peticiones = []
    with cliente_en_secuencia(respuestas, peticiones) as llm:
        return segmentar(analisis, llm, dos_llamadas=False), peticiones


def test_salida_valida_da_paso_video_con_tiempos_del_indice_y_confianza_alta(analisis):
    r, peticiones = _extraer(analisis, [RESPUESTA_EJEMPLO])

    assert (r.metodo, r.intentos, len(peticiones)) == ("llm", 1, 1)
    assert segmentos_de_inicio(r.pasos, analisis) == [4, 6, 9, 12, 17, 21]
    # Inicio del segmento elegido y fin del último antes del siguiente paso (README).
    assert [(p.numero, p.t_inicio, p.t_fin) for p in r.pasos] == [
        (1, 20.45, 31.64),
        (2, 33.44, 53.91),
        (3, 55.51, 73.56),
        (4, 74.76, 103.4),
        (5, 104.9, 125.62),
        (6, 127.32, 156.29),
    ]
    assert all((p.confianza, p.fuente) == ("alta", "audio") for p in r.pasos)
    assert all(p.responsable == "Técnica de mantenimiento" for p in r.pasos)
    assert [p.cita for p in r.pasos] == [cita for _, _, cita in PROPUESTA_EJEMPLO]


def test_cita_inventada_da_confianza_baja_y_fuente_inferido(analisis):
    datos = json.loads(RESPUESTA_EJEMPLO)
    datos[2]["cita"] = "se purga el aire con la válvula de alivio"  # no está en el audio
    r, _ = _extraer(analisis, [json.dumps(datos)])

    assert r.metodo == "llm"
    assert (r.pasos[2].confianza, r.pasos[2].fuente) == ("baja", "inferido")
    assert all(p.confianza == "alta" for i, p in enumerate(r.pasos) if i != 2)


def test_segmento_inexistente_se_reintenta_y_se_corrige(analisis):
    datos = json.loads(RESPUESTA_EJEMPLO)
    datos[3]["segmento_id"] = 99
    r, peticiones = _extraer(analisis, [json.dumps(datos), RESPUESTA_EJEMPLO])

    assert (r.metodo, r.intentos) == ("llm", 2)
    assert "el segmento 99 no existe" in peticiones[1]["messages"][-1]["content"]


def test_segmento_inexistente_que_persiste_cae_a_la_heuristica(analisis):
    datos = json.loads(RESPUESTA_EJEMPLO)
    datos[3]["segmento_id"] = 99
    r, peticiones = _extraer(analisis, [json.dumps(datos)] * 3)

    assert (r.metodo, r.intentos, len(peticiones)) == ("heuristica", 3, 3)
    assert "el segmento 99 no existe (tras 3 intentos)" in r.motivo_respaldo
    assert r.pasos == segmentar_heuristica(analisis)


def test_json_invalido_se_reintenta_con_el_error_en_el_prompt(analisis):
    r, peticiones = _extraer(analisis, [JSON_ROTO, RESPUESTA_EJEMPLO])

    assert (r.metodo, r.intentos, len(r.pasos)) == ("llm", 2, 6)
    segunda = peticiones[1]["messages"]
    # El cliente no expone el texto roto: se agrega solo la corrección.
    assert [m["role"] for m in segunda] == ["system", "user", "user"]
    assert segunda[:2] == peticiones[0]["messages"]
    assert "no devolvió JSON válido" in segunda[-1]["content"]
    assert f"{len(JSON_ROTO)} caracteres" in segunda[-1]["content"]


def test_json_invalido_tres_veces_cae_a_la_heuristica(analisis):
    r, peticiones = _extraer(analisis, [JSON_ROTO, json.dumps([propuesta(99)]), JSON_ROTO])

    assert (r.metodo, r.intentos, len(peticiones)) == ("heuristica", 3, 3)
    assert "no devolvió JSON válido" in r.motivo_respaldo
    assert "tras 3 intentos" in r.motivo_respaldo
    # Tercera llamada: corrección del JSON roto; respuesta y corrección del segmento 99.
    assert [m["role"] for m in peticiones[2]["messages"]] == [
        "system",
        "user",
        "user",
        "assistant",
        "user",
    ]


def test_la_extraccion_nunca_recibe_el_sop_ni_tiempos(analisis):
    datos = json.loads(RESPUESTA_EJEMPLO)
    datos[0]["segmento_id"] = 99
    _, peticiones = _extraer(analisis, [JSON_ROTO, json.dumps(datos), RESPUESTA_EJEMPLO])

    # Ninguna función de la extracción admite un SOP.
    for funcion in (segmentar, segmentar_con_llm, construir_mensajes, construir_pasos):
        assert not any("sop" in p.lower() for p in inspect.signature(funcion).parameters)

    assert len(peticiones) == 3  # original, tras JSON roto y tras segmento inexistente
    for peticion in peticiones:
        enviado = " ".join(m["content"] for m in peticion["messages"])
        comparable = _texto_comparable(enviado)
        for linea in SOP_PRUEBA:
            assert _texto_comparable(linea) not in comparable
        assert "SOP" not in enviado
        assert not re.search(r"\d+[.:]\d+", enviado), "un número con formato de tiempo"
        assert "t_inicio" not in json.dumps(peticion["format"])


def test_el_resultado_valida_contra_paso_video_y_se_serializa(analisis):
    r, _ = _extraer(analisis, [RESPUESTA_EJEMPLO])
    heuristica = segmentar_heuristica(analisis)

    lista = TypeAdapter(list[PasoVideo])
    for pasos in (r.pasos, heuristica):
        texto = lista.dump_json(pasos).decode()
        assert lista.validate_json(texto) == pasos
        for p, crudo in zip(pasos, json.loads(texto), strict=True):
            assert set(crudo) == set(PasoVideo.model_fields)
            assert PasoVideo.model_validate(crudo) == p


def test_misma_entrada_y_misma_respuesta_dan_el_mismo_resultado(analisis):
    for respuestas in ([RESPUESTA_EJEMPLO], [JSON_ROTO, RESPUESTA_EJEMPLO], [JSON_ROTO] * 3):
        r1, peticiones1 = _extraer(analisis, respuestas)
        r2, peticiones2 = _extraer(analisis, respuestas)

        assert r1 == r2
        assert peticiones1 == peticiones2  # mismos mensajes, esquema, temperatura y semilla


def test_segmentar_con_llm_devuelve_paso_video(analisis):
    with cliente_en_secuencia([RESPUESTA_EJEMPLO], []) as llm:
        pasos = segmentar_con_llm(analisis, llm, dos_llamadas=False)
    assert [p.numero for p in pasos] == [1, 2, 3, 4, 5, 6]


def test_un_rol_que_solo_trae_articulos_no_cuenta_como_mencionado():
    assert rol_mencionado("El", "el operador") is False


# ── Opción A de ADR-010: fronteras y redacción en dos llamadas ──────────────────────────────

FRONTERAS_EJEMPLO = json.dumps(
    [{"segmento_id": sid, "titulo": nombre} for sid, nombre, _ in PROPUESTA_EJEMPLO],
    ensure_ascii=False,
)
TITULOS_EJEMPLO = [nombre for _, nombre, _ in PROPUESTA_EJEMPLO]


def redaccion(numero, cita, *, responsable="Técnica de mantenimiento", **campos) -> dict:
    """Un paso como lo redactaría el LLM en la llamada 2."""
    return {
        "numero": numero,
        "descripcion": "Se hace el paso con cuidado.",
        "responsable": responsable,
        "cita": cita,
        **campos,
    }


def redaccion_ejemplo(**cambios) -> list[dict]:
    """Redacción válida de los 6 pasos; `cambios` reemplaza campos de un paso: {3: {...}}."""
    pasos = [redaccion(n, cita) for n, (_, _, cita) in enumerate(PROPUESTA_EJEMPLO, start=1)]
    for numero, campos in cambios.items():
        pasos[int(numero.removeprefix("p")) - 1].update(campos)
    return pasos


REDACCION_EJEMPLO = json.dumps(redaccion_ejemplo(), ensure_ascii=False)


def _extraer_a(analisis, respuestas):
    peticiones = []
    with cliente_en_secuencia(respuestas, peticiones) as llm:
        return segmentar(analisis, llm), peticiones


def test_opcion_a_es_el_camino_por_defecto_y_arma_los_pasos(analisis):
    r, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, REDACCION_EJEMPLO])

    assert (r.metodo, r.intentos, r.intentos_redaccion, r.motivo_sin_redaccion) == (
        "llm",
        1,
        1,
        None,
    )
    assert r.pasos_sin_redactar == 0
    assert [p["format"] for p in peticiones] == [ESQUEMA_FRONTERAS, ESQUEMA_REDACCION]
    assert segmentos_de_inicio(r.pasos, analisis) == [4, 6, 9, 12, 17, 21]
    assert [p.nombre for p in r.pasos] == TITULOS_EJEMPLO  # el título de la llamada 1
    assert [(p.t_inicio, p.t_fin) for p in r.pasos] == [
        (20.45, 31.64),
        (33.44, 53.91),
        (55.51, 73.56),
        (74.76, 103.4),
        (104.9, 125.62),
        (127.32, 156.29),
    ]
    assert [p.cita for p in r.pasos] == [cita for _, _, cita in PROPUESTA_EJEMPLO]
    assert all((p.confianza, p.fuente) == ("alta", "audio") for p in r.pasos)
    assert all(p.descripcion == "Se hace el paso con cuidado." for p in r.pasos)


def test_el_prompt_de_fronteras_es_el_v1_de_la_fase_4():
    numerados = "\n".join(f"[{s['id']}] {s['texto']}" for s in SEGMENTOS)
    # Copia literal del prompt v1 medido en la Fase 4 (F1 0.74), antes de RF-13.
    v1_fase4 = (
        "Etiquetas del video: maquina=cortadora; area=conversión; proceso=cambio de cuchilla.\n\n"
        f"Segmentos de la transcripción, numerados y en orden:\n{numerados}\n\n"
        "Identifica en qué segmento empieza cada paso del procedimiento. Un paso suele "
        "abarcar varios segmentos: no marques cada segmento como paso, y la introducción o "
        "los comentarios no inician pasos. "
        "Responde SOLO con "
        'una lista JSON de objetos {"segmento_id": número del segmento donde empieza el '
        'paso, "titulo": nombre corto del paso en español}, en orden. Usa solo números de '
        "segmento de la lista; no escribas tiempos."
    )
    sistema, usuario = construir_mensajes_fronteras(ANALISIS, ETIQUETAS)

    assert usuario["content"] == v1_fase4
    assert sistema["content"] == SISTEMA
    con_regla = construir_mensajes_fronteras(ANALISIS, ETIQUETAS, regla_aclaraciones=True)
    assert "aclaraciones, advertencias" in con_regla[1]["content"]


def test_el_prompt_de_redaccion_trae_los_pasos_fijos_sin_ejemplos_de_rol(analisis):
    _, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, REDACCION_EJEMPLO])
    usuario = peticiones[1]["messages"][1]["content"]
    texto = {s.id: s.texto for s in analisis.transcripcion}

    assert len(peticiones[1]["messages"]) == 2  # empieza de cero: sin el historial de la 1
    # Sin números de segmento: con [n] el modelo citaba el segmento n en el paso n (ADR-010).
    assert not re.search(r"\[\d+\]", usuario)
    introduccion, *bloques = usuario.split("\n\nPaso ")
    assert texto[1] in introduccion and texto[3] in introduccion and texto[4] not in introduccion
    assert bloques[0].startswith(f"1 · Ponerse guantes y lentes\n{texto[4]}\n{texto[5]}")
    assert bloques[5].startswith(f"6 · Abrir la llave y revisar fugas\n{texto[21]}")
    assert texto[25] in bloques[5] and texto[21] not in bloques[4]


def test_el_prompt_de_redaccion_pide_el_puesto_y_nunca_un_nombre(analisis):
    _, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, REDACCION_EJEMPLO])
    usuario = peticiones[1]["messages"][1]["content"]

    assert "el puesto de quien hace el paso, nunca el nombre de una persona" in usuario
    assert "describe los pasos en primera persona, ese puesto es el responsable" in usuario
    assert f'no se dice ningún puesto, "{NO_IDENTIFICADO}"' in usuario
    assert "de 4 a 15 palabras" in usuario
    assert "del texto de ese mismo paso" in usuario
    assert "la cita se deja en el idioma original" in usuario
    for ejemplo in ("Operador", "Supervisor", "por ejemplo"):
        assert ejemplo not in usuario


def test_el_prompt_de_redaccion_sin_introduccion():
    fronteras = [PropuestaFrontera(segmento_id=1, titulo="Todo")]
    usuario = construir_mensajes_redaccion(ANALISIS, fronteras)[1]["content"]
    assert "Introducción (antes del primer paso):\n(sin introducción)" in usuario


def test_redaccion_reintenta_solo_los_pasos_que_fallaron(analisis):
    corta = json.dumps(redaccion_ejemplo(p3={"cita": "libero la presión"}), ensure_ascii=False)
    solo_3 = json.dumps([redaccion(3, "libero la presión con el botón rojo")], ensure_ascii=False)
    r, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, corta, solo_3])

    assert (r.metodo, r.intentos, r.intentos_redaccion, len(peticiones)) == ("llm", 1, 2, 3)
    assert (r.pasos_sin_redactar, r.motivo_sin_redaccion) == (0, None)
    assert r.pasos[2].cita == "libero la presión con el botón rojo"
    assert all(p.confianza == "alta" for p in r.pasos)

    # El reintento repite el prompt y pide solo el paso 3, sin reenviar la respuesta anterior.
    reintento = peticiones[2]["messages"]
    assert [m["role"] for m in reintento] == ["system", "user", "user"]
    assert reintento[:2] == peticiones[1]["messages"]
    correccion = reintento[-1]["content"]
    assert (
        "paso 3: cita (value_error): la cita tiene 3 palabras y debe tener de 4 a 15" in correccion
    )
    assert "(numero 3)" in correccion
    assert RECORDATORIO_REDACCION in correccion
    assert "libero la presión" not in correccion  # el motivo no copia la cita
    for n in (1, 2, 4, 5, 6):
        assert f"paso {n}:" not in correccion


ESPERADOS = [1, 2, 3, 4, 5, 6]


def test_validar_redaccion_acepta_los_pasos_validos_aunque_otros_fallen():
    datos = redaccion_ejemplo(p2={"cita": "me pongo"}, p4={"t_inicio": 74.76})[:5]
    validos, fallos = _validar_redaccion(datos, ESPERADOS)

    assert sorted(validos) == [1, 3, 5]
    assert fallos[2].startswith("cita (value_error): la cita tiene 2 palabras")
    assert fallos[4] == "t_inicio (extra_forbidden)"
    assert fallos[6] == "falta en la respuesta"


def test_validar_redaccion_no_depende_del_orden_e_ignora_lo_que_no_se_pidio():
    datos = list(reversed(redaccion_ejemplo()))
    datos.append(redaccion(7, "un paso que no se pidió"))
    datos.append(redaccion(2, "me pongo"))  # repetido e inválido: vale el primero
    validos, fallos = _validar_redaccion(datos, ESPERADOS)

    assert sorted(validos) == ESPERADOS and fallos == {}


@pytest.mark.parametrize(
    "datos",
    [[], {"pasos": []}, "texto", [["1"]], [redaccion("1", "me pongo los guantes")]],
    ids=["vacia", "objeto", "texto", "no_objeto", "numero_texto"],
)
def test_validar_redaccion_sin_pasos_atribuibles(datos):
    validos, fallos = _validar_redaccion(datos, [1])
    assert validos == {}
    assert fallos[1] in (
        "la respuesta no es una lista con al menos un paso",
        "falta en la respuesta",
    )


@pytest.mark.parametrize(
    ("cita", "esperada"),
    [
        ("me pongo los guantes", "me pongo los guantes"),  # 4
        (" ".join(["palabra"] * 15), " ".join(["palabra"] * 15)),
        ("¿me pongo, los guantes?", "¿me pongo, los guantes?"),  # la puntuación no cuenta
        (" ".join(f"p{i}" for i in range(16)), " ".join(f"p{i}" for i in range(15))),
        ("uno — dos — tres — cuatro — cinco", "uno — dos — tres — cuatro — cinco"),
    ],
    ids=["4", "15", "puntuacion", "16_se_recorta", "guiones"],
)
def test_la_cita_redactada_de_4_a_15_palabras_y_las_largas_se_recortan(cita, esperada):
    assert RedaccionPaso.model_validate(redaccion(1, cita)).cita == esperada


@pytest.mark.parametrize("cita", ["me pongo guantes", "… ¿? …", ""])
def test_la_cita_de_menos_de_4_palabras_es_invalida(cita):
    _, fallos = _validar_redaccion([redaccion(1, cita)], [1])
    assert "la cita tiene" in fallos[1] and "debe tener de 4 a 15" in fallos[1]


def test_recortar_cita_cuenta_como_la_verificacion():
    assert recortar_cita("a, b; c. d", 2) == "a, b;"
    assert recortar_cita("¿uno? — dos tres", 2) == "¿uno? — dos"  # "—" no cuenta como palabra
    assert recortar_cita("rojo/verde azul", 2) == "rojo/verde"  # "rojo/verde" son dos
    assert recortar_cita("rojo/verde azul", 1) == ""
    assert recortar_cita("me pongo los guantes", 15) == "me pongo los guantes"  # sin recorte


def test_una_cita_literal_larga_se_recorta_y_sigue_siendo_alta(analisis):
    segmento_6 = analisis.transcripcion[5].texto  # 18 palabras, paso 2
    datos = redaccion_ejemplo(p2={"cita": segmento_6})
    r, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, json.dumps(datos, ensure_ascii=False)])

    assert len(peticiones) == 2  # aceptada al primer intento
    assert len(_texto_comparable(segmento_6).split()) == 18
    assert r.pasos[1].cita == recortar_cita(segmento_6)
    assert len(_texto_comparable(r.pasos[1].cita).split()) == 15
    assert (r.pasos[1].confianza, r.pasos[1].fuente) == ("alta", "audio")


def test_titulo_vacio_invalida_las_fronteras():
    with pytest.raises(PropuestaInvalida, match=r"titulo \(value_error\): título vacío"):
        _validar_propuestas([{"segmento_id": 2, "titulo": " "}], {2}, PropuestaFrontera)


def _sin_redactar(pasos, analisis, numeros=(1, 2, 3, 4, 5, 6)):
    """Comprueba que los pasos `numeros` conservan la frontera sin redactar."""
    assert segmentos_de_inicio(pasos, analisis) == [4, 6, 9, 12, 17, 21]
    assert [p.nombre for p in pasos] == TITULOS_EJEMPLO
    for p in pasos:
        if p.numero in numeros:
            assert (p.cita, p.descripcion, p.responsable) == ("", "", NO_IDENTIFICADO)
            assert (p.confianza, p.fuente) == ("baja", "inferido")
        else:
            assert p.cita and p.confianza == "alta"


def test_si_un_paso_nunca_se_redacta_los_demas_si(analisis):
    sin_6 = json.dumps(redaccion_ejemplo()[:5], ensure_ascii=False)
    r, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, sin_6, JSON_ROTO, sin_6])

    assert (r.metodo, r.intentos, r.intentos_redaccion, len(peticiones)) == ("llm", 1, 3, 4)
    assert r.motivo_respaldo is None  # no cae a la heurística
    assert r.pasos_sin_redactar == 1
    assert r.motivo_sin_redaccion == (
        "pasos sin redactar: 6 tras 3 intentos (paso 6: falta en la respuesta)"
    )
    _sin_redactar(r.pasos, analisis, numeros=(6,))
    # Los reintentos no acumulan historial: siempre prompt + una corrección.
    assert [len(p["messages"]) for p in peticiones[1:]] == [2, 3, 3]
    assert "paso 6: El modelo no devolvió JSON válido" in peticiones[3]["messages"][-1]["content"]


def test_si_toda_la_redaccion_falla_se_conservan_todas_las_fronteras(analisis):
    r, _ = _extraer_a(analisis, [FRONTERAS_EJEMPLO, JSON_ROTO, JSON_ROTO, JSON_ROTO])

    assert (r.metodo, r.intentos_redaccion, r.pasos_sin_redactar) == ("llm", 3, 6)
    assert r.motivo_sin_redaccion.startswith("pasos sin redactar: 1, 2, 3, 4, 5, 6 tras 3 intentos")
    _sin_redactar(r.pasos, analisis)


def test_si_ollama_se_cae_a_media_redaccion_se_conserva_lo_redactado(analisis):
    corta = json.dumps(redaccion_ejemplo(p3={"cita": "libero la presión"}), ensure_ascii=False)
    r, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, corta, 500, REDACCION_EJEMPLO])

    assert (r.metodo, r.intentos_redaccion, r.pasos_sin_redactar, len(peticiones)) == (
        "llm",
        2,
        1,
        3,
    )
    assert "LLMNoDisponible" in r.motivo_sin_redaccion
    assert "pasos sin redactar: 3" in r.motivo_sin_redaccion
    _sin_redactar(r.pasos, analisis, numeros=(3,))


def test_si_ollama_se_cae_en_la_redaccion_se_conservan_las_fronteras(analisis):
    r, peticiones = _extraer_a(analisis, [FRONTERAS_EJEMPLO, 500, REDACCION_EJEMPLO])

    assert (r.metodo, r.intentos, r.intentos_redaccion, len(peticiones)) == ("llm", 1, 1, 2)
    assert "LLMNoDisponible" in r.motivo_sin_redaccion
    assert r.pasos_sin_redactar == 6
    _sin_redactar(r.pasos, analisis)


def test_si_fallan_las_fronteras_va_a_la_heuristica_sin_redactar(analisis):
    malas = json.dumps([{"segmento_id": 99, "titulo": "Paso"}])
    r, peticiones = _extraer_a(analisis, [malas] * 3 + [REDACCION_EJEMPLO])

    assert (r.metodo, r.intentos, r.intentos_redaccion, len(peticiones)) == (
        "heuristica",
        3,
        0,
        3,
    )
    assert "el segmento 99 no existe (tras 3 intentos)" in r.motivo_respaldo
    assert r.pasos == segmentar_heuristica(analisis)


def test_si_ollama_no_responde_a_las_fronteras_va_directo_a_la_heuristica(analisis):
    r, peticiones = _extraer_a(analisis, [500, FRONTERAS_EJEMPLO, REDACCION_EJEMPLO])

    assert (r.metodo, r.intentos, len(peticiones)) == ("heuristica", 1, 1)
    assert "LLMNoDisponible" in r.motivo_respaldo


def test_fronteras_corregidas_y_luego_redaccion(analisis):
    con_99 = json.loads(FRONTERAS_EJEMPLO)
    con_99[2]["segmento_id"] = 99
    r, peticiones = _extraer_a(analisis, [json.dumps(con_99), FRONTERAS_EJEMPLO, REDACCION_EJEMPLO])

    assert (r.metodo, r.intentos, r.intentos_redaccion) == ("llm", 2, 1)
    assert "el segmento 99 no existe" in peticiones[1]["messages"][-1]["content"]
    assert RECORDATORIO_SEGMENTOS in peticiones[1]["messages"][-1]["content"]
    assert len(peticiones[2]["messages"]) == 2  # la redacción no arrastra la corrección


def test_redaccion_con_rol_que_no_se_dice_baja_la_confianza(analisis):
    datos = redaccion_ejemplo(p2={"responsable": "Operador"}, p3={"responsable": "n/a"})
    r, _ = _extraer_a(analisis, [FRONTERAS_EJEMPLO, json.dumps(datos, ensure_ascii=False)])

    assert (r.pasos[1].responsable, r.pasos[1].confianza) == ("Operador", "media")
    assert (r.pasos[2].responsable, r.pasos[2].confianza) == (NO_IDENTIFICADO, "alta")


def test_cita_redactada_de_otro_paso_queda_media(analisis):
    datos = redaccion_ejemplo(p1={"cita": "abro la llave de paso despacio"})
    r, _ = _extraer_a(analisis, [FRONTERAS_EJEMPLO, json.dumps(datos, ensure_ascii=False)])
    assert (r.pasos[0].confianza, r.pasos[0].fuente) == ("media", "audio")


def test_opcion_a_nunca_envia_el_sop_ni_tiempos(analisis):
    con_99 = json.loads(FRONTERAS_EJEMPLO)
    con_99[0]["segmento_id"] = 99
    corta = json.dumps(redaccion_ejemplo(p1={"cita": "me pongo"}), ensure_ascii=False)
    _, peticiones = _extraer_a(
        analisis, [JSON_ROTO, json.dumps(con_99), FRONTERAS_EJEMPLO, corta, REDACCION_EJEMPLO]
    )

    assert len(peticiones) == 5
    for peticion in peticiones:
        enviado = " ".join(m["content"] for m in peticion["messages"])
        comparable = _texto_comparable(enviado)
        for linea in SOP_PRUEBA:
            assert _texto_comparable(linea) not in comparable
        assert "SOP" not in enviado
        assert not re.search(r"\d+[.:]\d+", enviado), "un número con formato de tiempo"
        assert "t_inicio" not in json.dumps(peticion["format"])


def test_opcion_a_es_determinista_y_se_serializa(analisis):
    lista = TypeAdapter(list[PasoVideo])
    for respuestas in (
        [FRONTERAS_EJEMPLO, REDACCION_EJEMPLO],
        [FRONTERAS_EJEMPLO, JSON_ROTO, REDACCION_EJEMPLO],
        [FRONTERAS_EJEMPLO, 500],
    ):
        r1, peticiones1 = _extraer_a(analisis, respuestas)
        r2, peticiones2 = _extraer_a(analisis, respuestas)

        assert r1 == r2 and peticiones1 == peticiones2
        assert lista.validate_json(lista.dump_json(r1.pasos)) == r1.pasos


def test_segmentar_con_llm_en_dos_llamadas(analisis):
    with cliente_en_secuencia([FRONTERAS_EJEMPLO, REDACCION_EJEMPLO], []) as llm:
        pasos = segmentar_con_llm(analisis, llm)
    assert [p.nombre for p in pasos] == TITULOS_EJEMPLO
