"""Regresión contra los resultados publicados en Avance1.51.ipynb (datos reales de CaptainCook4D).

Requiere las anotaciones en DATA_DIR; si no están descargadas (p. ej. en CI), se salta.
Para correrla: ejecutar una vez el notebook del avance 2 o `sopvid.features.data.load_raw()`.
"""

import numpy as np
import pytest

from sopvid.features import data
from sopvid.features import preprocessing as pp

RAW_DIR = data.default_data_dir()
pytestmark = pytest.mark.skipif(
    not all((RAW_DIR / f.split("/")[-1]).exists() for f in data.FILES),
    reason=f"anotaciones de CaptainCook4D no descargadas en {RAW_DIR}",
)


@pytest.fixture(scope="module")
def avance1():
    raw = data.load_raw(RAW_DIR)
    steps = data.build_step_table(raw.complete, raw.errors_raw)
    parts = pp.split_steps(steps, raw.splits)
    params = pp.fit_preprocess(parts["train"], raw.video_info)
    train = pp.preprocess(parts["train"], params, raw.video_info)
    return raw, steps, parts, params, train


def test_tabla_y_particion(avance1):
    raw, steps, parts, _, _ = avance1

    assert data.count_misaligned(raw.complete, raw.errors_raw) == 0
    assert steps.shape == (5700, 23)
    sizes = {k: (len(v), v["recording_id"].nunique()) for k, v in parts.items()}
    assert sizes == {"train": (3158, 213), "val": (929, 62), "test": (1613, 109)}


def test_preprocesamiento_de_train(avance1):
    _, _, _, params, train = avance1

    assert round(100 * train[pp.TARGET].mean(), 3) == 28.879
    assert int(train["is_skipped"].sum()) == 171
    assert {k: round(float(np.expm1(v)), 2) for k, v in params["outliers"].items()} == {
        "log_p01": 2.99,
        "log_p99": 285.56,
    }
    assert train["verb_grouped"].nunique() == 19
    assert int((train["repeat_idx"] > 0).sum()) == 43
    assert train.loc[train["person_conflict"], "recording_id"].nunique() == 7
    assert train[pp.FEATURES_NUM + pp.FEATURES_BIN + pp.FEATURES_CAT].isna().sum().sum() == 0


def test_tabla_a_nivel_grabacion(avance1):
    *_, train = avance1

    recs = pp.build_recording_table(train)

    assert recs.shape == (213, 16)
    assert round(recs["n_steps"].mean(), 3) == 14.826
    assert round(recs["idle_time"].mean(), 3) == 124.675
    assert round(recs["n_overlaps"].mean(), 3) == 1.164
