"""Segmentación en pasos con LLM simulado (httpx.MockTransport): no requiere Ollama ni GPU."""

import json
import logging
import re
from pathlib import Path

import httpx
import pytest

from sopvid.contrato import Analisis, PasoVideo
from sopvid.lenguaje.llm import SEMILLA, ClienteLLM
from sopvid.percepcion.segmentacion import (
    ESQUEMA_PASOS,
    NO_IDENTIFICADO,
    PropuestaInvalida,
    _construir_con_rangos,
    construir_mensajes,
    construir_pasos,
    empieza_con_marcador,
    f1_fronteras,
    normalizar_responsable,
    rol_mencionado,
    segmentar,
    segmentar_con_llm,
    segmentar_heuristica,
    validar_propuesta,
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
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "llm"
    assert r.motivo_respaldo is None
    assert [(p.segmento_id, p.t_inicio, p.nombre) for p in r.pasos] == [
        (2, 4.5, "Apagar y bloquear"),
        (4, 16.0, "Retirar la guarda"),
        (6, 24.5, "Montar la cuchilla"),
    ]
    primero = r.pasos[0]
    assert primero.descripcion == "Se apaga la máquina y se bloquea el gabinete con candado."
    assert primero.responsable == "Operador"
    assert primero.cita == "Primero apagamos la máquina."
    assert r.pasos[1].responsable == NO_IDENTIFICADO  # vacío: nadie lo dice en el audio


def test_un_tiempo_escrito_por_el_llm_invalida_la_propuesta():
    respuesta = json.dumps([propuesta(2, t_inicio=999), propuesta(4)])
    with cliente_que_responde(respuesta) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

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
        validar_propuesta(datos, SEGMENTOS)


def test_el_motivo_de_rechazo_no_copia_texto_de_la_transcripcion():
    cita = "Se pone el candado en el gabinete."
    with pytest.raises(PropuestaInvalida) as exc:
        validar_propuesta([propuesta(2, nombre=cita, extra=cita, cita=1)], SEGMENTOS)
    assert "candado" not in str(exc.value)


def test_propuesta_invalida_cae_a_la_heuristica_y_registra_el_camino(caplog):
    respuesta = json.dumps([propuesta(2), propuesta(99)])
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
    assert r.intentos == 1  # el cliente reintenta la red una vez por dentro; aquí no se repite


def test_json_roto_cae_a_la_heuristica_sin_reintentos():
    peticiones = []
    with cliente_que_responde('[{"segmento_id": 2, "tit', peticiones=peticiones) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "heuristica"
    assert "LLMRespuestaInvalida" in r.motivo_respaldo
    assert len(peticiones) == r.intentos == 1


def test_sin_cliente_usa_la_heuristica():
    r = segmentar(SEGMENTOS, ETIQUETAS, None)
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
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert (r.metodo, r.intentos, len(peticiones)) == ("llm", 1, 1)
    assert [p.segmento_id for p in r.pasos] == [2, 4, 6]


def test_invalida_y_luego_valida_reenvia_la_respuesta_y_el_error():
    peticiones = []
    with cliente_en_secuencia([ID_INEXISTENTE, VALIDA], peticiones) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert (r.metodo, r.intentos, r.motivo_respaldo) == ("llm", 2, None)
    assert [p.segmento_id for p in r.pasos] == [2, 4, 6]

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
        segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert "t_inicio (extra_forbidden)" in peticiones[1]["messages"][-1]["content"]


def test_tres_invalidas_caen_a_la_heuristica_con_el_ultimo_motivo(caplog):
    peticiones = []
    with (
        caplog.at_level(logging.WARNING),
        cliente_en_secuencia([ID_INEXISTENTE, CON_TIEMPO, DUPLICADA], peticiones) as llm,
    ):
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert (r.metodo, r.intentos, len(peticiones)) == ("heuristica", 3, 3)
    assert r.pasos == segmentar_heuristica(SEGMENTOS)
    assert "inválida" in r.motivo_respaldo
    assert "el segmento 2 está duplicado" in r.motivo_respaldo  # el último, no el primero
    assert "tras 3 intentos" in r.motivo_respaldo
    # La tercera llamada lleva las dos respuestas anteriores y sus dos correcciones.
    assert [m["role"] for m in peticiones[2]["messages"]] == ["system", "user"] + [
        "assistant",
        "user",
    ] * 2
    assert caplog.text.count("Propuesta del LLM inválida") == 3


def test_segmentar_con_llm_lanza_el_ultimo_motivo():
    with (
        cliente_en_secuencia([ID_INEXISTENTE] * 3, []) as llm,
        pytest.raises(PropuestaInvalida, match="99 no existe.*tras 3 intentos"),
    ):
        segmentar_con_llm(SEGMENTOS, ETIQUETAS, llm)


def test_llm_no_disponible_va_directo_a_la_heuristica_sin_reintentos():
    peticiones = []
    with cliente_en_secuencia([500, VALIDA], peticiones) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "heuristica"
    assert "LLMNoDisponible" in r.motivo_respaldo
    assert len(peticiones) == r.intentos == 1


def test_llm_que_se_cae_a_media_correccion_no_se_reintenta():
    peticiones = []
    with cliente_en_secuencia([ID_INEXISTENTE, 500, VALIDA], peticiones) as llm:
        r = segmentar(SEGMENTOS, ETIQUETAS, llm)

    assert r.metodo == "heuristica"
    assert "LLMNoDisponible" in r.motivo_respaldo
    assert len(peticiones) == r.intentos == 2


def test_el_prompt_lleva_ids_y_etiquetas_pero_ningun_tiempo():
    mensajes = construir_mensajes(SEGMENTOS, ETIQUETAS)
    usuario = mensajes[1]["content"]

    assert "[4] La guarda tiene cuatro perillas." in usuario
    assert "maquina=cortadora" in usuario
    for s in SEGMENTOS:
        for t in (s["t_inicio"], s["t_fin"]):
            assert not re.search(rf"(?<![\d.]){re.escape(str(t))}(?![\d])", usuario)


def test_el_prompt_pide_los_campos_de_rf13_sin_sop():
    usuario = construir_mensajes(SEGMENTOS, ETIQUETAS)[1]["content"]

    for campo in ("segmento_id", "nombre", "descripcion", "responsable", "cita"):
        assert f"- {campo}:" in usuario
    assert f'"{NO_IDENTIFICADO}"' in usuario
    assert "de 4 a 15 palabras, sin parafrasear" in usuario
    assert "en español aunque la transcripción esté en otro idioma" in usuario
    assert "la cita se deja en el idioma original" in usuario
    assert "no escribas tiempos" in usuario
    assert "SOP" not in usuario  # la extracción nunca ve el SOP (sección 5.3)


def test_por_defecto_prompt_v1_y_la_regla_de_aclaraciones_es_opcional():
    por_defecto = construir_mensajes(SEGMENTOS, ETIQUETAS)[1]["content"]
    v1 = construir_mensajes(SEGMENTOS, ETIQUETAS, regla_aclaraciones=False)[1]["content"]
    v2 = construir_mensajes(SEGMENTOS, ETIQUETAS, regla_aclaraciones=True)[1]["content"]

    assert por_defecto == v1  # v2 se probó en la Fase 4 y se descartó (ADR-010)
    assert "aclaraciones, advertencias" not in v1
    assert "aclaraciones, advertencias" in v2


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
        segmentar(SEGMENTOS, ETIQUETAS, llm)

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
