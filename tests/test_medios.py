"""Pruebas de `sopvid.percepcion.medios` (etapa 2: duración y audio).

Cada prueba genera su propio video con ffmpeg (fixture `generar_video` de conftest.py) en
`tmp_path`; ningún medio se versiona. Las que necesitan ffmpeg real se saltan si no está
instalado; las de errores de ejecución simulan `subprocess.run` y corren siempre.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from sopvid.percepcion import medios
from sopvid.percepcion.medios import (
    FfmpegNoDisponible,
    FfmpegTiempoAgotado,
    MedioInvalido,
    duracion,
    extraer_audio,
)
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings

requiere_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe no están instalados",
)

SEGUNDOS = 3


def _ffprobe(archivo: Path) -> dict:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(archivo)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return json.loads(salida.stdout)


@pytest.fixture
def video_con_audio(generar_video) -> Path:
    return generar_video("con_audio.mp4", con_audio=True, segundos=SEGUNDOS)


@pytest.fixture
def video_sin_audio(generar_video) -> Path:
    return generar_video("sin_audio.mp4", con_audio=False, segundos=SEGUNDOS)


# ── Con ffmpeg real ──────────────────────────────────────────────────────────


@requiere_ffmpeg
def test_duracion_del_video(video_con_audio: Path) -> None:
    assert duracion(video_con_audio) == pytest.approx(SEGUNDOS, abs=0.2)


@requiere_ffmpeg
def test_duracion_de_video_sin_audio(video_sin_audio: Path) -> None:
    assert duracion(video_sin_audio) == pytest.approx(SEGUNDOS, abs=0.2)


@requiere_ffmpeg
def test_extraer_audio_mp3_mono_16k(video_con_audio: Path, tmp_path: Path) -> None:
    destino = tmp_path / "salida" / "anidada" / "audio.mp3"

    resultado = extraer_audio(video_con_audio, destino)

    assert resultado == destino
    info = _ffprobe(destino)
    (pista,) = info["streams"]
    assert pista["codec_type"] == "audio"
    assert pista["codec_name"] == "mp3"
    assert pista["channels"] == 1
    assert int(pista["sample_rate"]) == 16_000
    assert float(info["format"]["duration"]) == pytest.approx(SEGUNDOS, abs=0.2)


@requiere_ffmpeg
def test_extraer_audio_desde_temporal_sin_extension(video_con_audio: Path, tmp_path: Path) -> None:
    """El temporal termina en .part: sin `-f mp3` ffmpeg fallaría al inferir el formato."""
    destino = tmp_path / "audio.mp3"
    destino.write_bytes(b"version anterior")  # se sobrescribe

    extraer_audio(video_con_audio, destino)

    assert _ffprobe(destino)["format"]["format_name"] == "mp3"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["audio.mp3", "con_audio.mp4"]


@requiere_ffmpeg
def test_extraer_audio_de_video_sin_audio(video_sin_audio: Path, tmp_path: Path) -> None:
    destino = tmp_path / "audio.mp3"

    with pytest.raises(MedioInvalido, match="no tiene pista de audio"):
        extraer_audio(video_sin_audio, destino)
    assert not destino.exists()


@requiere_ffmpeg
def test_archivo_que_no_es_video(tmp_path: Path) -> None:
    falso = tmp_path / "falso.mp4"
    falso.write_text("esto no es un video", encoding="utf-8")

    with pytest.raises(MedioInvalido, match="ffprobe no lo pudo leer"):
        duracion(falso)
    with pytest.raises(MedioInvalido):
        extraer_audio(falso, tmp_path / "audio.mp3")
    assert not (tmp_path / "audio.mp3").exists()


# ── Sin ffmpeg (corren siempre) ──────────────────────────────────────────────


def test_ruta_inexistente(tmp_path: Path) -> None:
    falta = tmp_path / "no_existe.mp4"

    with pytest.raises(MedioInvalido, match="no existe"):
        duracion(falta)
    with pytest.raises(MedioInvalido, match="no existe"):
        extraer_audio(falta, tmp_path / "audio.mp3")


def test_ffmpeg_no_instalado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    monkeypatch.setattr(medios.shutil, "which", lambda _nombre: None)

    with pytest.raises(FfmpegNoDisponible, match="ffprobe"):
        duracion(video)


def test_binario_desaparece_al_ejecutar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    monkeypatch.setattr(medios.shutil, "which", lambda nombre: f"/opt/{nombre}")

    def run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(medios.subprocess, "run", run)

    with pytest.raises(FfmpegNoDisponible):
        duracion(video)


def test_tiempo_agotado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    llamadas: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(medios.shutil, "which", lambda nombre: f"/opt/{nombre}")

    def run(args, **kwargs):
        llamadas.append((args, kwargs))
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(medios.subprocess, "run", run)

    with pytest.raises(FfmpegTiempoAgotado, match="ffprobe no terminó en 7 s"):
        duracion(video, timeout_s=7)
    with pytest.raises(FfmpegTiempoAgotado):
        duracion(video)

    (args, kwargs), (_, kwargs_defecto) = llamadas
    assert isinstance(args, list)
    assert not kwargs.get("shell", False)
    assert kwargs["timeout"] == 7
    assert kwargs_defecto["timeout"] == get_settings().ffmpeg_timeout_s


def test_config_de_medios() -> None:
    assert Settings(media_dir=Path("media")).media_path == PROJECT_ROOT / "media"
    with pytest.raises(ValidationError):
        Settings(ffmpeg_timeout_s=0)
