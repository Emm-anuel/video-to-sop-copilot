"""Conversión de un SOP en Markdown o TXT al esquema SOP (`sopvid.lenguaje.sop_markdown`).

Todo el texto es inventado (tests/fixtures/README.md). Ninguna prueba usa la base de datos.
"""

import logging
import re
import unicodedata
from pathlib import Path

import pytest

from sopvid.contrato import SOP, Dato, Riesgo
from sopvid.lenguaje.sop_markdown import Advertencia, ErrorSOP, ResultadoConversion, convertir_sop
from sopvid.texto import NO_IDENTIFICADO

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures"
PLANTILLA = RAIZ / "docs" / "contrato" / "plantilla_sop.md"
MD = "sop_filtro_agua.md"
TXT = "sop_filtro_agua_simple.txt"
TITULO = "Cambio del cartucho del filtro de agua"
RESPONSABLE = "Técnico de mantenimiento"
BOM = "\N{BYTE ORDER MARK}"


def _leer(ruta: Path) -> str:
    # Siempre UTF-8: en Windows, sin encoding se lee en cp1252 y los acentos fallan.
    return ruta.read_text(encoding="utf-8")


def _readme() -> str:
    return _leer(FIXTURES / "README.md")


def _nombres_readme() -> list[str]:
    """Nombres de la tabla "Inicios de paso reales" de tests/fixtures/README.md."""
    nombres = re.findall(r"^\| \d+\. ([^|]+?) \| \d+ \|", _readme(), re.MULTILINE)
    assert len(nombres) == 6, "cambió la tabla de tests/fixtures/README.md"
    return nombres


def _inicios_readme() -> list[int]:
    m = re.search(r"Inicios de paso: `\[([\d, ]+)\]`", _readme())
    assert m, "cambió la línea de inicios de paso de tests/fixtures/README.md"
    return [int(x) for x in m.group(1).split(",")]


@pytest.fixture(scope="module")
def md() -> str:
    return _leer(FIXTURES / MD)


@pytest.fixture(scope="module")
def txt() -> str:
    return _leer(FIXTURES / TXT)


def _sop(pasos: str, antes: str = "") -> str:
    """SOP inventado mínimo: título, lo que vaya `antes` (resumen, riesgos…) y los pasos."""
    return f"# Prueba inventada\n\n{antes}## Pasos\n{pasos}"


def _tipos(r: ResultadoConversion) -> list[str]:
    return [a.tipo for a in r.advertencias]


# ── Fixtures del filtro de agua ──────────────────────────────────────────────────────────────


def test_plantilla_completa_en_markdown(md):
    r = convertir_sop(md)
    s, resumen = r.sop, r.sop.resumen

    assert r.advertencias == []
    assert s.titulo == TITULO
    assert [p.nombre for p in s.pasos] == _nombres_readme()
    assert [p.numero for p in s.pasos] == [1, 2, 3, 4, 5, 6]
    assert resumen.duracion_total_min == 3
    assert resumen.responsable == Dato(valor=RESPONSABLE, confianza="alta", fuente="documento")
    assert resumen.horario_frecuencia.valor.startswith("Cada tres meses")
    assert [e.nombre for e in resumen.roles] == [RESPONSABLE, "Supervisor de turno"]
    assert len(resumen.equipo_operacion) == 7
    assert resumen.riesgos == [
        Riesgo(
            descripcion="Agua a presión al abrir la carcasa",
            nivel="alto",
            paso=3,
            control="Liberar la presión hasta que el manómetro marque cero.",
        ),
        Riesgo(
            descripcion="Piso mojado", nivel="medio", paso=4, control="Cubeta debajo del filtro."
        ),
    ]
    assert len(resumen.en_caso_de_falla) == 2
    assert resumen.en_caso_de_falla[0].accion == "No usar extensión; avisar al supervisor de turno."
    assert s.puntos_clave == [] and s.palabras_clave == []  # no están en la plantilla


def test_pasos_de_la_plantilla_completa(md):
    pasos = convertir_sop(md).sop.pasos

    assert pasos[0].descripcion.startswith("Colocarse los guantes de nitrilo")
    assert pasos[0].equipo == ["Guantes de nitrilo", "Lentes de seguridad"]
    assert pasos[4].puntos_validacion == ["Cartucho centrado", "vaso apretado un cuarto de vuelta"]
    for p in pasos:
        assert (p.responsable, p.confianza, p.campos_inferidos) == (RESPONSABLE, "alta", [])
        assert p.tiempo_esperado_min == 0.5
        assert p.t_inicio is None and p.t_fin is None  # un SOP cargado no tiene tiempos


def test_lista_numerada_minima_en_txt(txt):
    r = convertir_sop(txt)
    s = r.sop

    assert r.advertencias == []
    assert s.titulo == TITULO
    assert [p.nombre for p in s.pasos] == _nombres_readme()
    assert s.resumen.responsable.valor == RESPONSABLE
    for p in s.pasos:
        assert (p.responsable, p.confianza, p.campos_inferidos) == (
            RESPONSABLE,
            "media",
            ["responsable"],
        )
        assert p.descripcion == "" and p.equipo == [] and p.tiempo_esperado_min is None
    # Lo que no aparece queda vacío: nada se inventa.
    assert s.resumen.objetivo.valor is None and s.resumen.duracion_total_min is None
    assert s.resumen.roles == [] and s.resumen.riesgos == []


def test_cruce_con_los_inicios_anotados_del_analisis(md, txt):
    inicios = _inicios_readme()
    assert len(inicios) == 6
    assert len(convertir_sop(md).sop.pasos) == len(inicios)
    assert len(convertir_sop(txt).sop.pasos) == len(inicios)


@pytest.mark.parametrize("archivo", [MD, TXT])
def test_ida_y_vuelta(archivo):
    sop = convertir_sop(_leer(FIXTURES / archivo)).sop
    assert SOP.model_validate_json(sop.model_dump_json()) == sop


def test_la_plantilla_vacia_convierte_sin_advertencias():
    r = convertir_sop(_leer(PLANTILLA))

    assert r.advertencias == []
    assert r.sop.titulo == "Título del procedimiento"
    assert len(r.sop.pasos) == 1
    assert r.sop.resumen.objetivo.valor is None and r.sop.resumen.roles == []
    assert r.sop.pasos[0].responsable == NO_IDENTIFICADO


# ── Finales de línea, BOM, mayúsculas, acentos y sinónimos ───────────────────────────────────


@pytest.mark.parametrize("archivo", [MD, TXT])
@pytest.mark.parametrize(
    "variante",
    [
        lambda t: t.replace("\n", "\r\n"),
        lambda t: BOM + t,
        lambda t: BOM + t.replace("\n", "\r\n"),
    ],
    ids=["crlf", "bom", "bom_crlf"],
)
def test_crlf_y_bom_dan_el_mismo_sop(archivo, variante):
    # Las variantes se construyen en memoria: no dependen de cómo guarde git el archivo.
    lf = _leer(FIXTURES / archivo).replace("\r\n", "\n")
    assert "\r" not in lf and not lf.startswith(BOM)
    assert convertir_sop(variante(lf)) == convertir_sop(lf)


# Encabezados y claves del fixture (no contenido): cambiarlos no debe cambiar el SOP.
ENCABEZADOS_Y_CLAVES = [
    "## Resumen",
    "## Roles",
    "## Equipo",
    "## Riesgos",
    "## En caso de falla",
    "## Pasos",
    "- Objetivo:",
    "- Alcance:",
    "- Responsable:",
    "- Lugar:",
    "- Horario:",
    "- Duración total (min):",
    "- Alto:",
    "- Medio:",
    "Paso:",
    "Control:",
    "- Equipo:",
    "- Validación:",
    "- Tiempo (min):",
]


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


@pytest.mark.parametrize("cambio", [str.upper, str.lower, _sin_acentos])
def test_encabezados_en_mayusculas_o_sin_acentos_dan_el_mismo_sop(md, cambio):
    variante = md
    for e in ENCABEZADOS_Y_CLAVES:
        assert e in md
        variante = variante.replace(e, cambio(e))
    assert variante != md
    assert convertir_sop(variante) == convertir_sop(md)


@pytest.mark.parametrize(
    ("original", "sinonimo"),
    [
        ("## Pasos", "## Procedimiento"),
        ("## Equipo\n", "## Equipo de operación\n"),
        ("- Horario:", "- Frecuencia:"),
        ("- Horario:", "- Horario / frecuencia:"),
        ("- Duración total (min):", "- Duración total:"),
        ("- Validación:", "- Puntos de validación:"),
        ("- Tiempo (min):", "- Duración:"),
        ("- Tiempo (min):", "- Tiempo:"),
    ],
)
def test_sinonimos_dan_el_mismo_sop(md, original, sinonimo):
    assert original in md
    assert convertir_sop(md.replace(original, sinonimo)) == convertir_sop(md)


# ── Formas de escribir los pasos ─────────────────────────────────────────────────────────────

NOMBRES = ["Cerrar la llave de paso", "Liberar la presión", "Abrir la llave"]


@pytest.mark.parametrize(
    "plantilla",
    ["### {n}. {nombre}", "### Paso {n}: {nombre}", "{n}. {nombre}"],
    ids=["subtitulo", "subtitulo_paso", "lista"],
)
def test_formas_de_escribir_los_pasos(plantilla):
    pasos = "".join(plantilla.format(n=n, nombre=x) + "\n" for n, x in enumerate(NOMBRES, 1))
    r = convertir_sop(_sop(pasos))
    assert [p.nombre for p in r.sop.pasos] == NOMBRES
    assert r.advertencias == []


def test_lista_numerada_con_descripcion_y_claves():
    r = convertir_sop(
        _sop(
            "1. Cerrar la llave de paso\n"
            "Girar a la derecha.\n"
            "  Hasta el tope.\n"
            "- Tiempo (min): 0,5\n"
            "- Equipo: Llave 2, cubeta; trapo\n"
            "- Validación: Presión de 0,5 bar; Sin fugas\n"
            "2. Abrir la llave\n"
        )
    )
    p1, p2 = r.sop.pasos
    assert r.advertencias == []
    assert p1.descripcion == "Girar a la derecha. Hasta el tope."
    assert p1.tiempo_esperado_min == 0.5  # coma decimal
    assert p1.equipo == ["Llave 2", "cubeta", "trapo"]
    assert p1.puntos_validacion == ["Presión de 0,5 bar", "Sin fugas"]  # la coma decimal no separa
    assert p2.descripcion == "" and p2.equipo == []


# ── Numeración ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("numeros", [[1, 2, 4], [1, 2, 2], [2, 3, 4], [1, 3, 2]])
def test_numeracion_irregular_se_renumera_y_avisa(numeros):
    pasos = "".join(f"{n}. {x}\n" for n, x in zip(numeros, NOMBRES, strict=True))
    r = convertir_sop(_sop(pasos))
    assert [p.numero for p in r.sop.pasos] == [1, 2, 3]
    assert [p.nombre for p in r.sop.pasos] == NOMBRES
    assert set(_tipos(r)) == {"numeracion"}


def test_numeracion_1_2_4_cita_la_linea_y_numeros():
    r = convertir_sop(_sop("1. Cerrar la llave\n2. Liberar la presión\n4. Abrir la llave\n"))
    (a,) = r.advertencias
    assert (a.tipo, a.linea) == ("numeracion", 6)
    assert "se esperaba el paso 3 y llegó el 4" in a.mensaje
    assert str(a).startswith("numeracion (línea 6): ")


def test_paso_sin_numero_se_numera_y_avisa():
    r = convertir_sop(_sop("### 1. Cerrar la llave\n### Abrir la llave\n"))
    assert [p.numero for p in r.sop.pasos] == [1, 2]
    assert _tipos(r) == ["numeracion"]


def test_el_riesgo_cita_el_numero_nuevo_tras_renumerar():
    riesgos = (
        "## Riesgos\n"
        "- Alto: Agua a presión. Paso: 4. Control: Liberar la presión.\n"
        "- Bajo: Goteo. Paso: 9.\n\n"
    )
    r = convertir_sop(
        _sop("1. Cerrar la llave\n2. Liberar la presión\n4. Abrir la llave\n", riesgos)
    )
    assert [x.paso for x in r.sop.resumen.riesgos] == [3, 9]  # 4 → 3; el 9 no existe y se conserva
    assert _tipos(r) == ["valor_invalido", "numeracion"]  # en orden de línea: riesgo 5, paso 10
    assert [a.linea for a in r.advertencias] == [5, 10]


def test_el_riesgo_que_cita_un_numero_repetido_se_conserva():
    riesgos = "## Riesgos\n- Alto: Agua a presión. Paso: 2.\n\n"
    r = convertir_sop(
        _sop("1. Cerrar la llave\n2. Liberar la presión\n2. Abrir la llave\n", riesgos)
    )
    assert r.sop.resumen.riesgos[0].paso == 2
    assert sorted(_tipos(r)) == ["numeracion", "valor_invalido"]


# ── Errores ──────────────────────────────────────────────────────────────────────────────────

SECRETOS = ("secreto", "confidencial", "Válvula", "válvula", "Cerrar", "llave")


@pytest.mark.parametrize(
    ("texto", "formato"),
    [
        ("", "# Título"),
        ("  \n\n\t\n", "# Título"),
        ("## Pasos\n1. Cerrar la llave secreta\n", "# Título"),
        ("Pasos:\n1. Cerrar la llave secreta\n", "# Título"),
        ("1. Cerrar la llave secreta\n", "# Título"),
        ("#\n\n## Pasos\n1. Cerrar la llave secreta\n", "# Título"),
        ("# Válvula secreta\n\nNota confidencial sin pasos.\n", "## Pasos"),
        ("# Válvula secreta\n\n## Pasos\nTexto confidencial sin numerar.\n", "## Pasos"),
        ("Válvula secreta\n\nResponsable: confidencial\n", "Pasos:"),
        ("# Válvula secreta\n\n## Pasos\n### 1. Cerrar la llave\n### 2.\n", "### 2. Nombre"),
        ("# Válvula secreta\n\n## Pasos\n1. Cerrar la llave\n2.\n", '"2. Nombre"'),
    ],
    ids=[
        "vacio",
        "solo_espacios",
        "sin_titulo_md",
        "sin_titulo_txt",
        "sin_titulo_lista",
        "titulo_vacio",
        "sin_seccion_de_pasos",
        "seccion_de_pasos_sin_pasos",
        "txt_sin_pasos",
        "subtitulo_sin_nombre",
        "item_sin_nombre",
    ],
)
def test_errores_dicen_el_formato_y_no_citan_el_sop(texto, formato):
    with pytest.raises(ErrorSOP) as exc:
        convertir_sop(texto)
    mensaje = str(exc.value)
    assert formato in mensaje
    assert not any(s in mensaje for s in SECRETOS)


def test_error_sop_es_value_error():
    assert issubclass(ErrorSOP, ValueError)


# ── Responsable ──────────────────────────────────────────────────────────────────────────────


def test_paso_sin_responsable_ni_en_el_resumen_queda_no_identificado():
    r = convertir_sop(_sop("1. Cerrar la llave de paso\n"))
    p = r.sop.pasos[0]
    assert (p.responsable, p.confianza, p.campos_inferidos) == (NO_IDENTIFICADO, "baja", [])
    assert r.sop.resumen.responsable.valor is None
    assert r.advertencias == []


def test_responsable_propio_se_conserva_y_el_que_falta_se_hereda():
    r = convertir_sop(
        _sop(
            "1. Cerrar la llave de paso\n- Responsable: Supervisor de turno\n2. Abrir la llave\n",
            "## Resumen\n- Responsable: Técnico\n\n",
        )
    )
    p1, p2 = r.sop.pasos
    assert (p1.responsable, p1.confianza, p1.campos_inferidos) == (
        "Supervisor de turno",
        "alta",
        [],
    )
    assert (p2.responsable, p2.confianza, p2.campos_inferidos) == (
        "Técnico",
        "media",
        ["responsable"],
    )


# ── Advertencias ─────────────────────────────────────────────────────────────────────────────


def test_clave_y_seccion_desconocidas_avisan_sin_citar_el_texto():
    r = convertir_sop(
        _sop(
            "1. Cerrar la llave\n- Color: rojo intenso\n- Tiempo (min): 1\n",
            "## Resumen\n- Presupuesto: confidencial\n- Objetivo: Probar\n\n"
            "## Anexos\nTexto secreto.\n\n",
        )
    )
    assert _tipos(r) == ["clave_desconocida", "seccion_desconocida", "clave_desconocida"]
    assert [a.linea for a in r.advertencias] == [4, 7, 12]
    assert r.sop.resumen.objetivo.valor == "Probar"
    assert r.sop.pasos[0].tiempo_esperado_min == 1
    avisos = " ".join(str(a) for a in r.advertencias)
    for palabra in ("Color", "rojo", "Presupuesto", "confidencial", "Anexos", "secreto"):
        assert palabra not in avisos


@pytest.mark.parametrize(
    ("total", "avisa"),
    [("3", False), ("3,6", False), ("2.6", False), ("3.8", True), ("2.4", True), ("10", True)],
)
def test_suma_de_tiempos_fuera_de_20_por_ciento(total, avisa):
    pasos = "1. Cerrar la llave\n- Tiempo (min): 1\n2. Abrir la llave\n- Tiempo (min): 2\n"
    r = convertir_sop(_sop(pasos, f"## Resumen\n- Duración total (min): {total}\n\n"))
    assert _tipos(r) == (["tiempos"] if avisa else [])
    if avisa:
        assert r.advertencias[0].linea is None


def test_sin_tiempo_en_algun_paso_no_compara_la_suma():
    pasos = "1. Cerrar la llave\n- Tiempo (min): 1\n2. Abrir la llave\n"
    r = convertir_sop(_sop(pasos, "## Resumen\n- Duración total (min): 50\n\n"))
    assert r.advertencias == []


@pytest.mark.parametrize(
    ("nombre", "avisa"),
    [
        ("Cerrar la llave", False),
        ("Ponerse guantes", False),
        ("Batir la mezcla", False),
        ("Beber agua", False),
        ("Colocarse los lentes", False),
        ("Llave cerrada", True),
        ("La llave", True),
        ("Revisión de fugas", True),
    ],
)
def test_nombre_que_no_empieza_en_infinitivo_avisa(nombre, avisa):
    r = convertir_sop(_sop(f"1. {nombre}\n"))
    assert _tipos(r) == (["infinitivo"] if avisa else [])
    assert r.sop.pasos[0].nombre == nombre  # solo avisa, no corrige


def test_valores_invalidos_avisan_y_no_se_inventan():
    riesgos = (
        "## Riesgos\n"
        "- Crítico: Agua. Paso: 1.\n"
        "- Alto: Agua. Paso: tres. Control: Cerrar.\n"
        "Sin nivel\n\n"
    )
    r = convertir_sop(_sop("1. Cerrar la llave\n- Tiempo (min): rápido\n", riesgos))
    assert _tipos(r) == ["valor_invalido"] * 4
    assert r.sop.resumen.riesgos == [
        Riesgo(descripcion="Agua", nivel="alto", paso=None, control="Cerrar.")
    ]
    assert r.sop.pasos[0].tiempo_esperado_min is None


def test_advertencia_es_un_tipo_estable():
    a = Advertencia("tiempos", None, "x")
    assert (a.tipo, a.linea) == ("tiempos", None)
    assert str(a) == "tiempos: x"


def test_comentarios_html_no_mueven_los_numeros_de_linea():
    r = convertir_sop(_sop("<!--\nvarias\nlíneas\n-->\n1. Cerrar la llave\n- Color: rojo\n"))
    assert [a.linea for a in r.advertencias] == [9]


# ── Log ──────────────────────────────────────────────────────────────────────────────────────


def test_el_log_solo_cuenta(md, caplog):
    with caplog.at_level(logging.DEBUG, logger="sopvid.lenguaje.sop_markdown"):
        sop = convertir_sop(md).sop
    log = " ".join(r.getMessage() for r in caplog.records)
    assert "6 pasos" in log and "0 advertencias" in log
    assert TITULO not in log and RESPONSABLE not in log
    assert not any(p.nombre in log for p in sop.pasos)
