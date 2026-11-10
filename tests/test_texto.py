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
