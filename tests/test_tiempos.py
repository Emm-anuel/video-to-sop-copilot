"""Tiempos del reporte (RF-16, ADR-021): duración narrada, comparación, total y horario.

Sin LLM ni MiniLM: el horario usa el vectorizador por palabras de `tests/dobles.py`. Las frases son
inventadas por el equipo (nada del cliente).
"""

import pytest

from apoyo import fila, pasos_del_video, resultado, sop_de_prueba
from dobles import embedder_palabras
from sopvid.contrato import (
    SOP,
    Contexto,
    Dato,
    Fusion,
    Juicio,
    PasoSOP,
    PasoVideo,
    ResultadoEmparejamiento,
    Resumen,
    Segmento,
    TiempoFila,
)
from sopvid.lenguaje.tiempos import (
    comparar,
    comparar_horario,
    duracion_en_texto,
    duracion_narrada,
    esperado_total,
    numeros_a_cifras,
    tiempo_de_paso,
    tiempo_total,
    tiempos_por_paso,
)

TOL = 0.20

# ── Duración narrada: tabla de frases ────────────────────────────────────────────────────────

CON_DURACION = [
    # español, cifra
    ("Esto tarda unos 5 minutos.", 5.0, "tarda unos 5 minutos"),
    ("Tarda como 30 segundos en salir el aire.", 0.5, "Tarda como 30 segundos"),
    ("Tardó 1,5 minutos en vaciarse.", 1.5, "Tardó 1,5 minutos"),
    ("Espera 2 horas antes de usarlo.", 120.0, "Espera 2 horas"),
    ("Son 5 minutos de espera.", 5.0, "5 minutos de espera"),
    # español, letra y giros
    ("Espero media hora a que seque.", 30.0, "Espero media hora"),
    ("Lo dejo un par de minutos.", 2.0, "dejo un par de minutos"),
    ("Toma un minuto y medio.", 1.5, "Toma un minuto y medio"),
    ("Espero veinticinco segundos.", 25 / 60, "Espero veinticinco segundos"),
    ("Espero treinta y cinco segundos.", 35 / 60, "Espero treinta y cinco segundos"),
    ("Esperamos un cuarto de hora.", 15.0, "Esperamos un cuarto de hora"),
    ("Dura más o menos medio minuto.", 0.5, "Dura más o menos medio minuto"),
    ("Tarda un minuto y treinta segundos.", 1.5, "Tarda un minuto y treinta segundos"),
    ("Lo dejo reposar durante una hora y media.", 90.0, "reposar durante una hora y media"),
    # español, rangos
    ("Tarda entre 5 y 10 minutos.", 7.5, "Tarda entre 5 y 10 minutos"),
    ("Dura de cinco a diez minutos.", 7.5, "Dura de cinco a diez minutos"),
    ("Espero 5-10 minutos.", 7.5, "Espero 5-10 minutos"),
    # inglés
    ("It takes about 5 minutes.", 5.0, "takes about 5 minutes"),
    ("Wait for half an hour.", 30.0, "Wait for half an hour"),
    ("It takes 5 to 10 minutes.", 7.5, "takes 5 to 10 minutes"),
    ("It usually takes between five and ten minutes.", 7.5, "takes between five and ten minutes"),
    ("Let it sit for twenty-five minutes.", 25.0, "sit for twenty-five minutes"),
    ("It takes a minute and a half.", 1.5, "takes a minute and a half"),
    ("This takes one and a half minutes.", 1.5, "takes one and a half minutes"),
    ("Wait a couple of minutes.", 2.0, "Wait a couple of minutes"),
    ("It takes a quarter of an hour.", 15.0, "takes a quarter of an hour"),
    ("It lasts 2 minutes and 30 seconds.", 2.5, "lasts 2 minutes and 30 seconds"),
    ("Then a 5-minute wait.", 5.0, "5-minute wait"),
]

SIN_DURACION = [
    "El manómetro marca menos de 2 bar.",
    "El manómetro marca cuatro bar.",
    "Le doy un cuarto de vuelta con la llave.",
    "Presiono tres segundos el botón.",
    "Mantengo presionado el botón durante tres segundos.",
    "Caliento el agua durante 5 minutos.",  # sin verbo de duración: cae al tiempo medido
    "Espero. Son 5 minutos.",  # el disparador está en otra cláusula
    "Cierro la llave de paso hasta el tope.",
    "Saco dos guantes de la caja.",
    "Hold the button for three seconds.",
    "Turn it a quarter of a turn.",
    "The gauge reads 4 bar.",
    "Tarda un ratito.",  # vago a propósito
]


@pytest.mark.parametrize(("frase", "minutos", "cita"), CON_DURACION)
def test_duracion_en_texto_con_duracion(frase: str, minutos: float, cita: str) -> None:
    hallada = duracion_en_texto(frase)
    assert hallada is not None
    assert hallada[0] == pytest.approx(minutos)
    assert hallada[1] == cita
    assert cita in frase  # literal, cortada del original


@pytest.mark.parametrize("frase", SIN_DURACION)
def test_duracion_en_texto_sin_duracion(frase: str) -> None:
    assert duracion_en_texto(frase) is None


def test_tabla_con_al_menos_20_frases() -> None:
    assert len(CON_DURACION) + len(SIN_DURACION) >= 20


def test_mas_de_seis_palabras_entre_disparador_y_cantidad_no_cuenta() -> None:
    assert duracion_en_texto("Espero que la presión del agua baje del todo, cinco minutos") is None
    assert duracion_en_texto("Espero que baje la presión unos cinco minutos")[0] == 5.0


def _seg(id_: int, t: float, t_fin: float, texto: str) -> Segmento:
    return Segmento(id=id_, t_inicio=t, t_fin=t_fin, texto=texto)


TRANSCRIPCION = [
    _seg(0, 0.0, 5.0, "Ahora el paso del secado."),
    _seg(1, 5.0, 10.0, "Lo dejo secar, tarda unos diez minutos."),
    _seg(2, 10.0, 15.0, "Y luego espero dos minutos más."),
    _seg(3, 15.0, 20.0, "Siguiente paso, espero media hora."),
]


def test_duracion_narrada_la_mas_cercana_al_inicio_del_tramo() -> None:
    narrada = duracion_narrada(TRANSCRIPCION, 0.0, 15.0)
    assert narrada is not None
    assert narrada.minutos == 10.0
    assert narrada.cita == "tarda unos diez minutos"  # el disparador más cercano
    assert narrada.t == 5.0  # el inicio de su segmento


def test_duracion_narrada_solo_en_los_segmentos_que_empiezan_en_el_tramo() -> None:
    assert duracion_narrada(TRANSCRIPCION, 10.0, 15.0).minutos == 2.0
    assert duracion_narrada(TRANSCRIPCION, 0.0, 5.0) is None
    # El segmento 3 empieza justo en el fin del tramo: es del paso siguiente.
    assert duracion_narrada(TRANSCRIPCION, 10.0, 15.0).t == 10.0


# ── Comparar con la tolerancia ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("esperado", "observado", "estado"),
    [
        (2.0, 4.0, "excede"),
        (2.0, 2.3, "en_tiempo"),
        (2.0, 1.5, "menor"),
        (None, 3.0, "sin_referencia"),
        (0.0, 3.0, "sin_referencia"),
        (2.0, 2.4, "en_tiempo"),  # justo en el límite de arriba
        (2.0, 1.6, "en_tiempo"),  # justo en el límite de abajo
        (2.0, 2.41, "excede"),
        (2.0, 1.59, "menor"),
        (0.5, 0.6, "en_tiempo"),
    ],
)
def test_comparar(esperado: float | None, observado: float, estado: str) -> None:
    assert comparar(esperado, observado, TOL) == estado


# ── Un paso: medida, narrada y fusión ────────────────────────────────────────────────────────


def _paso(numero: int, t_inicio: float, t_fin: float, cita: str = "Hago el paso.") -> PasoVideo:
    return PasoVideo(
        numero=numero,
        nombre=f"Paso {numero}",
        descripcion=cita,
        responsable="Operador",
        t_inicio=t_inicio,
        t_fin=t_fin,
        cita=cita,
        fuente="audio",
        confianza="alta",
    )


def test_tiempo_medido_sin_narracion() -> None:
    transcripcion = [_seg(0, 0.0, 240.0, "Cierro la válvula y reviso.")]
    tiempo = tiempo_de_paso(_paso(1, 0.0, 240.0), 2.0, transcripcion, TOL)
    assert tiempo == TiempoFila(
        esperado_min=2.0, observado_min=4.0, origen="medido", estado="excede"
    )


def test_la_narrada_gana_si_es_mayor_y_el_origen_lo_indica() -> None:
    # 20 s en el video, pero la espera de 3 minutos ocurre con un corte.
    transcripcion = [_seg(0, 10.0, 30.0, "Aplico el sellador y espero tres minutos.")]
    tiempo = tiempo_de_paso(_paso(1, 10.0, 30.0), 2.0, transcripcion, TOL)
    assert tiempo.origen == "narrado"
    assert tiempo.observado_min == 3.0
    assert tiempo.cita == "espero tres minutos"
    assert tiempo.estado == "excede"


def test_la_narrada_menor_que_la_medida_pierde() -> None:
    # Dice lo que debería tardar, pero en el video tardó 70 s.
    transcripcion = [_seg(0, 0.0, 70.0, "Esto tarda 30 segundos, me pongo los guantes.")]
    tiempo = tiempo_de_paso(_paso(1, 0.0, 70.0), 0.5, transcripcion, TOL)
    assert tiempo.origen == "medido"
    assert tiempo.cita == ""
    assert tiempo.observado_min == pytest.approx(1.17)
    assert tiempo.estado == "excede"


def test_esperado_cero_es_sin_referencia() -> None:
    tiempo = tiempo_de_paso(_paso(1, 0.0, 30.0), 0.0, [], TOL)
    assert tiempo.esperado_min is None
    assert tiempo.estado == "sin_referencia"


def _sop(esperados: list[float | None], total: float | None = None, horario: str | None = None):
    return SOP(
        titulo="Secado de piezas",
        resumen=Resumen(duracion_total_min=total, horario_frecuencia=Dato(valor=horario)),
        pasos=[
            PasoSOP(numero=i, nombre=f"Paso {i}", responsable="Operador", tiempo_esperado_min=e)
            for i, e in enumerate(esperados, start=1)
        ],
    )


def test_paso_fusionado_usa_el_tramo_completo_sin_intro_ni_cierre() -> None:
    # Originales: intro (0–10), paso partido en dos (10–40 y 40–70), paso 2 (70–90), cierre.
    pasos = [
        _paso(1, 0.0, 10.0, "Hola, soy el técnico."),
        _paso(2, 10.0, 70.0, "Pongo la pieza en la rejilla."),  # fusión de los originales 2 y 3
        _paso(3, 70.0, 90.0, "Guardo la pieza seca."),
        _paso(4, 90.0, 95.0, "Listo, terminé."),
    ]
    filas = [
        fila("Cumple", sop=0, video=1, pasos_video=pasos),
        fila("Cumple", sop=1, video=2, pasos_video=pasos),
        fila("Sobra", video=0, pasos_video=pasos, marco_operador="intro"),
        fila("Sobra", video=3, pasos_video=pasos, marco_operador="cierre"),
    ]
    sop = _sop([0.5, 0.5])
    base = resultado(sop, pasos, filas)
    fusiones = [
        Fusion(numero=1, originales=[1], paso_sop=1, citas=[pasos[0].cita], similitudes=[0.2]),
        Fusion(
            numero=2,
            originales=[2, 3],
            paso_sop=1,
            citas=[pasos[1].cita, "Espero a que escurra."],
            similitudes=[0.9, 0.7],
        ),
        Fusion(numero=3, originales=[4], paso_sop=2, citas=[pasos[2].cita], similitudes=[0.9]),
        Fusion(numero=4, originales=[5], paso_sop=2, citas=[pasos[3].cita], similitudes=[0.1]),
    ]
    con_fusion = ResultadoEmparejamiento(
        clasificacion=base.clasificacion, fusiones=fusiones, pasos_video=pasos
    )
    tiempos = tiempos_por_paso(con_fusion, sop, [], TOL)
    assert tiempos[0].observado_min == 1.0  # 10–70 s, sin los 10 s de la intro
    assert tiempos[0].estado == "excede"
    assert tiempos[1].observado_min == pytest.approx(0.33)  # 70–90 s, sin el cierre
    assert tiempos[2] is None and tiempos[3] is None  # intro y cierre: Sobra, sin tiempo


def test_paso_fusionado_busca_la_narrada_en_todo_el_tramo() -> None:
    transcripcion = [
        _seg(0, 10.0, 40.0, "Pongo la pieza en la rejilla."),
        _seg(1, 40.0, 70.0, "La dejo escurrir cinco minutos."),
    ]
    tiempo = tiempo_de_paso(_paso(2, 10.0, 70.0), 0.5, transcripcion, TOL)
    assert (tiempo.origen, tiempo.observado_min, tiempo.cita) == (
        "narrado",
        5.0,
        "dejo escurrir cinco minutos",
    )


# ── Filas y total ────────────────────────────────────────────────────────────────────────────


def _resultado_con_falta_y_sobra():
    # SOP de 3 pasos; el 2 falta; el video tiene un paso de más (Sobra, sin marco).
    pasos = pasos_del_video(
        ("Primero preparo el filtro nuevo.", "Limpio la mesa.", "Al final anoto la lectura.")
    )
    filas = [
        fila("Cumple", sop=0, video=0, pasos_video=pasos),
        fila("Falta", sop=1, pasos_video=pasos),
        fila("Parcial", sop=2, video=2, pasos_video=pasos, juicio=_juicio()),
        fila("Sobra", video=1, pasos_video=pasos),
    ]
    return pasos, filas


def _juicio() -> Juicio:
    return Juicio(
        origen="llm",
        veredicto="Parcial",
        justificacion="no dice qué anota",
        cita="anoto la lectura",
        similitud=0.7,
        prompt="juez_zona_gris_v1",
        intentos=1,
    )


def test_total_con_un_falta_y_un_sobra() -> None:
    sop = _sop([0.1, 0.1, 0.1], total=0.3)
    pasos, filas = _resultado_con_falta_y_sobra()
    res = resultado(sop, pasos, filas)
    tiempos = tiempos_por_paso(res, sop, [], TOL)
    assert [t is not None for t in tiempos] == [True, False, True, False]
    total = tiempo_total(tiempos, sop, TOL)
    # Solo los pares suman (el Sobra de 5 s y el Falta no), y se suman las filas tal como se
    # muestran: 0.08 + 0.08.
    assert total.observado_min == pytest.approx(0.16)
    assert total.esperado_min == 0.3
    assert total.estado == "menor"


def test_total_contra_la_suma_de_los_esperados_si_el_sop_no_trae_total() -> None:
    assert esperado_total(_sop([0.5, 1.0, 0.5])) == 2.0
    # Si algún paso no tiene tiempo, la suma sería parcial: sin referencia.
    assert esperado_total(_sop([0.5, None, 0.5])) is None


def test_total_sin_referencia() -> None:
    sop = sop_de_prueba()
    pasos = pasos_del_video()
    filas = [fila("Cumple", sop=i, video=i, pasos_video=pasos) for i in range(3)]
    tiempos = tiempos_por_paso(resultado(sop, pasos, filas), sop, [], TOL)
    assert all(t is not None and t.estado == "sin_referencia" for t in tiempos)
    total = tiempo_total(tiempos, sop, TOL)
    assert (total.esperado_min, total.estado) == (None, "sin_referencia")
    assert total.observado_min == 0.24  # 3 × 0.08, la suma de lo que muestra la tabla


# ── Horario ──────────────────────────────────────────────────────────────────────────────────

HORARIO_SOP = "Cada tres meses, o cuando el manómetro marque menos de 2 bar"
SEGMENTOS_HORARIO = [_seg(0, 1.5, 6.0, "Toca porque el manómetro marca menos de dos bar.")]


def _contexto(valor: str | None, t: float | None = 1.5) -> Contexto:
    if valor is None:
        return Contexto()
    if t is None:
        return Contexto(horario_mencionado=Dato(valor=valor, fuente="inferido", confianza="baja"))
    return Contexto(horario_mencionado=Dato(valor=valor, fuente="audio", confianza="alta", t=t))


@pytest.fixture
def embedder(tmp_path):
    return embedder_palabras(tmp_path)


def test_horario_coincide_con_una_alternativa_y_numeros_en_letra(embedder) -> None:
    contexto = _contexto("cuando el manómetro marque menos de dos bar")
    horario = comparar_horario(
        _sop([0.5], horario=HORARIO_SOP), contexto, SEGMENTOS_HORARIO, embedder, 0.75
    )
    assert horario.estado == "coincide"
    assert horario.esperado == HORARIO_SOP
    assert horario.t == 1.5
    assert horario.cita == "Toca porque el manómetro marca menos de dos bar."


def test_horario_coincide_por_coseno(embedder) -> None:
    contexto = _contexto("meses tres cada")  # sin contención; mismas palabras
    horario = comparar_horario(
        _sop([0.5], horario=HORARIO_SOP), contexto, SEGMENTOS_HORARIO, embedder, 0.75
    )
    assert horario.estado == "coincide"


def test_horario_distinto(embedder) -> None:
    contexto = _contexto("todos los días al empezar el turno")
    horario = comparar_horario(
        _sop([0.5], horario=HORARIO_SOP), contexto, SEGMENTOS_HORARIO, embedder, 0.75
    )
    assert horario.estado == "distinto"
    assert horario.observado == "todos los días al empezar el turno"


def test_horario_no_mencionado(embedder) -> None:
    sop = _sop([0.5], horario=HORARIO_SOP)
    for contexto in (None, _contexto(None), _contexto("cada tres meses", t=None)):
        horario = comparar_horario(sop, contexto, SEGMENTOS_HORARIO, embedder, 0.75)
        assert horario.estado == "no_mencionado"
        assert horario.observado is None and horario.t is None and horario.cita == ""


def test_horario_sin_referencia(embedder) -> None:
    horario = comparar_horario(
        _sop([0.5]), _contexto("cada tres meses"), SEGMENTOS_HORARIO, embedder, 0.75
    )
    assert horario.estado == "sin_referencia"
    assert horario.esperado is None
    assert horario.observado == "cada tres meses"  # lo dicho se muestra igual


def test_numeros_a_cifras() -> None:
    assert numeros_a_cifras("Cada tres meses") == "cada 3 meses"
    assert numeros_a_cifras("cada treinta y cinco días") == "cada 35 dias"
    assert numeros_a_cifras("every two weeks, a day") == "every 2 weeks a day"
