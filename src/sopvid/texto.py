"""Utilidades de texto compartidas por la segmentación del video, la lectura del SOP y el juez
de la zona gris (verificación de citas, regla 4 de CLAUDE.md)."""

import re
import unicodedata

NO_IDENTIFICADO = "No identificado"  # responsable cuando la fuente no lo dice (ADR-008)


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos (ñ → n) y todo lo que no sea letra, dígito o espacio → espacio.

    No colapsa espacios: quien compare por palabras usa `.split()`.
    """
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())


def comparable(texto: str) -> str:
    """`normalizar` con los espacios colapsados: la forma en que se comparan las citas."""
    return " ".join(normalizar(texto).split())


def contiene_cita(texto: str, cita: str) -> bool:
    """True si `cita` aparece en `texto` como secuencia contigua de palabras completas, tras
    pasar los dos por `comparable`. Una cita vacía (o solo puntuación) nunca aparece."""
    buscada = comparable(cita)
    return bool(buscada) and f" {buscada} " in f" {comparable(texto)} "


def contar_palabras(texto: str) -> int:
    """Palabras de `texto` contadas como en la verificación (la puntuación sola no cuenta)."""
    return len(comparable(texto).split())


def recortar_palabras(texto: str, max_palabras: int) -> str:
    """Primeros tokens de `texto` que suman a lo más `max_palabras` palabras (contadas como en
    `contar_palabras`). Si el texto era una cita literal, el recorte también lo es."""
    tomados: list[str] = []
    n = 0
    for token in texto.split():
        cuenta = contar_palabras(token)
        if n + cuenta > max_palabras:
            break
        tomados.append(token)
        n += cuenta
    return " ".join(tomados)
