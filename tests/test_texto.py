"""Utilidades de texto compartidas (`sopvid.texto`)."""

import pytest

from sopvid.percepcion import segmentacion
from sopvid.texto import NO_IDENTIFICADO, forma_busqueda, limpiar, normalizar


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Válvula", "valvula"),
        ("ÁÉÍÓÚ áéíóú ü Ü", "aeiou aeiou u u"),
        ("Ç ç", "c c"),
    ],
)
def test_quita_acentos(texto, esperado):
    assert normalizar(texto) == esperado


def test_pasa_a_minusculas():
    assert normalizar("PRESIÓN de Trabajo") == "presion de trabajo"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Año", "ano"),
        ("niño", "nino"),
        ("ÑANDÚ", "nandu"),
        ("Año, niño; ÑANDÚ", "ano  nino  nandu"),
    ],
)
def test_la_enie_queda_como_n(texto, esperado):
    assert normalizar(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Paso 3: cerrar.", "paso 3  cerrar "),
        ("llave-de-paso", "llave de paso"),
        ("4 bar.", "4 bar "),
        # ¿ y ¡ no tienen forma ASCII: desaparecen en vez de volverse espacio.
        ("¿Qué? ¡Listo!", "que  listo "),
        ("tab\tsalto\nfin", "tab salto fin"),
        ("ºC 2º", "oc 2o"),  # el ordinal se descompone en "o"
    ],
)
def test_la_puntuacion_se_vuelve_espacio(texto, esperado):
    assert normalizar(texto) == esperado


def test_no_colapsa_espacios():
    assert normalizar("  dos   espacios ") == "  dos   espacios "
    assert normalizar("Año, niño").split() == ["ano", "nino"]


def test_texto_vacio_e_idempotencia():
    assert normalizar("") == ""
    una = normalizar("¿Cerró la LLAVE de paso? Sí, señor.")
    assert normalizar(una) == una


def test_no_identificado_es_el_mismo_que_usa_la_segmentacion():
    assert NO_IDENTIFICADO == "No identificado"
    assert segmentacion.NO_IDENTIFICADO is NO_IDENTIFICADO


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("  Línea   de enjuague ", "Línea de enjuague"),
        ("null", ""),
        ("N/A", ""),
        ("Ninguno", ""),
        (None, ""),
        ("", ""),
    ],
)
def test_limpiar_colapsa_espacios_y_vacia_los_marcadores_de_vacio(texto, esperado):
    assert limpiar(texto) == esperado


def test_limpiar_con_vacios_propios():
    assert limpiar("No se menciona", frozenset({"no se menciona"})) == ""
    assert limpiar("No se menciona") == "No se menciona"


# ── forma_busqueda: menciones y búsqueda exacta (RF-24, ADR-023) ──────────────────────────────


@pytest.mark.parametrize(
    ("palabra", "esperado"),
    [
        ("Presiones", "presion"),
        ("presión", "presion"),
        ("VALORES", "valor"),
        ("filtros", "filtro"),
        ("valves", "valve"),
        ("Gauges", "gauge"),
        ("glass", "glass"),
        ("gas", "gas"),
        ("bar", "bar"),
        ("O-rings", "o ring"),
    ],
)
def test_forma_busqueda_quita_acentos_mayusculas_y_plural_simple(palabra, esperado):
    assert forma_busqueda(palabra) == esperado


def test_forma_busqueda_iguala_singular_y_plural():
    assert forma_busqueda("llave de paso") == forma_busqueda("Llaves de paso")
    assert forma_busqueda("shut-off valve") == forma_busqueda("Shut-off valves")


# La consulta y el índice de la búsqueda exacta (RF-33) pasan por `forma_busqueda`: lo que
# importa es que las dos formas de cada par den lo mismo. La salida se fija para que un cambio
# de regla se note aquí y no en una búsqueda que deja de encontrar.
@pytest.mark.parametrize(
    ("una", "otra", "forma"),
    [
        # Acentos y mayúsculas.
        ("Válvula", "valvula", "valvula"),
        ("PRESIÓN", "presión", "presion"),
        ("Manómetro", "MANOMETRO", "manometro"),
        # Ñ → n (la regla de `normalizar`); "año" = "ano" está en los choques.
        ("Niño", "nino", "nino"),
        # Signos pegados a la palabra.
        ("válvula,", "Válvula", "valvula"),
        ("¿cerró?", "cerró", "cerro"),
        ('"filtro".', "filtro", "filtro"),
        ("(manómetro)", "manómetro", "manometro"),
        # Plural en -s.
        ("filtros", "filtro", "filtro"),
        ("llaves", "llave", "llave"),
        ("valves", "valve", "valve"),
        # Plural en -es tras r, l, n, d, j.
        ("valores", "valor", "valor"),
        ("niveles", "nivel", "nivel"),
        ("presiones", "presión", "presion"),
        ("paredes", "pared", "pared"),
        ("relojes", "reloj", "reloj"),
        ("botones", "botón", "boton"),
        ("papeles", "papel", "papel"),
        ("flores", "flor", "flor"),
        # Singular en -e tras r, l, n, d, j: la e final se quita y alcanza al plural en -es.
        ("cables", "cable", "cabl"),
        ("calles", "calle", "call"),
        ("nombres", "nombre", "nombr"),
        ("detalles", "detalle", "detall"),
        ("torres", "torre", "torr"),
        ("grandes", "grande", "grand"),
        ("mensajes", "mensaje", "mensaj"),
        ("voltajes", "voltaje", "voltaj"),
        # Plural en -ces de una palabra en -z: la z final se vuelve "ce".
        ("luces", "luz", "luce"),
        ("veces", "vez", "vece"),
        ("lápices", "lápiz", "lapice"),
        ("peces", "pez", "pece"),
        ("voces", "voz", "voce"),
        ("nueces", "nuez", "nuece"),
        # Inglés: "-zes" ya no pierde la e y "-ces" no cambia.
        ("Cables", "cable", "cabl"),
        ("lines", "line", "lin"),
        ("sizes", "size", "size"),
        ("services", "service", "service"),
        ("devices", "device", "device"),
        ("pieces", "piece", "piece"),
        ("jazz", "Jazz", "jazz"),
    ],
)
def test_forma_busqueda_iguala_las_dos_formas(una, otra, forma):
    assert forma_busqueda(una) == forma_busqueda(otra) == forma


@pytest.mark.parametrize(
    ("una", "otra", "forma"),
    [
        ("año", "ano", "ano"),  # ñ → n (decisión del 15 nov)
        ("haz", "hace", "hace"),  # z final → ce
        ("cruz", "cruce", "cruce"),
        ("paz", "pace", "pace"),
        ("sale", "sal", "sal"),  # e tras l, r: se quita
        ("pare", "par", "par"),
        # Inglés, por la misma regla de la e (vistos al comparar el video E el 15 nov).
        ("here", "her", "her"),
        ("plane", "plan", "plan"),
        ("care", "car", "car"),
        ("made", "mad", "mad"),
        ("done", "don", "don"),  # "don't" da "don t": "done" encuentra "don't"
    ],
)
def test_forma_busqueda_choques_aceptados(una, otra, forma):
    """Palabras distintas con la misma forma: una búsqueda de una encuentra la otra. Se aceptan
    a cambio de que singular y plural coincidan; si alguno deja de chocar, la regla cambió."""
    assert forma_busqueda(una) == forma_busqueda(otra) == forma


@pytest.mark.parametrize(
    ("palabra", "forma"),
    [
        ("gas", "gas"),  # 3 letras: no se toca
        ("lunes", "lun"),
        ("análisis", "analisi"),
        ("crisis", "crisi"),
        ("glass", "glass"),
    ],
)
def test_forma_busqueda_de_palabras_que_no_se_singularizan_es_estable(palabra, forma):
    """Singular y plural son la misma palabra: la forma no es una palabra real, pero la consulta
    y el índice la recortan igual, así que se encuentran."""
    assert forma_busqueda(palabra) == forma_busqueda(palabra.upper()) == forma


@pytest.mark.parametrize(
    ("texto", "forma"),
    [
        ("11:30", "11 30"),  # una palabra de Whisper, dos tokens
        ("O-rings", "o ring"),
        ("—", ""),
        ("%", ""),
        ("¿?", ""),
        ("", ""),
    ],
)
def test_forma_busqueda_parte_en_tokens_y_vacia_los_signos(texto, forma):
    assert forma_busqueda(texto) == forma
