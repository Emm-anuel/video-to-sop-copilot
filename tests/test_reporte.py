"""Porcentaje de cumplimiento y semáforo (RF-19, SOP V1.0 §5.6).

Los resultados se arman a mano con pasos inventados: no hace falta MiniLM ni el juez.
"""

import pytest
from pydantic import ValidationError

from sopvid.contrato import (
    ESTADOS,
    Clasificacion,
    Fusion,
    Juicio,
    MarcoOperador,
    PasoVideo,
    ResultadoEmparejamiento,
    ResultadoPaso,
    ResumenClasificacion,
)
from sopvid.lenguaje import reporte
from sopvid.lenguaje.reporte import porcentaje, semaforo
from sopvid.plataforma import config

FUERA = " fuera"  # sufijo: "Cumple fuera" es un Cumple con la marca de fuera de orden

JUICIO_PARCIAL = Juicio(
    origen="llm",
    veredicto="Parcial",
    justificacion="no menciona el enjuague",
    cita="cita",
    similitud=0.6,
    prompt="juez_zona_gris_v1",
    intentos=1,
)


def _paso_video(i: int) -> PasoVideo:
    return PasoVideo(
        numero=i + 1,
        nombre=f"Paso {i + 1}",
        descripcion="",
        responsable="Operador",
        t_inicio=10.0 * i,
        t_fin=10.0 * i + 5,
        cita=f"cita {i + 1}",
        fuente="audio",
        confianza="alta",
    )


def armar(
    sop: list[str],
    sobras: tuple[MarcoOperador | None, ...] = (),
    indices_sop: list[int] | None = None,
) -> ResultadoEmparejamiento:
    """Resultado con un paso del SOP por elemento de `sop` (su estado, con FUERA si va marcado)
    y un Sobra por elemento de `sobras` (su `marco_operador`). `indices_sop` reemplaza los
    `indice_sop` 0..n-1 para probar clasificaciones incoherentes."""
    indices_sop = list(range(len(sop))) if indices_sop is None else indices_sop
    pasos_video: list[PasoVideo] = []
    pasos: list[ResultadoPaso] = []

    def nuevo_video() -> PasoVideo:
        paso = _paso_video(len(pasos_video))
        pasos_video.append(paso)
        return paso

    for indice_sop, spec in zip(indices_sop, sop, strict=True):
        estado, fuera = spec.removesuffix(FUERA), spec.endswith(FUERA)
        if estado == "Falta":
            pasos.append(ResultadoPaso(estado="Falta", indice_sop=indice_sop))
            continue
        video = nuevo_video()
        pasos.append(
            ResultadoPaso(
                estado=estado,
                indice_sop=indice_sop,
                indice_video=video.numero - 1,
                similitud=0.8,
                t_inicio=video.t_inicio,
                cita=video.cita,
                confianza="alta",
                fuera_de_orden=fuera,
                posicion_esperada=0 if fuera else None,
                posicion_observada=1 if fuera else None,
                juicio=JUICIO_PARCIAL if estado == "Parcial" else None,
            )
        )
    for marco in sobras:
        video = nuevo_video()
        pasos.append(
            ResultadoPaso(
                estado="Sobra",
                indice_video=video.numero - 1,
                t_inicio=video.t_inicio,
                cita=video.cita,
                confianza="alta",
                marco_operador=marco,
            )
        )

    conteo = {e: sum(p.estado == e and p.marco_operador is None for p in pasos) for e in ESTADOS}
    n_pares = sum(p.similitud is not None for p in pasos)
    resumen = ResumenClasificacion(
        conteo=conteo,
        pares=n_pares,
        pares_llm=conteo["zona_gris"],
        pct_pares_llm=100 * conteo["zona_gris"] / n_pares if n_pares else 0.0,
        fuera_de_orden=sum(p.fuera_de_orden for p in pasos),
        marco_operador=sum(p.marco_operador is not None for p in pasos),
    )
    fusiones = [
        Fusion(
            numero=p.numero, originales=[p.numero], paso_sop=1, citas=[p.cita], similitudes=[0.8]
        )
        for p in pasos_video
    ]
    return ResultadoEmparejamiento(
        clasificacion=Clasificacion(pasos=pasos, resumen=resumen),
        fusiones=fusiones,
        pasos_video=pasos_video,
    )


@pytest.fixture
def settings() -> config.Settings:
    """Cortes por defecto (90 / 70), sin leer el `.env` local."""
    return config.Settings(_env_file=None)


# ── porcentaje ───────────────────────────────────────────────────────────────────────────────


def test_todo_cumple_da_100_y_verde(settings):
    pct = porcentaje(armar(["Cumple"] * 4))
    assert pct == 100.0
    assert semaforo(pct, settings) == "verde"


@pytest.mark.parametrize(
    ("estado", "puntos"),
    [
        ("Cumple" + FUERA, 0.5),
        ("Parcial", 0.5),
        ("Parcial" + FUERA, 0.5),  # la marca no se suma: 0.5 una sola vez, no 0.25
        ("zona_gris", 0.0),
        ("zona_gris" + FUERA, 0.0),
        ("Falta", 0.0),
    ],
)
def test_puntos_de_un_paso_del_sop(estado, puntos):
    assert porcentaje(armar([estado])) == 100 * puntos


def test_mezcla_de_estados():
    # (1 + 0.5 + 0.5 + 0.5 + 0 + 0) / 6
    resultado = armar(
        ["Cumple", "Cumple" + FUERA, "Parcial", "Parcial" + FUERA, "Falta", "zona_gris"]
    )
    assert porcentaje(resultado) == pytest.approx(100 * 2.5 / 6)


@pytest.mark.parametrize("marco", [None, "intro", "cierre"])
def test_los_sobra_no_restan(marco):
    assert porcentaje(armar(["Cumple", "Parcial"], sobras=(marco, marco))) == 75.0


@pytest.mark.parametrize(
    ("sop", "esperado"),
    [
        (["Cumple"] * 9 + ["Falta"], 90.0),  # 9 de 10
        (["Cumple"] * 4 + ["Parcial"], 90.0),  # 4.5 de 5
        (["Cumple"] * 7 + ["Falta"] * 3, 70.0),
        (["Cumple"] * 3 + ["Parcial"] + ["Falta"], 70.0),  # 3.5 de 5
    ],
)
def test_bordes_exactos_salen_exactos(sop, esperado, settings):
    pct = porcentaje(armar(sop))
    assert pct == esperado  # igualdad exacta, sin approx
    assert semaforo(pct, settings) == ("verde" if esperado == 90 else "amarillo")


def test_sop_sin_pasos_falla():
    with pytest.raises(ValueError, match="no tiene pasos del SOP"):
        porcentaje(armar([], sobras=(None,)))


@pytest.mark.parametrize("indices", [[0, 0], [1, 2], [0, 2], [1]])
def test_indices_del_sop_incoherentes_fallan(indices):
    with pytest.raises(ValueError, match="indice_sop"):
        porcentaje(armar(["Cumple"] * len(indices), indices_sop=indices))


def test_indices_del_sop_desordenados_son_validos():
    assert porcentaje(armar(["Cumple", "Falta"], indices_sop=[1, 0])) == 50.0


# ── semaforo ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pct", "color"),
    [
        (100.0, "verde"),
        (90.0, "verde"),
        (89.99, "amarillo"),
        (70.0, "amarillo"),
        (69.99, "rojo"),
        (0.0, "rojo"),
    ],
)
def test_semaforo_con_los_cortes_por_defecto(pct, color, settings):
    assert semaforo(pct, settings) == color


@pytest.mark.parametrize(
    ("pct", "color"), [(80.0, "verde"), (79.99, "amarillo"), (50.0, "amarillo"), (49.99, "rojo")]
)
def test_semaforo_con_cortes_cambiados(pct, color):
    settings = config.Settings(_env_file=None, semaforo_verde=80, semaforo_amarillo=50)
    assert semaforo(pct, settings) == color


def test_semaforo_sin_settings_usa_la_configuracion(monkeypatch):
    settings = config.Settings(_env_file=None, semaforo_verde=60, semaforo_amarillo=40)
    monkeypatch.setattr(reporte, "get_settings", lambda: settings)
    assert semaforo(60.0) == "verde"
    assert semaforo(59.0) == "amarillo"


# ── Cortes en la configuración (RNF-14) ──────────────────────────────────────────────────────


def test_cortes_por_defecto(monkeypatch):
    for variable in ("SEMAFORO_VERDE", "SEMAFORO_AMARILLO"):
        monkeypatch.delenv(variable, raising=False)
    settings = config.Settings(_env_file=None)
    assert (settings.semaforo_verde, settings.semaforo_amarillo) == (90, 70)


def test_cortes_se_leen_del_entorno(monkeypatch):
    monkeypatch.setenv("SEMAFORO_VERDE", "85")
    monkeypatch.setenv("SEMAFORO_AMARILLO", "60.5")
    settings = config.Settings(_env_file=None)
    assert (settings.semaforo_verde, settings.semaforo_amarillo) == (85, 60.5)


@pytest.mark.parametrize("cortes", [{"semaforo_verde": 70}, {"semaforo_verde": 60}])
def test_verde_no_mayor_que_amarillo_falla(cortes):
    with pytest.raises(ValidationError, match="SEMAFORO_VERDE"):
        config.Settings(_env_file=None, **cortes)


@pytest.mark.parametrize(
    "cortes",
    [
        {"semaforo_verde": 100.1},
        {"semaforo_verde": -1, "semaforo_amarillo": -2},
        {"semaforo_amarillo": -0.1},
        {"semaforo_verde": 101, "semaforo_amarillo": 95},
    ],
)
def test_cortes_fuera_de_0_a_100_fallan(cortes):
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None, **cortes)
