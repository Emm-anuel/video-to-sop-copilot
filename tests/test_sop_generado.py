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

AGRUPACION = {
    "grupos": [{"pasos_video": [2, 3]}, {"pasos_video": [4, 5]}, {"pasos_video": [6]}],
    "fuera": [{"paso_video": 1, "tipo": "introduccion"}, {"paso_video": 7, "tipo": "cierre"}],
}
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
    "agrupar": (gen.ESQUEMA_AGRUPAR,),
    "pasos": (gen.ESQUEMA_PASOS, gen.ESQUEMA_PASOS_FOTOGRAMAS),
}


def guion(**cambios: list[Any]) -> dict[str, list[Any]]:
    return {"agrupar": [AGRUPACION], "pasos": [PASOS]} | cambios


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
    **kwargs: Any,
) -> gen.SOPGenerado:
    plazos = {"primer_token_s": 5, "inactividad_s": 5, "tope_s": 60} | kwargs
    return gen.generar_sop(
        analisis or analisis_ingles(),
        PASOS_VIDEO if pasos is None else pasos,
        llm,  # type: ignore[arg-type]
        contexto,
        embedder=embedder,
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
def test_validar_agrupacion_rechaza_lo_que_no_cubre_cada_paso_una_vez(respuesta, motivo):
    with pytest.raises(gen.RespuestaInvalida, match=motivo):
        gen.validar_agrupacion(respuesta, 7)


def test_una_agrupacion_invalida_se_corrige_al_reintentar(embedder):
    invalida = {"grupos": [{"pasos_video": [1, 3]}, {"pasos_video": [2, 4, 5, 6, 7]}], "fuera": []}
    llm = LLMGuionado(guion(agrupar=[invalida, AGRUPACION]))
    r = generar(llm, embedder)
    assert r.generacion.llamadas[0].intentos == 2
    assert len(r.sop.pasos) == 3
    correccion = llm.pedidos[1][1][-1]["content"]
    assert "no es de pasos consecutivos" in correccion


def test_si_la_agrupacion_falla_queda_un_paso_del_sop_por_paso_del_video(embedder):
    invalida = {"grupos": [{"pasos_video": [1, 3]}, {"pasos_video": [2, 4, 5, 6, 7]}], "fuera": []}
    pasos7 = [dict(PASOS[0], numero=n) for n in range(1, 8)]
    llm = LLMGuionado(guion(agrupar=[invalida], pasos=[pasos7]))
    r = generar(llm, embedder)
    assert r.generacion.agrupacion == "uno_a_uno"
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


# ── Lotes y fallas ───────────────────────────────────────────────────────────────────────────


def test_los_pasos_se_redactan_por_lotes(embedder, monkeypatch):
    monkeypatch.setattr(gen, "PASOS_POR_LOTE", 2)

    def lote(mensajes: list[dict[str, str]]) -> list[dict[str, Any]]:
        n = mensajes[-1]["content"].count("Paso ")
        return [dict(PASOS[0], numero=k) for k in range(1, n + 1)]

    llm = LLMGuionado(guion(pasos=[lote]))
    r = generar(llm, embedder)
    assert llm.etapas() == ["agrupar", "pasos", "pasos"]
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
