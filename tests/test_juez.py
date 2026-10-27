"""Juez Gemma 4 de la zona gris (ADR-012, punto 3) con Ollama simulado (httpx.MockTransport).

Todo el material es inventado por el equipo (regla 1 de CLAUDE.md). La prueba con Gemma 4 real
va marcada como "lento" y se salta si Ollama no responde.
"""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from sopvid.contrato import (
    SOP,
    VEREDICTOS,
    Clasificacion,
    Palabra,
    Par,
    PasoSOP,
    PasoVideo,
    Segmento,
)
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje import juez as jz
from sopvid.lenguaje.llm import SEMILLA, ClienteLLM
from sopvid.plataforma import config
from sopvid.texto import contiene_cita


@pytest.fixture(autouse=True)
def umbrales(monkeypatch):
    """Umbrales por defecto (0.55 / 0.75 / 0.55), sin importar el `.env`."""
    monkeypatch.setenv("UMBRAL_BAJO", "0.55")
    monkeypatch.setenv("UMBRAL_ALTO", "0.75")
    monkeypatch.setenv("UMBRAL_FUSION", "0.55")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


# ── Datos inventados ─────────────────────────────────────────────────────────────────────────


def _seg(id_: int, *palabras: tuple[str, float, float]) -> Segmento:
    return Segmento(
        id=id_,
        t_inicio=palabras[0][1],
        t_fin=palabras[-1][2],
        texto=" ".join(w for w, _, _ in palabras),
        palabras=[Palabra(w=w, t=t, t_fin=f) for w, t, f in palabras],
    )


# Dos pasos del video con la frontera en 4.0 s; el segmento 1 de Whisper la cruza: lleva el
# final del paso 1 ("de nitrilo y los lentes.") y el inicio del 2 ("Ahora cierro la llave").
TRANSCRIPCION = [
    _seg(0, ("Me", 0.0, 0.3), ("pongo", 0.3, 0.6), ("los", 0.6, 0.8), ("guantes", 0.8, 1.4)),
    _seg(
        1,
        ("de", 1.5, 1.7),
        ("nitrilo", 1.7, 2.2),
        ("y", 2.3, 2.4),
        ("los", 2.4, 2.6),
        ("lentes.", 2.6, 4.0),
        ("Ahora", 4.0, 4.3),  # empieza justo donde termina el paso 1: es del paso 2
        ("cierro", 4.3, 4.7),
        ("la", 4.7, 4.8),
        ("llave", 4.8, 5.2),
    ),
    _seg(
        2,
        ("de", 5.2, 5.4),
        ("paso", 5.4, 5.8),
        ("y", 5.9, 6.0),
        ("espero", 6.0, 6.5),
        ("que", 6.5, 6.6),
        ("el", 6.6, 6.7),
        ("manómetro", 6.7, 7.4),
        ("marque", 7.4, 7.9),
        ("cero.", 7.9, 9.0),
    ),
    _seg(
        3,
        ("Por", 12.0, 12.2),
        ("último", 12.2, 12.6),
        ("anoto", 12.6, 13.0),
        ("la", 13.0, 13.1),
        ("lectura", 13.1, 13.6),
        ("en", 13.6, 13.7),
        ("la", 13.7, 13.8),
        ("bitácora.", 13.8, 14.5),
    ),
]


def _video(numero: int, nombre: str, t_inicio: float, t_fin: float, cita: str) -> PasoVideo:
    return PasoVideo(
        numero=numero,
        nombre=nombre,
        descripcion="Resumen automático del paso.",
        responsable="Técnico",
        t_inicio=t_inicio,
        t_fin=t_fin,
        cita=cita,
        fuente="audio",
        confianza="alta",
    )


PASOS_VIDEO = [
    _video(1, "Ponerse el EPP", 0.0, 4.0, "Me pongo los guantes"),
    _video(2, "Cerrar la llave", 4.0, 9.0, "Ahora cierro la llave de paso"),
    _video(3, "Anotar la lectura", 12.0, 14.5, "anoto la lectura en la bitácora"),
]
PASOS_SOP = [
    PasoSOP(
        numero=1,
        nombre="Colocarse el equipo de protección",
        descripcion="Guantes de nitrilo y lentes de seguridad.",
        responsable="Técnico",
        equipo=["guantes de nitrilo", "lentes de seguridad"],
    ),
    PasoSOP(
        numero=2,
        nombre="Cerrar la válvula de suministro",
        descripcion="Cerrar la llave de paso y confirmar presión cero.",
        responsable="Técnico",
        puntos_validacion=["El manómetro marca 0 bar"],
    ),
    PasoSOP(
        numero=3,
        nombre="Registrar la lectura",
        descripcion="Anotar la lectura en la bitácora.",
        responsable="Técnico",
    ),
]
NARRACION_LLAVE = "Ahora cierro la llave de paso y espero que el manómetro marque cero."


def decision(
    veredicto: str = "Cumple",
    cita: str = "cierro la llave de paso",
    justificacion: str = "Cierra la llave y espera la presión cero, como pide el SOP.",
) -> dict[str, str]:
    """Respuesta del juez como la devolvería el LLM."""
    return {"cita": cita, "justificacion": justificacion, "veredicto": veredicto}


def cliente(*respuestas: Any, peticiones: list | None = None) -> ClienteLLM:
    """Cliente con Ollama simulado: cada petición recibe la siguiente respuesta (la última se
    repite). Un dict es el JSON del juez, un str el contenido crudo y una excepción, un fallo
    de transporte."""
    cola = list(respuestas)

    def manejador(request: httpx.Request) -> httpx.Response:
        if peticiones is not None:
            peticiones.append(json.loads(request.content))
        respuesta = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(respuesta, Exception):
            raise respuesta
        contenido = respuesta if isinstance(respuesta, str) else json.dumps(respuesta)
        return httpx.Response(
            200, json={"model": "falso", "message": {"role": "assistant", "content": contenido}}
        )

    return ClienteLLM("http://ollama.test:11434", "falso", transport=httpx.MockTransport(manejador))


def clasificacion(
    *pares: tuple[int, int, float], sop_sin_pareja=(), video_sin_pareja=()
) -> Clasificacion:
    """`clasificar` real sobre una asignación hecha a mano."""
    asignacion = emp.Asignacion(
        [Par(indice_sop=i, indice_video=j, similitud=s) for i, j, s in pares],
        list(sop_sin_pareja),
        list(video_sin_pareja),
    )
    return emp.clasificar(asignacion, PASOS_SOP, PASOS_VIDEO)


def aplicar(c: Clasificacion, llm: ClienteLLM) -> Clasificacion:
    return jz.aplicar_juez(c, PASOS_SOP, PASOS_VIDEO, TRANSCRIPCION, jz.JuezGemma(llm))


# El par 1 (cerrar la llave) en zona gris; los otros dos, Cumple.
UN_PAR_GRIS = ((0, 0, 0.9), (1, 1, 0.66), (2, 2, 0.9))


# ── Narración del paso ───────────────────────────────────────────────────────────────────────


def test_la_narracion_se_corta_por_palabra_y_no_por_segmento():
    assert jz.narracion_de(PASOS_VIDEO[0], TRANSCRIPCION) == (
        "Me pongo los guantes de nitrilo y los lentes."
    )
    assert jz.narracion_de(PASOS_VIDEO[1], TRANSCRIPCION) == NARRACION_LLAVE


def test_la_narracion_no_lleva_tiempos():
    narracion = jz.narracion_de(PASOS_VIDEO[1], TRANSCRIPCION)
    assert re.search(r"\d", narracion) is None


def test_segmento_sin_palabras_cuenta_solo_si_cae_entero_en_el_paso():
    dentro = Segmento(id=0, t_inicio=4.5, t_fin=6.0, texto="cierro la llave")
    cruza = Segmento(id=1, t_inicio=8.0, t_fin=10.0, texto="y sigo con otra cosa")
    assert jz.narracion_de(PASOS_VIDEO[1], [dentro, cruza]) == "cierro la llave"


# ── Los tres veredictos ──────────────────────────────────────────────────────────────────────


def test_cumple():
    peticiones: list = []
    resultado = aplicar(clasificacion(*UN_PAR_GRIS), cliente(decision(), peticiones=peticiones))

    paso = resultado.pasos[1]
    assert paso.estado == "Cumple"
    assert paso.juicio is not None
    assert (paso.juicio.origen, paso.juicio.veredicto, paso.juicio.intentos) == ("llm", "Cumple", 1)
    assert paso.juicio.cita == "cierro la llave de paso"
    assert paso.juicio.similitud == pytest.approx(0.66)
    assert paso.juicio.prompt == jz.PROMPT
    # La cita del resultado sigue siendo la del paso del video (regla 4).
    assert paso.cita == PASOS_VIDEO[1].cita and paso.t_inicio == PASOS_VIDEO[1].t_inicio
    assert len(peticiones) == 1
    assert resultado.resumen.juez == {"Cumple": 1, "Parcial": 0, "no_corresponde": 0, "respaldo": 0}
    assert resultado.resumen.pares_llm == 1
    assert resultado.resumen.conteo["Cumple"] == 3


def test_parcial_y_orden_lo_revisa():
    resultado = aplicar(
        clasificacion(*UN_PAR_GRIS),
        cliente(decision("Parcial", justificacion="Cierra la llave, no confirma los 0 bar.")),
    )

    paso = resultado.pasos[1]
    assert paso.estado == "Parcial"
    assert paso.juicio is not None and paso.juicio.veredicto == "Parcial"
    assert resultado.resumen.juez is not None and resultado.resumen.juez["Parcial"] == 1
    assert emp.orden(resultado).resumen.fuera_de_orden == 0


def test_no_corresponde_rompe_el_par_en_falta_y_sobra():
    # SOP 0 y 1 emparejados (el 1 en zona gris); el paso 2 del video ya era Sobra.
    c = jz.aplicar_juez(
        emp.clasificar(
            emp.Asignacion(
                [
                    Par(indice_sop=0, indice_video=0, similitud=0.9),
                    Par(indice_sop=1, indice_video=1, similitud=0.66),
                ],
                [],
                [2],
            ),
            PASOS_SOP[:2],
            PASOS_VIDEO,
        ),
        PASOS_SOP[:2],
        PASOS_VIDEO,
        TRANSCRIPCION,
        jz.JuezGemma(cliente(decision("no_corresponde"))),
    )

    assert [(p.estado, p.indice_sop, p.indice_video) for p in c.pasos] == [
        ("Cumple", 0, 0),
        ("Falta", 1, None),
        ("Sobra", None, 1),  # en el orden del video, antes del Sobra que ya estaba
        ("Sobra", None, 2),
    ]
    falta, sobra = c.pasos[1], c.pasos[2]
    assert falta.juicio is not None and falta.juicio.veredicto == "no_corresponde"
    assert sobra.juicio == falta.juicio
    assert (sobra.t_inicio, sobra.cita) == (PASOS_VIDEO[1].t_inicio, PASOS_VIDEO[1].cita)
    assert falta.cita == "" and falta.t_inicio is None
    assert c.resumen.juez == {"Cumple": 0, "Parcial": 0, "no_corresponde": 1, "respaldo": 0}
    assert (c.resumen.conteo["Falta"], c.resumen.conteo["Sobra"]) == (1, 2)
    assert (c.resumen.pares, c.resumen.pares_llm) == (2, 1)


def test_pares_fuera_de_la_zona_gris_no_van_al_juez():
    peticiones: list = []
    c = aplicar(
        clasificacion((0, 0, 0.9), (1, 1, 0.3), (2, 2, 0.9)),
        cliente(decision(), peticiones=peticiones),
    )
    assert peticiones == []
    assert c.resumen.juez == dict.fromkeys(("Cumple", "Parcial", "no_corresponde", "respaldo"), 0)


# ── Cita verificada por código (regla 4) ─────────────────────────────────────────────────────


def test_cita_inventada_se_rechaza_y_se_reintenta():
    peticiones: list = []
    inventada = "cierro la válvula principal muy despacio"
    resultado = aplicar(
        clasificacion(*UN_PAR_GRIS),
        cliente(decision(cita=inventada), decision(), peticiones=peticiones),
    )

    paso = resultado.pasos[1]
    assert paso.estado == "Cumple"
    assert paso.juicio is not None and paso.juicio.intentos == 2
    assert len(peticiones) == 2
    roles = [m["role"] for m in peticiones[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    correccion = peticiones[1]["messages"][-1]["content"]
    assert "no aparece tal cual" in correccion
    assert inventada not in correccion  # el motivo no copia texto


def test_tres_citas_inventadas_dejan_el_par_sin_revisar():
    peticiones: list = []
    resultado = aplicar(
        clasificacion(*UN_PAR_GRIS),
        cliente(decision(cita="cierro la válvula principal muy despacio"), peticiones=peticiones),
    )

    paso = resultado.pasos[1]
    assert paso.estado == "zona_gris"
    assert paso.juicio is not None
    assert (paso.juicio.origen, paso.juicio.motivo) == ("respaldo", "respuesta_invalida")
    assert paso.juicio.veredicto is None and paso.juicio.cita == ""
    assert len(peticiones) == jz.MAX_INTENTOS
    assert resultado.resumen.juez is not None and resultado.resumen.juez["respaldo"] == 1


def test_cita_de_otra_parte_del_video_se_rechaza():
    cita = "anoto la lectura en la bitácora"
    assert contiene_cita(" ".join(s.texto for s in TRANSCRIPCION), cita)  # sí está en el video

    juicio = jz.JuezGemma(cliente(decision(cita=cita))).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )

    assert (juicio.origen, juicio.motivo) == ("respaldo", "respuesta_invalida")


def test_cita_del_paso_vecino_en_un_segmento_que_cruza_la_frontera_se_rechaza():
    cita = "Ahora cierro la llave"  # del paso 2, en el segmento 1 que también toca el paso 1
    assert contiene_cita(TRANSCRIPCION[1].texto, cita)  # cortar por segmento la dejaría pasar
    peticiones: list = []

    c = aplicar(
        clasificacion((0, 0, 0.66), (1, 1, 0.9), (2, 2, 0.9)),
        cliente(decision(cita=cita), peticiones=peticiones),
    )

    paso = c.pasos[0]
    assert paso.estado == "zona_gris"
    assert paso.juicio is not None and paso.juicio.motivo == "respuesta_invalida"
    enviado = peticiones[0]["messages"][1]["content"]
    assert "Ahora" not in enviado and "lentes." in enviado


def test_cita_puede_diferir_en_acentos_y_puntuacion():
    juicio = jz.JuezGemma(cliente(decision(cita="espero que el MANOMETRO marque cero"))).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )
    assert juicio.origen == "llm"


def test_cita_corta_se_rechaza_y_la_larga_se_recorta():
    corta = jz.JuezGemma(cliente(decision(cita="la llave"))).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )
    assert corta.motivo == "respuesta_invalida"

    doble = f"{NARRACION_LLAVE} {NARRACION_LLAVE}"  # 26 palabras
    larga = jz.JuezGemma(cliente(decision(cita=doble))).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, doble
    )
    assert larga.origen == "llm"
    assert len(larga.cita.split()) == jz.PALABRAS_CITA[1]


def test_justificacion_larga_se_recorta_y_vacia_se_rechaza():
    larga = jz.JuezGemma(cliente(decision(justificacion="muy " * 200))).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )
    assert len(larga.justificacion) <= jz.MAX_JUSTIFICACION + 1
    assert larga.justificacion.endswith("…")

    vacia = jz.JuezGemma(cliente(decision(justificacion="  "))).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )
    assert vacia.motivo == "respuesta_invalida"


# ── Respuestas inválidas y Ollama caído ──────────────────────────────────────────────────────


def test_json_invalido_se_reintenta():
    peticiones: list = []
    juicio = jz.JuezGemma(cliente('{"cita": "cierro', decision(), peticiones=peticiones)).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )

    assert (juicio.origen, juicio.intentos) == ("llm", 2)
    # El cliente no expone el texto de un JSON roto: solo se agrega la corrección.
    assert [m["role"] for m in peticiones[1]["messages"]] == ["system", "user", "user"]
    assert "JSON válido" in peticiones[1]["messages"][-1]["content"]


@pytest.mark.parametrize(
    "datos",
    [
        {"cita": "cierro la llave de paso", "justificacion": "Bien."},
        {**decision(), "veredicto": "Cumple parcialmente"},
        {**decision(), "extra": 1},
        ["no", "es", "un", "objeto"],
    ],
    ids=["sin_veredicto", "veredicto_desconocido", "campo_extra", "lista"],
)
def test_respuesta_fuera_del_esquema_se_rechaza(datos):
    with pytest.raises(jz.RespuestaInvalida) as exc:
        jz.validar_respuesta(datos, NARRACION_LLAVE)
    assert "cierro" not in str(exc.value)  # solo campos y tipos de error


def test_ollama_caido_deja_los_pares_sin_revisar_y_no_insiste_en_la_corrida():
    peticiones: list = []
    resultado = aplicar(
        clasificacion((0, 0, 0.62), (1, 1, 0.66), (2, 2, 0.9)),
        cliente(httpx.ConnectError("sin conexión"), peticiones=peticiones),
    )

    grises = [p for p in resultado.pasos if p.estado == "zona_gris"]
    assert len(grises) == 2
    for paso in grises:
        assert paso.juicio is not None
        assert (paso.juicio.origen, paso.juicio.motivo) == ("respaldo", "llm_no_disponible")
    assert [p.juicio.intentos for p in grises if p.juicio] == [1, 0]
    assert [p.juicio.similitud for p in grises if p.juicio] == pytest.approx([0.62, 0.66])
    assert len(peticiones) == 2  # el reintento de transporte del cliente, solo en el primer par
    assert resultado.resumen.juez is not None and resultado.resumen.juez["respaldo"] == 2


def test_ollama_caido_se_recuerda_solo_durante_una_corrida():
    peticiones: list = []
    arriba = {"valor": False}

    def manejador(request: httpx.Request) -> httpx.Response:
        peticiones.append(json.loads(request.content))
        if not arriba["valor"]:
            raise httpx.ConnectError("sin conexión")
        return httpx.Response(
            200, json={"model": "falso", "message": {"content": json.dumps(decision())}}
        )

    llm = ClienteLLM("http://ollama.test:11434", "falso", transport=httpx.MockTransport(manejador))
    juez = jz.JuezGemma(llm)
    pares = ((0, 0, 0.62), (1, 1, 0.66), (2, 2, 0.9))

    primera = jz.aplicar_juez(clasificacion(*pares), PASOS_SOP, PASOS_VIDEO, TRANSCRIPCION, juez)
    assert primera.resumen.juez is not None and primera.resumen.juez["respaldo"] == 2
    assert len(peticiones) == 2

    arriba["valor"] = True
    # El primer par cita "cierro la llave de paso", que no está en su narración: tres intentos.
    segunda = jz.aplicar_juez(clasificacion(*pares), PASOS_SOP, PASOS_VIDEO, TRANSCRIPCION, juez)
    # El mismo juez vuelve a llamar al LLM: 3 intentos del primer par y 1 del segundo.
    assert len(peticiones) == 2 + jz.MAX_INTENTOS + 1
    assert segunda.pasos[1].estado == "Cumple"


def test_sin_narracion_no_llama_al_llm():
    peticiones: list = []
    hueco = _video(4, "Paso sin voz", 9.5, 11.0, "")
    juicio = jz.JuezGemma(cliente(decision(), peticiones=peticiones)).juzgar(
        PASOS_SOP[1], hueco, 0.6, jz.narracion_de(hueco, TRANSCRIPCION)
    )
    assert (juicio.origen, juicio.motivo, juicio.intentos) == ("respaldo", "sin_narracion", 0)
    assert peticiones == []


# ── Lo que se envía a Ollama ─────────────────────────────────────────────────────────────────


def test_la_peticion_restringe_la_salida_y_fija_la_semilla():
    peticiones: list = []
    jz.JuezGemma(cliente(decision(), peticiones=peticiones)).juzgar(
        PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE
    )

    cuerpo = peticiones[0]
    assert cuerpo["format"] == jz.ESQUEMA_JUEZ
    assert cuerpo["format"]["properties"]["veredicto"]["enum"] == list(VEREDICTOS)
    assert list(cuerpo["format"]["properties"]) == ["cita", "justificacion", "veredicto"]
    assert cuerpo["format"]["additionalProperties"] is False
    assert cuerpo["options"]["seed"] == SEMILLA
    assert cuerpo["options"]["temperature"] == 0


def test_el_prompt_lleva_solo_el_par_sin_tiempos_ni_coseno():
    mensajes = jz.construir_mensajes(
        jz.cargar_prompt(), PASOS_SOP[1], PASOS_VIDEO[1], NARRACION_LLAVE
    )

    assert [m["role"] for m in mensajes] == ["system", "user"]
    usuario = mensajes[1]["content"]
    assert PASOS_SOP[1].nombre in usuario and "El manómetro marca 0 bar" in usuario
    assert NARRACION_LLAVE in usuario
    for otro in (PASOS_SOP[0], PASOS_SOP[2]):  # ni el resto del SOP
        assert otro.nombre not in usuario
    assert re.search(r"\d+[.:]\d", usuario) is None  # ni tiempos ni el coseno
    assert "(ninguno)" in usuario  # el paso 2 del SOP no lista equipo


def test_el_prompt_v1_se_carga_del_paquete():
    prompt = jz.cargar_prompt()
    assert prompt.version == "juez_zona_gris_v1"
    assert '"Parcial"' in prompt.sistema and "o lo hizo de otra forma" not in prompt.sistema
    assert "Juez de la zona gris" not in prompt.sistema  # el preámbulo no se envía
    assert "$motivo" in prompt.correccion.template


PROMPT_MINIMO = """# preámbulo
## sistema
Eres un juez.
## usuario
$sop_nombre $sop_descripcion $sop_puntos $sop_equipo $video_nombre $video_descripcion $narracion
## correccion
Corrige: $motivo
"""


@pytest.mark.parametrize(
    ("texto", "error"),
    [
        (PROMPT_MINIMO.split("## correccion")[0], "secciones"),
        (PROMPT_MINIMO + "## sistema\notra vez\n", "repetida"),
        (PROMPT_MINIMO.replace("$narracion", ""), "marcadores"),
        (PROMPT_MINIMO.replace("$motivo", "$motivo $tiempo"), "marcadores"),
        (PROMPT_MINIMO + "## notas\nalgo\n", "secciones"),
    ],
    ids=["sin_correccion", "repetida", "falta_marcador", "marcador_de_mas", "seccion_de_mas"],
)
def test_prompt_mal_formado_falla(texto, error):
    assert jz.leer_prompt("minimo", PROMPT_MINIMO).version == "minimo"
    with pytest.raises(ValueError, match=error):
        jz.leer_prompt("minimo", texto)


# ── Dentro de emparejar ──────────────────────────────────────────────────────────────────────


class VectorizadorTabla:
    """Devuelve un vector fijo por texto: así se decide qué par cae en la zona gris."""

    def __init__(self, tabla: dict[str, np.ndarray]) -> None:
        self.tabla = tabla

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        return np.stack([self.tabla[s] for s in sentences])


def _base(k: int) -> np.ndarray:
    v = np.zeros(emp.DIMENSION)
    v[k] = 1.0
    return v


def test_emparejar_con_juez_revisa_el_orden_despues(tmp_path: Path):
    # SOP: 1 = cerrar la válvula, 2 = EPP. El video hace el EPP primero (Cumple con el 2) y
    # después cierra la llave (zona gris con el 1): el juez dice Parcial y queda fuera de orden.
    sop = SOP(
        titulo="SOP inventado",
        pasos=[
            PASOS_SOP[1].model_copy(update={"numero": 1}),
            PASOS_SOP[0].model_copy(update={"numero": 2}),
        ],
    )
    video = PASOS_VIDEO[:2]
    tabla = {
        emp.texto_para_embeber(sop.pasos[0]): _base(0),
        emp.texto_para_embeber(sop.pasos[1]): _base(2),
        emp.texto_para_embeber(video[0]): _base(2),
        emp.texto_para_embeber(video[1]): 0.66 * _base(0) + np.sqrt(1 - 0.66**2) * _base(1),
    }
    embedder = emp.Embedder("tabla", tmp_path, cargador=lambda _m, _c: VectorizadorTabla(tabla))
    juez = jz.JuezGemma(cliente(decision("Parcial")))
    emparejador: emp.Emparejador = emp.EmparejadorMiniLM(embedder, juez)

    resultado = emparejador.emparejar(sop, video, transcripcion=TRANSCRIPCION)

    pasos = resultado.clasificacion.pasos
    assert [(p.estado, p.fuera_de_orden) for p in pasos] == [("Parcial", True), ("Cumple", False)]
    assert pasos[0].juicio is not None and pasos[0].juicio.similitud == pytest.approx(0.66)
    assert resultado.clasificacion.resumen.pares_llm == 1
    assert resultado.clasificacion.resumen.fuera_de_orden == 1

    sin_juez = emp.emparejar(sop, video, embedder)
    assert [p.estado for p in sin_juez.clasificacion.pasos] == ["zona_gris", "Cumple"]
    assert sin_juez.clasificacion.resumen.juez is None


def _embedder_tabla(tmp_path: Path, tabla: dict[str, np.ndarray]) -> emp.Embedder:
    return emp.Embedder("tabla", tmp_path, cargador=lambda _m, _c: VectorizadorTabla(tabla))


def test_paso_extra_en_zona_gris_con_un_paso_omitido_deja_de_ir_fuera_de_orden(tmp_path: Path):
    # Caso de ADR-012: el SOP pide EPP → purgar → cerrar; el video hace EPP, cierra y al final
    # anota la lectura (un paso extra) sin purgar. MiniLM empareja "anotar" con "purgar" en zona
    # gris y, como llega al final, `orden` lo marca fuera de orden. El juez dice que no
    # corresponde: el par se rompe en Falta (purgar) + Sobra (anotar) y ya nada va fuera de orden.
    purgar = PasoSOP(
        numero=2, nombre="Purgar la línea", descripcion="Abrir el purgador.", responsable="Técnico"
    )
    sop = SOP(
        titulo="SOP inventado",
        pasos=[PASOS_SOP[0], purgar, PASOS_SOP[1].model_copy(update={"numero": 3})],
    )
    epp, llave, extra = PASOS_VIDEO  # t = 0, 4 y 12 s
    tabla = {
        emp.texto_para_embeber(sop.pasos[0]): _base(0),
        emp.texto_para_embeber(sop.pasos[1]): _base(1),
        emp.texto_para_embeber(sop.pasos[2]): _base(2),
        emp.texto_para_embeber(epp): _base(0),
        emp.texto_para_embeber(llave): _base(2),
        emp.texto_para_embeber(extra): 0.6 * _base(1) + 0.8 * _base(3),  # coseno 0.6 con purgar
    }
    embedder = _embedder_tabla(tmp_path, tabla)

    sin_juez = emp.emparejar(sop, PASOS_VIDEO, embedder).clasificacion
    purgado = sin_juez.pasos[1]
    assert (purgado.estado, purgado.indice_video) == ("zona_gris", 2)
    assert (purgado.fuera_de_orden, purgado.posicion_esperada, purgado.posicion_observada) == (
        True,
        1,
        2,
    )
    assert sin_juez.resumen.fuera_de_orden == 1

    juez = jz.JuezGemma(cliente(decision("no_corresponde", cita="anoto la lectura en la bitácora")))
    con_juez = emp.emparejar(
        sop, PASOS_VIDEO, embedder, juez=juez, transcripcion=TRANSCRIPCION
    ).clasificacion

    assert [(p.estado, p.indice_sop, p.indice_video) for p in con_juez.pasos] == [
        ("Cumple", 0, 0),
        ("Falta", 1, None),
        ("Cumple", 2, 1),
        ("Sobra", None, 2),
    ]
    assert not any(p.fuera_de_orden for p in con_juez.pasos)
    assert con_juez.resumen.fuera_de_orden == 0
    # El Sobra empieza después del último paso emparejado: ADR-016 lo marca como cierre (el
    # riesgo anotado del ADR: un paso extra al final). Sigue en la clasificación.
    assert con_juez.pasos[3].marco_operador == "cierre"
    assert (con_juez.resumen.conteo["Sobra"], con_juez.resumen.marco_operador) == (0, 1)
    assert con_juez.resumen.juez is not None and con_juez.resumen.juez["no_corresponde"] == 1


# ── Tiempo del juez (para el paper) ──────────────────────────────────────────────────────────


def test_el_tiempo_del_juez_se_mide_con_el_reloj():
    lecturas = iter([100.0, 103.25])  # solo dos lecturas: al empezar y al terminar
    resultado = jz.aplicar_juez(
        clasificacion(*UN_PAR_GRIS),
        PASOS_SOP,
        PASOS_VIDEO,
        TRANSCRIPCION,
        jz.JuezGemma(cliente(decision())),
        reloj=lambda: next(lecturas),
    )

    assert resultado.resumen.segundos_juez == pytest.approx(3.25)
    assert emp.orden(resultado).resumen.segundos_juez == pytest.approx(3.25)  # orden lo conserva


def test_el_tiempo_del_juez_se_mide_aunque_ollama_este_caido():
    lecturas = iter([10.0, 10.5])
    resultado = jz.aplicar_juez(
        clasificacion(*UN_PAR_GRIS),
        PASOS_SOP,
        PASOS_VIDEO,
        TRANSCRIPCION,
        jz.JuezGemma(cliente(httpx.ConnectError("sin conexión"))),
        reloj=lambda: next(lecturas),
    )
    assert resultado.resumen.segundos_juez == pytest.approx(0.5)


def test_el_tiempo_del_juez_va_en_el_resumen_de_emparejar_solo_con_juez(tmp_path: Path):
    tabla = {
        emp.texto_para_embeber(PASOS_SOP[1]): _base(0),
        emp.texto_para_embeber(PASOS_VIDEO[1]): 0.66 * _base(0) + np.sqrt(1 - 0.66**2) * _base(1),
    }
    sop = SOP(titulo="SOP inventado", pasos=[PASOS_SOP[1].model_copy(update={"numero": 1})])
    tabla[emp.texto_para_embeber(sop.pasos[0])] = _base(0)
    embedder = _embedder_tabla(tmp_path, tabla)
    video = [PASOS_VIDEO[1].model_copy(update={"numero": 1})]

    sin_juez = emp.emparejar(sop, video, embedder)
    assert sin_juez.clasificacion.resumen.segundos_juez is None

    con_juez = emp.emparejar(
        sop, video, embedder, juez=jz.JuezGemma(cliente(decision())), transcripcion=TRANSCRIPCION
    )
    segundos = con_juez.clasificacion.resumen.segundos_juez
    assert segundos is not None and segundos >= 0
    assert con_juez.clasificacion.pasos[0].estado == "Cumple"


def test_emparejar_con_juez_sin_transcripcion_falla():
    sop = SOP(titulo="SOP inventado", pasos=PASOS_SOP)
    with pytest.raises(ValueError, match="transcripción"):
        emp.emparejar(sop, PASOS_VIDEO, juez=jz.JuezGemma(cliente(decision())))


# ── Gemma 4 real ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.lento
def test_gemma_real_decide_con_una_cita_verificada():
    with ClienteLLM.desde_settings() as llm:
        if not llm.disponible(5.0):
            pytest.skip("Ollama no responde o no tiene el modelo de LLM_MODEL")
        juicio = jz.JuezGemma(llm).juzgar(PASOS_SOP[1], PASOS_VIDEO[1], 0.66, NARRACION_LLAVE)

    assert juicio.origen == "llm", juicio.motivo
    assert juicio.veredicto in VEREDICTOS
    assert contiene_cita(NARRACION_LLAVE, juicio.cita)
