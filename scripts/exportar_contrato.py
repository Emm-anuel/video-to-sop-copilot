"""Exporta el JSON Schema de `sopvid.contrato.Analisis` a docs/contrato/analisis.schema.json.

El archivo no se edita a mano: se regenera con este script cada vez que cambia el contrato, y
tests/test_contrato.py falla si deja de coincidir con el modelo.

Uso:
    python scripts/exportar_contrato.py
    python scripts/exportar_contrato.py --comprobar   # sale con 1 si el archivo está desactualizado
"""

import argparse
import json
import sys
from pathlib import Path

from sopvid.contrato import esquema_analisis

DESTINO = Path(__file__).resolve().parents[1] / "docs" / "contrato" / "analisis.schema.json"


def serializar() -> str:
    return json.dumps(esquema_analisis(), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--comprobar", action="store_true", help="no escribe; falla si el archivo difiere"
    )
    args = parser.parse_args()

    texto = serializar()
    actual = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else None
    if args.comprobar:
        if actual != texto:
            print(f"{DESTINO} está desactualizado: corre scripts/exportar_contrato.py")
            return 1
        print(f"{DESTINO} al día")
        return 0

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{'sin cambios' if actual == texto else 'escrito'}: {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
