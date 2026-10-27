"""Pruebas de `sopvid.percepcion.pipeline` y de `scripts/analizar_video.py`.

El video sale de la fixture `generar_video` (ffmpeg, 3 s; se salta si no hay ffmpeg) y la
transcripción, de un transcriptor falso con segmentos inventados: no se descarga ningún modelo.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from sopvid.contrato import Analisis, Idioma, Palabra, Segmento
from sopvid.percepcion import pipeline
from sopvid.percepcion.medios import MedioInvalido
from sopvid.percepcion.pipeline import (
    ARCHIVO_AUDIO,
    ARCHIVO_TXT,
    FIN_TRANSCRIPCION,
    INICIO_ETAPA,
    analizar_video,
)
from sopvid.percepcion.segmentacion import segmentar
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMA = RAIZ / "docs" / "contrato" / "analisis.schema.json"


def _segmento(id_: int, t: float, t_fin: float, texto: str) -> Segmento:
    palabras = texto.split()
    paso = (t_fin - t) / len(palabras)
    return Segmento(
        id=id_,
        t_inicio=t,
        t_fin=t_fin,
        texto=texto,
        palabras=[
            Palabra(w=w, t=round(t + i * paso, 3), t_fin=round(t + (i + 1) * paso, 3))
            for i, w in enumerate(palabras)
        ],
    )


# Narración inventada que cabe en el video de 3 s.
SEGMENTOS = [
    _segmento(0, 0.0, 0.9, "Primero reviso el manómetro."),
    _segmento(1, 1.0, 1.9, "Después cierro la válvula."),
    _segmento(2, 2.0, 2.8, "Por último anoto la lectura."),
]


class TranscriptorFalso:
    """Cumple el protocolo `Transcriptor`: entrega `segmentos` uno por uno por `al_segmento`."""

    def __init__(self, segmentos: list[Segmento] | None = None):
        self.segmentos = SEGMENTOS if segmentos is None else segmentos
        self.llamadas: list[tuple[Path, str | None, bool]] = []
        self.lineas_txt_vistas: list[int] = []

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        self.llamadas.append((audio, idioma, audio.is_file()))
        txt = audio.parent / ARCHIVO_TXT
        for segmento in self.segmentos:
            self.lineas_txt_vistas.append(len(txt.read_text(encoding="utf-8").splitlines()))
            if al_segmento is not None:
                al_segmento(segmento)
        codigo = idioma or "es"
        return Transcripcion(
            idioma=Idioma(
                codigo=codigo, confianza=1.0 if idioma else 0.97, fijado_a_mano=bool(idioma)
            ),
            segmentos=list(self.segmentos),
            duracion_s=3.0,
            modelo="falso",
            dispositivo="cpu",
            compute_type="int8",
            segundos=0.0,
        )


@pytest.fixture
def video(generar_video) -> Path:
    return generar_video("operador.mp4")


# ── analizar_video ───────────────────────────────────────────────────────────


def test_pipeline_completo(video: Path, tmp_path: Path) -> None:
    trabajo = tmp_path / "trabajo"
    transcriptor = TranscriptorFalso()

    analisis = analizar_video(video, 7, None, transcriptor, trabajo)

    assert isinstance(analisis, Analisis)
    assert analisis.video_id == 7
    assert analisis.duracion_s == pytest.approx(3, abs=0.2)
    assert analisis.idioma == Idioma(codigo="es", confianza=0.97)
    assert [s.texto for s in analisis.transcripcion] == [s.texto for s in SEGMENTOS]
    assert analisis.fotogramas == []
    ((audio, idioma, existia),) = transcriptor.llamadas
    assert (audio, idioma, existia) == (trabajo / ARCHIVO_AUDIO, None, True)
    # El TXT se escribe mientras avanza: antes de cada segmento ya están los anteriores.
    assert transcriptor.lineas_txt_vistas == [0, 1, 2]
    assert (trabajo / ARCHIVO_TXT).read_text(encoding="utf-8").splitlines() == [
        "[00:00] Primero reviso el manómetro.",
        "[00:01] Después cierro la válvula.",
        "[00:02] Por último anoto la lectura.",
    ]


def test_idioma_fijado_llega_al_transcriptor(video: Path, tmp_path: Path) -> None:
    transcriptor = TranscriptorFalso()

    analisis = analizar_video(video, 1, "es", transcriptor, tmp_path / "trabajo")

    assert transcriptor.llamadas[0][1] == "es"
    assert analisis.idioma.fijado_a_mano is True


def test_avance_en_orden_y_termina_en_100(video: Path, tmp_path: Path) -> None:
    avance: list[tuple[str, int]] = []

    analizar_video(
        video, 1, None, TranscriptorFalso(), tmp_path / "t", lambda e, p: avance.append((e, p))
    )

    etapas = [e for e, _ in avance]
    porcentajes = [p for _, p in avance]
    orden = list(INICIO_ETAPA)
    assert [orden.index(e) for e in etapas] == sorted(orden.index(e) for e in etapas)
    assert set(etapas) == set(orden)
    assert porcentajes == sorted(porcentajes)
    assert len(set(avance)) == len(avance)  # solo informa cuando cambia
    assert avance[0] == ("duracion", 0)
    assert avance[-1] == ("listo", 100)
    assert etapas.count("listo") == 1
    # La transcripción avanza con cada segmento (inicio + 3 segmentos), sin pasar de 95.
    en_transcripcion = [p for e, p in avance if e == "transcripcion"]
    assert len(en_transcripcion) == 4
    assert 15 == en_transcripcion[0] < en_transcripcion[-1] <= FIN_TRANSCRIPCION


def test_tiempos_recortados_a_la_duracion(
    video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whisper puede dejar el fin del último segmento unas centésimas después del video.

    ffprobe da la duración con microsegundos (el video sintético dura justo 3.0 s, así que se
    simula una que no): se redondea a milisegundos antes de recortar, y lo recortado queda
    exactamente en ese valor.
    """
    monkeypatch.setattr(pipeline, "duracion", lambda _video: 2.9876543)
    largo = _segmento(2, 2.0, 3.4, "Por último anoto la lectura.")
    # Empieza después del final. Dos palabras: una sola se uniría al anterior (`resegmentar`).
    fuera = _segmento(3, 3.5, 3.6, "Fin registrado.")
    transcriptor = TranscriptorFalso([*SEGMENTOS[:2], largo, fuera])

    analisis = analizar_video(video, 1, None, transcriptor, tmp_path / "trabajo")

    d = analisis.duracion_s
    assert d == 2.988
    ultimo, final = analisis.transcripcion[-2:]
    assert ultimo.t_inicio == 2.0
    assert ultimo.t_fin == d
    assert ultimo.palabras[-1].t_fin == d
    assert all(p.t <= d and p.t_fin <= d for p in ultimo.palabras)
    assert (final.t_inicio, final.t_fin) == (d, d)
    assert all(p.t == d and p.t_fin == d for p in final.palabras)
    for segmento in analisis.transcripcion:
        assert segmento.t_fin <= d
        assert all(p.t_fin <= d for p in segmento.palabras)
    # Los segmentos que ya cabían no cambian.
    assert analisis.transcripcion[:2] == SEGMENTOS[:2]


def test_transcripcion_fuera_del_contrato_no_se_devuelve(video: Path, tmp_path: Path) -> None:
    solapados = [_segmento(0, 0.0, 1.5, "uno dos tres"), _segmento(1, 1.0, 2.0, "cuatro cinco")]
    avance: list[tuple[str, int]] = []

    with pytest.raises(ValidationError, match="empieza"):
        analizar_video(
            video,
            1,
            None,
            TranscriptorFalso(solapados),
            tmp_path / "trabajo",
            lambda e, p: avance.append((e, p)),
        )
    assert ("listo", 100) not in avance


def test_video_sin_audio(generar_video, tmp_path: Path) -> None:
    mudo = generar_video("mudo.mp4", con_audio=False)
    avance: list[tuple[str, int]] = []
    transcriptor = TranscriptorFalso()

    with pytest.raises(MedioInvalido, match="no tiene pista de audio"):
        analizar_video(
            mudo, 1, None, transcriptor, tmp_path / "trabajo", lambda e, p: avance.append((e, p))
        )
    assert avance == [("duracion", 0), ("audio", 5)]
    assert transcriptor.llamadas == []


def test_video_inexistente_no_crea_la_carpeta(tmp_path: Path) -> None:
    trabajo = tmp_path / "trabajo"

    with pytest.raises(MedioInvalido, match="no existe"):
        analizar_video(tmp_path / "no_existe.mp4", 1, None, TranscriptorFalso(), trabajo)
    assert not trabajo.exists()


def test_el_analisis_alimenta_la_segmentacion(video: Path, tmp_path: Path) -> None:
    analisis = analizar_video(video, 1, None, TranscriptorFalso(), tmp_path / "trabajo")
    recargado = Analisis.model_validate_json(analisis.model_dump_json())

    resultado = segmentar(recargado, None)  # sin LLM: heurística

    assert resultado.metodo == "heuristica"
    assert resultado.pasos
    assert resultado.pasos[0].t_inicio == 0.0


# ── scripts/analizar_video.py ────────────────────────────────────────────────


def _cargar_script():
    spec = importlib.util.spec_from_file_location(
        "analizar_video", RAIZ / "scripts" / "analizar_video.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def script():
    return _cargar_script()


def test_script_escribe_json_valido_contra_el_esquema(video: Path, tmp_path: Path, script) -> None:
    salida = tmp_path / "salida"
    transcriptor = TranscriptorFalso()

    codigo = script.main(
        [str(video), "--salida", str(salida), "--idioma", "es", "--video-id", "3"], transcriptor
    )

    assert codigo == 0
    assert transcriptor.llamadas[0][1] == "es"
    crudo = (salida / "analisis.json").read_bytes()
    assert b"\r" not in crudo
    datos = json.loads(crudo.decode("utf-8"))
    esquema = json.loads(ESQUEMA.read_text(encoding="utf-8"))
    errores = sorted(Draft202012Validator(esquema).iter_errors(datos), key=str)
    assert errores == []
    assert Analisis.model_validate(datos).video_id == 3
    assert (salida / ARCHIVO_TXT).is_file()
    assert (salida / ARCHIVO_AUDIO).is_file()


def test_script_no_sobrescribe_sin_permiso(
    video: Path, tmp_path: Path, script, capsys: pytest.CaptureFixture[str]
) -> None:
    salida = tmp_path / "salida"
    salida.mkdir()
    previo = salida / "analisis.json"
    previo.write_text("{}", encoding="utf-8")
    transcriptor = TranscriptorFalso()

    codigo = script.main([str(video), "--salida", str(salida)], transcriptor)

    assert codigo == 1
    error = capsys.readouterr().err
    assert "ya existe" in error
    assert "--sobrescribir" in error
    assert previo.read_text(encoding="utf-8") == "{}"
    assert transcriptor.llamadas == []  # no se procesó nada


def test_script_sobrescribe_con_permiso(video: Path, tmp_path: Path, script) -> None:
    salida = tmp_path / "salida"
    salida.mkdir()
    previo = salida / "analisis.json"
    previo.write_text("{}", encoding="utf-8")

    codigo = script.main(
        [str(video), "--salida", str(salida), "--sobrescribir"], TranscriptorFalso()
    )

    assert codigo == 0
    assert Analisis.model_validate_json(previo.read_text(encoding="utf-8")).transcripcion


def test_script_video_invalido(tmp_path: Path, script, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = script.main(
        [str(tmp_path / "no_existe.mp4"), "--salida", str(tmp_path / "s")], TranscriptorFalso()
    )

    assert codigo == 1
    assert "no existe" in capsys.readouterr().err


def test_carpeta_por_defecto(script) -> None:
    media = Path("/srv/media")
    assert script.carpeta_salida(Path("videos/video_a.mp4"), None, media) == media / "video_a"
    assert script.carpeta_salida(Path("x.mp4"), Path("otra"), media) == Path("otra")
