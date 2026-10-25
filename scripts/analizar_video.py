r"""Analiza un video (duración, audio y transcripción) y escribe su `Analisis` del contrato.

Deja en la carpeta de salida `audio.mp3`, `transcripcion.txt` (se escribe mientras avanza) y
`analisis.json` (indent 2, UTF-8, saltos LF). Por defecto la carpeta es `MEDIA_DIR/<nombre del
video sin extensión>/`, ignorada por git. Si ya tiene `analisis.json`, sale con código 1 sin
procesar nada, salvo con --sobrescribir. Whisper se configura con las variables WHISPER_* (ver
docs/dev/transcripcion.md). El avance y los logs van a la salida de errores, sin texto
transcrito; un video inválido sale con código 1 y el mensaje.

Uso, desde la raíz del repo y con el entorno activado:

    python scripts/analizar_video.py video_a.mp4                  # → media/video_a/
    python scripts/analizar_video.py video_a.mp4 --idioma es --video-id 1
    python scripts/analizar_video.py video_a.mp4 --salida data/interim/video_a --sobrescribir

El JSON alimenta la extracción de pasos y el emparejamiento:

    analisis = Analisis.model_validate_json(Path("media/video_a/analisis.json").read_text("utf-8"))
    pasos = segmentacion.segmentar(analisis, llm).pasos
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from sopvid.contrato import Analisis
from sopvid.percepcion.medios import ErrorMedios
from sopvid.percepcion.pipeline import ARCHIVO_AUDIO, ARCHIVO_TXT, analizar_video
from sopvid.percepcion.transcripcion import Transcriptor, TranscriptorWhisper
from sopvid.plataforma.config import get_settings

ARCHIVO_ANALISIS = "analisis.json"


def serializar(analisis: Analisis) -> str:
    return json.dumps(analisis.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def carpeta_salida(video: Path, salida: Path | None, media: Path) -> Path:
    """`salida` si se dio; si no, `media/<nombre del video sin extensión>`."""
    return salida if salida is not None else media / video.stem


def main(argv: list[str] | None = None, transcriptor: Transcriptor | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", type=Path, help="archivo de video (o de audio)")
    parser.add_argument(
        "--salida", type=Path, help="carpeta de salida (por defecto, MEDIA_DIR/<nombre>)"
    )
    parser.add_argument("--idioma", help="código ISO 639-1 para fijar el idioma (p. ej. es)")
    parser.add_argument("--video-id", type=int, default=0, help="id del video (por defecto, 0)")
    parser.add_argument(
        "--sobrescribir", action="store_true", help="reemplaza un analisis.json existente"
    )
    args = parser.parse_args(argv)

    destino = carpeta_salida(args.video, args.salida, get_settings().media_path)
    ruta_json = destino / ARCHIVO_ANALISIS
    if ruta_json.exists() and not args.sobrescribir:
        print(
            f"error: {ruta_json} ya existe. Usa --sobrescribir para reemplazarlo o --salida "
            "para elegir otra carpeta.",
            file=sys.stderr,
        )
        return 1

    def al_avanzar(etapa: str, porcentaje: int) -> None:
        print(f"[{porcentaje:3d} %] {etapa}", file=sys.stderr, flush=True)

    try:
        analisis = analizar_video(
            args.video,
            args.video_id,
            args.idioma,
            transcriptor or TranscriptorWhisper(),
            destino,
            al_avanzar,
        )
    except ErrorMedios as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    ruta_json.write_text(serializar(analisis), encoding="utf-8", newline="\n")
    idioma = analisis.idioma
    origen = "fijado a mano" if idioma.fijado_a_mano else "detectado"
    palabras = sum(len(s.palabras) for s in analisis.transcripcion)
    print(
        f"Video {analisis.video_id}: {analisis.duracion_s:.1f} s · idioma {idioma.codigo} "
        f"({idioma.confianza:.2f}, {origen}) · {len(analisis.transcripcion)} segmentos, "
        f"{palabras} palabras"
    )
    for ruta in (ruta_json, destino / ARCHIVO_TXT, destino / ARCHIVO_AUDIO):
        print(f"  {ruta}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
