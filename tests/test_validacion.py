"""Validación encadenada en el procesador (RF-13, RF-14, RF-19; ADR-014, ADR-019).

Transcriptor, Ollama, juez y vectorizador son dobles (tests/dobles.py): no hace falta GPU,
Ollama ni MiniLM. La base es la de conftest.py y los videos salen de `generar_video` (ffmpeg).
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dobles import CONTEXTO, SEGMENTOS, SOP_PRUEBA, Entorno, guardar_sop
from sopvid.contrato import Contexto, Dispositivos, PasoVideo, ResultadoValidacion
from sopvid.lenguaje.validacion import INICIO_ETAPA
from sopvid.plataforma.modelos import Reporte, Video
from sopvid.plataforma.procesamiento import ERROR_SIN_SOP, FIN_ANALISIS_VALIDAR


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


@pytest.fixture
def subir_validar(client: TestClient, entorno: Entorno, generar_video):
    """Sube un video en modo validar contra SOP_PRUEBA y devuelve su id (sin correrlo)."""

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


def _reportes(session: Session, video_id: int) -> list[Reporte]:
    return list(session.scalars(select(Reporte).where(Reporte.video_id == video_id)))


# ── Camino feliz ─────────────────────────────────────────────────────────────────────────────


def test_encadena_y_guarda_reporte_y_pasos(entorno: Entorno, subir_validar) -> None:
    video_id = subir_validar()
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert (video.proceso, video.etapa, video.progreso, video.error) == (
        "listo",
        "listo",
        100,
        None,
    )
    assert video.transcripcion is not None
    # Los pasos de segmentar, antes de fusionar: uno por segmento, con su tiempo.
    pasos = [PasoVideo.model_validate(p) for p in video.pasos_video]
    assert [(p.t_inicio, p.cita) for p in pasos] == [(s.t_inicio, s.texto) for s in SEGMENTOS]
    [reporte] = _reportes(entorno.session, video_id)
    guardado = ResultadoValidacion.model_validate(reporte.resultado)
    # La ficha del doble es del mismo procedimiento: la afinidad pasa y va en la columna.
    assert guardado.afinidad is not None and not guardado.afinidad.bajo_umbral
    assert (reporte.sop_id, reporte.afinidad) == (video.sop_id, guardado.afinidad.valor)
    assert reporte.cumplimiento == Decimal("83.33")
    assert guardado.cumplimiento == pytest.approx(250 / 3)  # sin redondear
    assert guardado.semaforo == "amarillo"
    meta = guardado.metadatos
    assert (meta.segmentacion, meta.motivo_respaldo, meta.modelo_llm) == ("llm", None, "falso")
    assert meta.embedder == "vectorizador-guionado"
    assert meta.avisos == []
    assert set(meta.segundos) == {
        "duracion",
        "audio",
        "transcripcion",
        "contexto",
        "afinidad",
        "segmentacion",
        "emparejamiento",
        "personas",
        "tiempos",
    }
    assert (meta.umbrales.semaforo_verde, meta.umbrales.semaforo_amarillo) == (90, 70)
    assert (meta.umbrales.tolerancia_tiempo, meta.umbrales.umbral_horario) == (0.2, 0.75)
    # Tiempos (ADR-021): uno por resultado, solo en los pares, medidos sobre la transcripción.
    # El SOP de prueba no trae tiempos ni horario: todo sin referencia.
    pasos_clasificados = guardado.resultado.clasificacion.pasos
    assert len(guardado.tiempos) == len(pasos_clasificados)
    for paso, tiempo in zip(pasos_clasificados, guardado.tiempos, strict=True):
        assert (tiempo is not None) == (paso.estado in ("Cumple", "Parcial", "zona_gris"))
        if tiempo is not None:
            assert (tiempo.origen, tiempo.estado) == ("medido", "sin_referencia")
            del_video = guardado.resultado.pasos_video[paso.indice_video]
            assert tiempo.observado_min == round((del_video.t_fin - del_video.t_inicio) / 60, 2)
    assert guardado.tiempo_total is not None and guardado.tiempo_total.estado == "sin_referencia"
    assert guardado.horario is not None and guardado.horario.estado == "sin_referencia"
    assert meta.dispositivos == Dispositivos(
        gpu="GPU de prueba", transcripcion="cpu", llm="gpu", embedder="cpu"
    )
    assert entorno.juez.llamadas == [2]  # solo el par de la zona gris
    # La ficha de contexto, con la cita de la actividad verificada (regla 4).
    contexto = Contexto.model_validate(video.contexto)
    assert contexto.actividad.valor == CONTEXTO["actividad"]["valor"]
    assert (contexto.actividad.fuente, contexto.actividad.t) == ("audio", SEGMENTOS[0].t_inicio)
    assert [e.nombre for e in contexto.equipos] == CONTEXTO["equipos"]


def test_whisper_suelta_la_memoria_antes_de_ollama_y_ollama_al_final(
    entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "listo"
    # Una sola carga de Gemma: ficha de contexto, pasos y juez en la misma ventana.
    assert entorno.eventos == [
        "whisper_liberado",
        "tags",
        "chat:contexto",
        "chat:fronteras",
        "chat:redaccion",
        "descargar",
    ]
    assert entorno.ollama.descargas == [{"model": "falso", "keep_alive": 0}]
    assert [c._http.is_closed for c in entorno.clientes] == [True]


def test_el_avance_no_retrocede(entorno: Entorno, subir_validar) -> None:
    video_id = subir_validar()
    vistos: list[tuple[str, int]] = []

    def ver() -> None:
        video = entorno.video(video_id)
        vistos.append((video.etapa, video.progreso))

    entorno.transcriptor.antes = lambda i: ver()
    entorno.ollama.al_pedir = ver
    entorno.correr_pendientes()
    ver()

    progresos = [p for _, p in vistos]
    assert progresos == sorted(progresos)
    transcripcion = [p for e, p in vistos if e == "transcripcion"]
    assert transcripcion and max(transcripcion) < FIN_ANALISIS_VALIDAR
    assert ("contexto", INICIO_ETAPA["contexto"]) in vistos
    assert ("segmentacion", INICIO_ETAPA["segmentacion"]) in vistos
    assert ("emparejamiento", INICIO_ETAPA["emparejamiento"]) in vistos
    assert vistos[-1] == ("listo", 100)


# ── Ollama caído (ADR-019) ───────────────────────────────────────────────────────────────────


def test_ollama_caido_al_empezar_deja_error_reprocesable(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.ollama.disponible = False
    video_id = subir_validar()
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert video.proceso == "error"
    assert video.error.startswith("LLM no disponible: el análisis quedó guardado")
    assert f"/videos/{video_id}/validar" in video.error
    assert video.transcripcion is not None  # la transcripción no se pierde
    assert _reportes(entorno.session, video_id) == []
    assert entorno.eventos == ["whisper_liberado"]  # sin segmentar ni descargar
    assert client.get(f"/videos/{video_id}/reporte").status_code == 409

    # Ollama vuelve: se repite solo la validación, sin Whisper.
    entorno.ollama.disponible = True
    r = client.post(f"/videos/{video_id}/validar")
    assert (r.status_code, r.json()["proceso"]) == (202, "en_cola")
    entorno.correr_pendientes()

    assert entorno.transcriptor.idiomas == [None]  # transcribió una sola vez
    assert entorno.video(video_id).proceso == "listo"
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert (reporte["cumplimiento"], reporte["provisional"]) == (83.33, False)
    # Al repetir no hay segundos del análisis; la ficha no se había generado y se genera aquí.
    assert set(reporte["metadatos"]["segundos"]) == {
        "contexto",
        "afinidad",
        "segmentacion",
        "emparejamiento",
        "personas",
        "tiempos",
    }
    assert entorno.video(video_id).contexto is not None


def test_ollama_se_cae_a_medias_da_reporte_provisional(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.ollama.caido_en_chat = True
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "listo"
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert reporte["provisional"] is True
    assert reporte["metadatos"]["segmentacion"] == "heuristica"
    assert [a["tipo"] for a in reporte["metadatos"]["avisos"]] == [
        "contexto_sin_generar",
        "segmentacion_heuristica",
    ]
    assert all("manómetro" not in a["detalle"] for a in reporte["metadatos"]["avisos"])
    assert entorno.eventos[-1] == "descargar"  # se intenta aunque Ollama no responda
    assert entorno.video(video_id).contexto is None  # sin ficha: la próxima validación la intenta


# ── Ficha de contexto (RF-12) ────────────────────────────────────────────────────────────────


def _avisos(client: TestClient, video_id: int) -> list[dict]:
    return client.get(f"/videos/{video_id}/reporte").json()["metadatos"]["avisos"]


@pytest.mark.parametrize(
    ("falla", "detalle"),
    [
        ("mudo", "ficha de contexto vacía: llm_no_disponible"),
        ("json", "ficha de contexto vacía: respuesta_invalida tras 3 intentos"),
        ("tiempo", "ficha de contexto vacía: tiempo_excedido"),
    ],
)
def test_ficha_sin_generar_da_aviso_y_la_validacion_sigue(
    client: TestClient,
    entorno: Entorno,
    subir_validar,
    monkeypatch: pytest.MonkeyPatch,
    falla: str,
    detalle: str,
) -> None:
    if falla == "mudo":
        entorno.ollama.contexto_caido = True
    elif falla == "json":
        entorno.ollama.respuestas_contexto = ["no es json"]
    else:  # tope total de 0.2 s y una ficha que tarda más en llegar
        from sopvid.percepcion import contexto as ctx
        from sopvid.plataforma.config import Settings

        monkeypatch.setattr(ctx, "get_settings", lambda: Settings(llm_timeout_contexto_s=0.2))
        entorno.ollama.pausa_contexto_s = 0.05
    video_id = subir_validar()
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert (video.proceso, video.contexto) == ("listo", None)
    assert _avisos(client, video_id) == [{"tipo": "contexto_sin_generar", "detalle": detalle}]
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert reporte["provisional"] is True
    assert reporte["cumplimiento"] == 83.33  # los pasos y el juez no cambian
    assert entorno.eventos[-1] == "descargar"


def test_transcripcion_vacia_no_llama_al_modelo_para_la_ficha(
    client: TestClient, entorno: Entorno, subir_validar, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dobles

    monkeypatch.setattr(dobles, "SEGMENTOS", [])
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert "chat:contexto" not in entorno.eventos
    assert entorno.video(video_id).proceso == "listo"
    assert _avisos(client, video_id)[0] == {
        "tipo": "contexto_sin_generar",
        "detalle": "ficha de contexto vacía: transcripcion_vacia",
    }


def test_whisper_que_no_es_el_de_referencia_da_aviso_en_el_reporte_y_la_ficha(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.transcriptor.modelo = "small"
    video_id = subir_validar()
    entorno.correr_pendientes()

    reporte = client.get(f"/videos/{video_id}/reporte").json()
    [aviso] = reporte["metadatos"]["avisos"]
    assert aviso["tipo"] == "transcripcion_no_referencia"
    assert "manómetro" not in aviso["detalle"]
    assert reporte["provisional"] is True
    assert reporte["cumplimiento"] == 83.33  # el porcentaje no cambia
    contexto = client.get(f"/videos/{video_id}/contexto").json()
    assert contexto["avisos"] == [aviso]

    # Al repetir solo la validación, el modelo sale del análisis guardado.
    assert client.post(f"/videos/{video_id}/validar").status_code == 202
    entorno.correr_pendientes()
    assert _avisos(client, video_id) == [aviso]


def test_whisper_de_referencia_no_da_aviso(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()  # TranscriptorFalso dice "large-v3-turbo"
    entorno.correr_pendientes()

    assert _avisos(client, video_id) == []
    assert client.get(f"/videos/{video_id}/contexto").json()["avisos"] == []


def test_repetir_la_validacion_reusa_la_ficha_guardada(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()
    entorno.correr_pendientes()
    guardada = entorno.video(video_id).contexto
    assert entorno.eventos.count("chat:contexto") == 1

    assert client.post(f"/videos/{video_id}/validar").status_code == 202
    entorno.correr_pendientes()

    assert entorno.eventos.count("chat:contexto") == 1  # no volvió a llamar al modelo
    assert entorno.video(video_id).contexto == guardada
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert set(reporte["metadatos"]["segundos"]) == {
        "afinidad",
        "segmentacion",
        "emparejamiento",
        "personas",
        "tiempos",
    }
    assert reporte["provisional"] is False


def test_juez_sin_revisar_da_reporte_provisional(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    entorno.juez.veredicto = None  # respaldo: el par queda en zona_gris
    video_id = subir_validar()
    entorno.correr_pendientes()

    reporte = client.get(f"/videos/{video_id}/reporte").json()
    assert (reporte["cumplimiento"], reporte["semaforo"]) == (66.67, "rojo")
    assert reporte["provisional"] is True
    [aviso] = reporte["metadatos"]["avisos"]
    assert aviso == {
        "tipo": "juez_sin_revisar",
        "detalle": "1 pares de la zona gris sin revisar (llm_no_disponible: 1)",
    }
    assert reporte["conteo"]["sin_revisar"] == 1
    assert reporte["filas"][1]["estado"] == "zona_gris"


def test_error_en_la_validacion_descarga_y_cierra(entorno: Entorno, subir_validar) -> None:
    entorno.juez.error = RuntimeError("Después cierro la válvula")
    video_id = subir_validar()
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert (video.proceso, video.error) == ("error", "falló la etapa emparejamiento (RuntimeError)")
    assert entorno.eventos[-1] == "descargar"
    assert [c._http.is_closed for c in entorno.clientes] == [True]
    assert _reportes(entorno.session, video_id) == []


def test_validar_sin_sop_falla_antes_de_transcribir(entorno: Entorno) -> None:
    video = Video(titulo="viejo", archivo="x.mp4", modo="validar", proceso="en_cola")
    entorno.session.add(video)
    entorno.session.commit()

    entorno.procesador.procesar(video.id, None, entorno.transcriptor, lambda: None)

    video = entorno.video(video.id)
    assert (video.proceso, video.error) == ("error", ERROR_SIN_SOP)
    assert entorno.transcriptor.idiomas == []


# ── POST /videos/{id}/validar ────────────────────────────────────────────────────────────────


def test_revalidar_reemplaza_el_reporte(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()
    entorno.correr_pendientes()
    entorno.juez.veredicto = "Cumple"

    assert client.post(f"/videos/{video_id}/validar").status_code == 202
    entorno.correr_pendientes()

    [reporte] = _reportes(entorno.session, video_id)
    assert reporte.cumplimiento == Decimal("100.00")
    assert (
        entorno.session.scalar(
            select(func.count()).select_from(Reporte).where(Reporte.video_id == video_id)
        )
        == 1
    )


def test_revalidar_rechaza_lo_que_no_se_puede_validar(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    assert client.post("/videos/999999999/validar").status_code == 404

    generar = Video(titulo="g", archivo="x.mp4", modo="generar", proceso="listo")
    sin_analisis = Video(
        titulo="s",
        archivo="x.mp4",
        modo="validar",
        sop_id=guardar_sop(entorno.session).id,
        proceso="error",
    )
    entorno.session.add_all([generar, sin_analisis])
    entorno.session.commit()
    assert client.post(f"/videos/{generar.id}/validar").status_code == 422
    r = client.post(f"/videos/{sin_analisis.id}/validar")
    assert (r.status_code, r.json()["detail"]) == (
        409,
        "el video no tiene análisis guardado: vuelve a subirlo",
    )

    en_cola = subir_validar()
    r = client.post(f"/videos/{en_cola}/validar")
    assert (r.status_code, r.json()["detail"]["proceso"]) == (409, "en_cola")
    assert len(entorno.pendientes) == 1  # solo el de la subida


def test_sop_prueba_es_el_del_guion() -> None:
    """Los nombres del SOP de prueba son los prefijos que fija el vectorizador guionado."""
    from dobles import GUION_PRUEBA

    assert all(p.nombre in GUION_PRUEBA for p in SOP_PRUEBA.pasos)


# ── Dispositivos (ADR-018) ───────────────────────────────────────────────────────────────────


def _dispositivos(entorno: Entorno, video_id: int) -> Dispositivos:
    [reporte] = _reportes(entorno.session, video_id)
    return ResultadoValidacion.model_validate(reporte.resultado).metadatos.dispositivos


def test_gemma_en_cpu_queda_en_los_metadatos(entorno: Entorno, subir_validar) -> None:
    entorno.ollama.vram = 0
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert _dispositivos(entorno, video_id).llm == "cpu"


def test_revalidar_sin_whisper_deja_la_transcripcion_vacia(
    client: TestClient, entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert client.post(f"/videos/{video_id}/validar").status_code == 202
    entorno.correr_pendientes()

    assert _dispositivos(entorno, video_id) == Dispositivos(
        gpu="GPU de prueba", transcripcion=None, llm="gpu"
    )
