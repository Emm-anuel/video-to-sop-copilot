"""Exporta los JSON Schema de `sopvid.contrato` a docs/contrato/.

- `Analisis` → docs/contrato/analisis.schema.json
- `SOP`      → docs/contrato/sop.schema.json

Los archivos no se editan a mano: se regeneran con este script cada vez que cambia el contrato,
y tests/test_contrato.py falla si dejan de coincidir con los modelos.

Uso:
    python scripts/exportar_contrato.py
    python scripts/exportar_contrato.py --comprobar   # sale con 1 si alguno está desactualizado
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sopvid.contrato import esquema_analisis, esquema_sop

DIRECTORIO = Path(__file__).resolve().parents[1] / "docs" / "contrato"
ESQUEMAS: dict[str, Callable[[], dict[str, Any]]] = {
    "analisis.schema.json": esquema_analisis,
    "sop.schema.json": esquema_sop,
}


def serializar(esquema: dict[str, Any]) -> str:
    return json.dumps(esquema, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--comprobar", action="store_true", help="no escribe; falla si algún archivo difiere"
    )
    args = parser.parse_args()

    desactualizados = 0
    for nombre, esquema in ESQUEMAS.items():
        destino = DIRECTORIO / nombre
        texto = serializar(esquema())
        actual = destino.read_text(encoding="utf-8") if destino.exists() else None
        if args.comprobar:
            if actual != texto:
                print(f"{destino} está desactualizado: corre scripts/exportar_contrato.py")
                desactualizados += 1
            else:
                print(f"{destino} al día")
            continue

        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8", newline="\n")
        print(f"{'sin cambios' if actual == texto else 'escrito'}: {destino}")
    return 1 if desactualizados else 0


if __name__ == "__main__":
    sys.exit(main())
