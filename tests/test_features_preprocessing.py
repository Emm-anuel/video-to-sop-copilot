"""Tests de sopvid.features.preprocessing con una tabla de pasos sintética."""

import numpy as np
import pandas as pd
import pytest

from sopvid.features import preprocessing as pp


@pytest.fixture
def steps():
    """Dos grabaciones; el paso 11 de "a" está omitido (-1) y el paso 10 se repite."""
    return pd.DataFrame(
        {
            "recording_id": ["a", "a", "a", "a", "b", "b", "b"],
            "activity_name": ["R1"] * 4 + ["R2"] * 3,
            "person_id": [1, 1, 1, 1, 2, 2, 2],
            "environment": [5] * 7,
            "step_order": [0, 1, 2, 3, 0, 1, 2],
            "step_id": [10, 11, 10, 12, 20, 21, 22],
            "verb": ["add", "stir", "add", "chop", "add", "whisk", "fold"],
            "start_time": [0.0, -1.0, 30.0, 50.0, 0.0, 10.0, 35.0],
            "end_time": [10.0, -1.0, 50.0, 60.0, 20.0, 40.0, 45.0],
            "has_errors": [False, True, False, True, False, True, False],
            "n_error_tags": [0, 1, 0, 2, 0, 1, 0],
            "recording_has_errors": [True] * 4 + [True] * 3,
        }
    )


@pytest.fixture
def video_info():
    return pd.DataFrame(
        {
            "recording_id": ["a", "b"],
            "person_id": [1, 9],  # "b" tiene conflicto de persona
            "environment_id": [5, 5],
            "duration(sec)": [100.0, 50.0],
            "duration(min)": [100 / 60, 50 / 60],
        }
    )


def _with_raw_duration(df):
    d = df.copy()
    d["is_skipped"] = (d["start_time"] == -1) & (d["end_time"] == -1)
    d["duration"] = d["end_time"] - d["start_time"]
    return d


# ── Partición ───────────────────────────────────────────────────────────────


def test_split_steps_por_grabacion(steps):
    parts = pp.split_steps(steps, {"train": ["a"], "val": [], "test": ["b"]})

    assert len(parts["train"]) == 4 and set(parts["train"]["recording_id"]) == {"a"}
    assert parts["val"].empty
    assert len(parts["test"]) == 3
    assert parts["test"].index.tolist() == [0, 1, 2]


def test_split_steps_rechaza_grabaciones_repetidas(steps):
    with pytest.raises(ValueError, match="repetidas"):
        pp.split_steps(steps, {"train": ["a"], "val": ["a"], "test": ["b"]})


# ── Faltantes ───────────────────────────────────────────────────────────────


def test_fit_missing_ignora_pasos_omitidos(steps):
    params = pp.fit_missing(_with_raw_duration(steps))

    assert params["median_by_step"][10] == 15.0  # mediana de 10 y 20
    assert 11 not in params["median_by_step"]
    assert params["global_median"] == 15.0  # mediana de [10, 20, 10, 20, 30, 10]


def test_apply_missing_centinela_a_nan_e_imputa(steps):
    params = {"median_by_step": {11: 7.0}, "global_median": 99.0}

    d = pp.apply_missing(steps, params)

    assert d["is_skipped"].tolist() == [False, True, False, False, False, False, False]
    assert np.isnan(d.loc[1, "start_time"]) and np.isnan(d.loc[1, "end_time"])
    assert np.isnan(d.loc[1, "duration"])
    assert d.loc[1, "duration_imputed"] == 7.0
    # step_id sin referencia en train -> mediana global
    params_sin_11 = {"median_by_step": {}, "global_median": 99.0}
    assert pp.apply_missing(steps, params_sin_11).loc[1, "duration_imputed"] == 99.0


# ── Consistencia ────────────────────────────────────────────────────────────


def test_apply_consistency_repeticiones_y_conflicto(steps, video_info):
    d = pp.apply_consistency(steps, video_info)

    assert d["repeat_idx"].tolist() == [0, 0, 1, 0, 0, 0, 0]
    assert d.groupby("recording_id")["person_conflict"].first().to_dict() == {
        "a": False,
        "b": True,
    }


# ── Atípicos ────────────────────────────────────────────────────────────────


def test_iqr_bounds():
    lo, hi = pp.iqr_bounds([1, 2, 3, 4, 5])

    assert (lo, hi) == (-1.0, 7.0)  # Q1=2, Q3=4, IQR=2


def test_fit_y_apply_outliers_winsoriza_en_log(steps):
    miss = pp.fit_missing(_with_raw_duration(steps))
    d = pp.apply_missing(steps, miss)
    params = pp.fit_outliers(d)

    out = pp.apply_outliers(d, params, miss)

    assert out["log_duration"].min() >= params["log_p01"]
    assert out["log_duration"].max() <= params["log_p99"]
    # dur_ratio_step = log(duración / mediana del mismo step_id): 10 / 15
    assert out.loc[0, "dur_ratio_step"] == pytest.approx(np.log(10 / 15))


# ── Cardinalidad ────────────────────────────────────────────────────────────


def test_cardinalidad_normaliza_sinonimos_y_agrupa(steps, monkeypatch):
    monkeypatch.setattr(pp, "MIN_VERB_COUNT", 2)

    params = pp.fit_cardinality(steps)
    d = pp.apply_cardinality(steps, params)

    # stir/whisk -> mix (2), add (3); chop -> cut (1) y fold (1) quedan en "other"
    assert params["keep_verbs"] == ["add", "mix"]
    assert d["verb_grouped"].tolist() == ["add", "mix", "add", "other", "add", "mix", "other"]
    assert params["step_freq"][10] == pytest.approx(2 / 7)


def test_apply_cardinality_step_no_visto_vale_cero(steps):
    params = {"keep_verbs": ["add"], "step_freq": {10: 0.5}}

    d = pp.apply_cardinality(steps, params)

    assert (d.loc[d["step_id"] != 10, "step_freq"] == 0.0).all()


# ── Pipeline completo ───────────────────────────────────────────────────────


def test_preprocess_produce_las_caracteristicas_sin_nan(steps, video_info):
    params = pp.fit_preprocess(steps, video_info)

    d = pp.preprocess(steps, params, video_info)

    features = pp.FEATURES_NUM + pp.FEATURES_BIN + pp.FEATURES_CAT + [pp.TARGET]
    assert set(features) <= set(d.columns)
    assert d[features].isna().sum().sum() == 0
    assert d.loc[d["recording_id"] == "a", "rel_position"].tolist() == [0, 1 / 3, 2 / 3, 1]
    assert d["video_duration_s"].tolist() == [100.0] * 4 + [50.0] * 3


def test_fit_preprocess_solo_aprende_de_train(steps, video_info):
    train = steps[steps["recording_id"] == "a"]
    test = steps[steps["recording_id"] == "b"].reset_index(drop=True)

    params = pp.fit_preprocess(train, video_info)
    d = pp.preprocess(test, params, video_info)

    assert set(params["missing"]["median_by_step"]) == {10, 12}
    # los step_id de test no existen en train: frecuencia 0 y mediana global
    assert (d["step_freq"] == 0.0).all()
    assert (d["dur_ratio_step"] == np.log(d["duration"] / params["missing"]["global_median"])).all()


# ── Nivel grabación ─────────────────────────────────────────────────────────


def test_build_recording_table(steps, video_info):
    d = pp.apply_missing(steps, pp.fit_missing(_with_raw_duration(steps)))
    d["video_duration_s"] = d["recording_id"].map({"a": 100.0, "b": 50.0})

    r = pp.build_recording_table(d)

    a, b = r.loc["a"], r.loc["b"]
    assert (a["n_steps"], a["n_skipped"], a["n_error_steps"]) == (4, 1, 2)
    assert a["annotated_time"] == 40.0  # 10 + 20 + 10
    assert a["idle_time"] == 20.0  # huecos 10->30 (20 s) y 50->50 (0 s)
    assert a["n_overlaps"] == 0
    # cada paso de "b" empieza antes de que termine el anterior: 10 < 20 y 35 < 40
    assert b["n_overlaps"] == 2
    assert b["idle_time"] == 0.0
    assert b["coverage"] == pytest.approx((20 + 30 + 10) / 50)
    assert a["error_step_rate"] == 0.5
