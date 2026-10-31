"""Pruebas del reporte de validación (RF-19, RF-20) sin base, sin MiniLM y sin Ollama.

El `ResultadoEmparejamiento` se arma a mano con `tests/apoyo.py`: aquí se prueba lo que agrega el
reporte —el porcentaje de la sección 5.6, el semáforo y la tabla con cita y segundo—, no el
emparejamiento.
"""

import pytest
from pydantic import ValidationError

from apoyo import CITAS, fila, pasos_del_video, resultado, sop_de_prueba
from sopvid.contrato import Juicio
from sopvid.lenguaje.reporte import (
    UMBRAL_AMARILLO,
    UMBRAL_VERDE,
    FilaReporte,
    OrigenPasos,
    Reporte,
    armar_reporte,
    porcentaje,
    semaforo,
)

ORIGEN = OrigenPasos(metodo="llm", modelo="gemma4:e4b-it-q4_K_M", pasos=3)


def _juicio_parcial(cita: str, similitud: float = 0.62) -> Juicio:
    return Juicio(
        origen="llm",
        veredicto="Parcial",
        justificacion="Nombra el paso pero no describe cómo cerrar la válvula.",
        cita=cita,
        similitud=similitud,
        prompt="juez_zona_gris_v1",
        modelo="gemma4:e4b-it-q4_K_M",
        intentos=2,
    )


# ── Porcentaje y semáforo (sección 5.6) ──────────────────────────────────────


def test_tres_cumples_dan_cien_por_ciento_y_verde() -> None:
    sop = sop_de_prueba(("Preparar el filtro", "Cerrar la válvula"))
    pasos = pasos_del_video(("Primero preparo el filtro.", "Después cierro la válvula."))
    emparejado = resultado(
        sop,
        pasos,
        [
            fila("Cumple", sop=0, video=0, pasos_video=pasos),
            fila("Cumple", sop=1, video=1, pasos_video=pasos),
        ],
    )

    reporte = armar_reporte(7, sop, emparejado, ORIGEN)

    assert (reporte.cumplimiento, reporte.semaforo) == (100.0, "verde")
    assert reporte.resumen.pares == 2


def test_fuera_de_orden_cuenta_medio_y_falta_cuenta_cero() -> None:
    """Cumple (1) + Cumple fuera de orden (0.5) + Falta (0) sobre 3 pasos del SOP = 50 %."""
    sop = sop_de_prueba()
    pasos = pasos_del_video(("Primero preparo el filtro.", "Después anoto la lectura."))
    emparejado = resultado(
        sop,
        pasos,
        [
            fila("Cumple", sop=0, video=0, pasos_video=pasos),
            fila(
                "Cumple",
                sop=1,
                video=1,
                pasos_video=pasos,
                fuera_de_orden=True,
                posiciones=(1, 0),
            ),
            fila("Falta", sop=2, pasos_video=pasos),
        ],
    )

    assert porcentaje(emparejado, 3) == pytest.approx(50.0)
    reporte = armar_reporte(7, sop, emparejado, ORIGEN)
    assert (reporte.cumplimiento, reporte.semaforo) == (50.0, "rojo")
    assert reporte.faltan == [3]
    assert reporte.resumen.fuera_de_orden == 1
    assert reporte.filas[1].fuera_de_orden is True


def test_los_sobra_no_restan() -> None:
    sop = sop_de_prueba(("Preparar el filtro",))
    pasos = pasos_del_video(("Primero preparo el filtro.", "De paso reviso la manguera."))
    emparejado = resultado(
        sop,
        pasos,
        [
            fila("Cumple", sop=0, video=0, pasos_video=pasos),
            fila("Sobra", video=1, pasos_video=pasos),
        ],
    )

    reporte = armar_reporte(7, sop, emparejado, ORIGEN)

    assert reporte.cumplimiento == 100.0
    assert reporte.sobran == [2]


def test_parcial_con_juicio_cuenta_medio_y_trae_la_justificacion() -> None:
    sop = sop_de_prueba(("Preparar el filtro", "Cerrar la válvula"))
    pasos = pasos_del_video(("Primero preparo el filtro.", "Después cierro la válvula."))
    emparejado = resultado(
        sop,
        pasos,
        [
            fila("Cumple", sop=0, video=0, pasos_video=pasos),
            fila(
                "Parcial",
                sop=1,
                video=1,
                pasos_video=pasos,
                similitud=0.62,
                juicio=_juicio_parcial(CITAS[1]),
            ),
        ],
    )

    reporte = armar_reporte(7, sop, emparejado, ORIGEN)

    assert reporte.cumplimiento == 75.0
    assert reporte.semaforo == "amarillo"
    fila_parcial = reporte.filas[1]
    assert fila_parcial.justificacion.startswith("Nombra el paso")
    assert fila_parcial.confianza == "alta"


@pytest.mark.parametrize(
    ("pct", "esperado"),
    [
        (100.0, "verde"),
        (UMBRAL_VERDE, "verde"),
        (89.99, "amarillo"),
        (UMBRAL_AMARILLO, "amarillo"),
        (69.99, "rojo"),
        (0.0, "rojo"),
    ],
)
def test_semaforo(pct: float, esperado: str) -> None:
    assert semaforo(pct) == esperado


# ── La tabla del reporte (RF-20) ─────────────────────────────────────────────


def test_cada_fila_lleva_su_segundo_su_cita_y_sus_numeros() -> None:
    sop = sop_de_prueba()
    pasos = pasos_del_video(CITAS)
    emparejado = resultado(
        sop,
        pasos,
        [
            fila("Cumple", sop=0, video=0, pasos_video=pasos),
            fila("Falta", sop=1, pasos_video=pasos),
            fila("Sobra", video=2, pasos_video=pasos),
        ],
    )

    reporte = armar_reporte(11, sop, emparejado, ORIGEN, sop_id=4)

    assert [f.orden for f in reporte.filas] == [1, 2, 3]
    assert [f.nombre for f in reporte.filas] == [
        "Preparar el filtro",
        "Cerrar la válvula",
        "Al",  # nombre del paso del video que sobra
    ]
    cumple = reporte.filas[0]
    assert (cumple.paso_sop, cumple.paso_video, cumple.t_inicio, cumple.t_fin) == (1, 1, 0.0, 5.0)
    assert cumple.cita == CITAS[0]
    falta = reporte.filas[1]
    assert (falta.paso_sop, falta.paso_video, falta.t_inicio, falta.cita) == (2, None, None, "")
    sobra = reporte.filas[2]
    assert (sobra.paso_sop, sobra.paso_video, sobra.t_inicio) == (None, 3, 10.0)
    assert (reporte.video_id, reporte.sop_id, reporte.sop_titulo) == (
        11,
        4,
        "Cambio de filtro de agua",
    )
    assert reporte.faltan == [2] and reporte.sobran == [3]
    assert reporte.pasos_del_video == ORIGEN


def test_la_intro_del_operador_no_cuenta_como_sobra_pero_si_aparece() -> None:
    sop = sop_de_prueba(("Preparar el filtro",))
    pasos = pasos_del_video(("Les voy a mostrar cómo cambio el filtro.", CITAS[0]))
    emparejado = resultado(
        sop,
        pasos,
        [
            fila("Sobra", video=0, pasos_video=pasos, marco_operador="intro"),
            fila("Cumple", sop=0, video=1, pasos_video=pasos),
        ],
    )

    reporte = armar_reporte(7, sop, emparejado, ORIGEN)

    assert reporte.sobran == []
    assert reporte.resumen.conteo["Sobra"] == 0
    assert reporte.resumen.marco_operador == 1
    assert len(reporte.filas) == 2
    assert reporte.filas[0].marco_operador == "intro"
    assert reporte.filas[0].cita == "Les voy a mostrar cómo cambio el filtro."
    assert reporte.cumplimiento == 100.0


def test_el_reporte_rechaza_un_semaforo_que_no_corresponde() -> None:
    sop = sop_de_prueba(("Preparar el filtro",))
    pasos = pasos_del_video((CITAS[0],))
    reporte = armar_reporte(
        7,
        sop,
        resultado(sop, pasos, [fila("Cumple", sop=0, video=0, pasos_video=pasos)]),
        ORIGEN,
    )
    datos = reporte.model_dump(mode="json")
    datos["semaforo"] = "rojo"

    with pytest.raises(ValidationError, match="semaforo"):
        Reporte.model_validate(datos)


def test_una_fila_falta_no_puede_llevar_segundo() -> None:
    with pytest.raises(ValidationError, match="tiempos"):
        FilaReporte(orden=1, estado="Falta", nombre="Cerrar la válvula", paso_sop=2, t_inicio=9.0)


# ── Con la cascada de verdad (MiniLM, ~470 MB la primera vez) ────────────────


@pytest.mark.lento
def test_el_reporte_cuadra_con_un_emparejar_de_verdad() -> None:
    """`armar_reporte` sobre la cascada real: mismos conteos, mismas filas, mismo semáforo.

    Se corre con `pytest -m lento`; el resto de la suite usa `tests/apoyo.py` y no carga MiniLM.
    """
    from sopvid.lenguaje.emparejamiento import emparejar

    sop = sop_de_prueba(("Preparar el filtro", "Cerrar la válvula", "Anotar la lectura"))
    pasos = pasos_del_video(CITAS)

    resultado = emparejar(sop, pasos)
    reporte = armar_reporte(1, sop, resultado, OrigenPasos(metodo="heuristica", pasos=len(pasos)))

    assert reporte.resumen == resultado.clasificacion.resumen
    assert len(reporte.filas) == (
        sum(reporte.resumen.conteo.values()) + reporte.resumen.marco_operador
    )
    assert reporte.cumplimiento == round(porcentaje(resultado, len(sop.pasos)), 2)
    assert reporte.semaforo == semaforo(reporte.cumplimiento)
    assert [f.paso_sop for f in reporte.filas if f.paso_sop is not None] == [1, 2, 3]
    # Todo paso del video que sostiene un hallazgo trae su segundo, y son los del video.
    for una in reporte.filas:
        if una.paso_video is not None:
            assert una.t_inicio == pasos[una.paso_video - 1].t_inicio
            assert una.cita == pasos[una.paso_video - 1].cita
