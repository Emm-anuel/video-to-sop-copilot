"""Búsqueda exacta: `POST /buscar` y `GET /buscar/opciones` (RF-33 a RF-35, RF-37).

Con la base de pruebas (`db_session`, se revierte al final), videos guardados con
`dobles.guardar_video` y transcripciones inventadas. Al empezar, cada prueba despublica los videos
que ya hubiera en la base (dentro de su transacción), para que solo cuenten los suyos.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from dobles import Entorno, guardar_sop, guardar_video
from sopvid.contrato import (
    OpcionesBusqueda,
    Palabra,
    RespuestaBusqueda,
    Segmento,
)
from sopvid.lenguaje import busqueda
from sopvid.lenguaje.busqueda import armar_frase
from sopvid.percepcion import miniaturas
from sopvid.plataforma.api.buscar import SIN_PALABRAS, url_miniatura
from sopvid.plataforma.modelos import Busqueda, Sop, Video

AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    db_session.execute(update(Video).values(publicado=False))
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _segmento(id_: int, palabras: list[tuple[str, float]], dur: float = 0.4) -> Segmento:
    """Un segmento con una palabra por (texto, segundo de inicio)."""
    return Segmento(
        id=id_,
        t_inicio=palabras[0][1],
        t_fin=palabras[-1][1] + dur,
        texto=" ".join(w for w, _ in palabras),
        palabras=[Palabra(w=w, t=t, t_fin=t + dur) for w, t in palabras],
    )


def _seguidas(texto: str, t: float = 0.0, paso: float = 0.5) -> list[tuple[str, float]]:
    return [(w, t + i * paso) for i, w in enumerate(texto.split())]


def _video(
    entorno: Entorno,
    *segmentos: list[tuple[str, float]],
    publicar: bool = True,
    titulo: str = "Video de prueba",
    **columnas: object,
) -> Video:
    video = guardar_video(
        entorno.session,
        [_segmento(i, s) for i, s in enumerate(segmentos)],
        titulo=titulo,
        **columnas,
    )
    if publicar:
        busqueda.publicar(entorno.session, video, AHORA)
        entorno.session.commit()
    return video


def _buscar(client: TestClient, consulta: str, **filtros: int) -> RespuestaBusqueda:
    r = client.post("/buscar", json={"consulta": consulta, **filtros})
    assert r.status_code == 200, r.text
    return RespuestaBusqueda.model_validate(r.json())


def _resaltado(respuesta: RespuestaBusqueda, i: int = 0) -> str:
    resultado = respuesta.resultados[i]
    return resultado.frase[resultado.rango[0] : resultado.rango[1]]


# ── Palabras y frases ────────────────────────────────────────────────────────────────────────


def test_palabra_sola(client: TestClient, entorno: Entorno) -> None:
    video = _video(entorno, _seguidas("Primero reviso el manómetro.", t=10.0))

    r = _buscar(client, "manómetro")

    assert (r.consulta, r.consulta_normalizada, r.total) == ("manómetro", "manometro", 1)
    resultado = r.resultados[0]
    assert (resultado.video.id, resultado.video.titulo) == (video.id, "Video de prueba")
    assert (resultado.t_inicio, resultado.t_fin) == (11.5, pytest.approx(11.9))
    assert resultado.frase == "Primero reviso el manómetro."
    assert _resaltado(r) == "manómetro."
    assert resultado.miniatura == f"/videos/{video.id}/thumb?t=11.50"
    assert resultado.coincidencias == 1
    assert not resultado.recorte_inicio and not resultado.recorte_fin
    assert r.milisegundos >= 0


def test_frase_en_orden_con_los_tiempos_de_whisper(client: TestClient, entorno: Entorno) -> None:
    _video(entorno, [("Después", 3.2), ("cierro", 3.71), ("la", 4.03), ("válvula", 4.27)])

    r = _buscar(client, "cierro la válvula")

    assert r.total == 1
    assert (r.resultados[0].t_inicio, r.resultados[0].t_fin) == (3.71, 4.27 + 0.4)
    assert _resaltado(r) == "cierro la válvula"


def test_frase_en_desorden_o_incompleta_no_coincide(client: TestClient, entorno: Entorno) -> None:
    _video(entorno, _seguidas("Después cierro la válvula"))

    assert _buscar(client, "válvula la cierro").total == 0
    assert _buscar(client, "cierro válvula").total == 0


def test_frase_partida_entre_dos_segmentos(client: TestClient, entorno: Entorno) -> None:
    _video(
        entorno,
        _seguidas("Primero reviso el", t=0.0),
        _seguidas("manómetro y anoto", t=5.0),
    )

    r = _buscar(client, "el manómetro")

    assert r.total == 1
    assert (r.resultados[0].t_inicio, r.resultados[0].t_fin) == (1.0, pytest.approx(5.4))
    assert r.resultados[0].frase == "Primero reviso el manómetro y anoto"
    assert _resaltado(r) == "el manómetro"


def test_frase_larga_coincide_solo_completa_y_en_orden(
    client: TestClient, entorno: Entorno
) -> None:
    """Más de `TOKENS_UNIDOS` tokens: los primeros por self-join y la frase entera por arreglo."""
    texto = "primero cierro la llave de paso y después reviso el manómetro del filtro"
    _video(entorno, _seguidas(texto, t=2.0))
    palabras = texto.split()

    r = _buscar(client, " ".join(palabras[1:11]))  # 10 tokens, de "cierro" a "manómetro"
    assert r.total == 1
    assert (r.resultados[0].t_inicio, r.resultados[0].t_fin) == (2.5, pytest.approx(7.4))
    assert _resaltado(r) == " ".join(palabras[1:11])

    otra_al_final = " ".join([*palabras[1:10], "válvula"])  # igual salvo el último token
    assert _buscar(client, otra_al_final).total == 0
    mas_alla_del_final = " ".join([*palabras[6:], "hoy"])  # pasa del final del video
    assert _buscar(client, mas_alla_del_final).total == 0
    assert _buscar(client, texto).total == 1


def test_frase_muy_larga_responde_rapido(client: TestClient, entorno: Entorno) -> None:
    """Con 250 tokens, un join por token tardaba ~40 s solo en planificarse."""
    _video(entorno, _seguidas("uno dos tres"))

    r = client.post("/buscar", json={"consulta": " ".join(["x"] * 250)})  # 499 caracteres

    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["milisegundos"] < 1000


def test_acentos_mayusculas_y_plural(client: TestClient, entorno: Entorno) -> None:
    _video(entorno, _seguidas("Cierro la válvula del filtro"))

    assert _buscar(client, "VALVULAS").total == 1
    assert _buscar(client, "Filtros").total == 1
    assert _buscar(client, "la Válvula, del filtro!").total == 1


def test_choque_aceptado_haz_encuentra_hace(client: TestClient, entorno: Entorno) -> None:
    """`forma_busqueda` da lo mismo para "haz" y "hace" (choque aceptado, #24): buscar "haz"
    trae un resultado de más donde el operador dijo "hace"."""
    _video(entorno, _seguidas("Esto se hace con cuidado"))

    r = _buscar(client, "haz")

    assert r.total == 1
    assert _resaltado(r) == "hace"


def test_un_token_dentro_de_una_hora_resalta_la_palabra_entera(
    client: TestClient, entorno: Entorno
) -> None:
    _video(entorno, _seguidas("Empieza a las 11:30 en punto"))

    r = _buscar(client, "30")

    assert r.total == 1
    assert r.resultados[0].frase == "Empieza a las 11:30 en punto"
    assert _resaltado(r) == "11:30"
    assert _buscar(client, "11:30 en").total == 1


def test_consulta_vacia_o_solo_signos_da_400_y_no_se_registra(
    client: TestClient, entorno: Entorno
) -> None:
    antes = entorno.session.scalar(select(func.count()).select_from(Busqueda))

    for consulta in ["", "   ", "¿¡—%!?"]:
        r = client.post("/buscar", json={"consulta": consulta})
        assert r.status_code == 400
        assert r.json()["detail"] == SIN_PALABRAS

    assert entorno.session.scalar(select(func.count()).select_from(Busqueda)) == antes


def test_consulta_demasiado_larga_da_422(client: TestClient) -> None:
    assert client.post("/buscar", json={"consulta": "a" * 501}).status_code == 422


# ── Unión (RF-35) ────────────────────────────────────────────────────────────────────────────


def _alarmas(entorno: Entorno, *segundos: float, **columnas: object) -> Video:
    return _video(entorno, *[[("alarma", t)] for t in segundos], **columnas)


def test_une_a_0_2_y_4_s_en_un_resultado(client: TestClient, entorno: Entorno) -> None:
    _alarmas(entorno, 0.0, 2.0, 4.0)

    r = _buscar(client, "alarma")

    assert r.total == 1
    assert (r.resultados[0].t_inicio, r.resultados[0].coincidencias) == (0.0, 3)


def test_a_4_s_ya_no_se_une(client: TestClient, entorno: Entorno) -> None:
    _alarmas(entorno, 0.0, 4.0)

    r = _buscar(client, "alarma")

    assert [(x.t_inicio, x.coincidencias) for x in r.resultados] == [(0.0, 1), (4.0, 1)]


def test_une_en_cadena(client: TestClient, entorno: Entorno) -> None:
    """Cada una a < 3 s de la anterior, aunque la última quede a 7.5 s de la primera."""
    _alarmas(entorno, 0.0, 2.5, 5.0, 7.5, 20.0)

    r = _buscar(client, "alarma")

    assert [(x.t_inicio, x.coincidencias) for x in r.resultados] == [(0.0, 4), (20.0, 1)]


def test_con_unir_en_0_no_se_une_nada(client: TestClient, entorno: Entorno) -> None:
    entorno.settings.busqueda_unir_s = 0
    _alarmas(entorno, 0.0, 2.0, 4.0)

    r = _buscar(client, "alarma")

    assert [x.t_inicio for x in r.resultados] == [0.0, 2.0, 4.0]
    assert all(x.coincidencias == 1 for x in r.resultados)


def test_nunca_une_videos_distintos(client: TestClient, entorno: Entorno) -> None:
    a = _alarmas(entorno, 0.0)
    b = _alarmas(entorno, 0.0)

    r = _buscar(client, "alarma")

    assert r.total == 2
    assert {x.video.id for x in r.resultados} == {a.id, b.id}
    assert all(x.coincidencias == 1 for x in r.resultados)


def test_registra_la_busqueda_con_el_total_ya_unido(client: TestClient, entorno: Entorno) -> None:
    _alarmas(entorno, 0.0, 2.0, 4.0, 30.0)

    r = _buscar(client, "  la   alarma ")

    ultima = entorno.session.scalars(select(Busqueda).order_by(Busqueda.id.desc())).first()
    assert (ultima.consulta, ultima.num_resultados) == ("la alarma", 0)  # "la alarma" no está
    r = _buscar(client, "alarma")
    ultima = entorno.session.scalars(select(Busqueda).order_by(Busqueda.id.desc())).first()
    assert (ultima.consulta, ultima.num_resultados, r.total) == ("alarma", 2, 2)


# ── Orden y tope ─────────────────────────────────────────────────────────────────────────────


def test_orden_por_video_reciente_y_luego_por_segundo(client: TestClient, entorno: Entorno) -> None:
    entorno.settings.busqueda_unir_s = 0
    viejo = _alarmas(entorno, 1.0, 9.0, creado=AHORA - timedelta(days=1))
    nuevo = _alarmas(entorno, 2.0, 8.0, creado=AHORA)

    r = _buscar(client, "alarma")

    assert [(x.video.id, x.t_inicio) for x in r.resultados] == [
        (nuevo.id, 2.0),
        (nuevo.id, 8.0),
        (viejo.id, 1.0),
        (viejo.id, 9.0),
    ]


def test_tope_de_resultados_con_el_total_completo(client: TestClient, entorno: Entorno) -> None:
    entorno.settings.busqueda_unir_s = 0
    entorno.settings.busqueda_max_resultados = 2
    _alarmas(entorno, 0.0, 10.0, 20.0)

    r = _buscar(client, "alarma")

    assert (r.total, len(r.resultados)) == (3, 2)


# ── Filtros (RF-37) ──────────────────────────────────────────────────────────────────────────


def _sop(entorno: Entorno) -> Sop:
    return guardar_sop(entorno.session)


def test_filtro_por_video(client: TestClient, entorno: Entorno) -> None:
    a = _alarmas(entorno, 0.0)
    _alarmas(entorno, 0.0)

    r = _buscar(client, "alarma", video_id=a.id)

    assert [x.video.id for x in r.resultados] == [a.id]


def test_filtro_por_sop_incluye_el_video_del_que_se_genero(
    client: TestClient, entorno: Entorno
) -> None:
    sop = _sop(entorno)
    validado = _alarmas(entorno, 0.0, modo="validar", sop=sop)
    generador = _alarmas(entorno, 0.0, modo="generar", sop=sop)  # videos.sop_id = el generado
    _alarmas(entorno, 0.0, modo="validar", sop=_sop(entorno))
    _alarmas(entorno, 0.0)

    r = _buscar(client, "alarma", sop_id=sop.id)

    assert {x.video.id for x in r.resultados} == {validado.id, generador.id}
    assert all(x.sop is not None and x.sop.id == sop.id for x in r.resultados)
    assert r.resultados[0].sop.codigo == sop.codigo


def test_filtros_que_no_se_cruzan_dan_cero(client: TestClient, entorno: Entorno) -> None:
    sop = _sop(entorno)
    _alarmas(entorno, 0.0, modo="validar", sop=sop)
    otro = _alarmas(entorno, 0.0, modo="validar", sop=_sop(entorno))

    r = _buscar(client, "alarma", video_id=otro.id, sop_id=sop.id)

    assert (r.total, r.resultados) == (0, [])


def test_un_video_sin_publicar_responde_igual_que_uno_que_no_existe(
    client: TestClient, entorno: Entorno
) -> None:
    oculto = _alarmas(entorno, 0.0, publicar=False)
    quitado = _alarmas(entorno, 0.0)
    busqueda.despublicar(entorno.session, quitado)
    entorno.session.commit()

    respuestas = [
        _buscar(client, "alarma", video_id=v).model_dump(exclude={"milisegundos"})
        for v in (oculto.id, quitado.id, 999_999_999)
    ]

    assert respuestas[0] == respuestas[1] == respuestas[2]
    assert respuestas[0]["total"] == 0
    assert _buscar(client, "alarma").total == 0


# ── Frase de contexto y miniatura (RF-34) ────────────────────────────────────────────────────


def _numeradas(n: int) -> list[tuple[str, float]]:
    return [(f"w{i}", float(i)) for i in range(n)]


def test_frase_al_inicio_al_final_y_en_medio_del_video(
    client: TestClient, entorno: Entorno
) -> None:
    _video(entorno, _numeradas(30))
    palabras = [f"w{i}" for i in range(30)]

    inicio = _buscar(client, "w0").resultados[0]
    assert inicio.frase == " ".join(palabras[0:9])
    assert inicio.rango == (0, 2)
    assert (inicio.recorte_inicio, inicio.recorte_fin) == (False, True)

    fin = _buscar(client, "w29").resultados[0]
    assert fin.frase == " ".join(palabras[21:30])
    assert fin.frase[fin.rango[0] : fin.rango[1]] == "w29"
    assert (fin.recorte_inicio, fin.recorte_fin) == (True, False)

    medio = _buscar(client, "w15 w16").resultados[0]
    assert medio.frase == " ".join(palabras[7:25])
    assert medio.frase[medio.rango[0] : medio.rango[1]] == "w15 w16"
    assert (medio.recorte_inicio, medio.recorte_fin) == (True, True)


def test_video_corto_sin_recortes(client: TestClient, entorno: Entorno) -> None:
    _video(entorno, _numeradas(17))

    resultado = _buscar(client, "w8").resultados[0]

    assert resultado.frase == " ".join(f"w{i}" for i in range(17))
    assert (resultado.recorte_inicio, resultado.recorte_fin) == (False, False)


def test_frase_no_duplica_las_palabras_de_varios_tokens() -> None:
    """La ventana empieza en el segundo token de "11:30" (se salta) y "O-rings" son dos filas
    que vuelven a ser una palabra."""
    filas = [
        (4, "30", "11:30"),
        (5, "cambio", "cambio"),
        (6, "los", "los"),
        (7, "o", "O-rings"),
        (8, "ring", "O-rings"),
        (9, "hoy", "hoy"),
    ]

    frase = armar_frase(filas, 7, 8, ventana_hasta=30)

    assert frase.texto == "cambio los O-rings hoy"
    assert frase.texto[frase.rango[0] : frase.rango[1]] == "O-rings"
    assert (frase.recorte_inicio, frase.recorte_fin) == (True, False)


def test_frase_recorta_si_la_ventana_llega_al_tope() -> None:
    filas = [(i, f"w{i}", f"w{i}") for i in range(0, 3)]

    assert armar_frase(filas, 0, 0, ventana_hasta=2).recorte_fin
    assert not armar_frase(filas, 0, 0, ventana_hasta=5).recorte_fin


def test_sin_miniatura_si_el_video_no_tiene_imagen(client: TestClient, entorno: Entorno) -> None:
    video = _alarmas(entorno, 0.0)
    carpeta = miniaturas.carpeta_miniaturas((entorno.settings.media_path / video.archivo).parent)
    miniaturas.marcar_sin_imagen(carpeta)

    assert _buscar(client, "alarma").resultados[0].miniatura is None


def test_url_de_la_miniatura_trunca_a_centesimas() -> None:
    assert url_miniatura(3, 59.996) == "/videos/3/thumb?t=59.99"
    assert url_miniatura(3, 0.0) == "/videos/3/thumb?t=0.00"


# ── Opciones (RF-37) ─────────────────────────────────────────────────────────────────────────


def test_opciones_solo_publicados_y_sop_con_un_publicado(
    client: TestClient, entorno: Entorno
) -> None:
    con_publicado, sin_publicado = _sop(entorno), _sop(entorno)
    viejo = _alarmas(entorno, 0.0, creado=AHORA - timedelta(days=1))
    nuevo = _alarmas(entorno, 0.0, modo="validar", sop=con_publicado, creado=AHORA)
    _alarmas(entorno, 0.0, modo="validar", sop=sin_publicado, publicar=False)

    r = client.get("/buscar/opciones")

    assert r.status_code == 200
    opciones = OpcionesBusqueda.model_validate(r.json())
    assert [(v.id, v.sop_id) for v in opciones.videos] == [
        (nuevo.id, con_publicado.id),
        (viejo.id, None),
    ]
    assert [(s.id, s.codigo) for s in opciones.sops] == [(con_publicado.id, con_publicado.codigo)]
