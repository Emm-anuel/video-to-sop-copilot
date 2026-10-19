"""Experimento MiniLM para fronteras (M1 TextTiling, M2 fusión de cortes) con embeddings
sintéticos: cada "tema" es un vector base y cada segmento, su tema más ruido. Sin modelo."""

from collections.abc import Sequence

import numpy as np
import pytest

from sopvid.contrato import Analisis
from sopvid.percepcion import fronteras_minilm as fm

D = 16


def temas(largos: Sequence[int], ruido: float = 0.05, semilla: int = 0) -> np.ndarray:
    """Bloques consecutivos de segmentos; el bloque b usa el eje b como tema."""
    rng = np.random.default_rng(semilla)
    filas = []
    for b, largo in enumerate(largos):
        base = np.zeros(D)
        base[b] = 1.0
        filas += [base + ruido * rng.normal(size=D) for _ in range(largo)]
    return np.array(filas)


def analisis_de(n: int, primer_id: int = 10) -> Analisis:
    return Analisis(
        video_id=0,
        duracion_s=float(2 * n),
        idioma={"codigo": "es", "confianza": 1.0, "fijado_a_mano": True},
        transcripcion=[
            {"id": primer_id + i, "t_inicio": 2.0 * i, "t_fin": 2.0 * i + 1.5, "texto": f"s{i}"}
            for i in range(n)
        ],
    )


class EmbedderFijo:
    """Devuelve una matriz dada, fila por texto, y cuenta las llamadas."""

    def __init__(self, x: np.ndarray) -> None:
        self.x, self.llamadas = x, 0

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        self.llamadas += 1
        assert len(textos) == len(self.x)
        return self.x


# ── M1 ───────────────────────────────────────────────────────────────────────────────────────


def test_puntajes_bajan_en_el_cambio_de_tema():
    s = fm.puntajes_bloques(temas([4, 4]), k=2)
    assert len(s) == 7
    assert int(np.argmin(s)) == 3  # hueco antes de la posición 4
    assert s[3] < 0.2 < s[0]


def test_profundidades_de_hearst_en_una_curva_conocida():
    s = np.array([0.9, 0.5, 0.8, 0.8, 0.2, 0.7])
    # hueco 1: sube a 0.9 a la izquierda y a 0.8 a la derecha → 0.4 + 0.3
    # hueco 4: sube a 0.8 (cruza la meseta 0.8–0.8, pero no el 0.5) y a 0.7 → 0.6 + 0.5
    np.testing.assert_allclose(fm.profundidades(s), [0, 0.7, 0, 0, 1.1, 0], atol=1e-9)


def test_texttiling_encuentra_los_cambios_de_tema():
    assert fm.cortes_texttiling(temas([4, 3, 5])) == [0, 4, 7]


def test_texttiling_no_fuerza_una_introduccion():
    """El primer segmento siempre inicia paso; no se inventa una introducción."""
    assert fm.cortes_texttiling(temas([6]))[0] == 0


def test_texttiling_respeta_la_separacion_minima():
    x = temas([3, 1, 1, 3])  # dos cambios de tema seguidos
    inicios = fm.cortes_texttiling(x, c=0.0, separacion_min=2)
    assert all(b - a >= 2 for a, b in zip(inicios, inicios[1:], strict=False))


def test_un_umbral_mas_alto_no_agrega_cortes():
    x = temas([3, 4, 2, 5, 3], ruido=0.3, semilla=3)
    anteriores = None
    for c in (0.0, 0.25, 0.5, 0.75, 1.0):
        actuales = set(fm.cortes_texttiling(x, c=c))
        if anteriores is not None:
            assert actuales <= anteriores
        anteriores = actuales


def test_texttiling_casos_minimos():
    assert fm.cortes_texttiling(np.zeros((0, D))) == []
    assert fm.cortes_texttiling(temas([1])) == [0]


def test_inicios_texttiling_devuelve_ids_de_segmento():
    x = temas([4, 4])
    e = EmbedderFijo(x)
    assert fm.inicios_texttiling(analisis_de(8, primer_id=10), e) == [10, 14]
    assert e.llamadas == 1


# ── M2 ───────────────────────────────────────────────────────────────────────────────────────


def test_fusion_une_cortes_dentro_del_mismo_tema():
    x = temas([4, 4, 4])
    assert fm.fusionar_cortes(x, [0, 2, 4, 6, 8, 10], u=0.6) == [0, 4, 8]


def test_fusion_conserva_cortes_entre_temas_distintos():
    assert fm.fusionar_cortes(temas([3, 3, 3]), [0, 3, 6], u=0.6) == [0, 3, 6]


def test_fusion_nunca_quita_el_primer_inicio():
    x = temas([10])
    assert fm.fusionar_cortes(x, [2, 5, 8], u=0.6) == [2]


def test_un_umbral_mas_alto_fusiona_menos():
    x = temas([3, 3, 3, 3], ruido=0.6, semilla=1)
    pedidos = list(range(0, 12, 2))
    tamanos = [len(fm.fusionar_cortes(x, pedidos, u=u)) for u in (0.5, 0.6, 0.7, 0.99)]
    assert tamanos == sorted(tamanos)
    assert fm.fusionar_cortes(x, pedidos, u=1.0) == pedidos


def test_fusion_no_depende_del_orden_ni_de_duplicados():
    x = temas([4, 4, 4])
    assert fm.fusionar_cortes(x, [8, 0, 4, 2, 2, 6]) == fm.fusionar_cortes(x, [0, 2, 4, 6, 8])


def test_fusionar_inicios_traduce_ids():
    x = temas([4, 4])
    resultado = fm.fusionar_inicios(analisis_de(8, primer_id=10), [10, 12, 14, 16], EmbedderFijo(x))
    assert resultado == [10, 14]


def test_fusionar_inicios_rechaza_ids_inexistentes():
    with pytest.raises(KeyError):
        fm.fusionar_inicios(analisis_de(4), [99], EmbedderFijo(temas([4])))


def test_valores_por_defecto_fijados_antes_de_medir():
    """Registrados en el experimento del 19 oct antes de correr la medición."""
    assert (fm.K_VENTANA, fm.C_PROFUNDIDAD, fm.U_FUSION) == (2, 0.5, 0.6)
