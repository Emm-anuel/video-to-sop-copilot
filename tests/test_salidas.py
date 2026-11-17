"""Archivos de la transcripción para descargar (RF-31): TXT, SRT y nombre del archivo.

Funciones puras de `sopvid.salidas.transcripcion`, con transcripciones inventadas. El SRT se lee
con `leer_srt`, que exige el formato al pie de la letra (también lo usa test_descargas.py).
"""

import re

import pytest

from dobles import SEGMENTOS
from sopvid.contrato import Segmento
from sopvid.percepcion.transcripcion import linea_txt
from sopvid.salidas.transcripcion import nombre_archivo, srt, tiempo_srt, txt

_TIEMPO = r"(\d{2}):([0-5]\d):([0-5]\d),(\d{3})"
# Un bloque: número sin ceros a la izquierda, tiempos HH:MM:SS,mmm y una línea de texto que no
# empieza ni termina en espacio.
_BLOQUE = re.compile(rf"([1-9]\d*)\n{_TIEMPO} --> {_TIEMPO}\n(\S(?:[^\n]*\S)?)\n")


def _ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def leer_srt(contenido: str) -> list[tuple[int, int, str]]:
    """Los bloques como (inicio_ms, fin_ms, texto). Falla si el formato no es estricto: bloques
    separados por una línea en blanco, índices seguidos desde 1, fin ≥ inicio y sin solaparse."""
    if contenido == "":
        return []
    bloques = []
    for i, crudo in enumerate(contenido.split("\n\n"), start=1):
        crudo = crudo if crudo.endswith("\n") else crudo + "\n"
        m = _BLOQUE.fullmatch(crudo)
        assert m, f"bloque {i} mal formado: {crudo!r}"
        assert int(m[1]) == i, f"índice {m[1]} donde iba {i}"
        inicio, fin = _ms(*m.groups()[1:5]), _ms(*m.groups()[5:9])
        assert fin >= inicio, f"bloque {i}: fin antes del inicio"
        if bloques:
            assert inicio >= bloques[-1][1], f"bloque {i} se encima con el anterior"
        bloques.append((inicio, fin, m[10]))
    assert contenido.endswith("\n") and not contenido.endswith("\n\n\n")
    return bloques


def seg(id_: int, t: float, t_fin: float, texto: str) -> Segmento:
    return Segmento(id=id_, t_inicio=t, t_fin=t_fin, texto=texto)


# ── TXT ──────────────────────────────────────────────────────────────────────


def test_txt_es_el_formato_en_vivo_completo() -> None:
    assert txt(SEGMENTOS) == "".join(linea_txt(s) for s in SEGMENTOS)
    assert txt(SEGMENTOS).splitlines() == [
        "[00:00] Primero reviso el manómetro.",
        "[00:01] Después cierro la válvula.",
        "[00:02] Por último anoto la lectura.",
    ]


def test_txt_sin_segmentos_es_vacio() -> None:
    assert txt([]) == ""


# ── SRT ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("segundos", "marca"),
    [
        (0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (59.9994, "00:00:59,999"),
        (59.9996, "00:01:00,000"),
        (61.25, "00:01:01,250"),
        (3600 + 2 * 60 + 3.004, "01:02:03,004"),
        (36000, "10:00:00,000"),
    ],
)
def test_tiempo_srt(segundos: float, marca: str) -> None:
    assert tiempo_srt(segundos) == marca


def test_srt_un_bloque_por_segmento_con_indices_seguidos() -> None:
    contenido = srt(SEGMENTOS)

    assert contenido == (
        "1\n00:00:00,000 --> 00:00:00,900\nPrimero reviso el manómetro.\n"
        "\n"
        "2\n00:00:01,000 --> 00:00:01,900\nDespués cierro la válvula.\n"
        "\n"
        "3\n00:00:02,000 --> 00:00:02,800\nPor último anoto la lectura.\n"
    )
    assert leer_srt(contenido) == [
        (0, 900, "Primero reviso el manómetro."),
        (1000, 1900, "Después cierro la válvula."),
        (2000, 2800, "Por último anoto la lectura."),
    ]


def test_srt_acentos_y_enie_tal_cual() -> None:
    contenido = srt([seg(0, 0, 2, "El niño ajustó la cañería; ¿quién apagó el compresor?")])

    assert leer_srt(contenido)[0][2] == "El niño ajustó la cañería; ¿quién apagó el compresor?"
    assert "cañería".encode() in contenido.encode("utf-8")


def test_srt_recorta_el_fin_del_primero_si_se_enciman() -> None:
    contenido = srt(
        [
            seg(0, 0.0, 3.5, "Abro la tapa."),
            seg(1, 2.25, 4.0, "Saco el cartucho."),
            seg(2, 4.0, 6.0, "Pongo el nuevo."),
        ]
    )

    assert leer_srt(contenido) == [
        (0, 2250, "Abro la tapa."),  # recortado al inicio del siguiente
        (2250, 4000, "Saco el cartucho."),  # se toca con el siguiente: no se recorta
        (4000, 6000, "Pongo el nuevo."),
    ]


def test_srt_ordena_por_inicio_antes_de_recortar() -> None:
    contenido = srt([seg(5, 4.0, 5.0, "Después."), seg(2, 1.0, 4.5, "Antes.")])

    assert leer_srt(contenido) == [(1000, 4000, "Antes."), (4000, 5000, "Después.")]


def test_srt_salta_los_vacios_sin_gastar_indice() -> None:
    contenido = srt(
        [
            seg(0, 0.0, 1.0, "Uno."),
            seg(1, 1.0, 2.0, ""),
            seg(2, 2.0, 3.0, "   \n "),
            seg(3, 3.0, 4.0, "Dos."),
        ]
    )

    assert leer_srt(contenido) == [(0, 1000, "Uno."), (3000, 4000, "Dos.")]


def test_srt_un_vacio_encimado_no_recorta_al_anterior() -> None:
    contenido = srt([seg(0, 0.0, 2.0, "Uno."), seg(1, 1.0, 1.5, " "), seg(2, 2.0, 3.0, "Dos.")])

    assert leer_srt(contenido)[0] == (0, 2000, "Uno.")


def test_srt_texto_en_una_linea() -> None:
    """Un salto doble dentro del texto partiría el bloque: los espacios se colapsan."""
    contenido = srt([seg(0, 0.0, 1.0, "  Cierro\n\nla   válvula. ")])

    assert leer_srt(contenido) == [(0, 1000, "Cierro la válvula.")]


def test_srt_redondea_al_milisegundo_sin_solaparse() -> None:
    contenido = srt([seg(0, 0.0, 1.0006, "Uno."), seg(1, 1.0004, 2.0, "Dos.")])

    assert leer_srt(contenido) == [(0, 1000, "Uno."), (1000, 2000, "Dos.")]


def test_srt_sin_segmentos_con_texto_es_vacio() -> None:
    assert srt([]) == ""
    assert srt([seg(0, 0, 1, " ")]) == ""


def test_srt_de_mas_de_una_hora() -> None:
    contenido = srt([seg(0, 3725.5, 3727.0, "Ya casi termino.")])

    assert contenido.splitlines()[1] == "01:02:05,500 --> 01:02:07,000"


# ── Nombre del archivo ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("titulo", "nombre"),
    [
        ("Cambio de filtro", "cambio_de_filtro.srt"),
        ("Cambio de filtro: línea 3", "cambio_de_filtro_linea_3.srt"),
        ("Revisión del compresor (año 2026)", "revision_del_compresor_ano_2026.srt"),
        ("  ¿Señalización?  ¡Ya!  ", "senalizacion_ya.srt"),
        ("PIÑÓN / Engrane #4 & 5", "pinon_engrane_4_5.srt"),
        ('a"b\\c/d<e>f|g*h?i', "a_b_c_d_e_f_g_h_i.srt"),
        ("..\\..\\etc\\passwd", "etc_passwd.srt"),
    ],
)
def test_nombre_archivo(titulo: str, nombre: str) -> None:
    assert nombre_archivo(titulo, "srt", respaldo="video_7") == nombre


@pytest.mark.parametrize("titulo", ["", "   ", "¿¡!?", "—", "日本語"])
def test_nombre_archivo_sin_nada_usa_el_respaldo(titulo: str) -> None:
    assert nombre_archivo(titulo, "txt", respaldo="video_7") == "video_7.txt"


def test_nombre_archivo_largo_se_corta_sin_guion_al_final() -> None:
    nombre = nombre_archivo("palabra " * 40, "json", respaldo="video_7")

    assert nombre.endswith(".json")
    base = nombre.removesuffix(".json")
    assert len(base) <= 80
    assert not base.endswith("_")
    assert re.fullmatch(r"[a-z0-9_]+", base)
