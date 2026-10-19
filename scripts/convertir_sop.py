r"""Convierte un SOP de referencia en Markdown o TXT al JSON del esquema SOP (RF-03, ADR-015).

Lee el archivo en UTF-8 con la plantilla de docs/contrato/plantilla_sop.md, imprime las
advertencias en la salida de errores y escribe el JSON del SOP (indent 2, UTF-8, saltos LF).
Sin --salida, el JSON va a la salida estándar. Si el texto no sigue la plantilla (sin título, sin
pasos o un paso sin nombre) sale con código 1 y el mensaje, que solo cita números de paso y de
línea, nunca texto del SOP.

Uso, desde la raíz del repo y con el entorno activado:

    python scripts/convertir_sop.py mi_sop.md --salida data/interim/mi_sop.json
    python scripts/convertir_sop.py mi_sop.txt > mi_sop.json

    # regenera el fixture del contrato SOP (tests/fixtures/README.md)
    python scripts/convertir_sop.py tests/fixtures/sop_filtro_agua.md \
        --salida tests/fixtures/sop_ejemplo.json
"""

import argparse
import json
import sys
from pathlib import Path

from sopvid.contrato import SOP
from sopvid.lenguaje.sop_markdown import ErrorSOP, convertir_sop

EXTENSIONES = {".md", ".markdown", ".txt"}


def serializar(sop: SOP) -> str:
    return json.dumps(sop.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archivo", type=Path, help="SOP en .md o .txt (UTF-8)")
    parser.add_argument(
        "--salida", type=Path, help="ruta del JSON (por defecto, la salida estándar)"
    )
    args = parser.parse_args(argv)
    # Las advertencias llevan acentos: que una consola en cp1252 no tumbe el script.
    sys.stderr.reconfigure(errors="backslashreplace")

    if args.archivo.suffix.lower() not in EXTENSIONES:
        parser.error(f"se espera un archivo .md o .txt: {args.archivo}")
    try:
        texto = args.archivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        parser.error(f"no existe: {args.archivo}")
    except UnicodeDecodeError:
        print(f"error: {args.archivo} no está en UTF-8; guárdalo como UTF-8", file=sys.stderr)
        return 1

    try:
        resultado = convertir_sop(texto)
    except ErrorSOP as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for advertencia in resultado.advertencias:
        print(f"advertencia: {advertencia}", file=sys.stderr)
    json_sop = serializar(resultado.sop).encode("utf-8")
    if args.salida is None:
        sys.stdout.buffer.write(json_sop)  # bytes: sin "\r\n" de Windows ni cp1252
        sys.stdout.flush()
    else:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_bytes(json_sop)
    print(
        f"{len(resultado.sop.pasos)} pasos, {len(resultado.advertencias)} advertencias"
        + (f": {args.salida}" if args.salida else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
