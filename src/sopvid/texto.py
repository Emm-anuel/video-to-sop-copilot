"""Utilidades de texto compartidas por la segmentación del video y la lectura del SOP."""

import re
import unicodedata

NO_IDENTIFICADO = "No identificado"  # responsable cuando la fuente no lo dice (ADR-008)


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos (ñ → n) y todo lo que no sea letra, dígito o espacio → espacio.

    No colapsa espacios: quien compare por palabras usa `.split()`.
    """
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())
