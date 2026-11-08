"""Afinidad de contexto (RF-17, ADR-020) con fichas y SOP inventados, sin LLM.

Por defecto, MiniLM se sustituye por una bolsa de palabras (`dobles.VectorizadorPalabras`): basta
para probar la lógica (componentes, palabras genéricas, evidencia, mapeo y explicación). Las
pruebas "lento" repiten los casos con MiniLM real (`pytest -m lento`) e imprimen los valores, que
se anotan en ADR-020.

Todo es inventado por el equipo (CLAUDE.md §2.1): los SOP son los fixtures de plantilla y las
fichas, las de abajo.
"""

from pathlib import Path

import pytest

from dobles import embedder_palabras
from sopvid.contrato import SOP, Contexto, Dato, Elemento, PasoSOP, Resumen
from sopvid.lenguaje import afinidad as af
from sopvid.lenguaje.emparejamiento import Embedder
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def _sop(archivo: str) -> SOP:
    return convertir_sop((FIXTURES / archivo).read_text(encoding="utf-8")).sop


def _dato(valor: str, fuente: str = "audio", confianza: str = "alta") -> Dato:
    return Dato(
        valor=valor, fuente=fuente, confianza=confianza, t=None if fuente == "inferido" else 1.0
    )


def _ficha(actividad: str, tema: str, proposito: str, lugar: str | None, equipos: list[str],
           evidencia: dict[str, tuple[str, str]] | None = None) -> Contexto:  # fmt: skip
    """Ficha con datos de audio y confianza alta, salvo los de `evidencia` (fuente, confianza)."""
    evidencia = evidencia or {}
    datos = {"actividad": actividad, "tema": tema, "proposito": proposito, "lugar": lugar}
    return Contexto(
        **{
            campo: _dato(valor, *evidencia.get(campo, ("audio", "alta")))
            for campo, valor in datos.items()
            if valor is not None
        },
        equipos=[Elemento(nombre=e) for e in equipos],
    )


FICHA_FILTRO = _ficha(
    "Cambio del cartucho del filtro de agua",
    "Mantenimiento del filtro de agua",
    "Reemplazar el cartucho del filtro de agua sin fugas",
    "Línea de enjuague",
    ["guantes de nitrilo", "lentes de seguridad", "llave de carcasa", "cubeta", "cartucho nuevo",
     "bolsa de residuos"],
)  # fmt: skip
FICHA_CAFE = _ficha(
    "Preparación de café en cafetera de goteo",
    "Bebidas para el personal",
    "Tener una jarra de café lista al empezar el turno",
    "Sala de descanso",
    ["cafetera", "filtro de papel", "café molido", "jarra"],
)
FICHA_MINISPLIT = _ficha(
    "Cambio del filtro de aire del minisplit",
    "Mantenimiento de aire acondicionado",
    "Reemplazar el filtro de aire para que el equipo enfríe bien",
    "Oficina administrativa",
    ["escalera", "filtro de aire nuevo", "guantes de nitrilo", "paño"],
)

# Dos procedimientos distintos que solo comparten palabras genéricas (línea, máquina, botón,
# panel, equipo).
SOP_ARRANQUE = SOP(
    titulo="Arranque de la máquina llenadora de la línea 2",
    resumen=Resumen(
        objetivo=Dato(valor="Arrancar la llenadora desde el panel de la línea con el botón verde"),
        equipo_operacion=[
            Elemento(nombre="Panel de control"),
            Elemento(nombre="Botón verde"),
            Elemento(nombre="Tolva de botellas"),
        ],
    ),  # fmt: skip
    pasos=[PasoSOP(numero=1, nombre="Encender la llenadora", responsable="Operador de llenado")],
)
FICHA_LIMPIEZA_ETIQUETADORA = _ficha(
    "Limpieza de la máquina etiquetadora de la línea 3",
    "Limpieza del equipo",
    "Quitar el pegamento de los rodillos de la etiquetadora con el botón de paro activado",
    "Línea 3",
    ["botón de paro", "panel", "rodillos", "espátula"],
)


@pytest.fixture
def embedder(tmp_path: Path) -> Embedder:
    return embedder_palabras(tmp_path)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


# ── Casos de aceptación con fichas inventadas ────────────────────────────────────────────────


def test_mismo_procedimiento_supera_el_umbral(embedder: Embedder, settings: Settings) -> None:
    a = af.afinidad(_sop("sop_filtro_agua.md"), FICHA_FILTRO, embedder, settings)
    assert a is not None
    assert a.valor >= settings.afinidad_min and not a.bajo_umbral
    assert set(a.componentes) == {"global", "actividad", "objetivo", "equipos"}
    assert "actividad parecida al título" in a.explicacion


def test_procedimiento_muy_distinto_queda_bajo_el_umbral(
    embedder: Embedder, settings: Settings
) -> None:
    a = af.afinidad(_sop("sop_filtro_agua.md"), FICHA_CAFE, embedder, settings)
    assert a is not None
    assert a.valor < settings.afinidad_min and a.bajo_umbral
    assert "actividad distinta del título" in a.explicacion
    assert "ningún equipo en común" in a.explicacion
    assert "lugar distinto" in a.explicacion


def test_procedimiento_cercano_queda_entre_los_dos(embedder: Embedder, settings: Settings) -> None:
    sop = _sop("sop_filtro_agua.md")
    cercano = af.afinidad(sop, FICHA_MINISPLIT, embedder, settings)
    mismo = af.afinidad(sop, FICHA_FILTRO, embedder, settings)
    distinto = af.afinidad(sop, FICHA_CAFE, embedder, settings)
    assert cercano is not None and mismo is not None and distinto is not None
    # El valor exacto se anota en ADR-020 (con MiniLM, prueba lenta); aquí, solo el orden.
    assert distinto.valor <= cercano.valor < mismo.valor


def test_palabras_genericas_no_suben_la_afinidad(embedder: Embedder, settings: Settings) -> None:
    a = af.afinidad(SOP_ARRANQUE, FICHA_LIMPIEZA_ETIQUETADORA, embedder, settings)
    assert a is not None
    assert a.valor < settings.afinidad_min
    assert "ningún equipo en común" in a.explicacion  # "Panel de control" ≠ "panel"


def test_sin_ficha_no_hay_afinidad(embedder: Embedder, settings: Settings) -> None:
    assert af.afinidad(_sop("sop_filtro_agua.md"), None, embedder, settings) is None


def test_ficha_sin_datos_comparables_no_da_afinidad(embedder: Embedder, settings: Settings) -> None:
    assert af.afinidad(_sop("sop_filtro_agua.md"), Contexto(), embedder, settings) is None


# ── Piezas ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Línea de enjuague", "enjuague"),
        ("Panel de control", "control"),
        ("el botón del panel de la máquina", ""),
        ("Cambio del cartucho del filtro de agua", "Cambio del cartucho del filtro de agua"),
        ("Equipo de protección", "protección"),
        (None, ""),
    ],
)
def test_sin_genericas(texto: str | None, esperado: str) -> None:
    assert af.sin_genericas(texto) == esperado


def test_mapeo_lineal_recortado(settings: Settings) -> None:
    assert af.mapear(settings.afinidad_cos_cero, settings) == 0
    assert af.mapear(settings.afinidad_cos_cien, settings) == 100
    assert af.mapear(-1.0, settings) == 0 and af.mapear(1.0, settings) == 100
    medio = (settings.afinidad_cos_cero + settings.afinidad_cos_cien) / 2
    assert af.mapear(medio, settings) == pytest.approx(50)


def test_el_mapeo_exige_cero_menor_que_cien() -> None:
    with pytest.raises(ValueError, match="AFINIDAD_COS_CERO"):
        Settings(_env_file=None, afinidad_cos_cero=0.8, afinidad_cos_cien=0.8)


def test_un_dato_inferido_pesa_menos(embedder: Embedder, settings: Settings) -> None:
    """La actividad coincide y el propósito no. Con la actividad inferida, el propósito (de
    audio) pesa más en el promedio y la afinidad baja; los componentes no cambian."""

    def ficha(evidencia: dict[str, tuple[str, str]] | None = None) -> Contexto:
        return _ficha(
            "Cambio del cartucho del filtro de agua", "", "Preparar café para la oficina", None,
            [], evidencia,
        )  # fmt: skip

    sop = _sop("sop_filtro_agua.md")
    de_audio = af.afinidad(sop, ficha(), embedder, settings)
    inferida = af.afinidad(sop, ficha({"actividad": ("inferido", "baja")}), embedder, settings)
    assert de_audio is not None and inferida is not None
    assert inferida.componentes["actividad"] == de_audio.componentes["actividad"]
    assert inferida.valor < de_audio.valor
    assert "actividad parecida al título (dato inferido)" in inferida.explicacion
    assert af.factor(Dato(valor="x", fuente="inferido", confianza="alta")) == 0.5


def test_sin_actividad_usa_el_tema(embedder: Embedder, settings: Settings) -> None:
    ficha = _ficha("", "Cambio del cartucho del filtro de agua", "", None, [])
    ficha = ficha.model_copy(update={"actividad": Contexto().actividad})
    a = af.afinidad(_sop("sop_filtro_agua.md"), ficha, embedder, settings)
    assert a is not None and a.componentes["actividad"] == 100


def test_explicacion_de_lo_que_falta(embedder: Embedder, settings: Settings) -> None:
    sop = SOP(
        titulo="Cambio del cartucho del filtro de agua",
        pasos=[PasoSOP(numero=1, nombre="Cerrar la llave", responsable="Técnico")],
    )
    ficha = _ficha("Cambio del cartucho del filtro de agua", "", "", None, ["cubeta"])
    ficha = ficha.model_copy(update={"proposito": Contexto().proposito})
    a = af.afinidad(sop, ficha, embedder, settings)
    assert a is not None
    assert a.explicacion.split("; ") == [
        "actividad parecida al título",
        "objetivo no indicado en el SOP",
        "el SOP no lista equipo",
        "lugar no indicado en el SOP",
    ]
    assert set(a.componentes) == {"global", "actividad"}


def test_equipo_de_los_pasos_si_el_resumen_no_lo_trae(
    embedder: Embedder, settings: Settings
) -> None:
    sop = SOP(
        titulo="Cambio del cartucho",
        pasos=[
            PasoSOP(numero=1, nombre="Aflojar", responsable="Técnico", equipo=["Llave de carcasa"]),
            PasoSOP(numero=2, nombre="Recoger", responsable="Técnico",
                    equipo=["Cubeta", "llave de carcasa"]),
        ],
    )  # fmt: skip
    assert af.equipos_del_sop(sop) == ["Llave de carcasa", "Cubeta"]
    ficha = _ficha("Cambio del cartucho", "", "", None, ["cubeta"])
    a = af.afinidad(sop, ficha, embedder, settings)
    assert a is not None and a.componentes["equipos"] == 50
    assert "1 de 2 equipos del SOP en el video (Cubeta)" in a.explicacion


# ── MiniLM real (lento) ──────────────────────────────────────────────────────────────────────


@pytest.mark.lento
def test_minilm_casos_de_aceptacion(settings: Settings) -> None:
    e = Embedder()
    sop = _sop("sop_filtro_agua.md")
    mismo = af.afinidad(sop, FICHA_FILTRO, e, settings)
    cercano = af.afinidad(sop, FICHA_MINISPLIT, e, settings)
    distinto = af.afinidad(sop, FICHA_CAFE, e, settings)
    genericas = af.afinidad(SOP_ARRANQUE, FICHA_LIMPIEZA_ETIQUETADORA, e, settings)
    for nombre, a in (("mismo", mismo), ("cercano", cercano), ("distinto", distinto),
                      ("genericas", genericas)):  # fmt: skip
        assert a is not None
        print(f"{nombre}: {a.valor} {a.componentes} · {a.explicacion}")
    assert mismo is not None and mismo.valor >= settings.afinidad_min
    assert distinto is not None and distinto.valor < settings.afinidad_min
    assert genericas is not None and genericas.valor < settings.afinidad_min
