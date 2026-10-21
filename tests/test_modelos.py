"""Tablas de la sección 10 contra la base real (requiere `alembic upgrade head`).

Cada test corre en la transacción de `db_session`, que se revierte al final. Solo datos
inventados por el equipo (`tests/fixtures/sop_ejemplo.json`).
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from sopvid.plataforma.db import Base
from sopvid.plataforma.modelos import Busqueda, Palabra, Reporte, Sop, Video

RAIZ = Path(__file__).resolve().parents[1]
SOP_EJEMPLO = RAIZ / "tests" / "fixtures" / "sop_ejemplo.json"
TABLAS = {"sops", "videos", "reportes", "palabras", "busquedas"}


@pytest.fixture
def contenido() -> dict:
    return json.loads(SOP_EJEMPLO.read_text(encoding="utf-8"))


@pytest.fixture
def sop(db_session, contenido) -> Sop:
    sop = Sop(titulo=contenido["titulo"], origen="cargado", contenido=contenido)
    db_session.add(sop)
    db_session.flush()
    return sop


def _video(sop: Sop | None, **cambios) -> Video:
    datos = {"titulo": "Video de prueba", "archivo": "videos/prueba.mp4", "modo": "validar"}
    return Video(sop=sop, **(datos | cambios))


def _reporte(video: Video, sop: Sop, **cambios) -> Reporte:
    datos = {"afinidad": 80, "cumplimiento": Decimal("87.50"), "resultado": {"pasos": []}}
    return Reporte(video=video, sop=sop, **(datos | cambios))


def _palabra(video: Video, posicion: int, **cambios) -> Palabra:
    datos = {
        "palabra_normalizada": "cartucho",
        "palabra_original": "cartucho",
        "t_inicio": 1.0,
        "t_fin": 1.4,
    }
    return Palabra(video_id=video.id, posicion=posicion, **(datos | cambios))


def _falla_al_guardar(session, *objetos) -> None:
    session.add_all(objetos)
    with pytest.raises(IntegrityError):
        session.flush()


# --- Esquema -------------------------------------------------------------------------------


def test_las_cinco_tablas_existen_en_head(engine):
    head = ScriptDirectory.from_config(Config(str(RAIZ / "alembic.ini"))).get_current_head()
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tablas = set(inspect(conn).get_table_names())

    assert version == head, "La base no está en head: corre `alembic upgrade head`"
    assert tablas >= TABLAS


def test_los_modelos_y_la_base_no_tienen_deriva(engine):
    """Si alguien cambia un modelo sin migración (o al revés), esta lista deja de estar vacía."""
    with engine.connect() as conn:
        diferencias = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diferencias == []


# --- sops ----------------------------------------------------------------------------------


def test_sop_guarda_el_contenido_y_genera_el_codigo(db_session, sop, contenido):
    db_session.expire_all()
    leido = db_session.get(Sop, sop.id)

    assert leido.contenido == contenido
    assert leido.codigo == f"SOP-{sop.id:04d}"
    assert leido.creado is not None


def test_codigo_no_se_trunca_con_ids_de_mas_de_cuatro_cifras(db_session, contenido):
    sop = Sop(id=1_234_567, titulo="SOP inventado", origen="generado", contenido=contenido)
    db_session.add(sop)
    db_session.flush()

    assert sop.codigo == "SOP-1234567"


def test_codigo_no_se_puede_escribir_a_mano(db_session):
    # Columna generada: la base rechaza un valor explícito (por eso no puede duplicarse).
    with pytest.raises(ProgrammingError, match="codigo"):
        db_session.execute(
            text(
                "INSERT INTO sops (codigo, titulo, origen, contenido) "
                "VALUES ('SOP-0001', 'x', 'cargado', '{}')"
            )
        )


def test_sop_rechaza_origen_invalido(db_session, contenido):
    _falla_al_guardar(db_session, Sop(titulo="x", origen="importado", contenido=contenido))


# --- videos y reportes ---------------------------------------------------------------------


def test_video_validar_con_reporte_y_relaciones(db_session, sop):
    video = _video(sop, duracion=42.5, idioma="es")
    db_session.add_all([video, _reporte(video, sop)])
    db_session.flush()
    db_session.expire_all()

    leido = db_session.get(Video, video.id)
    assert (leido.proceso, leido.progreso, leido.publicado) == ("en_cola", 0, False)
    assert leido.sop.codigo == sop.codigo
    assert sop.videos == [leido]
    assert leido.reporte.cumplimiento == Decimal("87.50")
    assert leido.reporte.sop is sop
    assert leido.reporte.video is leido


def test_video_generar_puede_no_tener_sop_todavia(db_session):
    video = _video(None, modo="generar")
    db_session.add(video)
    db_session.flush()

    assert video.sop_id is None


@pytest.mark.parametrize(
    "cambios",
    [{"modo": "editar"}, {"proceso": "pausado"}, {"progreso": 150}, {"duracion": -1.0}],
    ids=["modo", "proceso", "progreso", "duracion"],
)
def test_video_rechaza_valores_invalidos(db_session, sop, cambios):
    _falla_al_guardar(db_session, _video(sop, **cambios))


@pytest.mark.parametrize(
    "cambios",
    [{"afinidad": 120}, {"cumplimiento": Decimal("100.01")}, {"cumplimiento": -0.5}],
    ids=["afinidad", "cumplimiento_alto", "cumplimiento_negativo"],
)
def test_reporte_rechaza_valores_fuera_de_rango(db_session, sop, cambios):
    _falla_al_guardar(db_session, _reporte(_video(sop), sop, **cambios))


def test_cumplimiento_redondea_antes_de_la_check(db_session, sop):
    # Un 100 % calculado con flotantes no debe romper la CHECK (motivo de Numeric(5,2)).
    reporte = _reporte(_video(sop), sop, cumplimiento=100.000000000001)
    db_session.add(reporte)
    db_session.flush()
    db_session.expire_all()

    assert db_session.get(Reporte, reporte.id).cumplimiento == Decimal("100.00")


def test_un_solo_reporte_por_video(db_session, sop):
    video = _video(sop)
    db_session.add_all([video, _reporte(video, sop)])
    db_session.flush()

    _falla_al_guardar(db_session, Reporte(video_id=video.id, sop_id=sop.id, resultado={}))


def test_no_se_borra_un_sop_con_videos(db_session, sop):
    db_session.add(_video(sop))
    db_session.flush()
    assert sop.videos  # cargados: el ORM no debe ponerles sop_id = NULL

    db_session.delete(sop)
    with pytest.raises(IntegrityError, match="fk_videos_sop_id_sops"):
        db_session.flush()


@pytest.mark.parametrize("cargar_reporte", [True, False], ids=["orm", "base"])
def test_borrar_un_video_borra_su_reporte(db_session, sop, cargar_reporte):
    video = _video(sop)
    reporte = _reporte(video, sop)
    db_session.add_all([video, reporte])
    db_session.flush()
    video_id, reporte_id = video.id, reporte.id
    db_session.expire_all()

    if cargar_reporte:
        db_session.delete(db_session.get(Video, video_id))
        db_session.flush()
    else:
        # DELETE directo: lo resuelve el ON DELETE CASCADE de la base, sin el ORM.
        db_session.execute(delete(Video).where(Video.id == video_id))
    db_session.expire_all()

    assert db_session.get(Reporte, reporte_id) is None


# --- palabras ------------------------------------------------------------------------------


@pytest.fixture
def video(db_session, sop) -> Video:
    video = _video(sop, publicado=True)
    db_session.add(video)
    db_session.flush()
    return video


def test_palabras_posicion_duplicada_falla(db_session, video):
    _falla_al_guardar(db_session, _palabra(video, 0), _palabra(video, 0, t_inicio=2.0, t_fin=2.3))


@pytest.mark.parametrize(
    "tiempos",
    [{"t_inicio": 3.0, "t_fin": 2.0}, {"t_inicio": -0.1, "t_fin": 0.2}],
    ids=["fin_antes_de_inicio", "inicio_negativo"],
)
def test_palabras_tiempos_invalidos_fallan(db_session, video, tiempos):
    _falla_al_guardar(db_session, _palabra(video, 0, **tiempos))


def test_borrar_un_video_borra_sus_palabras(db_session, video):
    db_session.add_all([_palabra(video, i, t_inicio=i, t_fin=i + 0.4) for i in range(3)])
    db_session.flush()
    video_id = video.id

    db_session.delete(video)
    db_session.flush()
    db_session.expunge_all()

    restantes = db_session.scalar(
        select(func.count()).select_from(Palabra).where(Palabra.video_id == video_id)
    )
    assert restantes == 0


# --- busquedas -----------------------------------------------------------------------------


def test_busqueda_se_guarda_y_se_lee(db_session):
    busqueda = Busqueda(consulta="cambiar cartucho", num_resultados=2)
    db_session.add(busqueda)
    db_session.flush()
    db_session.expire_all()

    leida = db_session.get(Busqueda, busqueda.id)
    assert (leida.consulta, leida.num_resultados) == ("cambiar cartucho", 2)
    assert leida.fecha is not None


def test_busqueda_num_resultados_negativo_falla(db_session):
    _falla_al_guardar(db_session, Busqueda(consulta="x", num_resultados=-1))
