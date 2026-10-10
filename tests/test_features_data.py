"""Tests de sopvid.features.data con anotaciones sintéticas (sin red)."""

import json

import pandas as pd
import pytest

from sopvid.features import data


def _step(step_id, start, end, desc="Add-Add salt", has_errors=False):
    return {
        "step_id": step_id,
        "description": desc,
        "start_time": start,
        "end_time": end,
        "has_errors": has_errors,
    }


@pytest.fixture
def complete():
    return {
        "1_1": {
            "activity_id": 1,
            "activity_name": "Receta A",
            "person_id": 3,
            "environment": 8,
            "steps": [
                _step(10, 0.0, 10.0, "Pour -Pour 1 egg"),
                _step(11, -1, -1, "Add-Add salt", has_errors=True),
            ],
        },
        "2_5": {
            "activity_id": 2,
            "activity_name": "Receta B",
            "person_id": 4,
            "environment": 5,
            "steps": [_step(20, 5.0, 25.0, "Measure and add-Measure and add flour")],
        },
    }


@pytest.fixture
def errors_raw():
    return [
        {
            "recording_id": "1_1",
            "is_error": True,
            "step_annotations": [
                {"step_id": 10, "start_time": 0.0, "errors": []},
                {
                    "step_id": 11,
                    "start_time": -1,
                    "errors": [{"tag": "Missing Step"}, {"tag": "Order Error"}],
                },
            ],
        },
        {
            "recording_id": "2_5",
            "is_error": False,
            "step_annotations": [{"step_id": 20, "start_time": 5.0}],
        },
    ]


def test_build_step_table_una_fila_por_paso(complete, errors_raw):
    steps = data.build_step_table(complete, errors_raw)

    assert len(steps) == 3
    assert steps["step_order"].tolist() == [0, 1, 0]
    assert steps["recording_id"].tolist() == ["1_1", "1_1", "2_5"]


def test_build_step_table_verbo_y_etiquetas(complete, errors_raw):
    steps = data.build_step_table(complete, errors_raw)

    assert steps["verb"].tolist() == ["pour", "add", "measure and add"]
    assert data.error_tag_columns(steps) == ["err_missing_step", "err_order_error"]
    assert steps["err_missing_step"].tolist() == [0, 1, 0]
    assert steps["n_error_tags"].tolist() == [0, 2, 0]
    assert steps["recording_has_errors"].tolist() == [True, True, False]


def test_count_misaligned(complete, errors_raw):
    assert data.count_misaligned(complete, errors_raw) == 0

    errors_raw[0]["step_annotations"][0]["start_time"] = 99.0
    assert data.count_misaligned(complete, errors_raw) == 1


def test_video_meta_renombra_columnas():
    vi = pd.DataFrame(
        {
            "recording_id": ["1_1"],
            "environment_id": [8],
            "person_id": [3],
            "duration(sec)": [60.0],
            "duration(min)": [1.0],
        }
    )

    meta = data.video_meta(vi)

    assert {"env_meta", "person_meta", "video_duration_s", "video_duration_min"} <= set(meta)


def test_load_raw_usa_cache_sin_descargar(tmp_path, monkeypatch, complete, errors_raw):
    (tmp_path / "complete_step_annotations.json").write_text(json.dumps(complete))
    (tmp_path / "error_annotations.json").write_text(json.dumps(errors_raw))
    (tmp_path / "video_information.csv").write_text("recording_id,person_id\n1_1,3\n")
    (tmp_path / "recordings_data_split_combined.json").write_text(json.dumps({"train": ["1_1"]}))

    def sin_red(*args, **kwargs):
        raise AssertionError("no debía descargar: los archivos ya están en caché")

    monkeypatch.setattr(data.urllib.request, "urlretrieve", sin_red)

    raw = data.load_raw(tmp_path)

    assert set(raw.complete) == {"1_1", "2_5"}
    assert raw.splits == {"train": ["1_1"]}
    assert len(raw.video_info) == 1


def test_fetch_descarga_desde_el_commit_fijo(tmp_path, monkeypatch):
    llamadas = []

    def falso_urlretrieve(url, dest):
        llamadas.append(url)
        dest.write_text("{}")

    monkeypatch.setattr(data.urllib.request, "urlretrieve", falso_urlretrieve)

    data.fetch("metadata/video_information.csv", tmp_path)
    data.fetch("metadata/video_information.csv", tmp_path)  # segunda vez: caché

    assert llamadas == [f"{data.BASE_URL}/metadata/video_information.csv"]
    assert data.COMMIT in llamadas[0]
