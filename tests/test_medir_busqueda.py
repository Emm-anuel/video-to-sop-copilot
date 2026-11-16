"""Partes puras de `scripts/medir_busqueda.py`: desplazar tiempos, elegir consultas, palabras de
RNF-03 y percentiles. La medición de verdad siembra 50 videos en Postgres: se lanza a mano."""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_busqueda as mb  # noqa: E402  (la ruta se ajusta arriba)

from sopvid.contrato import Analisis, Idioma, Palabra, Segmento  # noqa: E402
from sopvid.lenguaje.busqueda import TOKENS_UNIDOS, normalizar_consulta  # noqa: E402


def _analisis(texto: str, t0: float = 0.0) -> Analisis:
    palabras = [Palabra(w=w, t=t0 + i, t_fin=t0 + i + 0.5) for i, w in enumerate(texto.split())]
    segmento = Segmento(
        id=0, t_inicio=palabras[0].t, t_fin=palabras[-1].t_fin, texto=texto, palabras=palabras
    )
    return Analisis(
        video_id=1,
        duracion_s=palabras[-1].t_fin,
        idioma=Idioma(codigo="es", confianza=0.9),
        transcripcion=[segmento],
    )


def test_desplazar_mueve_segmentos_y_palabras() -> None:
    original = _analisis("abro la llave")

    movido = mb.desplazar(original, 13.7)

    assert movido.transcripcion[0].t_inicio == pytest.approx(13.7)
    assert [p.t for p in movido.transcripcion[0].palabras] == pytest.approx([13.7, 14.7, 15.7])
    assert movido.duracion_s == pytest.approx(original.duracion_s + 13.7)
    assert mb.desplazar(original, 0) is original


def test_palabras_de_salta_las_que_quedan_vacias() -> None:
    assert [w for w, _ in mb.palabras_de(_analisis("abro — la llave"))] == ["abro", "la", "llave"]


def test_elegir_consultas_por_tipo_sin_repetir() -> None:
    frecuentes = "la llave de paso queda bien muy cerrada"
    texto = " ".join([frecuentes] * 5 + [f"rara{i:02d} palabra{i:02d}" for i in range(40)])
    corpus = {"video_a": _analisis(texto), "video_b": _analisis("la llave queda cerrada hoy")}

    consultas = mb.elegir_consultas(corpus)

    tipos = [t for t, _ in consultas]
    assert tipos.count("comun") == 8 and tipos.count("rara") == 8
    assert {"frase", "frase_larga", "sin_resultados"} <= set(tipos)
    assert len({c for _, c in consultas}) == len(consultas)
    assert dict(consultas[:1]) == {"comun": "la"}
    larga = next(c for t, c in consultas if t == "frase_larga")
    assert len(normalizar_consulta(larga)) > TOKENS_UNIDOS
    for tipo, consulta in consultas:
        if tipo == "frase":
            assert 2 <= len(consulta.split()) <= 4


def test_palabras_rnf03_unicas_y_repartidas() -> None:
    analisis = _analisis(" ".join(f"w{i}" for i in range(30)) + " w3 w3")

    palabras = mb.palabras_rnf03(analisis)

    assert len(palabras) == 10
    assert "w3" not in [w for w, _ in palabras]
    assert palabras[0] == ("w0", 0.0) and palabras[-1] == ("w29", 29.0)


def test_percentil_interpola() -> None:
    assert mb.percentil([1, 2, 3, 4], 50) == 2.5
    assert mb.percentil([10], 95) == 10
    assert mb.percentil(list(range(1, 101)), 95) == pytest.approx(95.05)
    with pytest.raises(ValueError):
        mb.percentil([], 50)


def test_concatenar_hasta_el_objetivo_sin_encimar_y_con_ids_nuevos() -> None:
    a, b = _analisis("abro la llave de paso"), _analisis("cierro la válvula", t0=3.0)

    largo = mb.concatenar([a, b], objetivo=12, desde_s=2.0)

    segmentos = largo.transcripcion
    assert [s.id for s in segmentos] == list(range(len(segmentos)))
    assert segmentos[0].t_inicio == 2.0  # la primera pieza conserva sus tiempos + desde_s
    assert segmentos[1].t_inicio == pytest.approx(segmentos[0].t_fin + mb.PAUSA_S)
    tokens = sum(len(s.palabras) for s in segmentos)
    assert 12 <= tokens < 12 + 5  # corta en el borde del segmento que pasa el objetivo
    assert largo.duracion_s == segmentos[-1].t_fin


def test_videos_sinteticos_con_y_sin_concatenar() -> None:
    corpus = {"video_a": _analisis("uno dos tres"), "video_b": _analisis("cuatro cinco")}

    copias = mb.videos_sinteticos(corpus, n_videos=4)
    largos = mb.videos_sinteticos(corpus, palabras_por_video=10, n_videos=4)

    assert [e for e, _, _ in copias] == ["video_a", "video_b", "video_a", "video_b"]
    assert [r for _, _, r in copias] == [True, False, False, False]
    assert copias[2][1].transcripcion[0].t_inicio == pytest.approx(mb.DESPLAZAMIENTO_S)
    assert [r for _, _, r in largos] == [True, False, False, False]
    assert all(sum(len(s.palabras) for s in a.transcripcion) >= 10 for _, a, _ in largos)
    assert largos[1][1].transcripcion[0].palabras[0].w == "cuatro"  # empieza por otra clave
