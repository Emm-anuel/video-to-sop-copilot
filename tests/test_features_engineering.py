"""Tests de sopvid.features.engineering con recetas y grabaciones sintéticas."""

import numpy as np
import pandas as pd
import pytest

from sopvid.features import engineering as fe

# Receta A: Add -> Mix -> Pour. Receta B tiene un ciclo: Heat -> Stir -> Heat.
GRAPHS = {
    "Receta A": {
        "steps": {
            "0": "START",
            "1": "Add-Add salt",
            "2": "Mix -Mix well",
            "3": "Pour-Pour it",
            "4": "END",
        },
        "edges": [[0, 1], [1, 2], [2, 3], [3, 4]],
    },
    "Receta B": {
        "steps": {
            "0": "START",
            "1": "Heat-Heat pan",
            "2": "Stir-Stir",
            "3": "Heat-Heat pan",
            "4": "END",
        },
        "edges": [[0, 1], [1, 2], [2, 3], [3, 4]],
    },
}
ADD, MIX, POUR = (101, "Add-Add salt"), (102, "Mix-Mix well"), (103, "Pour-Pour it")
HEAT, STIR = (201, "Heat-Heat pan"), (202, "Stir-Stir")


def _rec(rid, activity, rows):
    """rows: (paso, inicio, fin, has_errors) en el orden de la anotación."""
    return [
        {
            "recording_id": rid,
            "activity_name": activity,
            "step_order": i,
            "step_id": step[0],
            "description": step[1],
            "verb": step[1].split("-")[0].strip().lower(),
            "start_time": start,
            "end_time": end,
            "has_errors": err,
        }
        for i, (step, start, end, err) in enumerate(rows)
    ]


@pytest.fixture
def train():
    rows = (
        _rec("r1", "Receta A", [(ADD, 0, 10, False), (MIX, 12, 20, False), (POUR, 25, 30, False)])
        # r2: Mix empieza antes que su predecesor Add (inversión de orden)
        + _rec("r2", "Receta A", [(ADD, 15, 25, True), (MIX, 0, 10, True), (POUR, 30, 40, False)])
        # r3: Mix omitido (-1)
        + _rec("r3", "Receta A", [(ADD, 0, 10, False), (MIX, -1, -1, True), (POUR, 20, 30, True)])
        # r4: Stir se traslapa 5 s con Heat; Heat se repite
        + _rec(
            "r4", "Receta B", [(HEAT, 0, 20, False), (STIR, 15, 25, True), (HEAT, 30, 40, False)]
        )
        + _rec(
            "r5", "Receta B", [(HEAT, 0, 30, False), (STIR, 35, 45, False), (HEAT, 50, 60, True)]
        )
        + _rec("r6", "Receta A", [(ADD, 0, 8, True), (MIX, 10, 30, False), (POUR, 31, 33, False)])
    )
    return pd.DataFrame(rows)


@pytest.fixture
def test():
    # step_id 104 no existe en train (misma descripción que Pour)
    rows = _rec(
        "t1",
        "Receta A",
        [(ADD, 0, 12, False), (MIX, 14, 22, True), ((104, "Pour-Pour it"), 23, 30, False)],
    )
    rows += _rec(
        "t2", "Receta B", [(HEAT, 0, 25, True), (STIR, 26, 30, False), (HEAT, 31, 50, False)]
    )
    return pd.DataFrame(rows)


@pytest.fixture
def video_info():
    ids = ["r1", "r2", "r3", "r4", "r5", "r6", "t1", "t2"]
    durs = [40.0, 50.0, 35.0, 45.0, 65.0, 40.0, 35.0, 55.0]
    return pd.DataFrame(
        {
            "recording_id": ids,
            "person_id": range(len(ids)),
            "environment_id": 1,
            "duration(sec)": durs,
            "duration(min)": [d / 60 for d in durs],
        }
    )


@pytest.fixture
def feats(train, video_info):
    return fe.add_step_features(train, video_info, GRAPHS).set_index(["recording_id", "step_order"])


# ── Características sin aprendizaje ─────────────────────────────────────────


def test_map_graph_nodes_por_descripcion_y_ciclos(train):
    nodes = fe.map_graph_nodes(train, GRAPHS)

    # "Mix-Mix well" coincide con "Mix -Mix well" pese al espacio; en B la 2.ª "Heat" es el nodo 3
    assert nodes[train["recording_id"] == "r1"].tolist() == [1, 2, 3]
    assert nodes[train["recording_id"] == "r4"].tolist() == [1, 2, 3]


def test_map_graph_nodes_usa_el_step_id_si_la_descripcion_no_existe(train):
    raro = train.copy()
    raro.loc[0, "description"] = "Add-texto que no está en el grafo"

    assert fe.map_graph_nodes(raro, GRAPHS).iloc[0] == 1  # nodo más frecuente del step_id 101


def test_posicion_por_inicio_y_no_por_step_order(feats):
    r2 = feats.loc["r2"]

    assert r2["exec_idx"].tolist() == [1, 0, 2]  # Mix (step_order 1) empezó primero
    assert r2["is_first"].tolist() == [0, 1, 0]
    assert r2["is_last"].tolist() == [0, 0, 1]
    assert r2["rel_exec_pos"].tolist() == [0.5, 0.0, 1.0]


def test_contexto_huecos_y_traslapes(feats):
    r1, r4 = feats.loc["r1"], feats.loc["r4"]

    assert r1["gap_prev"].tolist() == [0.0, 2.0, 5.0]
    assert r1["gap_next"].tolist() == [2.0, 5.0, 0.0]
    assert r4["overlap_prev"].tolist() == [0.0, 5.0, 0.0]
    assert r4["overlap_next"].tolist() == [5.0, 0.0, 0.0]


def test_orden_inversion_y_predecesor_ausente(feats):
    r2, r3 = feats.loc["r2"], feats.loc["r3"]

    assert r2.loc[1, ["n_pred", "n_pred_after", "order_violation"]].tolist() == [1, 1, 1]
    assert r2.loc[0, "n_pred"] == 0  # Add solo depende de START
    assert r3.loc[2, ["n_pred_absent", "n_pred_after"]].tolist() == [1, 0]


def test_pasos_omitidos_sin_caracteristicas_de_ejecucion(feats):
    omitido = feats.loc[("r3", 1)]

    assert omitido["is_skipped"]
    assert omitido[fe.POSITION + fe.CONTEXT + fe.ORDER].isna().all()
    assert np.isnan(omitido["duration"])


def test_nivel_grabacion(feats):
    assert feats.loc["r3", "rec_n_steps"].tolist() == [3, 3, 3]  # cuenta también el omitido
    assert feats.loc["r4", "repeat_idx"].tolist() == [0, 0, 1]
    assert feats.loc["r4", "rec_repeat_frac"].iloc[0] == pytest.approx(1 / 3)
    assert feats.loc["r4", "rec_duration"].iloc[0] == 45.0


def test_no_usa_la_etiqueta(train, video_info):
    volteada = train.assign(has_errors=~train["has_errors"])
    cols = fe.POSITION + fe.CONTEXT + fe.ORDER + fe.RECORDING + fe.STEP

    a = fe.add_step_features(train, video_info, GRAPHS)[cols]
    b = fe.add_step_features(volteada, video_info, GRAPHS)[cols]

    pd.testing.assert_frame_equal(a, b)


# ── Transformadores que aprenden ────────────────────────────────────────────


def _one_step_per_recording(values):
    return pd.DataFrame(
        {
            "recording_id": [f"g{i}" for i in range(len(values))],
            "step_id": 1,
            "duration": values,
            "cat": "a",
        }
    )


def test_step_duration_encoder_fuera_de_pliegue():
    X = _one_step_per_recording([10.0, 20.0, 30.0, 40.0, 50.0])
    enc = fe.StepDurationEncoder(n_splits=5)

    oof = enc.fit_transform(X)
    full = enc.transform(X)

    # en train, la grabación con 10 s se compara con la mediana de las otras cuatro (35 s)
    assert oof[0, 0] == pytest.approx(np.log(10 / 35))
    # en prueba se usa la mediana de todo train (30 s)
    assert full[0, 0] == pytest.approx(np.log(10 / 30))


def test_step_duration_encoder_paso_no_visto_usa_mediana_global():
    enc = fe.StepDurationEncoder().fit(_one_step_per_recording([10.0, 20.0, 30.0]))
    nuevo = pd.DataFrame({"recording_id": ["x"], "step_id": [99], "duration": [40.0]})

    assert enc.transform(nuevo)[0, 0] == pytest.approx(np.log(40 / 20))


def test_target_encoder_no_ve_su_propia_etiqueta():
    X = _one_step_per_recording([1.0] * 5)
    y = np.array([1, 0, 0, 0, 0])
    enc = fe.GroupedTargetEncoder(["cat"], smoothing=10, n_splits=5)

    oof = enc.fit_transform(X, y)

    assert oof[0, 0] == 0.0  # las otras 4 grabaciones tienen y = 0
    # ajuste completo: (1 + 10·0.2) / (5 + 10) = 0.2
    assert enc.transform(X)[0, 0] == pytest.approx(0.2)


def test_frequency_encoder_categoria_no_vista_vale_cero():
    enc = fe.FrequencyEncoder(["cat"]).fit(pd.DataFrame({"cat": ["a", "a", "b", "a"]}))

    out = enc.transform(pd.DataFrame({"cat": ["a", "z"]}))

    assert out[:, 0].tolist() == [0.75, 0.0]


def test_column_selector_con_prefijos():
    X = pd.DataFrame(columns=["x", "activity_name_A", "activity_name_B", "y"], data=[[1, 2, 3, 4]])

    sel = fe.ColumnSelector(["y"], prefixes=("activity_name_",)).fit(X)

    assert sel.transform(X).columns.tolist() == ["activity_name_A", "activity_name_B", "y"]
    with pytest.raises(ValueError, match="inexistentes"):
        fe.ColumnSelector(["no_existe"]).fit(X)


# ── build_features ──────────────────────────────────────────────────────────


def test_final_transforms_cubre_todas_las_numericas():
    assert set(fe.FINAL_TRANSFORMS) == set(fe.NUMERIC)


def test_build_features_forma_y_columnas(train, test, video_info):
    fs = fe.build_features(train, test, video_info=video_info, task_graphs=GRAPHS)

    expected = fe.FINAL_SELECTED + ["activity_name_Receta A", "activity_name_Receta B"]
    assert set(fs.X_train.columns) == set(expected)
    assert list(fs.X_test.columns) == list(fs.X_train.columns)
    assert len(fs.X_train) == len(train) - 1  # sin el paso omitido
    assert len(fs.X_test) == len(test)
    assert not fs.X_train.isna().any().any() and not fs.X_test.isna().any().any()
    assert fs.y_train.index.equals(fs.X_train.index)
    assert fs.y_train.tolist() == train.drop(index=7)["has_errors"].astype(int).tolist()


def test_build_features_ajusta_solo_con_train(train, test, video_info):
    fs = fe.build_features(train, test, video_info=video_info, task_graphs=GRAPHS)
    pipe_freq = fs.pipeline.named_steps["features"].named_transformers_["high"]

    # el step_id 104 solo existe en test: frecuencia 0, aprendida de train
    assert 104 not in pipe_freq.freq_["step_id"]
    sid = fs.pipeline.named_steps["features"].transform(fe.prepare_steps(test, video_info, GRAPHS))
    assert sid.loc[test.index[test["step_id"] == 104], "step_id_freq"].tolist() == [0.0]
    # el escalador se centró con train
    assert fs.X_train["rec_n_steps"].mean() == pytest.approx(0.0, abs=1e-9)


def test_build_features_sin_seleccion_devuelve_todo(train, test, video_info):
    fs = fe.build_features(train, test, video_info=video_info, task_graphs=GRAPHS, select=False)

    assert len(fs.X_train.columns) > len(fe.FINAL_SELECTED) + 2
    assert {"duration", "gap_prev", "verb_norm_freq"} <= set(fs.X_train.columns)
