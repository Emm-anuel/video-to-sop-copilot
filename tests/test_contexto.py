"""Ficha de contexto del video (RF-12): `sopvid.percepcion.contexto`, sin LLM real.

La transcripción, los fotogramas y las respuestas de Gemma son inventados por el equipo
(CLAUDE.md §2.1). Ollama se simula con `OllamaFalso` (en flujo, como `chat_en_flujo`).
"""

import json
from typing import Any

import pytest

from dobles import OllamaFalso
from sopvid.contrato import Analisis, Contexto, Fotograma, Idioma, Segmento
from sopvid.percepcion import contexto as ctx
from sopvid.texto import NO_IDENTIFICADO

TEXTOS = [
    "Buenos días, soy Laura, técnica de mantenimiento de la línea de enjuague.",
    "¿Cada cuánto se cambia el cartucho?",
    "El cartucho se cambia cada tres meses, siempre en el turno de la mañana.",
    "Primero cierro la llave de paso y reviso el manómetro.",
    "Si algo falla, mejor avisen al supervisor de turno.",
    "Al final otra vez cierro la llave de paso.",
]
FOTOGRAMAS = [
    Fotograma(
        t=3.5,
        archivo="f001.jpg",
        descripcion="Una persona con chaleco de supervisor junto a un filtro en la pared.",
        equipos=["Filtro de cartucho", "manometro"],
        personas=1,
        texto_visible=["SUPERVISOR"],
    ),
    Fotograma(t=21.0, archivo="f002.jpg", descripcion="Tubería con una llave de paso azul."),
]


def _analisis(
    textos: list[str] = TEXTOS, idioma: str = "es", fotogramas: list[Fotograma] | None = None
) -> Analisis:
    segmentos = [
        Segmento(id=i, t_inicio=5.0 * i, t_fin=5.0 * i + 4.0, texto=t) for i, t in enumerate(textos)
    ]
    return Analisis(
        video_id=7,
        duracion_s=5.0 * len(textos),
        idioma=Idioma(codigo=idioma, confianza=0.99),
        transcripcion=segmentos,
        fotogramas=fotogramas or [],
    )


def _ficha(**cambios: Any) -> dict[str, Any]:
    """Respuesta de Gemma con todo vacío salvo `cambios`."""
    vacio = {"cita": "", "valor": None}
    base = {
        "actividad": vacio,
        "tema": vacio,
        "lugar": vacio,
        "horario_mencionado": vacio,
        "proposito": vacio,
        "resumen": None,
        "personas": [],
        "equipos": [],
    }
    return base | cambios


def _generar(
    respuestas: list[Any], analisis: Analisis | None = None, **kwargs: Any
) -> tuple[ctx.ResultadoContexto, OllamaFalso]:
    ollama = OllamaFalso([])
    ollama.respuestas_contexto = respuestas
    with ollama.cliente() as cliente:
        plazos = {"primer_token_s": 5, "inactividad_s": 5, "tope_s": 30} | kwargs
        resultado = ctx.generar_contexto(analisis or _analisis(), cliente, **plazos)
    return resultado, ollama


# ── Citas: el código pone fuente, confianza y segundo (regla 4) ─────────────────────────────


def test_cita_que_existe_da_audio_alta_y_el_segundo_de_su_segmento():
    ficha = _ficha(
        actividad={"cita": "les cambio el cartucho", "valor": None},
        lugar={
            "cita": "técnica de mantenimiento de la línea de enjuague",
            "valor": "Línea de enjuague",
        },
        horario_mencionado={
            "cita": "cada tres meses, siempre en el turno de la mañana",
            "valor": "Cada tres meses, en el turno de la mañana",
        },
    )
    r, _ = _generar([ficha])

    assert r.generado and r.motivo is None
    assert r.contexto.lugar.model_dump() == {
        "valor": "Línea de enjuague",
        "confianza": "alta",
        "fuente": "audio",
        "t": 0.0,
        "cita": "",
    }
    assert r.contexto.horario_mencionado.t == 10.0
    assert r.contexto.horario_mencionado.fuente == "audio"
    assert r.contexto.actividad == Contexto().actividad  # sin valor: vacío aunque traiga cita


def test_cita_repetida_toma_el_primer_segmento():
    r, _ = _generar([_ficha(actividad={"cita": "cierro la llave de paso", "valor": "Cerrar"})])

    assert r.contexto.actividad.t == 15.0  # está en el segmento 3 y en el 5


def test_cita_que_no_aparece_queda_inferida_con_confianza_baja_y_sin_segundo():
    ficha = _ficha(
        lugar={"cita": "en la planta norte de la empresa", "valor": "Planta norte"},
        tema={"cita": "", "valor": "Mantenimiento"},
    )
    r, _ = _generar([ficha])

    for dato in (r.contexto.lugar, r.contexto.tema):
        assert (dato.fuente, dato.confianza, dato.t) == ("inferido", "baja", None)
    assert r.contexto.lugar.valor == "Planta norte"  # el valor se conserva
    assert r.citas_no_verificadas == 2


def test_cita_que_cruza_dos_segmentos():
    ficha = _ficha(tema={"cita": "reviso el manómetro. Si algo falla", "valor": "Mantenimiento"})
    r, _ = _generar([ficha])

    assert (r.contexto.tema.fuente, r.contexto.tema.confianza, r.contexto.tema.t) == (
        "audio",
        "alta",
        15.0,
    )


# Largo de la cita (contexto_v2): menos de 2 palabras o que no aparece → inferido; 2 o 3 que
# aparecen → audio con confianza media; de 4 a 25 → alta (una más larga se recorta a 25).
@pytest.mark.parametrize(
    ("cita", "esperado"),
    [
        ("", ("inferido", "baja", None)),
        ("manómetro", ("inferido", "baja", None)),  # 1 palabra, aunque aparece
        ("el manómetro", ("audio", "media", 15.0)),  # 2
        ("línea de enjuague", ("audio", "media", 0.0)),  # 3, el sustantivo solo
        ("la línea de enjuague", ("audio", "alta", 0.0)),  # 4
        ("la planta norte", ("inferido", "baja", None)),  # 3 que no aparecen
        ("supervisor   de\nturno", ("audio", "media", 20.0)),  # espacios y salto de línea
    ],
    ids=["vacia", "una", "dos", "tres", "cuatro", "tres_inventadas", "espacios"],
)
def test_confianza_segun_el_largo_de_la_cita(cita: str, esperado: tuple) -> None:
    r, _ = _generar([_ficha(lugar={"cita": cita, "valor": "Un lugar"})])

    lugar = r.contexto.lugar
    assert (lugar.fuente, lugar.confianza, lugar.t) == esperado


# Un segmento de 30 palabras, para los límites de 25.
LARGO = (
    "Hoy reviso la bomba del cuarto de máquinas del edificio dos porque el tablero marcó una "
    "alarma de presión baja durante el turno de la noche y hay que revisar"
)


@pytest.mark.parametrize(
    ("palabras", "esperado"),
    [(25, (0.0, "alta")), (30, (0.0, "alta"))],  # 30 se recorta a sus primeras 25
)
def test_cita_de_25_o_mas_palabras(palabras: int, esperado: tuple) -> None:
    assert len(LARGO.split()) == 30  # inventado
    cita = " ".join(LARGO.split()[:palabras])
    assert ctx.ubicar_cita(cita, _analisis([LARGO]).transcripcion) == esperado


def test_cita_larga_que_no_es_literal_no_vale():
    cita = " ".join(LARGO.split()[:20]) + " y luego cambio la junta de la tapa"
    assert ctx.ubicar_cita(cita, _analisis([LARGO]).transcripcion) is None


def test_una_persona_con_cita_de_tres_palabras_se_conserva():
    persona = {
        "cita": "supervisor de turno",
        "nombre": "",
        "rol": "Supervisor de turno",
        "participacion": "mencionado",
    }
    r, _ = _generar([_ficha(personas=[persona])])

    [supervisor] = r.contexto.personas
    assert (supervisor.t, supervisor.cita) == (20.0, "supervisor de turno")


def test_el_resumen_va_inferido_con_confianza_media_y_sin_cita():
    r, _ = _generar([_ficha(resumen="Laura cambia el cartucho del filtro de agua.")])

    assert r.contexto.resumen.model_dump() == {
        "valor": "Laura cambia el cartucho del filtro de agua.",
        "confianza": "media",
        "fuente": "inferido",
        "t": None,
        "cita": "",
    }


def test_la_ficha_lleva_el_aviso_si_whisper_no_es_el_de_referencia():
    analisis = _analisis().model_copy(update={"modelo_transcripcion": "small"})
    r, _ = _generar([_ficha()], analisis)
    [aviso] = r.contexto.avisos
    assert aviso.tipo == "transcripcion_no_referencia"

    r, _ = _generar(
        [_ficha()], _analisis().model_copy(update={"modelo_transcripcion": "large-v3-turbo"})
    )
    assert r.contexto.avisos == []


# ── Fotogramas: solo si existen ─────────────────────────────────────────────────────────────


def test_sin_fotogramas_ni_el_prompt_ni_el_esquema_los_mencionan():
    r, ollama = _generar([_ficha()])

    enviado = json.dumps(ollama.mensajes_contexto[0], ensure_ascii=False).lower()
    esquema = json.dumps(ollama.esquemas_contexto[0])
    assert "fotograma" not in enviado and "[f=" not in enviado
    assert '"f"' not in esquema and "fotograma" not in esquema.lower()
    assert ollama.esquemas_contexto[0] == ctx.ESQUEMA_CONTEXTO
    assert "[s=0] Buenos días" in ollama.mensajes_contexto[0][1]["content"]
    assert r.fotogramas == 0


def test_la_entrada_no_lleva_tiempos():
    _, ollama = _generar([_ficha()], _analisis(fotogramas=FOTOGRAMAS))

    usuario = ollama.mensajes_contexto[0][1]["content"]
    for segundo in ("3.5", "21.0", "15.0", "0.0"):
        assert segundo not in usuario


def test_con_fotogramas_entran_numerados_y_el_esquema_acepta_el_numero():
    ficha = _ficha(
        lugar={"cita": "", "valor": "Junto al filtro de la pared", "f": 1},
        tema={"cita": "", "valor": "Mantenimiento", "f": 9},  # no existe
        personas=[
            {"cita": "", "nombre": "", "rol": "Supervisor", "participacion": "participa", "f": 1}
        ],
        equipos=["Manómetro", "Llave de paso"],
    )
    r, ollama = _generar([ficha], _analisis(fotogramas=FOTOGRAMAS))

    sistema, usuario = (m["content"] for m in ollama.mensajes_contexto[0])
    assert "[f=1] Una persona con chaleco" in usuario and "[f=2] Tubería" in usuario
    assert "equipos: Filtro de cartucho; manometro" in usuario
    assert "fotogramas" in sistema.lower()
    assert ollama.esquemas_contexto[0] == ctx.ESQUEMA_CONTEXTO_FOTOGRAMAS
    assert r.fotogramas == 2

    assert r.contexto.lugar.model_dump() == {
        "valor": "Junto al filtro de la pared",
        "confianza": "media",
        "fuente": "visual",
        "t": 3.5,
        "cita": "",
    }
    assert (r.contexto.tema.fuente, r.contexto.tema.t) == ("inferido", None)
    [persona] = r.contexto.personas
    assert (persona.nombre, persona.rol, persona.t, persona.cita) == (
        NO_IDENTIFICADO,
        "Supervisor",
        3.5,
        "",
    )
    # Los de Gemma y los de los fotogramas, sin repetir ("manometro" = "Manómetro").
    assert [e.nombre for e in r.contexto.equipos] == [
        "Manómetro",
        "Llave de paso",
        "Filtro de cartucho",
    ]


def test_con_fotogramas_la_cita_verificada_gana_al_fotograma():
    ficha = _ficha(lugar={"cita": "la línea de enjuague", "valor": "Línea de enjuague", "f": 2})
    r, _ = _generar([ficha], _analisis(fotogramas=FOTOGRAMAS))

    assert (r.contexto.lugar.fuente, r.contexto.lugar.t) == ("audio", 0.0)


# ── Personas ────────────────────────────────────────────────────────────────────────────────


def test_personas_participa_mencionado_y_rol_sin_nombre():
    personas = [
        {
            "cita": "soy Laura, técnica de mantenimiento",
            "nombre": "Laura",
            "rol": "Técnica de mantenimiento",
            "participacion": "participa",
        },
        {
            "cita": "mejor avisen al supervisor de turno",
            "nombre": "",
            "rol": "Supervisor de turno",
            "participacion": "mencionado",
        },
    ]
    r, _ = _generar([_ficha(personas=personas)])

    laura, supervisor = r.contexto.personas
    assert (laura.nombre, laura.participacion, laura.t) == ("Laura", "participa", 0.0)
    assert laura.cita == "soy Laura, técnica de mantenimiento"
    assert (supervisor.nombre, supervisor.rol) == (NO_IDENTIFICADO, "Supervisor de turno")
    assert (supervisor.participacion, supervisor.t) == ("mencionado", 20.0)
    assert r.personas_descartadas == 0


def test_personas_sin_evidencia_o_sin_identidad_se_descartan():
    personas = [
        {"cita": "soy Pedro, el jefe de planta", "nombre": "Pedro", "rol": None,
         "participacion": "mencionado"},  # cita inventada
        {"cita": "Buenos días, soy Laura, técnica", "nombre": "N/A", "rol": "null",
         "participacion": "participa"},  # sin nombre ni rol
    ]  # fmt: skip
    r, _ = _generar([_ficha(personas=personas)])

    assert r.contexto.personas == []
    assert r.personas_descartadas == 2


def test_la_misma_persona_dos_veces_se_junta():
    personas = [
        {"cita": "Buenos días, soy Laura", "nombre": "Laura", "rol": None,
         "participacion": "mencionado"},
        {"cita": "soy Laura, técnica de mantenimiento", "nombre": "laura",
         "rol": "Técnica de mantenimiento", "participacion": "participa"},
    ]  # fmt: skip
    r, _ = _generar([_ficha(personas=personas)])

    [laura] = r.contexto.personas
    assert (laura.nombre, laura.rol, laura.participacion) == (
        "Laura",
        "Técnica de mantenimiento",
        "participa",
    )


# ── Idioma y vacíos ─────────────────────────────────────────────────────────────────────────


def test_video_en_ingles_valores_en_espanol_y_citas_en_ingles_verificadas():
    textos = [
        "Hi, I am Tom, the maintenance technician on the rinse line.",
        "Today I will show you how to replace the water filter cartridge.",
    ]
    ficha = _ficha(
        actividad={
            "cita": "how to replace the water filter cartridge",
            "valor": "Cambio del cartucho del filtro de agua",
        },
        personas=[{
            "cita": "I am Tom, the maintenance technician",
            "nombre": "Tom",
            "rol": "Técnico de mantenimiento",
            "participacion": "participa",
        }],
    )  # fmt: skip
    r, ollama = _generar([ficha], _analisis(textos, idioma="en"))

    assert "Idioma de la transcripción: en" in ollama.mensajes_contexto[0][1]["content"]
    assert r.contexto.actividad.valor == "Cambio del cartucho del filtro de agua"
    assert (r.contexto.actividad.fuente, r.contexto.actividad.t) == ("audio", 5.0)
    [tom] = r.contexto.personas
    assert (tom.cita, tom.t, tom.rol) == (
        "I am Tom, the maintenance technician",
        0.0,
        "Técnico de mantenimiento",
    )


def test_null_y_na_en_valores_y_listas_quedan_vacios():
    ficha = _ficha(
        lugar={"cita": "", "valor": "N/A"},
        horario_mencionado={"cita": "", "valor": "No se menciona"},
        proposito={"cita": "null", "valor": "null"},
        resumen="null",
        equipos=["null", "N/A", "", "Manómetro", "manómetro"],
    )
    r, _ = _generar([ficha])

    vacio = Contexto()
    for campo in ("lugar", "horario_mencionado", "proposito", "resumen"):
        assert getattr(r.contexto, campo) == getattr(vacio, campo), campo
    assert [e.nombre for e in r.contexto.equipos] == ["Manómetro"]
    assert r.citas_no_verificadas == 0


# ── Fallas: ficha vacía con su motivo, nunca una excepción ──────────────────────────────────


def test_ollama_mudo_deja_la_ficha_vacia_sin_reintentar():
    ollama = OllamaFalso([])
    ollama.contexto_caido = True
    with ollama.cliente() as cliente:
        r = ctx.generar_contexto(_analisis(), cliente, primer_token_s=5, inactividad_s=5)

    assert (r.generado, r.motivo, r.intentos) == (False, "llm_no_disponible", 1)
    assert r.contexto == Contexto()
    assert ollama.eventos == ["chat:contexto"]


def test_json_invalido_tres_veces_deja_la_ficha_vacia():
    r, ollama = _generar(["no es json"])

    assert (r.generado, r.motivo, r.intentos) == (False, "respuesta_invalida", 3)
    assert ollama.eventos == ["chat:contexto"] * 3
    correccion = ollama.mensajes_contexto[1][-1]["content"]
    assert "no devolviste un JSON válido" in correccion
    assert len(ollama.mensajes_contexto[1]) == 3  # sistema, usuario y la corrección


def test_una_respuesta_fuera_del_esquema_se_reintenta():
    sin_equipos = {k: v for k, v in _ficha().items() if k != "equipos"}
    r, ollama = _generar([sin_equipos, _ficha(tema={"cita": "", "valor": "Mantenimiento"})])

    assert r.generado and r.intentos == 2
    assert "equipos: missing" in ollama.mensajes_contexto[1][-1]["content"]
    assert r.contexto.tema.valor == "Mantenimiento"


def test_corte_por_tiempo_no_se_reintenta():
    ollama = OllamaFalso([])
    ollama.respuestas_contexto = [_ficha(resumen="Una ficha que tarda en llegar. " * 4)]
    ollama.pausa_contexto_s = 0.05
    with ollama.cliente() as cliente:
        r = ctx.generar_contexto(
            _analisis(), cliente, primer_token_s=5, inactividad_s=5, tope_s=0.2
        )

    assert (r.generado, r.motivo, r.intentos) == (False, "tiempo_excedido", 1)
    assert ollama.eventos == ["chat:contexto"]


@pytest.mark.parametrize("textos", [[], ["   ", ""]], ids=["sin_segmentos", "en_blanco"])
def test_transcripcion_vacia_no_llama_al_modelo(textos):
    r, ollama = _generar([_ficha()], _analisis(textos))

    assert (r.generado, r.motivo, r.intentos, r.modelo) == (False, "transcripcion_vacia", 0, None)
    assert ollama.eventos == []


# ── Métricas y aviso ────────────────────────────────────────────────────────────────────────


def test_registra_tokens_espera_al_primer_token_y_velocidad():
    r, _ = _generar([_ficha()])

    assert (r.tokens_entrada, r.prompt, r.modelo, r.intentos) == (100, "contexto_v2", "falso", 1)
    assert r.tokens_salida and r.tokens_salida > 0
    assert r.tokens_por_s == pytest.approx(20.0)
    assert r.primer_token_s is not None and r.segundos >= 0


def test_aviso_solo_si_la_ficha_quedo_vacia_y_sin_texto_del_video():
    r, _ = _generar([_ficha()])
    assert ctx.aviso_contexto(r) is None

    r, _ = _generar(["no es json"])
    aviso = ctx.aviso_contexto(r)
    assert aviso is not None and aviso.tipo == "contexto_sin_generar"
    assert aviso.detalle == "ficha de contexto vacía: respuesta_invalida tras 3 intentos"


@pytest.mark.parametrize("version", ["contexto_v1", "contexto_v2"])
def test_el_prompt_tiene_sus_cinco_secciones(version: str):
    prompt = ctx.cargar_prompt(version)
    assert set(prompt.extras) == {"sistema_fotogramas", "usuario_fotogramas"}
    assert "fotograma" not in (prompt.sistema + prompt.usuario.template).lower()


def test_se_puede_pedir_la_ficha_con_otra_version_del_prompt():
    ollama = OllamaFalso([])
    with ollama.cliente() as cliente:
        r = ctx.generar_contexto(_analisis(), cliente, version="contexto_v1")
    assert r.prompt == "contexto_v1"
    assert ollama.mensajes_contexto[0][0]["content"] == ctx.cargar_prompt("contexto_v1").sistema
