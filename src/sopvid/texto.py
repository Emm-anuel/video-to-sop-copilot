"""Utilidades de texto compartidas por la segmentación del video, la lectura del SOP, el juez
de la zona gris y la ficha de contexto (verificación de citas, regla 4 de CLAUDE.md)."""

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


# Lo que el LLM escribe a veces en lugar de dejar el campo vacío (con el JSON compacto salía
# ["null"] en listas vacías), comparado con `comparable`: se trata como vacío.
VACIOS = frozenset({"null", "none", "ninguno", "ninguna", "n a", "na"})


def limpiar(texto: str | None, vacios: frozenset[str] = VACIOS) -> str:
    """`texto` con los espacios colapsados, o "" si está vacío o es uno de `vacios`."""
    limpio = " ".join((texto or "").split())
    return "" if comparable(limpio) in vacios else limpio


def contiene_cita(texto: str, cita: str) -> bool:
    """True si `cita` aparece en `texto` como secuencia contigua de palabras completas, tras
    pasar los dos por `comparable`. Una cita vacía (o solo puntuación) nunca aparece."""
    buscada = comparable(cita)
    return bool(buscada) and f" {buscada} " in f" {comparable(texto)} "


def contar_palabras(texto: str) -> int:
    """Palabras de `texto` contadas como en la verificación (la puntuación sola no cuenta)."""
    return len(comparable(texto).split())


def forma_busqueda(palabra: str) -> str:
    """Forma de una palabra para contar menciones y buscar (RF-24, ADR-023): `comparable` (sin
    acentos ni mayúsculas) y en singular por un plural simple: "-es" se quita tras r, l, n, d, z
    o j ("presiones" → "presion", "valores" → "valor") y "-s" tras cualquier otra letra
    ("valves" → "valve", "filtros" → "filtro"), en palabras de más de 3 letras y sin tocar "-ss"
    ("glass"). Es un recorte de terminaciones, no un lematizador: es la misma regla de plural de
    `personas.forma_base`, sin quitar el género. Una frase da sus palabras unidas por espacios.
    """
    return " ".join(_singular(p) for p in comparable(palabra).split())


def _singular(p: str) -> str:
    if len(p) > 4 and p.endswith("es") and p[-3] in "rlndzj":
        return p[:-2]
    if len(p) > 3 and p.endswith("s") and not p.endswith("ss"):
        return p[:-1]
    return p


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
