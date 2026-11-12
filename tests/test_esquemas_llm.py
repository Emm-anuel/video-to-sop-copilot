"""Ningún esquema JSON que se le manda a Gemma lleva `revisado` (ADR-025, regla 4 de CLAUDE.md).

`revisado` dice que una persona editó o confirmó un dato en el editor. Si el campo se colara en
la respuesta que se le pide al modelo, Gemma podría marcar como revisado por una persona un dato
que él mismo inventó. Los esquemas del LLM son modelos `*Libre` aparte del contrato, así que hoy
no lo llevan; esta prueba lo vigila.

Recorre todos los `ESQUEMA_*` de módulo del paquete `sopvid` (si aparece uno nuevo, falla hasta
que se agregue a `ESPERADOS`, para que nadie se salte la revisión) y el esquema por lote de los
fotogramas, que se arma en cada llamada.
"""

import importlib
import pkgutil
from typing import Any

import pytest

import sopvid
from sopvid.percepcion.fotogramas import esquema_lote

# Esquema → llamada a Gemma que lo usa.
ESPERADOS = {
    "sopvid.percepcion.contexto.ESQUEMA_CONTEXTO": "ficha de contexto (RF-12)",
    "sopvid.percepcion.contexto.ESQUEMA_CONTEXTO_FOTOGRAMAS": "ficha de contexto con imágenes",
    "sopvid.percepcion.segmentacion.ESQUEMA_FRONTERAS": "segmentación: fronteras",
    "sopvid.percepcion.segmentacion.ESQUEMA_REDACCION": "segmentación: redacción",
    "sopvid.percepcion.segmentacion.ESQUEMA_PASOS": "segmentación en una llamada",
    "sopvid.lenguaje.sop_generado.ESQUEMA_AGRUPAR_V1": "SOP generado: agrupar (v1)",
    "sopvid.lenguaje.sop_generado.ESQUEMA_AGRUPAR": "SOP generado: agrupar (etiquetas, v2)",
    "sopvid.lenguaje.sop_generado.ESQUEMA_PASOS": "SOP generado: redactar los pasos",
    "sopvid.lenguaje.sop_generado.ESQUEMA_PASOS_FOTOGRAMAS": "SOP generado: pasos con imágenes",
    "sopvid.lenguaje.sop_generado.ESQUEMA_RESUMEN": "SOP generado: cuadro resumen",
    "sopvid.lenguaje.sop_generado.ESQUEMA_RESUMEN_FOTOGRAMAS": "SOP generado: resumen con imágenes",
    "sopvid.lenguaje.sop_generado.ESQUEMA_CLAVES": "SOP generado: puntos y palabras clave",
    "sopvid.lenguaje.juez.ESQUEMA_JUEZ": "juez de la zona gris",
    "sopvid.lenguaje.lectura_sop.ESQUEMA_SOP_LIBRE": "SOP de texto libre (sin plantilla)",
}


def _esquema(ruta: str) -> dict[str, Any]:
    modulo, _, nombre = ruta.rpartition(".")
    return getattr(importlib.import_module(modulo), nombre)


def _esquemas_de_modulo() -> dict[int, str]:
    """Todos los dicts `ESQUEMA_*` de los módulos de `sopvid`, por identidad (un esquema que otro
    módulo importa cuenta una vez), con la primera ruta donde aparece."""
    encontrados: dict[int, str] = {}
    for info in pkgutil.walk_packages(sopvid.__path__, prefix="sopvid."):
        modulo = importlib.import_module(info.name)
        for nombre, valor in vars(modulo).items():
            if nombre.startswith("ESQUEMA_") and isinstance(valor, dict):
                encontrados.setdefault(id(valor), f"{info.name}.{nombre}")
    return encontrados


def _claves(esquema: Any) -> set[str]:
    """Todas las claves de diccionario del esquema, a cualquier profundidad (propiedades,
    `required`, `$defs`…), más los textos de las listas."""
    if isinstance(esquema, dict):
        return set(esquema) | {c for v in esquema.values() for c in _claves(v)}
    if isinstance(esquema, list):
        return {c for v in esquema for c in _claves(v)} | {v for v in esquema if isinstance(v, str)}
    return set()


def test_estan_todos_los_esquemas_que_van_a_gemma():
    """Un esquema nuevo tiene que pasar por esta revisión: agrégalo a ESPERADOS."""
    esperados = {id(_esquema(r)) for r in ESPERADOS}
    encontrados = _esquemas_de_modulo()
    nuevos = sorted(ruta for i, ruta in encontrados.items() if i not in esperados)
    assert not nuevos, f"esquemas sin revisar: {nuevos}"
    assert esperados <= set(encontrados)


@pytest.mark.parametrize("ruta", sorted(ESPERADOS))
def test_ningun_esquema_del_llm_lleva_revisado(ruta):
    esquema = _esquema(ruta)
    assert esquema, f"{ruta} está vacío"
    assert "revisado" not in _claves(esquema), f"{ruta} ({ESPERADOS[ruta]}) lleva `revisado`"


@pytest.mark.parametrize("n", [1, 8, 20])
def test_el_esquema_de_los_fotogramas_no_lleva_revisado(n):
    assert "revisado" not in _claves(esquema_lote(n))


def test_la_prueba_detecta_revisado_si_se_cuela():
    """La búsqueda mira dentro de propiedades anidadas y de `required`."""
    colado = {"properties": {"pasos": {"items": {"properties": {"revisado": {"type": "boolean"}}}}}}
    assert "revisado" in _claves(colado)
    assert "revisado" in _claves({"required": ["valor", "revisado"]})
