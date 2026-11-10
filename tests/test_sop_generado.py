"""SOP generado desde el video (RF-22 a RF-25; ADR-023): `sopvid.lenguaje.sop_generado`, sin LLM
real ni MiniLM.

La transcripción (en inglés, para probar el SOP en español con citas en el idioma original), los
pasos del video, la ficha y las respuestas de Gemma son inventados por el equipo (CLAUDE.md §2.1)
y no se parecen a los videos de prueba A–E: son otro procedimiento. `LLMGuionado` responde según
el esquema que se le pide, como Ollama con `format`.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dobles import embedder_palabras
from sopvid.contrato import (
    SOP,
    Analisis,
    Contexto,
    Dato,
    Idioma,
    Palabra,
    PasoVideo,
    Persona,
    Segmento,
)
from sopvid.lenguaje import sop_generado as gen
from sopvid.lenguaje.llm import LLMNoDisponible, LLMRespuestaInvalida, RespuestaLLM
from sopvid.lenguaje.sop_markdown import empieza_con_infinitivo
from sopvid.plataforma.config import Settings, get_settings
from sopvid.texto import NO_IDENTIFICADO

# ── Video inventado: lubricar una cadena de transporte, narrado en inglés ────────────────────

TEXTOS = [
    "Hello, I'm Ana, the line operator. Today I lubricate the conveyor chain.",  # 0 intro
    "First I put on my nitrile gloves and my safety glasses.",  # 1
    "The gloves protect my hands from the oil.",  # 2
    "Next I stop the conveyor with the red stop button.",  # 3
    "The conveyor is stopped and the green light is off.",  # 4
    "Then I apply oil to the chain links with the oil can.",  # 5
    "This takes about two minutes, so I wait.",  # 6
    "Done, the chain is lubricated.",  # 7 cierre
]
DURACION_SEGMENTO = 10.0


def _segmento(i: int, texto: str) -> Segmento:
    """Segmento i de 10 s con tiempos por palabra repartidos a lo largo de 8 s."""
    t0 = DURACION_SEGMENTO * i
    palabras = texto.split()
    paso = 8.0 / len(palabras)
    return Segmento(
        id=i,
        t_inicio=t0,
        t_fin=t0 + 8.0,
        texto=texto,
        palabras=[
            Palabra(w=f" {w}", t=round(t0 + k * paso, 3), t_fin=round(t0 + (k + 1) * paso, 3))
            for k, w in enumerate(palabras)
        ],
    )


def analisis_ingles(textos: list[str] = TEXTOS) -> Analisis:
    return Analisis(
        video_id=41,
        duracion_s=DURACION_SEGMENTO * len(textos),
        idioma=Idioma(codigo="en", confianza=0.97),
        transcripcion=[_segmento(i, t) for i, t in enumerate(textos)],
    )


def _paso(numero: int, segmentos: tuple[int, int], nombre: str, cita: str) -> PasoVideo:
    a, b = segmentos
    return PasoVideo(
        numero=numero,
        nombre=nombre,
        descripcion=f"Descripción del paso {numero}.",
        responsable="Operadora de línea",
        t_inicio=DURACION_SEGMENTO * a,
        t_fin=DURACION_SEGMENTO * b + 8.0,
        cita=cita,
        fuente="audio",
        confianza="alta",
    )


# La segmentación parte de más (ADR-010): 7 pasos del video para 3 acciones, más intro y cierre.
PASOS_VIDEO = [
    _paso(1, (0, 0), "Presentación", "I'm Ana, the line operator"),
    _paso(2, (1, 1), "Colocación de guantes", "I put on my nitrile gloves"),
    _paso(3, (2, 2), "Protección de manos", "The gloves protect my hands"),
    _paso(4, (3, 3), "Paro del transportador", "I stop the conveyor with the red stop button"),
    _paso(5, (4, 4), "Verificación del paro", "The conveyor is stopped"),
    _paso(6, (5, 6), "Aplicación de aceite", "I apply oil to the chain links"),
    _paso(7, (7, 7), "Cierre", "Done, the chain is lubricated"),
]

CONTEXTO = Contexto(
    actividad=Dato(valor="Lubricar la cadena del transportador", fuente="audio", t=0.0),
    lugar=Dato(valor="Línea de empaque", confianza="media", fuente="inferido"),
    personas=[
        Persona(
            nombre="Ana",
            rol="Operadora de línea",
            participacion="participa",
            t=0.0,
            cita="I'm Ana, the line operator",
        )
    ],
)

# Agrupación v2: una etiqueta por paso del video; el código arma [2, 3], [4, 5] y [6].
ETIQUETAS = ["introduccion", "nuevo", "continua", "nuevo", "continua", "nuevo", "cierre"]
AGRUPACION = {"pasos": [{"paso_video": n, "etiqueta": e} for n, e in enumerate(ETIQUETAS, 1)]}
# La misma agrupación en el formato de la v1 (grupos completos), que se conserva.
AGRUPACION_V1 = {
    "grupos": [{"pasos_video": [2, 3]}, {"pasos_video": [4, 5]}, {"pasos_video": [6]}],
    "fuera": [{"paso_video": 1, "tipo": "introduccion"}, {"paso_video": 7, "tipo": "cierre"}],
}
# Una agrupación v2 que no cubre todos los pasos del video (se reintenta).
AGRUPACION_INCOMPLETA = {"pasos": AGRUPACION["pasos"][:5]}
PASOS = [
    {
        "numero": 1,
        "nombre": "Colocarse el equipo de protección",
        "descripcion": "Ponerse guantes de nitrilo y lentes de seguridad antes de empezar.",
        "equipo": [
            {"cita": "I put on my nitrile gloves", "valor": "Guantes de nitrilo"},
            {"cita": "my safety glasses", "valor": "Lentes de seguridad"},
        ],
        "puntos_validacion": [],
    },
    {
        "numero": 2,
        "nombre": "Detener el transportador",
        "descripcion": "Oprimir el botón rojo de paro y confirmar que la luz verde se apague.",
        "equipo": [],
        "puntos_validacion": [
            {"cita": "the green light is off", "valor": "Luz verde apagada"},
            {"cita": "the machine reads zero amps", "valor": "Corriente en cero"},
        ],
    },
    {
        "numero": 3,
        "nombre": "Aplicar aceite a la cadena",
        "descripcion": "Aplicar aceite a los eslabones con la aceitera durante unos dos minutos.",
        "equipo": [{"cita": "with the oil can", "valor": "Aceitera"}],
        "puntos_validacion": [],
    },
]


RESUMEN = {
    "titulo": "Lubricación de la cadena del transportador",
    "objetivo": {
        "cita": "Today I lubricate the conveyor chain",
        "valor": "Lubricar la cadena del transportador",
    },
    "alcance": {"cita": "", "valor": None},
    "duracion_total": {"cita": ""},
    "riesgos": [
        {
            "cita": "I stop the conveyor with the red stop button",
            "descripcion": "Atrapamiento con la cadena en movimiento",
            "nivel": "alto",
            "control": "Detener el transportador con el botón de paro",
        },
        {
            "cita": "the oil is very slippery on the floor",
            "descripcion": "Piso resbaloso",
            "nivel": "medio",
            "control": "",
        },
    ],
    "en_caso_de_falla": [
        {"cita": "", "situacion": "La luz verde no se apaga", "accion": "Avisar al supervisor"}
    ],
}


CLAVES = {
    "puntos_clave": [
        {
            "cita": "I stop the conveyor with the red stop button",
            "texto": "Detener el transportador antes de lubricar.",
        },
        {"cita": "", "texto": "Usar aceite limpio."},
    ],
    "palabras_clave": [
        {"termino": "guante", "literal": "glove", "categoria": "seguridad"},
        {"termino": "transportador", "literal": "Conveyor", "categoria": "equipo"},
        {"termino": "aceitera", "literal": "oil can", "categoria": "equipo"},
        {"termino": "manómetro", "literal": "pressure gauge", "categoria": "equipo"},
    ],
}


class LLMGuionado:
    """Cliente del LLM falso: responde a cada esquema con la siguiente respuesta de su lista (la
    última se repite). Una respuesta puede ser un objeto (JSON), una excepción que se lanza o una
    función de los mensajes. Registra cada petición en `pedidos` como (etapa, mensajes)."""

    modelo = "gemma-falso"
    num_ctx = 8192

    def __init__(self, respuestas: dict[str, list[Any]]):
        self.respuestas = respuestas
        self.pedidos: list[tuple[str, list[dict[str, str]]]] = []

    def chat_en_flujo(self, mensajes: list[dict[str, str]], **kwargs: Any) -> RespuestaLLM:
        etapa = _etapa(kwargs["esquema"])
        self.pedidos.append((etapa, mensajes))
        lista = self.respuestas.get(etapa) or [LLMNoDisponible("sin guion")]
        hechas = sum(e == etapa for e, _ in self.pedidos)
        r = lista[min(hechas, len(lista)) - 1]
        if callable(r) and not isinstance(r, Exception):
            r = r(mensajes)
        if isinstance(r, Exception):
            raise r
        return RespuestaLLM(
            texto=json.dumps(r),
            datos=r,
            modelo=self.modelo,
            razon_fin="stop",
            metricas={"prompt_eval_count": 300, "eval_count": 120, "eval_duration": 6_000_000_000},
            primer_token_s=0.4,
        )

    def etapas(self) -> list[str]:
        return [e for e, _ in self.pedidos]


def _etapa(esquema: dict[str, Any]) -> str:
    for etapa, candidatos in ESQUEMAS.items():
        if any(esquema is c for c in candidatos):
            return etapa
    raise AssertionError("esquema desconocido")


ESQUEMAS: dict[str, tuple[dict[str, Any], ...]] = {
    "agrupar": (gen.ESQUEMA_AGRUPAR, gen.ESQUEMA_AGRUPAR_V1),
    "pasos": (gen.ESQUEMA_PASOS, gen.ESQUEMA_PASOS_FOTOGRAMAS),
    "resumen": (gen.ESQUEMA_RESUMEN, gen.ESQUEMA_RESUMEN_FOTOGRAMAS),
    "claves": (gen.ESQUEMA_CLAVES,),
}


def guion(**cambios: list[Any]) -> dict[str, list[Any]]:
    base = {"agrupar": [AGRUPACION], "pasos": [PASOS], "resumen": [RESUMEN], "claves": [CLAVES]}
    return base | cambios


@pytest.fixture
def embedder(tmp_path: Path):
    return embedder_palabras(tmp_path / "modelos")


def generar(
    llm: LLMGuionado,
    embedder: Any,
    *,
    analisis: Analisis | None = None,
    pasos: list[PasoVideo] | None = None,
    contexto: Contexto | None = CONTEXTO,
    candado: bool | None = False,
    **kwargs: Any,
) -> gen.SOPGenerado:
    """Sin candado salvo que se pida: las pruebas del candado tienen su propio vectorizador."""
    plazos = {"primer_token_s": 5, "inactividad_s": 5, "tope_s": 60} | kwargs
    return gen.generar_sop(
        analisis or analisis_ingles(),
        PASOS_VIDEO if pasos is None else pasos,
        llm,  # type: ignore[arg-type]
        contexto,
        embedder=embedder,
        candado=candado,
        **plazos,
    )


def _evidencia(paso: Any, campo: str, valor: str | None = None) -> Any:
    return next(e for e in paso.evidencia if e.campo == campo and valor in (None, e.valor))


# ── Pasos: agrupados, en español, con la evidencia que pone el código ────────────────────────


def test_el_sop_tiene_un_paso_por_grupo_con_numero_y_tiempos_del_video(embedder):
    r = generar(LLMGuionado(guion()), embedder)
    sop = SOP.model_validate(r.sop.model_dump())  # el esquema completo valida
    assert [p.numero for p in sop.pasos] == [1, 2, 3]
    assert [(p.t_inicio, p.t_fin) for p in sop.pasos] == [(10.0, 28.0), (30.0, 48.0), (50.0, 68.0)]
    assert r.generacion.grupos == [[2, 3], [4, 5], [6]]
    assert [(f.paso_video, f.tipo) for f in r.generacion.fuera] == [
        (1, "introduccion"),
        (7, "cierre"),
    ]
    assert r.generacion.agrupacion == "llm"
    assert r.generacion.etiquetas == ETIQUETAS
    assert r.advertencias == []


def test_los_nombres_van_en_infinitivo_y_la_descripcion_en_espanol(embedder):
    sop = generar(LLMGuionado(guion()), embedder).sop
    assert all(empieza_con_infinitivo(p.nombre) for p in sop.pasos)
    assert sop.pasos[0].descripcion.startswith("Ponerse guantes")


def test_un_nombre_sin_infinitivo_deja_una_advertencia(embedder):
    pasos = [dict(PASOS[0], nombre="Colocación del equipo"), *PASOS[1:]]
    r = generar(LLMGuionado(guion(pasos=[pasos])), embedder)
    assert [(a.tipo, a.mensaje) for a in r.advertencias] == [
        ("infinitivo", "el nombre del paso 1 no empieza con un infinitivo")
    ]


def test_la_cita_que_existe_da_audio_con_su_segundo_y_la_que_no_queda_inferida(embedder):
    paso = generar(LLMGuionado(guion()), embedder).sop.pasos[1]
    luz = _evidencia(paso, "puntos_validacion", "Luz verde apagada")
    assert (luz.fuente, luz.confianza, luz.t, luz.cita) == (
        "audio",
        "alta",
        40.0,
        "the green light is off",
    )
    amps = _evidencia(paso, "puntos_validacion", "Corriente en cero")
    assert (amps.fuente, amps.confianza, amps.t, amps.cita) == ("inferido", "baja", None, "")
    assert "puntos_validacion" in paso.campos_inferidos
    assert paso.puntos_validacion == ["Luz verde apagada", "Corriente en cero"]


def test_una_cita_de_dos_o_tres_palabras_da_confianza_media(embedder):
    pasos = [dict(PASOS[0], equipo=[{"cita": "safety glasses", "valor": "Lentes"}]), *PASOS[1:]]
    paso = generar(LLMGuionado(guion(pasos=[pasos])), embedder).sop.pasos[0]
    lentes = _evidencia(paso, "equipo", "Lentes")
    assert (lentes.fuente, lentes.confianza, lentes.t) == ("audio", "media", 10.0)


def test_el_paso_lleva_la_mejor_cita_de_sus_pasos_del_video(embedder):
    paso = generar(LLMGuionado(guion()), embedder).sop.pasos[0]
    assert (paso.cita, paso.fuente, paso.confianza) == (
        "I put on my nitrile gloves",
        "audio",
        "alta",
    )


def test_el_responsable_es_el_rol_de_la_persona_de_la_ficha_nunca_su_nombre(embedder):
    sop = generar(LLMGuionado(guion()), embedder).sop
    assert {p.responsable for p in sop.pasos} == {"Operadora de línea"}
    ev = _evidencia(sop.pasos[0], "responsable")
    # El rol está en español y la cita en inglés: la persona se dijo, el rol es una traducción.
    assert (ev.fuente, ev.confianza, ev.t, ev.cita) == (
        "audio",
        "media",
        0.0,
        "I'm Ana, the line operator",
    )
    assert "responsable" not in sop.pasos[0].campos_inferidos
    assert all("Ana" not in p.responsable for p in sop.pasos)


def test_sin_ficha_el_responsable_queda_inferido(embedder):
    sop = generar(LLMGuionado(guion()), embedder, contexto=None).sop
    paso = sop.pasos[0]
    assert paso.responsable == "Operadora de línea"  # el rol que escribió la segmentación
    assert _evidencia(paso, "responsable").fuente == "inferido"
    assert "responsable" in paso.campos_inferidos


def test_el_tiempo_narrado_gana_y_lleva_su_cita(embedder):
    paso = generar(LLMGuionado(guion()), embedder).sop.pasos[2]
    assert paso.tiempo_esperado_min == 2.0
    ev = _evidencia(paso, "tiempo_esperado_min")
    assert (ev.fuente, ev.t, ev.cita) == ("audio", 60.0, "takes about two minutes")
    assert "tiempo_esperado_min" not in paso.campos_inferidos


def test_sin_duracion_narrada_el_tiempo_es_el_medido_e_inferido(embedder):
    paso = generar(LLMGuionado(guion()), embedder).sop.pasos[0]
    # Del inicio del grupo (10 s) al inicio del siguiente paso del video (30 s), ADR-021.
    assert paso.tiempo_esperado_min == round(20 / 60, 2)
    ev = _evidencia(paso, "tiempo_esperado_min")
    assert (ev.fuente, ev.confianza) == ("inferido", "media")
    assert "tiempo_esperado_min" in paso.campos_inferidos


def test_la_medida_del_ultimo_paso_llega_al_cierre_aunque_quede_fuera(embedder):
    sin_narrar = TEXTOS[:6] + ["I keep going, so I wait.", TEXTOS[7]]
    r = generar(LLMGuionado(guion()), embedder, analisis=analisis_ingles(sin_narrar))
    paso = r.sop.pasos[2]
    assert paso.tiempo_esperado_min == round((70 - 50) / 60, 2)


def test_los_valores_de_lista_pierden_los_separadores_de_la_plantilla(embedder):
    pasos = [
        dict(
            PASOS[0], equipo=[{"cita": "my nitrile gloves", "valor": "Guantes, nitrilo; talla M"}]
        ),
        *PASOS[1:],
    ]
    paso = generar(LLMGuionado(guion(pasos=[pasos])), embedder).sop.pasos[0]
    assert paso.equipo == ["Guantes nitrilo talla M"]


def test_el_equipo_repetido_se_junta(embedder):
    repetido = [{"cita": "my nitrile gloves", "valor": v} for v in ("Guantes", "guantes", "Guante")]
    pasos = [dict(PASOS[0], equipo=repetido), *PASOS[1:]]
    paso = generar(LLMGuionado(guion(pasos=[pasos])), embedder).sop.pasos[0]
    assert paso.equipo == ["Guantes"]


# ── Gemma no ve ni escribe tiempos ───────────────────────────────────────────────────────────


def test_ningun_mensaje_a_gemma_lleva_segundos_ni_numeros_de_segmento(embedder):
    llm = LLMGuionado(guion())
    generar(llm, embedder)
    for _etapa, mensajes in llm.pedidos:
        for m in mensajes:
            assert not re.search(r"\d+[.:]\d+|\[s=|\[t=", m["content"]), m["content"][:200]


def test_un_campo_de_tiempo_en_la_respuesta_deja_el_paso_sin_redactar(embedder):
    con_tiempo = [dict(PASOS[0], t_inicio=3.0), *PASOS[1:]]
    r = generar(LLMGuionado(guion(pasos=[con_tiempo])), embedder)
    assert r.sop.pasos[0].nombre == "Colocación de guantes"  # el del paso del video
    assert r.sop.pasos[0].t_inicio == 10.0  # el tiempo sale de la transcripción, no del LLM
    assert "pasos sin redactar [1]" in r.advertencias[0].mensaje


# ── Agrupación ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("respuesta", "motivo"),
    [
        (
            {"grupos": [{"pasos_video": [1, 3]}, {"pasos_video": [2, 4, 5, 6, 7]}], "fuera": []},
            "consecutivos",
        ),
        ({"grupos": [{"pasos_video": [1, 2, 3, 4, 5, 6, 7, 8]}], "fuera": []}, "no existen"),
        ({"grupos": [{"pasos_video": [1, 2]}, {"pasos_video": [2, 3]}], "fuera": []}, "repetidos"),
        ({"grupos": [{"pasos_video": [1, 2, 3]}], "fuera": []}, "sin grupo ni fuera"),
        (
            {
                "grupos": [{"pasos_video": [4, 5, 6, 7]}, {"pasos_video": [1, 2, 3]}],
                "fuera": [],
            },
            "orden",
        ),
        ({"grupos": [], "fuera": [{"paso_video": 1, "tipo": "cierre"}]}, "ningún grupo"),
    ],
)
def test_validar_agrupacion_v1_rechaza_lo_que_no_cubre_cada_paso_una_vez(respuesta, motivo):
    with pytest.raises(gen.RespuestaInvalida, match=motivo):
        gen.validar_agrupacion(respuesta, 7)


def test_la_agrupacion_v1_se_conserva(embedder, monkeypatch):
    monkeypatch.setattr(gen, "PROMPT_AGRUPAR", "sop_generado_agrupar_v1")
    llm = LLMGuionado(guion(agrupar=[AGRUPACION_V1]))
    r = generar(llm, embedder)
    assert r.generacion.grupos == [[2, 3], [4, 5], [6]]
    assert r.generacion.etiquetas == []
    assert r.generacion.llamadas[0].prompt == "sop_generado_agrupar_v1"


def _etiquetas(*pares: tuple[int, str]) -> dict[str, Any]:
    return {"pasos": [{"paso_video": n, "etiqueta": e} for n, e in pares]}


@pytest.mark.parametrize(
    ("respuesta", "motivo"),
    [
        (_etiquetas(*((n, "nuevo") for n in range(1, 9))), "no existen"),
        (_etiquetas(*((n, "nuevo") for n in range(1, 8)), (3, "continua")), "más de una"),
        (_etiquetas(*((n, "nuevo") for n in range(1, 6))), r"sin etiqueta: \[6, 7\]"),
        (_etiquetas(*((n, "comentario") for n in range(1, 8))), "ningún paso es una acción"),
    ],
)
def test_validar_etiquetas_exige_una_por_paso_del_video_y_alguna_accion(respuesta, motivo):
    with pytest.raises(gen.RespuestaInvalida, match=motivo):
        gen.validar_etiquetas(respuesta, 7)


def test_las_etiquetas_se_ordenan_por_paso_del_video():
    desordenadas = {"pasos": list(reversed(AGRUPACION["pasos"]))}
    assert gen.validar_etiquetas(desordenadas, 7) == ETIQUETAS


def test_una_etiqueta_desconocida_no_valida():
    with pytest.raises(ValidationError):
        gen.validar_etiquetas(_etiquetas((1, "nuevo"), (2, "repetido")), 2)


def test_el_codigo_arma_los_grupos_con_las_etiquetas():
    a = gen.agrupar_por_etiquetas(ETIQUETAS)
    assert a.grupos == [[2, 3], [4, 5], [6]]
    assert [(f.paso_video, f.tipo) for f in a.fuera] == [(1, "introduccion"), (7, "cierre")]
    assert a.etiquetas == ETIQUETAS


def test_un_continua_sin_grupo_abierto_empieza_uno():
    # El primero y el que sigue a una pregunta del entrevistador: cada grupo, de pasos seguidos.
    a = gen.agrupar_por_etiquetas(["continua", "continua", "entrevistador", "continua", "nuevo"])
    assert a.grupos == [[1, 2], [4], [5]]
    assert [(f.paso_video, f.tipo) for f in a.fuera] == [(3, "entrevistador")]


def test_una_agrupacion_invalida_se_corrige_al_reintentar(embedder):
    llm = LLMGuionado(guion(agrupar=[AGRUPACION_INCOMPLETA, AGRUPACION]))
    r = generar(llm, embedder)
    assert r.generacion.llamadas[0].intentos == 2
    assert len(r.sop.pasos) == 3
    correccion = llm.pedidos[1][1][-1]["content"]
    assert "pasos del video sin etiqueta: [6, 7]" in correccion


def test_si_la_agrupacion_falla_queda_un_paso_del_sop_por_paso_del_video(embedder):
    pasos7 = [dict(PASOS[0], numero=n) for n in range(1, 8)]
    llm = LLMGuionado(guion(agrupar=[AGRUPACION_INCOMPLETA], pasos=[pasos7]))
    r = generar(llm, embedder, candado=True)
    assert r.generacion.agrupacion == "uno_a_uno"
    assert r.generacion.cortes_candado == []  # el candado solo revisa lo que agrupó Gemma
    assert r.generacion.llamadas[0].intentos == gen.MAX_INTENTOS
    assert len(r.sop.pasos) == 7
    assert r.advertencias[0].tipo == "sop_incompleto"
    assert "agrupación (respuesta_invalida)" in r.advertencias[0].mensaje


def test_un_json_roto_se_reintenta_y_ollama_caido_no(embedder):
    llm = LLMGuionado(guion(agrupar=[LLMRespuestaInvalida("roto"), AGRUPACION]))
    assert generar(llm, embedder).generacion.llamadas[0].intentos == 2
    llm = LLMGuionado(guion(agrupar=[LLMNoDisponible("caído")]))
    llamada = generar(llm, embedder).generacion.llamadas[0]
    assert (llamada.ok, llamada.motivo, llamada.intentos) == (False, "llm_no_disponible", 1)


# ── Candado por coseno (ADR-023) ─────────────────────────────────────────────────────────────


class VectorizadorPorPaso:
    """Embedder falso: cada paso del video es un vector unitario en el plano; los pasos 2 y 3
    forman un ángulo con coseno `coseno_2_3`, y 4 y 5, uno con coseno 0.9. Guarda los textos
    de cada llamada (la primera es la del candado) para revisar que van en minúsculas y con la
    cita."""

    def __init__(self, coseno_2_3: float):
        import math

        angulo = math.acos(coseno_2_3)
        self.vectores = {
            1: (1.0, 0.0),
            2: (1.0, 0.0),
            3: (math.cos(angulo), math.sin(angulo)),
            4: (0.0, 1.0),
            5: (math.sin(math.acos(0.9)), 0.9),
            6: (1.0, 0.0),
            7: (1.0, 0.0),
        }
        self.llamadas: list[list[str]] = []

    def embed(self, textos: list[str]) -> Any:
        import numpy as np

        self.llamadas.append(list(textos))
        return np.array([self.vectores[i] for i in range(1, len(textos) + 1)])


def test_el_candado_parte_un_continua_poco_parecido_al_anterior(embedder):
    vectorizador = VectorizadorPorPaso(coseno_2_3=0.30)
    r = generar(
        LLMGuionado(guion(pasos=[PASOS + [dict(PASOS[2], numero=4)]])), vectorizador, candado=True
    )
    assert r.generacion.grupos == [[2], [3], [4, 5], [6]]
    assert (r.generacion.candado, r.generacion.cortes_candado) == (True, [3])
    assert r.generacion.etiquetas == ETIQUETAS  # lo que dijo Gemma queda tal cual
    assert len(r.sop.pasos) == 4
    assert (
        vectorizador.llamadas[0][1]
        == "colocación de guantes. descripción del paso 2. i put on my nitrile gloves"
    )


def test_el_candado_respeta_un_continua_parecido(embedder):
    r = generar(LLMGuionado(guion()), VectorizadorPorPaso(coseno_2_3=0.80), candado=True)
    assert r.generacion.grupos == [[2, 3], [4, 5], [6]]
    assert (r.generacion.candado, r.generacion.cortes_candado) == (True, [])


def test_el_candado_usa_umbral_fusion():
    a = gen.agrupar_por_etiquetas(ETIQUETAS)
    vectorizador = VectorizadorPorPaso(coseno_2_3=0.60)
    assert gen.aplicar_candado(a, PASOS_VIDEO, vectorizador, 0.55).cortes == []  # type: ignore[arg-type]
    assert gen.aplicar_candado(a, PASOS_VIDEO, vectorizador, 0.65).cortes == [3]  # type: ignore[arg-type]


def test_sin_grupos_de_mas_de_un_paso_el_candado_no_vectoriza():
    class SinUso:
        def embed(self, textos: list[str]) -> Any:
            raise AssertionError("no debía vectorizar")

    a = gen.agrupar_por_etiquetas(["nuevo", "nuevo", "cierre"])
    assert gen.aplicar_candado(a, PASOS_VIDEO[:3], SinUso()).grupos == [[1], [2]]  # type: ignore[arg-type]


def test_el_candado_sale_de_la_configuracion(embedder, monkeypatch):
    monkeypatch.setenv("SOP_CANDADO", "false")
    get_settings.cache_clear()
    try:
        r = generar(LLMGuionado(guion()), VectorizadorPorPaso(coseno_2_3=0.30), candado=None)
    finally:
        get_settings.cache_clear()
    assert (r.generacion.candado, r.generacion.grupos) == (False, [[2, 3], [4, 5], [6]])


# ── Lotes y fallas ───────────────────────────────────────────────────────────────────────────


def test_los_pasos_se_redactan_por_lotes(embedder, monkeypatch):
    monkeypatch.setattr(gen, "PASOS_POR_LOTE", 2)

    def lote(mensajes: list[dict[str, str]]) -> list[dict[str, Any]]:
        n = mensajes[-1]["content"].count("Paso ")
        return [dict(PASOS[0], numero=k) for k in range(1, n + 1)]

    llm = LLMGuionado(guion(pasos=[lote]))
    r = generar(llm, embedder)
    assert llm.etapas() == ["agrupar", "pasos", "pasos", "resumen", "claves"]
    assert [p.numero for p in r.sop.pasos] == [1, 2, 3]


def test_si_falla_la_redaccion_el_sop_sale_con_los_pasos_del_video_y_el_aviso(embedder):
    llm = LLMGuionado(guion(pasos=[LLMNoDisponible("caído")]))
    r = generar(llm, embedder)
    assert [p.nombre for p in r.sop.pasos] == [
        "Colocación de guantes",
        "Paro del transportador",
        "Aplicación de aceite",
    ]
    assert all(p.confianza == "baja" for p in r.sop.pasos)
    assert all({"nombre", "descripcion"} <= set(p.campos_inferidos) for p in r.sop.pasos)
    assert r.sop.pasos[0].descripcion == "Descripción del paso 2. Descripción del paso 3."
    tipos = [a.tipo for a in r.advertencias]
    assert tipos[0] == "sop_incompleto" and "[1, 2, 3]" in r.advertencias[0].mensaje


def test_un_paso_que_falta_en_la_respuesta_queda_sin_redactar_y_los_demas_se_usan(embedder):
    llm = LLMGuionado(guion(pasos=[PASOS[:2]]))
    r = generar(llm, embedder)
    assert r.sop.pasos[0].nombre == "Colocarse el equipo de protección"
    assert r.sop.pasos[2].nombre == "Aplicación de aceite"
    assert "pasos sin redactar [3]" in r.advertencias[0].mensaje


def test_sin_pasos_del_video_no_hay_sop(embedder):
    with pytest.raises(gen.SinPasosDelVideo, match="vuelve a generar"):
        generar(LLMGuionado(guion()), embedder, pasos=[])


def test_se_registran_tokens_y_velocidad_de_cada_llamada(embedder):
    r = generar(LLMGuionado(guion()), embedder)
    for llamada in r.generacion.llamadas:
        assert (llamada.tokens_salida, llamada.tokens_por_s, llamada.primer_token_s) == (
            120,
            20.0,
            0.4,
        )
    assert r.generacion.modelo == "gemma-falso"


# ── Cuadro resumen por código ────────────────────────────────────────────────────────────────


def test_el_resumen_toma_lugar_responsable_roles_personas_y_equipo_sin_repetir(embedder):
    r = generar(LLMGuionado(guion()), embedder).sop.resumen
    assert r.version == "1.0"
    assert r.lugar == CONTEXTO.lugar
    assert r.horario_frecuencia.fuente == "inferido" and r.horario_frecuencia.valor is None
    assert (r.responsable.valor, r.responsable.fuente, r.responsable.t) == (
        "Operadora de línea",
        "audio",
        0.0,
    )
    assert [e.nombre for e in r.roles] == ["Operadora de línea"]
    assert r.personas == CONTEXTO.personas
    assert [e.nombre for e in r.equipo_operacion] == [
        "Guantes de nitrilo",
        "Lentes de seguridad",
        "Aceitera",
    ]


def test_la_duracion_total_es_la_suma_de_los_pasos(embedder):
    sop = generar(LLMGuionado(guion()), embedder).sop
    assert sop.resumen.duracion_total_min == round(
        sum(p.tiempo_esperado_min or 0 for p in sop.pasos), 2
    )


def test_sin_titulo_propuesto_va_la_actividad_de_la_ficha_o_uno_generico():
    assert gen.titulo_de(None, CONTEXTO, 41) == "Lubricar la cadena del transportador"
    assert gen.titulo_de("  ", None, 41) == "Procedimiento del video 41"


def test_sin_responsable_conocido_el_del_resumen_queda_vacio(embedder):
    pasos = [p.model_copy(update={"responsable": NO_IDENTIFICADO}) for p in PASOS_VIDEO]
    sop = generar(LLMGuionado(guion()), embedder, pasos=pasos, contexto=None).sop
    assert sop.resumen.responsable.valor is None
    assert all(p.responsable == NO_IDENTIFICADO for p in sop.pasos)


# ── Cuadro resumen con Gemma (RF-22) ─────────────────────────────────────────────────────────


def test_el_resumen_lleva_titulo_objetivo_riesgos_y_fallas_con_su_evidencia(embedder):
    r = generar(LLMGuionado(guion()), embedder)
    sop = r.sop
    assert sop.titulo == "Lubricación de la cadena del transportador"
    objetivo = sop.resumen.objetivo
    assert (objetivo.valor, objetivo.fuente, objetivo.confianza, objetivo.t, objetivo.cita) == (
        "Lubricar la cadena del transportador",
        "audio",
        "alta",
        0.0,
        "Today I lubricate the conveyor chain",
    )
    assert sop.resumen.alcance == gen._dato_vacio()  # no se dice: vacío e inferido
    atrapamiento, piso = sop.resumen.riesgos
    # El paso del riesgo lo pone el código: su cita cae en el tramo del paso 2 (30 a 50 s).
    assert (atrapamiento.nivel, atrapamiento.paso, atrapamiento.t, atrapamiento.fuente) == (
        "alto",
        2,
        30.0,
        "audio",
    )
    assert (piso.paso, piso.fuente, piso.confianza, piso.t, piso.cita) == (
        None,
        "inferido",
        "baja",
        None,
        "",
    )
    [falla] = sop.resumen.en_caso_de_falla
    assert (falla.situacion, falla.fuente, falla.confianza) == (
        "La luz verde no se apaga",
        "inferido",
        "baja",
    )
    assert r.generacion.duracion_narrada is None
    assert [x.etapa for x in r.generacion.llamadas] == ["agrupar", "pasos", "resumen", "claves"]


def test_el_resumen_no_pide_lo_que_sale_de_la_ficha():
    propiedades = set(gen.ESQUEMA_RESUMEN["properties"])
    assert propiedades == {
        "titulo",
        "objetivo",
        "alcance",
        "duracion_total",
        "riesgos",
        "en_caso_de_falla",
    }
    riesgo = gen.ESQUEMA_RESUMEN["properties"]["riesgos"]["items"]["properties"]
    assert "paso" not in riesgo  # el número de paso lo pone el código


def test_un_riesgo_dicho_en_la_presentacion_no_tiene_paso(embedder):
    riesgos = [dict(RESUMEN["riesgos"][0], cita="I'm Ana, the line operator")]
    llm = LLMGuionado(guion(resumen=[dict(RESUMEN, riesgos=riesgos)]))
    [riesgo] = generar(llm, embedder).sop.resumen.riesgos
    assert (riesgo.t, riesgo.paso) == (0.0, None)


def test_la_duracion_total_narrada_gana_a_la_suma(embedder):
    textos = ["Hello, I'm Ana, the line operator. The whole job takes about five minutes."]
    textos += TEXTOS[1:]
    resumen = dict(RESUMEN, duracion_total={"cita": "The whole job takes about five minutes"})
    r = generar(LLMGuionado(guion(resumen=[resumen])), embedder, analisis=analisis_ingles(textos))
    assert r.sop.resumen.duracion_total_min == 5.0
    narrada = r.generacion.duracion_narrada
    assert narrada is not None
    assert (narrada.valor, narrada.fuente, narrada.t) == ("5", "audio", 0.0)


@pytest.mark.parametrize(
    "cita",
    [
        "The whole job takes about ten minutes",  # no aparece en la transcripción
        "Today I lubricate the conveyor chain",  # aparece, pero no dice una duración
    ],
)
def test_una_duracion_total_sin_evidencia_deja_la_suma_de_los_pasos(embedder, cita):
    resumen = dict(RESUMEN, duracion_total={"cita": cita})
    r = generar(LLMGuionado(guion(resumen=[resumen])), embedder)
    sop = r.sop
    assert sop.resumen.duracion_total_min == round(
        sum(p.tiempo_esperado_min or 0 for p in sop.pasos), 2
    )
    assert r.generacion.duracion_narrada is None


def test_si_falla_el_resumen_el_sop_sale_con_el_titulo_de_la_ficha_y_el_aviso(embedder):
    r = generar(LLMGuionado(guion(resumen=[LLMNoDisponible("caído")])), embedder)
    assert r.sop.titulo == "Lubricar la cadena del transportador"
    assert r.sop.resumen.riesgos == [] and r.sop.resumen.objetivo.valor is None
    assert len(r.sop.pasos) == 3
    assert r.sop.resumen.lugar == CONTEXTO.lugar  # lo de la ficha se conserva
    [aviso] = r.advertencias
    assert aviso.tipo == "sop_incompleto" and "cuadro resumen (llm_no_disponible)" in aviso.mensaje


def test_el_resumen_recibe_la_transcripcion_la_ficha_y_los_pasos_sin_tiempos(embedder):
    llm = LLMGuionado(guion())
    generar(llm, embedder)
    [usuario] = [m["content"] for e, ms in llm.pedidos if e == "resumen" for m in ms[1:]]
    assert "1. Colocarse el equipo de protección" in usuario
    assert "Ana (Operadora de línea), participa" in usuario
    assert TEXTOS[3] in usuario


# ── Puntos y palabras clave (RF-24) ──────────────────────────────────────────────────────────


def _t_palabra(analisis: Analisis, segmento: int, palabra: int) -> float:
    return analisis.transcripcion[segmento].palabras[palabra].t


def test_las_menciones_se_cuentan_con_la_forma_literal_y_sus_segundos(embedder):
    analisis = analisis_ingles()
    sop = generar(LLMGuionado(guion()), embedder, analisis=analisis).sop
    por_termino = {p.termino: p for p in sop.palabras_clave}
    guante = por_termino["guante"]
    # "glove" encuentra "gloves" (plural simple) en los segmentos 1 y 2.
    assert (guante.menciones, guante.t, guante.literal) == (
        2,
        [_t_palabra(analisis, 1, 6), _t_palabra(analisis, 2, 1)],
        "glove",
    )
    # Sin mayúsculas: "Conveyor" encuentra las tres veces que se dice "conveyor".
    assert por_termino["transportador"].menciones == 3
    # Varias palabras: el segundo es el de la primera ("oil" de "oil can").
    assert por_termino["aceitera"].t == [_t_palabra(analisis, 5, 10)]


def test_un_termino_sin_menciones_se_descarta(embedder):
    sop = generar(LLMGuionado(guion()), embedder).sop
    assert "manómetro" not in {p.termino for p in sop.palabras_clave}
    assert all(p.menciones == len(p.t) > 0 for p in sop.palabras_clave)


def test_un_termino_repetido_se_junta_sin_duplicar_segundos(embedder):
    claves = dict(
        CLAVES,
        palabras_clave=[
            {"termino": "transportador", "literal": "conveyor", "categoria": "equipo"},
            {"termino": "Transportador", "literal": "conveyors", "categoria": "equipo"},
        ],
    )
    [palabra] = generar(LLMGuionado(guion(claves=[claves])), embedder).sop.palabras_clave
    assert (palabra.termino, palabra.menciones) == ("transportador", 3)


def test_video_en_ingles_termino_en_espanol_y_literal_en_ingles(embedder):
    sop = generar(LLMGuionado(guion()), embedder).sop
    aceitera = next(p for p in sop.palabras_clave if p.termino == "aceitera")
    assert (aceitera.termino, aceitera.literal, aceitera.categoria) == (
        "aceitera",
        "oil can",
        "equipo",
    )


def test_en_espanol_las_dos_formas_pueden_ser_iguales_y_cuentan_acentos_y_plural():
    analisis = Analisis(
        video_id=3,
        duracion_s=20.0,
        idioma=Idioma(codigo="es", confianza=0.99),
        transcripcion=[
            _segmento(0, "Primero reviso el manómetro de la línea."),
            _segmento(1, "Los MANOMETROS marcan cero."),
        ],
    )
    claves = gen._ClavesLibre.model_validate(
        {
            "puntos_clave": [],
            "palabras_clave": [
                {"termino": "manómetro", "literal": "manómetro", "categoria": "equipo"}
            ],
        }
    )
    _, [palabra], descartadas = gen.aplicar_claves(claves, analisis, gen._Evidencias(analisis))
    assert (palabra.menciones, palabra.t, descartadas) == (
        2,
        [_t_palabra(analisis, 0, 3), _t_palabra(analisis, 1, 1)],
        0,
    )


def test_los_puntos_clave_llevan_su_evidencia(embedder):
    detener, aceite = generar(LLMGuionado(guion()), embedder).sop.puntos_clave
    assert (detener.t, detener.fuente, detener.confianza) == (30.0, "audio", "alta")
    assert (aceite.t, aceite.fuente, aceite.confianza, aceite.cita) == (
        None,
        "inferido",
        "baja",
        "",
    )


def test_menciones_sin_tiempos_por_palabra_usan_el_inicio_del_segmento():
    analisis = Analisis(
        video_id=3,
        duracion_s=20.0,
        idioma=Idioma(codigo="en", confianza=0.9),
        transcripcion=[Segmento(id=0, t_inicio=4.0, t_fin=8.0, texto="Check the O-rings.")],
    )
    assert gen.menciones("o-ring", gen.palabras_con_tiempo(analisis)) == [4.0]


def test_si_fallan_las_claves_el_sop_sale_sin_ellas_y_con_el_aviso(embedder):
    r = generar(LLMGuionado(guion(claves=[LLMNoDisponible("caído")])), embedder)
    assert (r.sop.puntos_clave, r.sop.palabras_clave) == ([], [])
    [aviso] = r.advertencias
    assert aviso.tipo == "sop_incompleto" and "puntos y palabras clave" in aviso.mensaje


@pytest.mark.parametrize("version", ["sop_generado_agrupar_v2", "sop_generado_agrupar_v3"])
def test_la_v2_y_la_v3_usan_las_mismas_etiquetas(embedder, monkeypatch, version):
    monkeypatch.setattr(gen, "PROMPT_AGRUPAR", version)
    llm = LLMGuionado(guion())
    r = generar(llm, embedder)
    assert r.generacion.grupos == [[2, 3], [4, 5], [6]]
    assert r.generacion.llamadas[0].prompt == version


def test_el_candado_esta_apagado_por_defecto():
    assert Settings.model_fields["sop_candado"].default is False


# ── Equipo sin repetir y valores en español (ADR-023, prueba manual de E) ────────────────────


class VectorizadorPorNombre:
    """Embedder falso: un vector fijo por nombre (en minúsculas); guarda lo que recibe."""

    def __init__(self, vectores: dict[str, tuple[float, float]]):
        self.vectores = vectores
        self.recibidos: list[str] = []

    def embed(self, textos: list[str]) -> Any:
        import numpy as np

        self.recibidos += textos
        return np.array([self.vectores[t] for t in textos])


def test_el_equipo_se_une_por_coseno_en_minusculas_y_conserva_el_primer_nombre():
    vectorizador = VectorizadorPorNombre(
        {
            "botón rojo en la carcasa": (1.0, 0.0),
            "cubeta": (0.0, 1.0),
            "botón rojo": (0.95, 0.31),  # coseno 0.95 con el primero
            "cubo": (0.2, 0.98),  # coseno 0.98 con la cubeta
        }
    )
    nombres = ["Botón rojo en la carcasa", "Cubeta", "botón rojo", "Cubetas", "Cubo"]
    unidos = gen.unir_equipo(nombres, vectorizador, 0.9)  # type: ignore[arg-type]
    assert unidos == ["Botón rojo en la carcasa", "Cubeta"]
    assert "cubetas" not in vectorizador.recibidos  # el plural ya se unió sin MiniLM
    assert all(t == t.lower() for t in vectorizador.recibidos)


def test_el_equipo_se_compara_contra_los_guardados_no_en_cadena():
    # a~b (0.92) y b~c (0.92), pero a y c (0.70) son distintos: c queda.
    import math

    def angulo(grados: float) -> tuple[float, float]:
        return (math.cos(math.radians(grados)), math.sin(math.radians(grados)))

    vectorizador = VectorizadorPorNombre(
        {"a": angulo(0), "b": angulo(math.degrees(math.acos(0.92))), "c": angulo(45.6)}
    )
    assert gen.unir_equipo(["a", "b", "c"], vectorizador, 0.9) == ["a", "c"]  # type: ignore[arg-type]


def test_con_un_solo_nombre_no_vectoriza():
    class SinUso:
        def embed(self, textos: list[str]) -> Any:
            raise AssertionError("no debía vectorizar")

    assert gen.unir_equipo(["Aceitera", "aceiteras"], SinUso()) == ["Aceitera"]  # type: ignore[arg-type]


def test_el_umbral_del_equipo_sale_de_la_configuracion(monkeypatch):
    vectorizador = VectorizadorPorNombre({"x": (1.0, 0.0), "y": (0.8, 0.6)})  # coseno 0.8
    monkeypatch.setenv("UMBRAL_EQUIPO", "0.75")
    get_settings.cache_clear()
    try:
        assert gen.unir_equipo(["x", "y"], vectorizador) == ["x"]  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()
    assert Settings.model_fields["umbral_equipo"].default == 0.85


@pytest.mark.parametrize(
    ("valor", "sin_traducir"),
    [
        ("oil can", True),
        ("The conveyor is stopped", True),
        ("Aceitera", False),
        ("Detener el transportador", False),  # "transportador" no es "conveyor"
        ("Botón rojo de paro (red stop)", False),  # 2 de 4 palabras: no más de la mitad
        ("", False),
        (None, False),
        ("10 kg", False),  # sin palabras que contar
    ],
)
def test_un_valor_copiado_del_video_parece_sin_traducir(valor, sin_traducir):
    palabras = gen.vocabulario(analisis_ingles())
    assert gen.parece_sin_traducir(valor, palabras) is sin_traducir


def test_un_sop_con_valores_en_ingles_deja_una_advertencia_por_lugar(embedder):
    pasos = [dict(p) for p in PASOS]
    pasos[2] = dict(PASOS[2], equipo=[{"cita": "with the oil can", "valor": "oil can"}])
    resumen = dict(RESUMEN)
    resumen["riesgos"] = [
        dict(RESUMEN["riesgos"][0], control="I stop the conveyor with the red stop button")
    ]
    r = generar(LLMGuionado(guion(pasos=[pasos], resumen=[resumen])), embedder)
    avisos = [a for a in r.advertencias if a.tipo == "sin_traducir"]
    assert [a.mensaje.split(":")[0] for a in avisos] == [
        "equipo de operación",
        "riesgo 1, control",
        "paso 3, equipo",
    ]
    assert all("oil" not in a.mensaje and "conveyor" not in a.mensaje for a in avisos)


def test_un_video_en_espanol_no_se_revisa():
    analisis = analisis_ingles().model_copy(update={"idioma": Idioma(codigo="es", confianza=1)})
    sop = SOP.model_validate(
        {"titulo": "x", "pasos": [{"numero": 1, "nombre": "The conveyor", "responsable": "T"}]}
    )
    assert gen.revisar_idioma(sop, analisis) == []
    assert gen.revisar_idioma(sop, analisis_ingles())[0].tipo == "sin_traducir"


def test_los_prompts_de_redaccion_piden_los_valores_en_espanol():
    assert (gen.PROMPT_PASOS, gen.PROMPT_RESUMEN) == (
        "sop_generado_pasos_v2",
        "sop_generado_resumen_v2",
    )
    for version in (gen.PROMPT_PASOS, gen.PROMPT_RESUMEN):
        assert "Todo lo que no es cita va en español" in gen.cargar_prompt(version).sistema
