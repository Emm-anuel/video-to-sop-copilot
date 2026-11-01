"""Validación encadenada en el procesador (RF-13, RF-14, RF-19; ADR-014, ADR-017).

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

from dobles import SEGMENTOS, SOP_PRUEBA, Entorno, guardar_sop
from sopvid.contrato import Dispositivos, PasoVideo, ResultadoValidacion
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
    assert (reporte.sop_id, reporte.afinidad) == (video.sop_id, None)
    assert reporte.cumplimiento == Decimal("83.33")
    guardado = ResultadoValidacion.model_validate(reporte.resultado)
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
        "segmentacion",
        "emparejamiento",
    }
    assert (meta.umbrales.semaforo_verde, meta.umbrales.semaforo_amarillo) == (90, 70)
    assert meta.dispositivos == Dispositivos(
        gpu="GPU de prueba", transcripcion="cpu", llm="gpu", embedder="cpu"
    )
    assert entorno.juez.llamadas == [2]  # solo el par de la zona gris


def test_whisper_suelta_la_memoria_antes_de_ollama_y_ollama_al_final(
    entorno: Entorno, subir_validar
) -> None:
    video_id = subir_validar()
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "listo"
    assert entorno.eventos == [
        "whisper_liberado",
        "tags",
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
    assert ("segmentacion", INICIO_ETAPA["segmentacion"]) in vistos
    assert ("emparejamiento", INICIO_ETAPA["emparejamiento"]) in vistos
    assert vistos[-1] == ("listo", 100)


# ── Ollama caído (ADR-017) ───────────────────────────────────────────────────────────────────


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
    # Al repetir no hay segundos del análisis.
    assert set(reporte["metadatos"]["segundos"]) == {"segmentacion", "emparejamiento"}


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
    assert [a["tipo"] for a in reporte["metadatos"]["avisos"]] == ["segmentacion_heuristica"]
    assert "manómetro" not in reporte["metadatos"]["avisos"][0]["detalle"]
    assert entorno.eventos[-1] == "descargar"  # se intenta aunque Ollama no responda


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
