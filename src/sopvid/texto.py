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
    """Forma de una palabra para contar menciones (RF-24, ADR-023) y para la búsqueda exacta
    (RF-33): la consulta y el índice pasan por aquí. `comparable` (sin acentos, ñ → n, sin
    mayúsculas ni signos) y en singular por un plural simple:

    - "-es" se quita tras r, l, n, d o j ("presiones" → "presion", "valores" → "valor");
    - "-s" se quita tras cualquier otra letra ("valves" → "valve", "filtros" → "filtro"), en
      palabras de más de 3 letras y sin tocar "-ss" ("glass");
    - una "z" final se vuelve "ce" ("luz" → "luce"), la raíz de su plural ("luces" → "luce"),
      sin tocar "-zz" ("jazz"). Así el inglés en "-ces" no cambia ("services" → "service");
    - al final, una "e" tras r, l, n, d o j se quita en formas de más de 3 letras, para que el
      singular en "-e" alcance a su plural en "-es": "cable" y "cables" → "cabl", "calle" y
      "calles" → "call", "mensaje" y "mensajes" → "mensaj"; "flor" y "flores" siguen en "flor".

    Es un recorte de terminaciones, no un lematizador: lo que importa es que el singular y el
    plural den lo mismo, no que la forma sea una palabra ("lunes" → "lun", "análisis" →
    "analisi"). Choques aceptados (probados en tests/test_texto.py): "año" = "ano",
    "haz" = "hace", "cruz" = "cruce", "paz" = "pace", "sale" = "sal", "pare" = "par" y, en
    inglés, "here" = "her", "plane" = "plan", "care" = "car", "made" = "mad", "done" = "don"
    (de "don't").
    `personas.forma_base` usa su propia regla, que además quita el género (ADR-020). Una frase
    da sus palabras unidas por espacios; una palabra de solo signos da "".

    El índice de búsqueda guarda esta forma: si la regla cambia, hay que volver a publicar los
    videos publicados (docs/dev/api.md).
    """
    return " ".join(_singular(p) for p in comparable(palabra).split())


def _singular(p: str) -> str:
    if len(p) > 4 and p.endswith("es") and p[-3] in "rlndj":
        p = p[:-2]
    elif len(p) > 3 and p.endswith("s") and not p.endswith("ss"):
        p = p[:-1]
    elif len(p) > 2 and p.endswith("z") and not p.endswith("zz"):
        p = p[:-1] + "ce"
    if len(p) > 3 and p.endswith("e") and p[-2] in "rlndj":
        p = p[:-1]
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
