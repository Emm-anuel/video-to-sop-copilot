"""Índice de la búsqueda exacta (`lenguaje/busqueda.py`, RF-32, RF-33).

Las funciones puras usan transcripciones inventadas; las de la base, la transacción de
`db_session` (se revierte al final) y videos guardados con `dobles.guardar_video`.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dobles import SEGMENTOS, guardar_video
from sopvid.contrato import Analisis, Idioma, Palabra, Segmento
from sopvid.lenguaje import busqueda
from sopvid.lenguaje.busqueda import PalabraIndice, palabras_indexables
from sopvid.plataforma.modelos import Palabra as FilaPalabra
from sopvid.plataforma.modelos import Video


def _segmento(id_: int, palabras: list[tuple[str, float, float]], texto: str = "") -> Segmento:
    return Segmento(
        id=id_,
        t_inicio=palabras[0][1] if palabras else 0.0,
        t_fin=palabras[-1][2] if palabras else 0.0,
        texto=texto or " ".join(w for w, _, _ in palabras),
        palabras=[Palabra(w=w, t=t, t_fin=f) for w, t, f in palabras],
    )


def _analisis(*segmentos: Segmento) -> Analisis:
    return Analisis(
        video_id=1,
        duracion_s=max((s.t_fin for s in segmentos), default=0.0),
        idioma=Idioma(codigo="es", confianza=0.9),
        transcripcion=list(segmentos),
    )


# Inventado: dos segmentos, con acentos, un plural, una hora, un guion suelto y signos pegados.
DOS_SEGMENTOS = (
    _segmento(0, [(" Cierro", 0.0, 0.4), (" las", 0.4, 0.6), (" válvulas,", 0.6, 1.2)]),
    _segmento(
        1,
        [(" a", 1.5, 1.6), (" las", 1.6, 1.8), (" 11:30", 1.8, 2.5), (" —", 2.5, 2.6),
         (" ¿listo?", 2.6, 3.0)],
    ),
)  # fmt: skip


def _formas(filas: list[PalabraIndice]) -> list[str]:
    return [f.palabra_normalizada for f in filas]


# ── Puras ─────────────────────────────────────────────────────────────────────────────────────


def test_una_fila_por_token_con_posiciones_consecutivas_en_todo_el_video():
    filas = palabras_indexables(_analisis(*DOS_SEGMENTOS))

    assert _formas(filas) == ["cierro", "las", "valvula", "a", "las", "11", "30", "listo"]
    # No vuelven a 0 en el segundo segmento.
    assert [f.posicion for f in filas] == list(range(8))


def test_el_original_conserva_acentos_y_signos_sin_el_espacio_de_whisper():
    filas = palabras_indexables(_analisis(*DOS_SEGMENTOS))
    assert [f.palabra_original for f in filas][:3] == ["Cierro", "las", "válvulas,"]
    assert filas[-1].palabra_original == "¿listo?"


def test_una_palabra_con_varios_tokens_da_filas_seguidas_con_su_segundo():
    filas = palabras_indexables(_analisis(*DOS_SEGMENTOS))
    hora = [f for f in filas if f.palabra_original == "11:30"]

    assert [(f.palabra_normalizada, f.posicion) for f in hora] == [("11", 5), ("30", 6)]
    assert {(f.t_inicio, f.t_fin) for f in hora} == {(1.8, 2.5)}


def test_una_palabra_de_solo_signos_no_se_indexa_ni_gasta_posicion():
    filas = palabras_indexables(_analisis(*DOS_SEGMENTOS))

    assert all(f.palabra_original != "—" for f in filas)
    # "30" (posición 6) y "listo" (7) quedan seguidas aunque el guion iba en medio: la consulta
    # "11:30 — listo" también pierde el guion y la frase coincide.
    assert (filas[6].palabra_normalizada, filas[7].palabra_normalizada) == ("30", "listo")


def test_los_tiempos_son_los_de_whisper_sin_redondear():
    seg = _segmento(0, [("presión", 12.345678, 12.9876)])
    (fila,) = palabras_indexables(_analisis(seg))
    assert (fila.t_inicio, fila.t_fin) == (12.345678, 12.9876)


def test_un_segmento_sin_palabras_usa_el_tiempo_del_segmento():
    sin_palabras = Segmento(id=0, t_inicio=4.0, t_fin=6.0, texto="Reviso los manómetros.")
    filas = palabras_indexables(_analisis(sin_palabras))

    assert _formas(filas) == ["reviso", "los", "manometro"]
    assert {(f.t_inicio, f.t_fin) for f in filas} == {(4.0, 6.0)}
    assert filas[2].palabra_original == "manómetros."


def test_transcripcion_vacia_no_da_filas():
    assert palabras_indexables(_analisis()) == []


def test_original_y_forma_se_recortan_al_largo_de_la_columna():
    larga = "a" * 150
    (fila,) = palabras_indexables(_analisis(_segmento(0, [(larga, 0.0, 1.0)])))
    assert len(fila.palabra_original) == len(fila.palabra_normalizada) == busqueda.LARGO_PALABRA


# ── Contra la base ────────────────────────────────────────────────────────────────────────────


def _filas(session: Session, video: Video) -> list[FilaPalabra]:
    consulta = select(FilaPalabra).where(FilaPalabra.video_id == video.id)
    return list(session.scalars(consulta.order_by(FilaPalabra.posicion)))


def test_indexar_guarda_una_fila_por_palabra(db_session: Session):
    video = guardar_video(db_session, list(DOS_SEGMENTOS))

    n = busqueda.indexar(db_session, video)
    db_session.commit()

    filas = _filas(db_session, video)
    assert n == len(filas) == 8
    assert [f.posicion for f in filas] == list(range(8))
    assert filas[2].palabra_normalizada == "valvula"
    assert filas[2].palabra_original == "válvulas,"
    assert (filas[2].t_inicio, filas[2].t_fin) == (0.6, 1.2)


def test_indexar_dos_veces_reemplaza_sin_duplicar(db_session: Session):
    video = guardar_video(db_session)
    esperadas = sum(len(s.palabras) for s in SEGMENTOS)

    busqueda.indexar(db_session, video)
    db_session.commit()
    assert busqueda.indexar(db_session, video) == esperadas
    db_session.commit()

    assert busqueda.contar(db_session, video) == esperadas


def test_indexar_no_toca_otros_videos(db_session: Session):
    uno, otro = guardar_video(db_session), guardar_video(db_session, list(DOS_SEGMENTOS))
    busqueda.indexar(db_session, uno)
    busqueda.indexar(db_session, otro)
    db_session.commit()

    busqueda.indexar(db_session, uno)
    busqueda.desindexar(db_session, uno)
    db_session.commit()

    assert busqueda.contar(db_session, uno) == 0
    assert busqueda.contar(db_session, otro) == 8


def test_desindexar_borra_las_palabras_del_video(db_session: Session):
    video = guardar_video(db_session)
    busqueda.indexar(db_session, video)
    db_session.commit()

    assert busqueda.desindexar(db_session, video) == sum(len(s.palabras) for s in SEGMENTOS)
    db_session.commit()
    assert busqueda.contar(db_session, video) == 0


def test_publicar_y_despublicar_ponen_las_columnas(db_session: Session):
    video = guardar_video(db_session)
    ahora = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

    estado = busqueda.publicar(db_session, video, ahora)
    db_session.commit()
    assert (video.publicado, video.publicado_en) == (True, ahora)
    assert estado.palabras_indexadas == busqueda.contar(db_session, video) > 0

    estado = busqueda.despublicar(db_session, video)
    db_session.commit()
    assert (video.publicado, video.publicado_en) == (False, None)
    assert (estado.publicado, estado.palabras_indexadas) == (False, 0)
    assert busqueda.contar(db_session, video) == 0


def test_borrar_el_video_borra_sus_palabras_en_cascada(db_session: Session):
    video = guardar_video(db_session)
    busqueda.indexar(db_session, video)
    db_session.commit()
    video_id = video.id

    db_session.delete(video)
    db_session.commit()

    consulta = select(FilaPalabra.id).where(FilaPalabra.video_id == video_id)
    assert db_session.scalars(consulta).all() == []


@pytest.mark.parametrize("ya_publicado", [False, True])
def test_publicar_al_terminar_solo_si_no_estaba_publicado(db_session: Session, ya_publicado):
    antes = datetime(2026, 11, 1, tzinfo=UTC)
    video = guardar_video(
        db_session, publicado=ya_publicado, publicado_en=antes if ya_publicado else None
    )

    busqueda.publicar_al_terminar(db_session, video.id)

    db_session.refresh(video)
    assert video.publicado
    if ya_publicado:  # no se vuelve a indexar ni cambia la fecha
        assert video.publicado_en == antes
        assert busqueda.contar(db_session, video) == 0
    else:
        assert video.publicado_en > antes
        assert busqueda.contar(db_session, video) == sum(len(s.palabras) for s in SEGMENTOS)
