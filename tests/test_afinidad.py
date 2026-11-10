"""Afinidad de contexto (RF-17, ADR-020) con fichas y SOP inventados, sin LLM.

Las pruebas del flujo (detención con "afinidad_baja" y `?continuar=true`) usan la base y los
dobles de tests/dobles.py, como las de la validación.

Por defecto, MiniLM se sustituye por una bolsa de palabras (`dobles.VectorizadorPalabras`): basta
para probar la lógica (componentes, palabras genéricas, evidencia, mapeo y explicación). Las
pruebas "lento" repiten los casos con MiniLM real (`pytest -m lento`) e imprimen los valores, que
se anotan en ADR-020.

Todo es inventado por el equipo (CLAUDE.md §2.1): los SOP son los fixtures de plantilla y las
fichas, las de abajo.
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from dobles import Entorno, embedder_palabras, guardar_sop
from sopvid.contrato import SOP, Contexto, Dato, DetencionAfinidad, Elemento, PasoSOP, Resumen
from sopvid.lenguaje import afinidad as af
from sopvid.lenguaje.emparejamiento import Embedder
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.config import Settings
from sopvid.plataforma.modelos import Reporte

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


# ── Flujo con afinidad baja (ADR-020): procesador y API, con los dobles de tests/dobles.py ───

# Ficha de otro procedimiento: ninguna palabra en común con SOP_PRUEBA ("Revisión de la línea de
# agua"). Las citas van vacías: los datos quedan inferidos, y aun así cuentan.
CONTEXTO_OTRO = {
    "actividad": {"cita": "", "valor": "Preparación de café en la cafetera"},
    "tema": {"cita": "", "valor": "Bebidas"},
    "lugar": {"cita": "", "valor": "Sala de descanso"},
    "horario_mencionado": {"cita": "", "valor": None},
    "proposito": {"cita": "", "valor": "Tener café listo al empezar el turno"},
    "resumen": "Se prepara café.",
    "personas": [],
    "equipos": ["Cafetera", "Jarra"],
}


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


@pytest.fixture
def subir_validar(client: TestClient, entorno: Entorno, generar_video):
    def subir() -> int:
        sop = guardar_sop(entorno.session)
        r = client.post(
            "/videos",
            files={"archivo": ("operador.mp4", generar_video().read_bytes(), "video/mp4")},
            data={"titulo": "Revisión", "modo": "validar", "sop_id": str(sop.id)},
        )
        assert r.status_code == 202
        return r.json()["id"]

    return subir


def _reporte(session: Session, video_id: int) -> Reporte:
    return session.scalars(select(Reporte).where(Reporte.video_id == video_id)).one()


def test_afinidad_baja_detiene_la_validacion_antes_de_segmentar(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.ollama.respuestas_contexto = [CONTEXTO_OTRO]
    video_id = subir_validar()
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert (video.proceso, video.etapa, video.error) == ("afinidad_baja", "afinidad", None)
    assert video.pasos_video is None
    assert video.contexto is not None  # la ficha se guarda: al continuar no se repite
    # Gemma generó la ficha y se descargó; nunca segmentó.
    assert "chat:contexto" in entorno.eventos and "chat:fronteras" not in entorno.eventos
    assert entorno.eventos[-1] == "descargar"

    reporte = _reporte(entorno.session, video_id)
    detencion = DetencionAfinidad.model_validate(reporte.resultado)
    assert reporte.cumplimiento is None and reporte.afinidad == detencion.afinidad.valor
    assert detencion.afinidad.bajo_umbral and detencion.afinidad.valor < 60
    assert "actividad distinta del título (dato inferido)" in detencion.afinidad.explicacion
    assert set(detencion.segundos) >= {"transcripcion", "contexto", "afinidad"}
    # Detenida antes de segmentar: ni personas ni tiempos (ADR-021).
    assert not {"personas", "tiempos"} & set(detencion.segundos)
    assert detencion.dispositivos is not None and detencion.dispositivos.llm == "gpu"

    estado = client.get(f"/videos/{video_id}").json()
    assert estado["proceso"] == "afinidad_baja"
    assert estado["afinidad"] == detencion.afinidad.model_dump(mode="json")
    r = client.get(f"/videos/{video_id}/reporte")
    assert (r.status_code, r.json()["detail"]["proceso"]) == (409, "afinidad_baja")


def test_continuar_da_el_reporte_con_la_afinidad_bajo_el_umbral(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.ollama.respuestas_contexto = [CONTEXTO_OTRO]
    video_id = subir_validar()
    entorno.correr_pendientes()
    afinidad = client.get(f"/videos/{video_id}").json()["afinidad"]

    r = client.post(f"/videos/{video_id}/validar", params={"continuar": "true"})
    assert (r.status_code, r.json()["proceso"]) == (202, "en_cola")
    entorno.correr_pendientes()

    assert entorno.transcriptor.idiomas == [None]  # sin repetir Whisper
    assert entorno.eventos.count("chat:contexto") == 1  # ni la ficha
    assert entorno.video(video_id).proceso == "listo"
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert reporte["afinidad"] == afinidad and reporte["afinidad"]["bajo_umbral"] is True
    assert reporte["cumplimiento"] == 83.33  # la afinidad no cambia el porcentaje (§5.6)
    assert reporte["tiempo_total"] is not None  # al continuar sí se calculan los tiempos
    assert client.get(f"/videos/{video_id}").json()["afinidad"] == afinidad
    fila = _reporte(entorno.session, video_id)
    assert (fila.afinidad, fila.cumplimiento) == (afinidad["valor"], Decimal("83.33"))


def test_repetir_sin_continuar_se_vuelve_a_detener(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.ollama.respuestas_contexto = [CONTEXTO_OTRO]
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert client.post(f"/videos/{video_id}/validar").status_code == 202
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "afinidad_baja"
    assert "chat:fronteras" not in entorno.eventos


def test_sin_ficha_no_hay_afinidad_y_la_validacion_sigue(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.ollama.contexto_caido = True
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "listo"
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert reporte["afinidad"] is None
    assert [a["tipo"] for a in reporte["metadatos"]["avisos"]] == ["contexto_sin_generar"]
    assert client.get(f"/videos/{video_id}").json()["afinidad"] is None
    assert _reporte(entorno.session, video_id).afinidad is None


def test_la_misma_ficha_del_procedimiento_pasa(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()  # CONTEXTO del doble: la actividad es el título del SOP
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "listo"
    afinidad = client.get(f"/videos/{video_id}/reporte").json()["afinidad"]
    assert afinidad["valor"] >= 60 and afinidad["bajo_umbral"] is False
