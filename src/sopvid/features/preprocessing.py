"""Partición y preprocesamiento de la tabla a nivel paso de CaptainCook4D.

Lógica copiada de `docs/entregables/Semana 3/Avance1.51.ipynb` (secciones 4, 5.6 y 8) sin
cambios. Diferencias solo de forma:

- `apply_consistency` y `preprocess` reciben `video_info` como parámetro (en el notebook era
  una variable global).
- `fit_preprocess` encadena los `fit_*` en el mismo orden que el notebook, para obtener
  `PARAMS` con una sola llamada.

Regla anti-fuga: todo `fit_*` se ajusta solo con la partición de entrenamiento.
"""

import numpy as np
import pandas as pd

from sopvid.features.data import video_meta

SPLITS = ("train", "val", "test")

VERB_SYNONYMS = {
    "measure and add": "add",
    "cut or tear": "cut",
    "slice": "cut",
    "chop": "cut",
    "dice": "cut",
    "mince": "cut",
    "stir": "mix",
    "whisk": "mix",
    "combine": "mix",
}
MIN_VERB_COUNT = 30

FEATURES_NUM = ["log_duration", "dur_ratio_step", "rel_position", "step_freq", "repeat_idx"]
FEATURES_BIN = ["is_skipped"]
FEATURES_CAT = ["activity_name", "verb_grouped"]
TARGET = "has_errors"


# ── Partición (avance 1, §4) ────────────────────────────────────────────────


def split_steps(steps: pd.DataFrame, splits: dict) -> dict[str, pd.DataFrame]:
    """Asigna la partición oficial *combined* de CaptainCook4D (por grabación).

    No es aleatoria ni usa semilla: es la partición publicada por los autores del dataset,
    así que ninguna grabación aparece en dos particiones.
    """
    split_of = {rid: name for name, ids in splits.items() for rid in ids}
    all_ids = [rid for ids in splits.values() for rid in ids]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Hay grabaciones repetidas entre particiones")

    full = steps.copy()
    full["split"] = full["recording_id"].map(split_of)
    return {name: full[full["split"] == name].reset_index(drop=True) for name in SPLITS}


# ── Valores faltantes (avance 1, §8.1) ──────────────────────────────────────


def fit_missing(train: pd.DataFrame) -> dict:
    t = train.loc[~train["is_skipped"]]
    return {
        "median_by_step": t.groupby("step_id")["duration"].median().to_dict(),
        "global_median": float(t["duration"].median()),
    }


def apply_missing(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    d = df.copy()
    d["is_skipped"] = (d["start_time"] == -1) & (d["end_time"] == -1)
    for c in ["start_time", "end_time"]:
        d[c] = d[c].where(~d["is_skipped"], np.nan)
    d["duration"] = d["end_time"] - d["start_time"]
    fill = d["step_id"].map(params["median_by_step"]).fillna(params["global_median"])
    d["duration_imputed"] = d["duration"].fillna(fill)
    return d


# ── Duplicados e inconsistencias (avance 1, §8.2) ───────────────────────────


def apply_consistency(df: pd.DataFrame, video_info: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["repeat_idx"] = d.groupby(["recording_id", "step_id"]).cumcount()
    pm = video_info.set_index("recording_id")["person_id"]
    d["person_conflict"] = d["person_id"].astype(int) != d["recording_id"].map(pm)
    return d


# ── Atípicos (avance 1, §8.3) ───────────────────────────────────────────────


def iqr_bounds(x, k: float = 1.5) -> tuple[float, float]:
    q1, q3 = np.percentile(x, [25, 75])
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def fit_outliers(df: pd.DataFrame) -> dict:
    x = np.log1p(df.loc[~df["is_skipped"], "duration"])
    return {"log_p01": float(x.quantile(0.01)), "log_p99": float(x.quantile(0.99))}


def apply_outliers(df: pd.DataFrame, params: dict, miss: dict) -> pd.DataFrame:
    d = df.copy()
    d["log_duration"] = np.log1p(d["duration_imputed"]).clip(params["log_p01"], params["log_p99"])
    ref = d["step_id"].map(miss["median_by_step"]).fillna(miss["global_median"])
    d["dur_ratio_step"] = np.log(d["duration_imputed"] / ref)
    return d


# ── Alta cardinalidad (avance 1, §8.4) ──────────────────────────────────────


def fit_cardinality(df: pd.DataFrame) -> dict:
    vb = df["verb"].astype(str).replace(VERB_SYNONYMS)
    counts = vb.value_counts()
    keep = sorted(counts[counts >= MIN_VERB_COUNT].index)
    step_freq = (df["step_id"].value_counts() / len(df)).to_dict()
    return {"keep_verbs": keep, "step_freq": step_freq}


def apply_cardinality(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    d = df.copy()
    vb = d["verb"].astype(str).replace(VERB_SYNONYMS)
    d["verb_grouped"] = np.where(vb.isin(params["keep_verbs"]), vb, "other")
    d["step_freq"] = d["step_id"].map(params["step_freq"]).fillna(0.0)
    return d


# ── Pipeline completo (avance 1, §8.6) ──────────────────────────────────────


def fit_preprocess(train: pd.DataFrame, video_info: pd.DataFrame) -> dict:
    """Ajusta todos los parámetros con entrenamiento, en el mismo orden que el avance 1."""
    d = train.copy()
    d["is_skipped"] = (d["start_time"] == -1) & (d["end_time"] == -1)
    d["duration"] = d["end_time"] - d["start_time"]
    miss_params = fit_missing(d)
    pp = apply_missing(d, miss_params)
    pp = apply_consistency(pp, video_info)
    out_params = fit_outliers(pp)
    pp = apply_outliers(pp, out_params, miss_params)
    card_params = fit_cardinality(pp)
    return {"missing": miss_params, "outliers": out_params, "cardinality": card_params}


def preprocess(df_raw: pd.DataFrame, params: dict, video_info: pd.DataFrame) -> pd.DataFrame:
    """Aplica las transformaciones ya ajustadas, sin recalcular nada."""
    d = df_raw.copy()
    if "video_duration_s" not in d:
        meta = video_meta(video_info)
        d = d.merge(meta[["recording_id", "video_duration_s"]], on="recording_id", how="left")
    d = apply_missing(d, params["missing"])
    d = apply_consistency(d, video_info)
    d = apply_outliers(d, params["outliers"], params["missing"])
    d = apply_cardinality(d, params["cardinality"])
    d["rel_position"] = d["step_order"] / d.groupby("recording_id")["step_order"].transform("max")
    return d


# ── Tabla a nivel grabación (avance 1, §5.6) ────────────────────────────────


def build_recording_table(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por grabación. Requiere `duration`, `is_skipped` y `video_duration_s`."""
    d = df.copy()
    v = ~d["is_skipped"]
    d["dur_valid"] = d["duration"].where(v)
    # tiempo muerto entre el fin de un paso y el inicio del siguiente (solo pasos ejecutados)
    d_sorted = d[v].sort_values(["recording_id", "start_time"])
    d_sorted["gap"] = d_sorted["start_time"] - d_sorted.groupby("recording_id")["end_time"].shift()
    gaps = d_sorted.groupby("recording_id")["gap"].agg(lambda g: g.clip(lower=0).sum())
    overlaps = d_sorted.groupby("recording_id")["gap"].agg(lambda g: (g < 0).sum())

    r = d.groupby("recording_id").agg(
        activity_name=("activity_name", "first"),
        person_id=("person_id", "first"),
        environment=("environment", "first"),
        video_duration_s=("video_duration_s", "first"),
        recording_has_errors=("recording_has_errors", "first"),
        n_steps=("step_id", "size"),
        n_skipped=("is_skipped", "sum"),
        n_error_steps=("has_errors", "sum"),
        n_error_tags=("n_error_tags", "sum"),
        mean_step_dur=("dur_valid", "mean"),
        median_step_dur=("dur_valid", "median"),
        annotated_time=("dur_valid", "sum"),
    )
    r["error_step_rate"] = r["n_error_steps"] / r["n_steps"]
    r["coverage"] = r["annotated_time"] / r["video_duration_s"]
    r["idle_time"] = gaps
    r["n_overlaps"] = overlaps
    return r
