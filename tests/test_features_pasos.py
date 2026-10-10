"""Tests de sopvid.features.pasos con frases y pasos sintéticos."""

import pandas as pd
import pytest

from sopvid.features import pasos as fp


@pytest.fixture
def asr():
    # v1: frases en 0, 10, 10 (mismo segundo), 20, 30; v2: 0, 5 (orden de entrada invertido)
    return pd.DataFrame(
        {
            "vid": ["v1", "v1", "v1", "v1", "v1", "v2", "v2"],
            "start_second": [0, 10, 10, 20, 30, 5, 0],
            "text": ["a", "b1", "b2", "c", "d", "y", "x"],
        }
    )


@pytest.fixture
def pasos():
    rows = [
        # v1 (train, 40 s)
        ("v1", 1, 9.0, 12.0),  # a 1 s de las frases en 10 -> la primera (b1)
        ("v1", 2, 15.0, 18.0),  # empate 5 s entre 10 y 20 -> la anterior (b1)
        ("v1", 3, 23.0, 25.0),  # a 3 s de 20 (c) y 7 s de 30
        ("v1", 4, 26.0, 28.0),  # a 4 s de 30 (d) y 6 s de 20
        # v2 (val_seen, 8 s)
        ("v2", 5, 4.5, 6.0),
    ]
    df = pd.DataFrame(rows, columns=["vid", "step_id", "start", "end"])
    df["activity"] = df["vid"].map({"v1": "Make A", "v2": "Make B"})
    df["subset"] = df["vid"].map({"v1": "train", "v2": "val_seen"})
    df["duration"] = df["vid"].map({"v1": 40.0, "v2": 8.0})
    df["partial"] = "Full Match"
    return df


@pytest.fixture
def frases(asr, pasos):
    return fp.build_phrase_table(asr, pasos)


def test_tabla_de_frases_orden_y_tiempos(frases):
    v1, v2 = frases[frases.vid == "v1"], frases[frases.vid == "v2"]

    assert v1["text"].tolist() == ["a", "b1", "b2", "c", "d"]  # empate en 10 s: orden de entrada
    assert v1["idx"].tolist() == [0, 1, 2, 3, 4]
    assert v1["t_fin"].tolist() == [10.0, 10.0, 20.0, 30.0, 40.0]  # la última: duración
    assert v2["text"].tolist() == ["x", "y"]  # se ordena por tiempo
    assert v2["t_fin"].tolist() == [5.0, 8.0]
    assert set(frases.columns) >= {"activity", "subset", "duration"}


def test_asignacion_frase_mas_cercana_y_empates(frases, pasos):
    asig = fp.assign_step_starts(frases, pasos, tol=4)
    texto = frases["text"].to_numpy()

    assert texto[asig["fila"]].tolist() == ["b1", "b1", "c", "d", "y"]
    assert asig["dist"].tolist() == [1.0, 5.0, 3.0, 4.0, 0.5]
    assert asig["asignado"].tolist() == [True, False, True, True, True]


def test_etiqueta_cada_inicio_marca_a_lo_sumo_una_frase(frases, pasos):
    y = fp.label_phrases(frases, pasos, tol=4)

    assert dict(zip(frases["text"], y, strict=True)) == {
        "a": 0,
        "b1": 1,
        "b2": 0,
        "c": 1,
        "d": 1,
        "x": 0,
        "y": 1,
    }


def test_tolerancia_mas_amplia_asigna_mas_inicios(frases, pasos):
    a2 = fp.assign_step_starts(frases, pasos, tol=2)["asignado"].sum()
    a6 = fp.assign_step_starts(frases, pasos, tol=6)["asignado"].sum()

    assert (a2, a6) == (2, 5)


def test_ventana_asimetrica_solo_mira_hacia_adelante(frases, pasos):
    # [0, +4]: el paso en 23 s ya no puede usar la frase de 20 s (está antes)
    asig = fp.assign_step_starts(frases, pasos, antes=0, despues=4)
    texto = frases["text"].to_numpy()

    assert asig["asignado"].tolist() == [True, False, False, True, True]
    assert texto[asig.loc[asig["asignado"], "fila"]].tolist() == ["b1", "d", "y"]


def test_ventana_requiere_parametros(frases, pasos):
    with pytest.raises(ValueError, match="tol"):
        fp.assign_step_starts(frases, pasos)


def test_video_sin_frases_no_se_asigna(frases, pasos):
    extra = pd.DataFrame(
        [{"vid": "v9", "step_id": 9, "start": 1.0, "end": 2.0, "partial": "Full Match"}]
    )

    asig = fp.assign_step_starts(frases, pd.concat([pasos, extra], ignore_index=True), tol=6)

    assert asig.iloc[-1][["fila", "asignado"]].tolist() == [-1, False]


def test_reporte_de_tolerancias(frases, pasos):
    rep = fp.tolerance_report(frases, pasos, {"±2 s": (2, 2), "±4 s": (4, 4)})

    assert rep.loc["±4 s", "frases_positivas"] == 4
    assert rep.loc["±4 s", "inicios_sin_frase"] == 1
    assert rep.loc["±2 s", "% positivos"] == pytest.approx(100 * 2 / 7)


def test_inicios_al_azar_dentro_del_video(pasos):
    azar = fp.random_step_starts(pasos, seed=1)

    assert (azar["start"] >= 0).all() and (azar["start"] <= azar["duration"]).all()
    assert not azar["start"].equals(pasos["start"])


def test_particion_por_video(frases):
    parts = fp.split_by_video(frases)

    assert set(parts["train"].vid) == {"v1"} and set(parts["test"].vid) == {"v2"}


def test_particion_rechaza_videos_en_ambas(frases):
    mezcla = frases.copy()
    mezcla.loc[mezcla.index[0], "subset"] = "val_seen"  # una frase de v1 en test

    with pytest.raises(ValueError, match="train y en test"):
        fp.split_by_video(mezcla)
