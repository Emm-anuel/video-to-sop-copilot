"""Utilidades de texto compartidas (`sopvid.texto`)."""

import pytest

from sopvid.percepcion import segmentacion
from sopvid.texto import NO_IDENTIFICADO, normalizar


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
