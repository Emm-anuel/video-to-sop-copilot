"""SOP generado en la API (RF-22 a RF-27; ADR-023): modo generar, `GET /videos/{id}/sop`,
`POST /videos/{id}/generar`, `PUT /sops/{id}`, la biblioteca y el Markdown.

Sin GPU, Ollama ni MiniLM: `Entorno` (dobles.py) con la base de conftest.py, `OllamaFalso` para
Gemma (sus respuestas por defecto, `AGRUPACION_SOP`…, son para `SEGMENTOS`) y los videos de
`generar_video` (ffmpeg). Todo es inventado por el equipo (CLAUDE.md §2.1).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dobles import Entorno, JuezFalso, guardar_sop
from sopvid.contrato import SOP, GeneracionSOP
from sopvid.lenguaje.sop_markdown import convertir_sop, empieza_con_infinitivo
from sopvid.percepcion.segmentacion import Segmentacion
from sopvid.plataforma import procesamiento
from sopvid.plataforma.modelos import Sop, Video
from sopvid.plataforma.procesamiento import (
    ERROR_LLM_GENERAR,
    MENSAJE_SOP_GENERADO_REINICIO,
    MENSAJE_SOP_REINICIO,
    marcar_sops_interrumpidos,
)


@pytest.fixture
def entorno(db_session: Session, tmp_path: Path) -> Entorno:
    return Entorno(db_session, tmp_path)


@pytest.fixture
def client(entorno: Entorno) -> Iterator[TestClient]:
    with TestClient(entorno.app) as cliente:
        yield cliente


def subir(client: TestClient, video: bytes, **datos: str) -> int:
    formulario = {"titulo": "Revisión de la línea", "modo": "generar", **datos}
    r = client.post(
        "/videos", data=formulario, files={"archivo": ("operador.mp4", video, "video/mp4")}
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


@pytest.fixture
def generado(client: TestClient, entorno: Entorno, generar_video) -> int:
    """Un video de modo generar ya procesado; devuelve su id."""
    video_id = subir(client, generar_video().read_bytes())
    entorno.correr_pendientes()
    assert entorno.video(video_id).proceso == "listo"
    return video_id


def _sop_id(entorno: Entorno, video_id: int) -> int:
    sop_id = entorno.video(video_id).sop_id
    assert sop_id is not None
    return sop_id


# ── Modo generar ─────────────────────────────────────────────────────────────────────────────


def test_el_sop_generado_se_guarda_fuera_de_la_biblioteca_y_se_consulta(
    client: TestClient, entorno: Entorno, generado: int
) -> None:
    r = client.get(f"/videos/{generado}/sop")
    assert r.status_code == 200
    sop = SOP.model_validate(r.json())
    assert [p.nombre for p in sop.pasos] == [
        "Revisar el manómetro",
        "Cerrar la válvula",
        "Anotar la lectura",
    ]
    assert all(empieza_con_infinitivo(p.nombre) for p in sop.pasos)
    assert [(p.t_inicio, p.t_fin) for p in sop.pasos] == [(0.0, 0.9), (1.0, 1.9), (2.0, 2.8)]
    assert sop.palabras_clave[0].termino == "manómetro"

    sop_id = _sop_id(entorno, generado)
    detalle = client.get(f"/sops/{sop_id}").json()
    assert (detalle["origen"], detalle["en_biblioteca"], detalle["metodo"]) == (
        "generado",
        False,
        None,
    )
    generacion = GeneracionSOP.model_validate(detalle["generacion"])
    assert (generacion.video_id, generacion.grupos, generacion.dispositivo_llm) == (
        generado,
        [[1], [2], [3]],
        "gpu",
    )
    assert (generacion.contexto_reusado, generacion.segmentacion_reusada) == (False, False)
    assert [x.etapa for x in generacion.llamadas] == ["agrupar", "pasos", "resumen", "claves"]
    estado = client.get(f"/sops/{sop_id}/estado").json()
    assert (estado["estado"], estado["origen"], estado["en_biblioteca"]) == (
        "listo",
        "generado",
        False,
    )


def test_get_sop_da_409_mientras_no_esta_listo_y_422_en_modo_validar(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    video_id = subir(client, generar_video().read_bytes())
    r = client.get(f"/videos/{video_id}/sop")
    assert r.status_code == 409
    assert r.json()["detail"]["proceso"] == "en_cola"

    sop = guardar_sop(entorno.session)
    validar = subir(client, generar_video().read_bytes(), modo="validar", sop_id=str(sop.id))
    assert client.get(f"/videos/{validar}/sop").status_code == 422
    assert client.get("/videos/999999/sop").status_code == 404


def test_una_falla_a_media_generacion_deja_el_sop_incompleto_con_sus_pasos(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    entorno.ollama.respuestas_generado["resumen"] = "esto no es JSON"
    video_id = subir(client, generar_video().read_bytes())
    entorno.correr_pendientes()

    assert entorno.video(video_id).proceso == "listo"
    sop = SOP.model_validate(client.get(f"/videos/{video_id}/sop").json())
    assert len(sop.pasos) == 3
    assert sop.titulo == "Revisión de la línea de agua"  # la actividad de la ficha
    advertencias = client.get(f"/sops/{_sop_id(entorno, video_id)}").json()["advertencias"]
    assert [a["tipo"] for a in advertencias] == ["sop_incompleto"]
    assert "cuadro resumen (respuesta_invalida)" in advertencias[0]["mensaje"]


def test_sin_pasos_del_video_el_video_queda_en_error_y_no_hay_sop(
    client: TestClient, entorno: Entorno, generar_video, monkeypatch: pytest.MonkeyPatch
) -> None:
    vacia = Segmentacion([], "heuristica", "transcripción vacía", None)
    monkeypatch.setattr(procesamiento, "segmentar", lambda *_a, **_k: vacia)
    video_id = subir(client, generar_video().read_bytes())
    entorno.correr_pendientes()

    video = entorno.video(video_id)
    assert video.proceso == "error"
    assert "No hay pasos del video" in (video.error or "")
    assert video.sop_id is None
    assert entorno.eventos[-1] == "descargar"  # Gemma se suelta igual


def test_los_sop_generados_interrumpidos_dicen_que_se_repita_la_generacion(
    db_session: Session,
) -> None:
    cargado = Sop(origen="cargado", estado="convirtiendo")
    generado = Sop(origen="generado", estado="convirtiendo", en_biblioteca=False)
    db_session.add_all([cargado, generado])
    db_session.commit()

    assert marcar_sops_interrumpidos(db_session) >= 2
    assert (cargado.estado, cargado.error) == ("error", MENSAJE_SOP_REINICIO)
    assert (generado.estado, generado.error) == ("error", MENSAJE_SOP_GENERADO_REINICIO)


# ── Repetir la generación (RNF-07) ───────────────────────────────────────────────────────────


def test_repetir_la_generacion_reusa_ficha_y_segmentacion_y_el_mismo_sop(
    client: TestClient, entorno: Entorno, generado: int
) -> None:
    sop_id = _sop_id(entorno, generado)
    entorno.eventos.clear()

    r = client.post(f"/videos/{generado}/generar")
    assert r.status_code == 202
    entorno.correr_pendientes()

    # Sin Whisper, sin ficha y sin segmentar: solo las cuatro llamadas del SOP.
    assert entorno.eventos == [
        "tags",
        "chat:agrupar",
        "chat:pasos",
        "chat:resumen",
        "chat:claves",
        "descargar",
    ]
    assert _sop_id(entorno, generado) == sop_id  # fuera de la biblioteca, se reescribe
    generacion = client.get(f"/sops/{sop_id}").json()["generacion"]
    assert (generacion["contexto_reusado"], generacion["segmentacion_reusada"]) == (True, True)


def test_repetir_con_segmentar_vuelve_a_pedir_los_pasos_del_video(
    client: TestClient, entorno: Entorno, generado: int
) -> None:
    entorno.eventos.clear()
    client.post(f"/videos/{generado}/generar?segmentar=true")
    entorno.correr_pendientes()
    assert "chat:fronteras" in entorno.eventos and "chat:contexto" not in entorno.eventos


def test_repetir_no_pisa_un_sop_que_ya_esta_en_la_biblioteca(
    client: TestClient, entorno: Entorno, generado: int
) -> None:
    anterior = _sop_id(entorno, generado)
    assert client.post(f"/sops/{anterior}/biblioteca").status_code == 200
    client.post(f"/videos/{generado}/generar")
    entorno.correr_pendientes()

    nuevo = _sop_id(entorno, generado)
    assert nuevo != anterior
    assert client.get(f"/sops/{anterior}").json()["en_biblioteca"] is True
    assert client.get(f"/sops/{nuevo}").json()["en_biblioteca"] is False


def test_repetir_la_generacion_responde_422_409_y_sin_ollama_error_reprocesable(
    client: TestClient, entorno: Entorno, generado: int, generar_video
) -> None:
    sop = guardar_sop(entorno.session)
    validar = subir(client, generar_video().read_bytes(), modo="validar", sop_id=str(sop.id))
    assert client.post(f"/videos/{validar}/generar").status_code == 422  # validar
    en_cola = subir(client, generar_video().read_bytes())
    assert client.post(f"/videos/{en_cola}/generar").status_code == 409

    entorno.ollama.disponible = False
    assert client.post(f"/videos/{generado}/generar").status_code == 202
    entorno.cola.correr_pendientes()
    video = entorno.video(generado)
    assert (video.proceso, video.error) == ("error", ERROR_LLM_GENERAR.format(id=generado))


# ── Corregir, biblioteca y uso como referencia (RF-26, RF-27) ────────────────────────────────


def test_put_guarda_la_version_corregida_y_rechaza_un_sop_invalido(
    client: TestClient, entorno: Entorno, generado: int
) -> None:
    sop_id = _sop_id(entorno, generado)
    sop = client.get(f"/videos/{generado}/sop").json()

    invalido: dict[str, Any] = {**sop, "pasos": [{**sop["pasos"][0], "numero": 2}]}
    assert client.put(f"/sops/{sop_id}", json=invalido).status_code == 422
    sin_pasos = {**sop, "pasos": []}
    assert client.put(f"/sops/{sop_id}", json=sin_pasos).status_code == 422
    con_extra = {**sop, "inventado": True}
    assert client.put(f"/sops/{sop_id}", json=con_extra).status_code == 422
    assert client.get(f"/videos/{generado}/sop").json() == sop  # no se tocó

    corregido = {**sop, "titulo": "Revisión semanal de la línea de agua"}
    corregido["pasos"] = [*sop["pasos"][:2], {**sop["pasos"][2], "nombre": "Registrar la lectura"}]
    r = client.put(f"/sops/{sop_id}", json=corregido)
    assert r.status_code == 200
    guardado = client.get(f"/videos/{generado}/sop").json()
    assert guardado["titulo"] == "Revisión semanal de la línea de agua"
    assert guardado["pasos"][2]["nombre"] == "Registrar la lectura"
    assert entorno.session.get(Sop, sop_id).titulo == "Revisión semanal de la línea de agua"


def test_put_de_un_sop_que_no_esta_listo_da_409(client: TestClient, entorno: Entorno) -> None:
    fila = Sop(origen="generado", estado="convirtiendo", en_biblioteca=False)
    entorno.session.add(fila)
    entorno.session.commit()
    sop = SOP(titulo="x", pasos=[{"numero": 1, "nombre": "Hacer", "responsable": "Yo"}])
    assert client.put(f"/sops/{fila.id}", json=sop.model_dump(mode="json")).status_code == 409
    assert client.post(f"/sops/{fila.id}/biblioteca").status_code == 409
    assert client.put("/sops/999999", json=sop.model_dump(mode="json")).status_code == 404


def test_un_sop_generado_sirve_como_referencia_solo_desde_la_biblioteca(
    client: TestClient, entorno: Entorno, generado: int, generar_video
) -> None:
    sop_id = _sop_id(entorno, generado)
    datos = {"modo": "validar", "sop_id": str(sop_id)}
    r = client.post(
        "/videos",
        data={"titulo": "Otra revisión", **datos},
        files={"archivo": ("operador.mp4", generar_video().read_bytes(), "video/mp4")},
    )
    assert r.status_code == 422
    assert "no está en la biblioteca" in r.json()["detail"]

    r = client.post(f"/sops/{sop_id}/biblioteca")
    assert (r.status_code, r.json()["en_biblioteca"]) == (200, True)
    assert client.post(f"/sops/{sop_id}/biblioteca").status_code == 200  # idempotente

    entorno.juez = JuezFalso("Cumple")
    entorno.eventos.clear()
    video_id = subir(client, generar_video().read_bytes(), **datos)
    entorno.correr_pendientes()

    assert "chat:sop" not in entorno.eventos  # sin conversión
    reporte = client.get(f"/videos/{video_id}/reporte").json()
    # El mismo video contra el SOP que se generó desde él (RF-27).
    assert reporte["sop"]["id"] == sop_id
    assert reporte["cumplimiento"] >= 90
    assert reporte["semaforo"] == "verde"


# ── Markdown (ADR-015) ───────────────────────────────────────────────────────────────────────


def contenido_de_plantilla(sop: SOP) -> dict[str, Any]:
    """Lo que la plantilla Markdown lleva: sin evidencia, tiempos del video ni claves."""
    r = sop.resumen
    return {
        "titulo": sop.titulo,
        "resumen": {
            **{
                campo: getattr(r, campo).valor
                for campo in ("objetivo", "alcance", "responsable", "lugar", "horario_frecuencia")
            },
            "duracion_total_min": r.duracion_total_min,
            "roles": [e.model_dump() for e in r.roles],
            "equipo": [e.model_dump() for e in r.equipo_operacion],
            "riesgos": [
                x.model_dump(include={"descripcion", "nivel", "paso", "control"}) for x in r.riesgos
            ],
            "fallas": [x.model_dump(include={"situacion", "accion"}) for x in r.en_caso_de_falla],
        },
        "pasos": [
            p.model_dump(
                include={
                    "numero",
                    "nombre",
                    "descripcion",
                    "responsable",
                    "equipo",
                    "puntos_validacion",
                    "tiempo_esperado_min",
                }
            )
            for p in sop.pasos
        ],
    }


def test_el_markdown_vuelve_al_mismo_contenido_con_convertir_sop(
    client: TestClient, entorno: Entorno, generar_video
) -> None:
    entorno.ollama.respuestas_generado["resumen"] = {
        "titulo": "Revisión de la línea de agua",
        "objetivo": {"cita": "Primero reviso el manómetro", "valor": "Confirmar la presión"},
        "alcance": {"cita": "", "valor": "Solo la línea de agua"},
        "duracion_total": {"cita": ""},
        "riesgos": [
            {
                "cita": "Después cierro la válvula",
                "descripcion": "Golpe de ariete al cerrar.",
                "nivel": "medio",
                "control": "Cerrar despacio.",
            }
        ],
        "en_caso_de_falla": [
            {"cita": "", "situacion": "La válvula no cierra", "accion": "Avisar al supervisor"}
        ],
    }
    video_id = subir(client, generar_video().read_bytes())
    entorno.correr_pendientes()
    sop_id = _sop_id(entorno, video_id)

    r = client.get(f"/sops/{sop_id}.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    generado = SOP.model_validate(client.get(f"/videos/{video_id}/sop").json())
    assert generado.resumen.riesgos[0].paso == 2  # la cita cae en el tramo del paso 2
    vuelta = convertir_sop(r.text)
    assert vuelta.advertencias == []
    assert contenido_de_plantilla(vuelta.sop) == contenido_de_plantilla(generado)


def test_el_markdown_de_un_sop_que_no_esta_listo_da_409(
    client: TestClient, entorno: Entorno
) -> None:
    fila = Sop(origen="generado", estado="error", error="x", en_biblioteca=False)
    entorno.session.add(fila)
    entorno.session.commit()
    assert client.get(f"/sops/{fila.id}.md").status_code == 409
    assert client.get("/sops/999999.md").status_code == 404


def test_el_video_lleva_el_sop_en_sop_id(entorno: Entorno, generado: int) -> None:
    video = entorno.session.get(Video, generado)
    assert video is not None and video.sop is not None
    assert video.sop.estado == "listo"
