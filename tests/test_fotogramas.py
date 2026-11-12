"""Descripción opcional de imágenes con Gemma (RF-11, ADR-024), sin GPU ni Ollama.

Ollama es el doble de tests/dobles.py (`OllamaFalso`: cuenta las imágenes de cada llamada de
visión) y los videos son sintéticos (fixture `generar_video`: testsrc con un texto conocido y un
tono); nada del cliente.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dobles import (
    CONTEXTO,
    EQUIPO_VISTO,
    SOP_PRUEBA,
    TEXTO_VISTO,
    Entorno,
    OllamaFalso,
    descripciones_lote,
    guardar_sop,
)
from sopvid.contrato import Analisis, Contexto, GeneracionSOP, Idioma, ReporteValidacion
from sopvid.lenguaje.validacion import INICIO_ETAPA, INICIO_ETAPA_IMAGENES
from sopvid.percepcion.contexto import ESQUEMA_CONTEXTO_FOTOGRAMAS
from sopvid.percepcion.fotogramas import (
    avisos_fotogramas,
    cuantas_imagenes,
    describir_fotogramas,
    imagenes_de,
    tiempos_parejos,
)
from sopvid.plataforma.config import Settings
from sopvid.plataforma.modelos import Sop
from sopvid.plataforma.procesamiento import INICIO_GENERAR_IMAGENES

AJUSTES = Settings(fotogramas_lote=2, pasos_por_min=2.2)

# ── Cuántas y cuándo ─────────────────────────────────────────────────────────────────────────


def test_n_son_los_pasos_del_sop_en_modo_validar() -> None:
    assert cuantas_imagenes("validar", 6, 135, AJUSTES) == 6
    assert cuantas_imagenes("validar", 12, 30, AJUSTES) == 12  # no depende de la duración


def test_n_tiene_minimo_y_tope_de_20() -> None:
    assert cuantas_imagenes("validar", 2, 135, AJUSTES) == 4  # FOTOGRAMAS_MIN
    assert cuantas_imagenes("validar", 35, 135, AJUSTES) == 20  # ADR-002
    assert cuantas_imagenes("generar", None, 10, AJUSTES) == 4
    assert cuantas_imagenes("generar", None, 3600, AJUSTES) == 20


def test_n_por_duracion_en_modo_generar_o_sin_sop() -> None:
    assert cuantas_imagenes("generar", None, 227.3, AJUSTES) == 8  # E: 3.79 min × 2.2
    assert cuantas_imagenes("validar", None, 300, AJUSTES) == 11  # SOP aún sin pasos


def test_el_tope_no_pasa_de_20_en_la_configuracion() -> None:
    with pytest.raises(ValueError):
        Settings(fotogramas_max=21)
    with pytest.raises(ValueError):
        Settings(fotogramas_min=10, fotogramas_max=5)


def test_reparto_parejo_en_el_centro_de_cada_tramo() -> None:
    assert tiempos_parejos(4, 100) == [12.5, 37.5, 62.5, 87.5]
    tiempos = tiempos_parejos(7, 135)
    huecos = [b - a for a, b in zip(tiempos, tiempos[1:], strict=False)]
    assert max(huecos) - min(huecos) < 1e-2
    assert tiempos_parejos(0, 100) == []


# ── Por lotes, con el doble de Ollama ────────────────────────────────────────────────────────


@pytest.fixture
def video(generar_video) -> Path:
    return generar_video("operador.mp4", segundos=6, texto=TEXTO_VISTO)


def _describir(video: Path, tmp_path: Path, ollama: OllamaFalso, n: int = 5, **ajustes: Any) -> Any:
    settings = Settings(**{"fotogramas_lote": 2, **ajustes})
    with ollama.cliente() as llm:
        return describir_fotogramas(video, tmp_path / "v", 6.0, n, llm, settings=settings)


def test_describe_por_lotes_y_el_codigo_pone_t_y_archivo(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    avances: list[float] = []
    with ollama.cliente() as llm:
        r = describir_fotogramas(
            video, tmp_path / "v", 6.0, 5, llm, settings=AJUSTES, al_avanzar=avances.append
        )
    assert ollama.imagenes_por_llamada == [2, 2, 1]  # lotes de FOTOGRAMAS_LOTE
    assert [f.t for f in r.fotogramas] == tiempos_parejos(5, 6.0)
    assert [f.archivo for f in r.fotogramas] == [f"fotogramas/f{k:02d}.jpg" for k in range(1, 6)]
    assert all((tmp_path / "v" / f.archivo).is_file() for f in r.fotogramas)
    assert r.fotogramas[0].equipos == [EQUIPO_VISTO]
    assert r.fotogramas[0].texto_visible == [TEXTO_VISTO]
    assert r.fotogramas[0].personas == 1
    assert (r.pedidas, r.descritas, r.incompletas, r.sin_imagen) == (5, 5, False, False)
    assert avances == pytest.approx([2 / 5, 4 / 5, 1.0])  # imágenes hechas / pedidas
    assert avisos_fotogramas(r) == []


def test_indices_que_no_son_del_lote_se_descartan(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])

    def con_basura(n: int) -> dict[str, Any]:
        datos = descripciones_lote(n)
        extra = dict(datos["imagenes"][0], i=n + 5)  # fuera del lote: el esquema no lo impide
        repetido = dict(datos["imagenes"][0], descripcion="otra vez la primera")
        vacia = dict(datos["imagenes"][-1], descripcion="  ")
        datos["imagenes"] = [*datos["imagenes"][:-1], extra, repetido, vacia]
        return datos

    ollama.respuestas_fotogramas = [con_basura]
    r = _describir(video, tmp_path, ollama, n=2)
    # La última imagen viene vacía en los 3 intentos: se queda la primera, una vez.
    assert [f.descripcion for f in r.fotogramas] == ["Operador junto a un tablero, imagen 1"]
    assert ollama.imagenes_por_llamada == [2, 2, 2]
    assert [a.tipo for a in avisos_fotogramas(r)] == ["imagenes_incompletas"]


def test_un_riesgo_copiado_del_ejemplo_del_prompt_se_descarta(video: Path, tmp_path: Path) -> None:
    """RNF-06: la frase de ejemplo que Gemma copió literal en E es una observación inventada."""
    ollama = OllamaFalso([])

    def con_ejemplo(n: int) -> dict[str, Any]:
        datos = descripciones_lote(n)
        datos["imagenes"][0]["riesgos"] = [
            "Falta de guantes o lentes cuando la tarea los pide a la vista.",
            "Piso mojado junto a la cubeta",
            "Ninguno visible.",  # relleno: equivale a lista vacía
        ]
        return datos

    ollama.respuestas_fotogramas = [con_ejemplo]
    r = _describir(video, tmp_path, ollama, n=2)
    assert r.fotogramas[0].riesgos == ["Piso mojado junto a la cubeta"]
    assert r.descritas == 2  # la imagen se queda; solo sale el riesgo copiado


def test_el_prompt_ya_no_trae_la_frase_de_ejemplo() -> None:
    from sopvid.percepcion.fotogramas import RIESGOS_DE_EJEMPLO, cargar_prompt
    from sopvid.texto import comparable

    prompt = comparable(cargar_prompt().sistema)
    assert RIESGOS_DE_EJEMPLO
    assert not any(ejemplo in prompt for ejemplo in RIESGOS_DE_EJEMPLO)


def test_un_lote_que_falla_tres_veces_no_detiene_a_los_demas(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    # Lote 1 bien; lote 2, JSON roto 3 veces; lote 3 bien.
    ollama.respuestas_fotogramas = [None, "{roto", "{roto", "{roto", None]
    r = _describir(video, tmp_path, ollama, n=5)
    assert ollama.imagenes_por_llamada == [2, 2, 2, 2, 1]
    assert [f.archivo for f in r.fotogramas] == ["fotogramas/f01.jpg", "fotogramas/f02.jpg",
                                                  "fotogramas/f05.jpg"]  # fmt: skip
    assert (r.lotes, r.lotes_fallidos, r.motivo) == (3, 1, "respuesta_invalida")
    avisos = avisos_fotogramas(r)
    assert [a.tipo for a in avisos] == ["imagenes_incompletas"]
    assert avisos[0].detalle.startswith("2 de 5 imágenes")


def test_ollama_caido_no_pide_los_lotes_que_faltan(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    ollama.fotogramas_caido = True
    r = _describir(video, tmp_path, ollama, n=5)
    assert r.fotogramas == []
    assert ollama.imagenes_por_llamada == [2]  # una llamada y se detiene
    assert (r.motivo, r.lotes_fallidos) == ("llm_no_disponible", 3)
    assert [a.tipo for a in avisos_fotogramas(r)] == ["imagenes_incompletas"]


def test_sin_memoria_baja_el_lote_a_la_mitad_y_reintenta(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    ollama.fotogramas_memoria_max = 4  # con 6 imágenes por llamada no cabe; con 3, sí
    r = _describir(video, tmp_path, ollama, n=6, fotogramas_lote=6)
    assert ollama.imagenes_por_llamada == [6, 3, 3]
    assert (r.descritas, r.lote_degradado, r.motivo) == (6, 3, None)
    assert avisos_fotogramas(r) == []


def test_sin_memoria_tampoco_a_la_mitad_no_tira_el_analisis(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    ollama.fotogramas_memoria_max = 1
    r = _describir(video, tmp_path, ollama, n=6, fotogramas_lote=4)
    assert ollama.imagenes_por_llamada == [4, 2]  # un solo reintento, con la mitad
    assert (r.descritas, r.lote_degradado, r.motivo) == (0, 2, "memoria_insuficiente")
    avisos = avisos_fotogramas(r)
    assert [a.tipo for a in avisos] == ["imagenes_incompletas"]
    assert "memoria_insuficiente" in avisos[0].detalle


def test_un_error_que_no_es_de_memoria_no_degrada(video: Path, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    ollama.fotogramas_caido = True
    r = _describir(video, tmp_path, ollama, n=6, fotogramas_lote=4)
    assert ollama.imagenes_por_llamada == [4]
    assert (r.lote_degradado, r.motivo) == (None, "llm_no_disponible")


def test_sin_imagen_no_llama_al_modelo(generar_video, tmp_path: Path) -> None:
    ollama = OllamaFalso([])
    r = _describir(generar_video(segundos=6, imagen="ninguna"), tmp_path, ollama)
    assert r.sin_imagen and r.fotogramas == []
    assert ollama.imagenes_por_llamada == []
    assert [a.tipo for a in avisos_fotogramas(r)] == ["sin_imagen"]


def test_imagenes_de_dice_lo_que_se_uso() -> None:
    analisis = Analisis(video_id=1, duracion_s=3, idioma=Idioma(codigo="es", confianza=1),
                        transcripcion=[])  # fmt: skip
    assert imagenes_de(None, analisis).model_dump() == {
        "descritas": False,
        "cantidad": 0,
        "tokens_entrada": None,
        "tokens_salida": None,
    }


# ── En la validación y en la generación (API) ────────────────────────────────────────────────


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def _subir(
    client: TestClient, entorno: Entorno, video: Path, modo: str = "validar", **datos: str
) -> int:
    formulario = {"titulo": "Revisión", "modo": modo, **datos}
    if modo == "validar":
        formulario["sop_id"] = str(guardar_sop(entorno.session).id)
    r = client.post(
        "/videos",
        files={"archivo": ("operador.mp4", video.read_bytes(), "video/mp4")},
        data=formulario,
    )
    assert r.status_code == 202
    return r.json()["id"]


def _vigilar(entorno: Entorno, video_id: int) -> list[tuple[str, int]]:
    vistos: list[tuple[str, int]] = []

    def ver() -> None:
        v = entorno.video(video_id)
        vistos.append((v.etapa, v.progreso))

    entorno.transcriptor.antes = lambda i: ver()
    entorno.ollama.al_pedir = ver
    entorno.correr_pendientes()
    ver()
    return vistos


def test_apagado_por_defecto_cero_llamadas_de_vision(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    assert entorno.settings.fotogramas_describir is False
    video_id = _subir(client, entorno, generar_video())
    vistos = _vigilar(entorno, video_id)
    assert entorno.ollama.imagenes_por_llamada == []
    assert "chat:fotogramas" not in entorno.eventos
    assert all(etapa != "fotogramas" for etapa, _ in vistos)
    progresos = [p for _, p in vistos]
    assert progresos == sorted(progresos)
    assert ("contexto", INICIO_ETAPA["contexto"]) in vistos
    reporte = ReporteValidacion.model_validate(client.get(f"/videos/{video_id}/reporte").json())
    assert reporte.metadatos.imagenes.descritas is False
    assert "fotogramas" not in reporte.metadatos.segundos
    assert entorno.video(video_id).fotogramas == []


def test_analizar_imagenes_true_gana_sobre_settings(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _subir(client, entorno, generar_video(), analizar_imagenes="true")
    vistos = _vigilar(entorno, video_id)
    # SOP_PRUEBA tiene 3 pasos: N sube a FOTOGRAMAS_MIN (4), en un lote de 8.
    assert len(SOP_PRUEBA.pasos) == 3
    assert entorno.ollama.imagenes_por_llamada == [4]
    # Las imágenes van antes de la ficha, en la misma carga de Gemma (una sola descarga).
    assert entorno.eventos.index("chat:fotogramas") < entorno.eventos.index("chat:contexto")
    assert entorno.eventos.count("descargar") == 1
    assert entorno.ollama.esquemas_contexto == [ESQUEMA_CONTEXTO_FOTOGRAMAS]
    usuario = entorno.ollama.mensajes_contexto[0][-1]["content"]
    assert "[f=1]" in usuario and "[f=4]" in usuario and TEXTO_VISTO in usuario

    progresos = [p for _, p in vistos]
    assert progresos == sorted(progresos)
    transcripcion = [p for e, p in vistos if e == "transcripcion"]
    assert transcripcion and max(transcripcion) < INICIO_ETAPA_IMAGENES["fotogramas"]
    assert ("fotogramas", INICIO_ETAPA_IMAGENES["fotogramas"]) in vistos
    assert ("contexto", INICIO_ETAPA_IMAGENES["contexto"]) in vistos
    assert vistos[-1] == ("listo", 100)

    reporte = ReporteValidacion.model_validate(client.get(f"/videos/{video_id}/reporte").json())
    imagenes = reporte.metadatos.imagenes
    assert (imagenes.descritas, imagenes.cantidad) == (True, 4)
    assert "fotogramas" in reporte.metadatos.segundos
    assert reporte.provisional is False
    guardados = entorno.video(video_id).fotogramas
    assert [f["archivo"] for f in guardados] == [f"fotogramas/f{k:02d}.jpg" for k in range(1, 5)]


def test_analizar_imagenes_false_gana_sobre_settings(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    # La API lee `entorno.settings` en cada petición.
    entorno.settings = entorno.settings.model_copy(update={"fotogramas_describir": True})
    video_id = _subir(client, entorno, generar_video(), analizar_imagenes="false")
    entorno.correr_pendientes()
    assert entorno.ollama.imagenes_por_llamada == []
    assert entorno.video(video_id).proceso == "listo"


def test_settings_encendido_sin_parametro_describe(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    entorno.settings = entorno.settings.model_copy(update={"fotogramas_describir": True})
    _subir(client, entorno, generar_video())
    entorno.correr_pendientes()
    assert entorno.ollama.imagenes_por_llamada == [4]


def test_un_dato_tomado_de_una_imagen_sale_con_fuente_visual(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    # El lugar no se dice en la transcripción: Gemma lo toma de la imagen 2 (`f`).
    entorno.ollama.respuestas_contexto = [
        {**CONTEXTO, "lugar": {"cita": "", "valor": "Cuarto de bombas", "f": 2}}
    ]
    video_id = _subir(client, entorno, generar_video(), analizar_imagenes="true")
    entorno.correr_pendientes()
    contexto = Contexto.model_validate(client.get(f"/videos/{video_id}/contexto").json())
    fotogramas = entorno.video(video_id).fotogramas
    assert contexto.lugar.valor == "Cuarto de bombas"
    assert (contexto.lugar.fuente, contexto.lugar.confianza) == ("visual", "media")
    assert contexto.lugar.t == fotogramas[1]["t"]  # el segundo lo pone el código
    assert EQUIPO_VISTO in [e.nombre for e in contexto.equipos]


def test_ollama_cae_en_las_imagenes_y_el_analisis_termina(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    entorno.ollama.fotogramas_caido = True
    video_id = _subir(client, entorno, generar_video(), analizar_imagenes="true")
    entorno.correr_pendientes()
    assert entorno.video(video_id).proceso == "listo"
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert "imagenes_incompletas" in [a["tipo"] for a in reporte["metadatos"]["avisos"]]
    assert reporte["provisional"] is True  # falla del sistema (ADR-019)
    assert reporte["metadatos"]["imagenes"]["descritas"] is False
    assert entorno.video(video_id).fotogramas == []


def test_repetir_la_validacion_no_vuelve_a_describir(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _subir(client, entorno, generar_video(), analizar_imagenes="true")
    entorno.correr_pendientes()
    assert (
        client.post(f"/videos/{video_id}/validar", params={"segmentar": "true"}).status_code == 202
    )
    entorno.correr_pendientes()
    assert entorno.ollama.imagenes_por_llamada == [4]  # solo el primer proceso
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert reporte["metadatos"]["imagenes"]["descritas"] is True  # las guardadas
    assert reporte["metadatos"]["imagenes"]["cantidad"] == 4


def test_modo_generar_con_imagenes(client: TestClient, entorno: Entorno, generar_video) -> None:
    video_id = _subir(client, entorno, generar_video(), modo="generar", analizar_imagenes="true")
    vistos = _vigilar(entorno, video_id)
    assert entorno.ollama.imagenes_por_llamada == [4]  # 3 s de video: FOTOGRAMAS_MIN
    assert entorno.eventos.index("chat:fotogramas") < entorno.eventos.index("chat:contexto")
    progresos = [p for _, p in vistos]
    assert progresos == sorted(progresos)
    assert ("fotogramas", INICIO_GENERAR_IMAGENES["fotogramas"]) in vistos
    assert vistos[-1] == ("listo", 100)
    video = entorno.video(video_id)
    fila = entorno.session.get(Sop, video.sop_id)
    generacion = GeneracionSOP.model_validate(fila.generacion)
    assert (generacion.imagenes.descritas, generacion.imagenes.cantidad) == (True, 4)
    carpeta = entorno.settings.media_path / "videos" / str(video_id) / "miniaturas"
    assert len(list(carpeta.glob("t*.jpg"))) == len(fila.contenido["pasos"])


def test_modo_generar_apagado_y_sin_imagen(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = _subir(client, entorno, generar_video(imagen="ninguna"), modo="generar")
    vistos = _vigilar(entorno, video_id)
    assert entorno.ollama.imagenes_por_llamada == []
    assert all(etapa != "fotogramas" for etapa, _ in vistos)
    fila = entorno.session.get(Sop, entorno.video(video_id).sop_id)
    assert "sin_imagen" in [a["tipo"] for a in fila.advertencias]
    assert GeneracionSOP.model_validate(fila.generacion).imagenes.descritas is False
