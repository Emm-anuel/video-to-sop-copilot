"""Ingeniería de características para `has_errors` (avance 2).

Dos niveles, para respetar la regla anti-fuga:

1. `add_step_features`: características que **no aprenden de los datos** (posición, contexto
   temporal, orden según el grafo de la receta y agregados por grabación). Solo miran la propia
   grabación y nunca la etiqueta, así que pueden calcularse antes de particionar.
2. Transformadores de scikit-learn que **sí aprenden** (duración típica de cada paso, codificadores,
   transformaciones y escaladores). Se ajustan solo con entrenamiento dentro de un `Pipeline`;
   los que usan estadísticas por categoría se calculan fuera de pliegue (GroupKFold por grabación)
   en `fit_transform`, de modo que una fila de entrenamiento nunca ve su propio valor.

`build_features` reúne las decisiones finales del avance 2 y es la entrada del avance 3.
"""

import re
from typing import NamedTuple

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.pipeline import FunctionTransformer, Pipeline
from sklearn.preprocessing import (
    OneHotEncoder,
    OrdinalEncoder,
    PowerTransformer,
    RobustScaler,
    StandardScaler,
)

from sopvid.features.data import video_meta
from sopvid.features.preprocessing import TARGET, VERB_SYNONYMS

SEED = 51
GROUP = "recording_id"

# ── Características sin aprendizaje ─────────────────────────────────────────

POSITION = ["exec_idx", "rel_exec_pos", "rel_start", "is_first", "is_last"]
CONTEXT = ["gap_prev", "overlap_prev", "gap_next", "overlap_next"]
ORDER = ["n_pred", "n_pred_after", "n_pred_absent", "order_violation"]
RECORDING = ["rec_n_steps", "rec_duration", "rec_repeat_frac"]
STEP = ["duration", "repeat_idx"]
# Salidas de StepDurationEncoder (aprenden de train)
DURATION_REL = ["dur_ratio_step", "dur_z_step"]

BINARY = ["is_first", "is_last", "order_violation"]
NUMERIC = STEP + DURATION_REL + POSITION + CONTEXT + ORDER + RECORDING
NUMERIC = [c for c in NUMERIC if c not in BINARY]
HIGH_CARD = ["step_id", "verb_norm"]
LOW_CARD = ["activity_name"]


def _norm_desc(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" -", "-").replace("- ", "-")).strip().lower()


def map_graph_nodes(steps: pd.DataFrame, graphs: dict[str, dict]) -> pd.Series:
    """Nodo del grafo de la receta que corresponde a cada paso anotado.

    `step_id` es global y los nodos son locales a cada receta, así que se une por descripción.
    En recetas con ciclos (la misma descripción en varios nodos) la k-ésima aparición del paso
    en la grabación se asigna al k-ésimo nodo con esa descripción. Si la descripción no aparece
    en el grafo, se usa el nodo más frecuente de su `step_id`.
    """
    nodes_by_desc: dict[tuple[str, str], list[int]] = {}
    for act, g in graphs.items():
        for k, desc in sorted(g["steps"].items(), key=lambda kv: int(kv[0])):
            nodes_by_desc.setdefault((act, _norm_desc(desc)), []).append(int(k))

    desc = steps["description"].map(_norm_desc)
    occurrence = steps.assign(_d=desc).groupby([GROUP, "_d"]).cumcount()
    nodes = []
    for act, d, k in zip(steps["activity_name"], desc, occurrence, strict=True):
        candidates = nodes_by_desc.get((act, d))
        nodes.append(candidates[min(k, len(candidates) - 1)] if candidates else np.nan)
    node = pd.Series(nodes, index=steps.index, dtype="float")

    fallback = node.groupby(steps["step_id"]).agg(
        lambda s: s.mode().iloc[0] if s.notna().any() else np.nan
    )
    return node.fillna(steps["step_id"].map(fallback))


def _order_features(rec: pd.DataFrame, edges: list[list[int]]) -> pd.DataFrame:
    """Predecesores directos de cada paso ejecutado según el grafo (sin START)."""
    preds: dict[int, list[int]] = {}
    for a, b in edges:
        if a != 0:
            preds.setdefault(b, []).append(a)

    executed = rec[~rec["is_skipped"]]
    first_start = executed.groupby("node")["start_time"].min()
    out = pd.DataFrame(index=rec.index, columns=ORDER, dtype="float")
    for idx, row in executed.iterrows():
        p = preds.get(int(row["node"]), []) if pd.notna(row["node"]) else []
        starts = [first_start.get(n) for n in p]
        absent = sum(s is None for s in starts)
        after = sum(s is not None and s > row["start_time"] for s in starts)
        out.loc[idx] = [len(p), after, absent, int(after > 0)]
    return out


def add_step_features(
    steps: pd.DataFrame, video_info: pd.DataFrame, graphs: dict[str, dict]
) -> pd.DataFrame:
    """Agrega las características que no aprenden de los datos (ni de la etiqueta).

    Devuelve todas las filas. Las características de los pasos omitidos (tiempos = -1) quedan
    en NaN: el modelo del avance 2 solo usa pasos ejecutados (ver `executed_steps`).
    """
    d = steps.copy()
    d["is_skipped"] = (d["start_time"] == -1) & (d["end_time"] == -1)
    for c in ["start_time", "end_time"]:
        d[c] = d[c].where(~d["is_skipped"], np.nan)
    d["duration"] = d["end_time"] - d["start_time"]
    if "video_duration_s" not in d:
        meta = video_meta(video_info)[[GROUP, "video_duration_s"]]
        d = d.merge(meta, on=GROUP, how="left").set_axis(d.index)

    d["repeat_idx"] = d.groupby([GROUP, "step_id"]).cumcount()
    d["verb_norm"] = d["verb"].astype(str).replace(VERB_SYNONYMS)
    d["node"] = map_graph_nodes(d, graphs)

    # Posición y contexto temporal: solo pasos ejecutados, en orden de inicio
    ex = d[~d["is_skipped"]].sort_values([GROUP, "start_time", "step_order"])
    g = ex.groupby(GROUP)
    n_exec = g["start_time"].transform("size")
    ex["exec_idx"] = g.cumcount()
    ex["rel_exec_pos"] = (ex["exec_idx"] / (n_exec - 1).where(n_exec > 1, 1)).astype(float)
    ex["rel_start"] = ex["start_time"] / ex["video_duration_s"]
    ex["is_first"] = (ex["exec_idx"] == 0).astype(int)
    ex["is_last"] = (ex["exec_idx"] == n_exec - 1).astype(int)

    prev_end = g["end_time"].shift()
    next_start = g["start_time"].shift(-1)
    ex["gap_prev"] = (ex["start_time"] - prev_end).clip(lower=0).fillna(0.0)
    ex["overlap_prev"] = (prev_end - ex["start_time"]).clip(lower=0).fillna(0.0)
    ex["gap_next"] = (next_start - ex["end_time"]).clip(lower=0).fillna(0.0)
    ex["overlap_next"] = (ex["end_time"] - next_start).clip(lower=0).fillna(0.0)
    d = d.join(ex[POSITION + CONTEXT])

    # Orden esperado de la receta
    order = [
        _order_features(rec, graphs[rec["activity_name"].iloc[0]]["edges"])
        for _, rec in d.groupby(GROUP)
    ]
    d = d.join(pd.concat(order))

    # Nivel grabación (sin usar la etiqueta ni los pasos omitidos)
    rg = d.groupby(GROUP)
    d["rec_n_steps"] = rg["step_id"].transform("size")
    d["rec_duration"] = d["video_duration_s"]
    d["rec_repeat_frac"] = rg["repeat_idx"].transform(lambda r: (r > 0).mean())
    return d


def executed_steps(df: pd.DataFrame) -> pd.DataFrame:
    """Filas del modelo del avance 2: pasos ejecutados (con segmento de video)."""
    return df[~df["is_skipped"]]


# ── Transformadores que aprenden de train ───────────────────────────────────


def _group_folds(groups: pd.Series, n_splits: int):
    return GroupKFold(n_splits=n_splits).split(np.zeros(len(groups)), groups=groups)


class StepDurationEncoder(TransformerMixin, BaseEstimator):
    """Duración relativa a la típica del mismo `step_id`.

    - `dur_ratio_step` = log(duración / mediana del paso), como en el avance 1.
    - `dur_z_step` = z-score de log(duración) dentro del paso (desv. global si hay < 3 casos).

    Entrada: columnas `step_id`, `recording_id` y `duration`. En `fit_transform` cada fila de
    entrenamiento se codifica con estadísticas de los otros pliegues (GroupKFold por grabación);
    así no ve su propia duración y su distribución coincide con la de prueba.
    """

    def __init__(self, n_splits: int = 5, min_count: int = 3):
        self.n_splits = n_splits
        self.min_count = min_count

    @staticmethod
    def _stats(X: pd.DataFrame) -> dict:
        logd = np.log(X["duration"].clip(lower=0.1))
        by = logd.groupby(X["step_id"])
        return {
            "median": X.groupby("step_id")["duration"].median(),
            "mean": by.mean(),
            "std": by.std(),
            "count": by.size(),
            "g_median": float(X["duration"].median()),
            "g_mean": float(logd.mean()),
            "g_std": float(logd.std()),
        }

    def _encode(self, X: pd.DataFrame, s: dict) -> np.ndarray:
        sid = X["step_id"]
        logd = np.log(X["duration"].clip(lower=0.1))
        med = sid.map(s["median"]).fillna(s["g_median"])
        mean = sid.map(s["mean"]).fillna(s["g_mean"])
        std = sid.map(s["std"].where(s["count"] >= self.min_count)).fillna(s["g_std"])
        std = std.where(std > 0, s["g_std"])
        ratio = np.log(X["duration"].clip(lower=0.1) / med)
        return np.column_stack([ratio, (logd - mean) / std])

    def fit(self, X, y=None):
        self.stats_ = self._stats(X)
        return self

    def transform(self, X):
        return self._encode(X, self.stats_)

    def fit_transform(self, X, y=None, **fit_params):
        out = np.empty((len(X), 2))
        for tr, va in _group_folds(X[GROUP], self.n_splits):
            out[va] = self._encode(X.iloc[va], self._stats(X.iloc[tr]))
        self.fit(X)
        return out

    def get_feature_names_out(self, input_features=None):
        return np.array(DURATION_REL, dtype=object)


class FrequencyEncoder(TransformerMixin, BaseEstimator):
    """Proporción de filas de train con esa categoría (0 si no se vio en train)."""

    def __init__(self, columns: list[str]):
        self.columns = columns

    def fit(self, X, y=None):
        self.freq_ = {c: X[c].value_counts(normalize=True) for c in self.columns}
        return self

    def transform(self, X):
        return np.column_stack([X[c].map(self.freq_[c]).fillna(0.0) for c in self.columns])

    def get_feature_names_out(self, input_features=None):
        return np.array([f"{c}_freq" for c in self.columns], dtype=object)


class GroupedTargetEncoder(TransformerMixin, BaseEstimator):
    """Target encoding con suavizado: (suma_y + m·prior) / (n + m).

    `fit_transform` calcula fuera de pliegue con GroupKFold por grabación (requiere la columna
    `recording_id`), para que la etiqueta de una fila no entre en su propia codificación.
    """

    def __init__(self, columns: list[str], smoothing: float = 10.0, n_splits: int = 5):
        self.columns = columns
        self.smoothing = smoothing
        self.n_splits = n_splits

    def _stats(self, X, y):
        y = pd.Series(np.asarray(y, dtype=float), index=X.index)
        prior = float(y.mean())
        stats = {c: y.groupby(X[c]).agg(["sum", "count"]) for c in self.columns}
        return prior, stats

    def _encode(self, X, prior, stats):
        m = self.smoothing
        cols = []
        for c in self.columns:
            enc = (stats[c]["sum"] + m * prior) / (stats[c]["count"] + m)
            cols.append(X[c].map(enc).fillna(prior))
        return np.column_stack(cols)

    def fit(self, X, y):
        self.prior_, self.stats_ = self._stats(X, y)
        return self

    def transform(self, X):
        return self._encode(X, self.prior_, self.stats_)

    def fit_transform(self, X, y=None, **fit_params):
        y = np.asarray(y)
        out = np.empty((len(X), len(self.columns)))
        for tr, va in _group_folds(X[GROUP], self.n_splits):
            prior, stats = self._stats(X.iloc[tr], y[tr])
            out[va] = self._encode(X.iloc[va], prior, stats)
        self.fit(X, y)
        return out

    def get_feature_names_out(self, input_features=None):
        return np.array([f"{c}_te" for c in self.columns], dtype=object)


class ColumnSelector(TransformerMixin, BaseEstimator):
    """Conserva las columnas indicadas y las que empiezan con algún prefijo (bloques one-hot).

    El orden de salida es el de la matriz de entrada.
    """

    def __init__(self, columns: list[str], prefixes: tuple[str, ...] = ()):
        self.columns = columns
        self.prefixes = prefixes

    def fit(self, X, y=None):
        missing = [c for c in self.columns if c not in X.columns]
        if missing:
            raise ValueError(f"columnas inexistentes: {missing}")
        keep = set(self.columns)
        self.columns_ = [
            c for c in X.columns if c in keep or any(c.startswith(p) for p in self.prefixes)
        ]
        return self

    def transform(self, X):
        return X[self.columns_]

    def get_feature_names_out(self, input_features=None):
        return np.array(self.columns_, dtype=object)


# ── Ensamble del preprocesador ──────────────────────────────────────────────


def high_card_encoder(kind: str, smoothing: float = 10.0, min_frequency: int = 10):
    """Codificador de `step_id` y `verb_norm`: "freq", "target", "onehot" o None."""
    if kind == "freq":
        return FrequencyEncoder(HIGH_CARD), HIGH_CARD
    if kind == "target":
        return GroupedTargetEncoder(HIGH_CARD, smoothing=smoothing), HIGH_CARD + [GROUP]
    if kind == "onehot":
        ohe = OneHotEncoder(
            min_frequency=min_frequency,
            handle_unknown="infrequent_if_exist",
            sparse_output=False,
        )
        return ohe, HIGH_CARD
    raise ValueError(f"codificación desconocida: {kind}")


def numeric_transformer(transforms: dict[str, str], scaler: str = "standard") -> ColumnTransformer:
    """Transformación por columna ("log1p", "yeo-johnson" o "none") y luego escalamiento."""
    scalers = {"standard": StandardScaler, "robust": RobustScaler}

    def pipe(step):
        steps = [("transform", step)] if step is not None else []
        return Pipeline([*steps, ("scale", scalers[scaler]())])

    groups = {
        "log1p": FunctionTransformer(np.log1p, feature_names_out="one-to-one"),
        "yeo-johnson": PowerTransformer(method="yeo-johnson", standardize=False),
        "none": None,
    }
    parts = []
    for kind, step in groups.items():
        cols = [c for c, t in transforms.items() if t == kind]
        if cols:
            parts.append((kind, pipe(step), cols))
    return ColumnTransformer(parts, verbose_feature_names_out=False)


def make_preprocessor(
    numeric: list[str],
    transforms: dict[str, str] | None = None,
    scaler: str = "standard",
    high_card: str | None = "target",
    smoothing: float = 10.0,
    min_frequency: int = 10,
    binary: list[str] | None = None,
    low_card: list[str] | None = None,
    low_card_encoding: str = "onehot",
    select: list[str] | None = None,
    select_prefixes: tuple[str, ...] = (),
) -> Pipeline:
    """Pipeline de scikit-learn que va de la tabla de pasos a la matriz X.

    `numeric` puede incluir las salidas de `StepDurationEncoder` (`dur_ratio_step`,
    `dur_z_step`); se calculan primero y después se transforman y escalan con las demás.
    """
    transforms = transforms or {}
    binary = BINARY if binary is None else binary
    low_card = LOW_CARD if low_card is None else low_card

    base_num = [c for c in numeric if c not in DURATION_REL]
    stage1 = [
        ("dur", StepDurationEncoder(), ["step_id", GROUP, "duration"]),
        ("num", "passthrough", base_num),
    ]
    if binary:
        stage1.append(("bin", "passthrough", binary))
    if low_card:
        if low_card_encoding == "onehot":
            low = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        else:
            low = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        stage1.append(("low", low, low_card))
    if high_card:
        enc, cols = high_card_encoder(high_card, smoothing, min_frequency)
        stage1.append(("high", enc, cols))
    features = ColumnTransformer(stage1, verbose_feature_names_out=False)

    num_t = {c: transforms.get(c, "none") for c in numeric}
    scale = numeric_transformer(num_t, scaler)
    scale.remainder = "passthrough"
    steps = [("features", features), ("scale", scale)]
    if select is not None:
        steps.append(("select", ColumnSelector(select, select_prefixes)))
    return Pipeline(steps).set_output(transform="pandas")


def make_model(preprocessor: Pipeline) -> Pipeline:
    """Regresión logística balanceada, solo como evidencia de las decisiones del avance 2."""
    clf = LogisticRegression(class_weight="balanced", max_iter=5000)
    return Pipeline([("prep", preprocessor), ("clf", clf)])


def grouped_cv_auc_pr(estimator, X: pd.DataFrame, y: pd.Series, n_splits: int = 5) -> np.ndarray:
    """AUC-PR (average precision) con GroupKFold por grabación, ajustando todo en cada pliegue."""
    cv = GroupKFold(n_splits=n_splits)
    return cross_val_score(
        clone(estimator), X, y, groups=X[GROUP], cv=cv, scoring="average_precision"
    )


# ── Decisiones finales del avance 2 ─────────────────────────────────────────

# Tomadas en docs/entregables/Semana 4/Avance2.51.ipynb; la sección 5 del notebook verifica
# que coincidan con lo que calcula.

# §3.8: |asimetría| > 0.5 y no cero-inflada -> la transformación que más la reduce.
FINAL_TRANSFORMS: dict[str, str] = {
    "duration": "yeo-johnson",
    "repeat_idx": "none",
    "dur_ratio_step": "none",
    "dur_z_step": "yeo-johnson",
    "exec_idx": "yeo-johnson",
    "rel_exec_pos": "none",
    "rel_start": "none",
    "gap_prev": "yeo-johnson",
    "overlap_prev": "none",
    "gap_next": "yeo-johnson",
    "overlap_next": "none",
    "n_pred": "yeo-johnson",
    "n_pred_after": "none",
    "n_pred_absent": "none",
    "rec_n_steps": "none",
    "rec_duration": "log1p",
    "rec_repeat_frac": "none",
}
# §3.9: StandardScaler (RobustScaler deja escalas originales donde el IQR es 0).
FINAL_SCALER = "standard"
# §3.6: frecuencia (empata con target y one-hot, 2 columnas, no usa la etiqueta).
FINAL_HIGH_CARD = "freq"
# §4.6: varianza, redundancia (|ρ| > 0.9) y relevancia (ANOVA, información mutua, χ²).
FINAL_SELECTED: list[str] = [
    "rec_duration",
    "exec_idx",
    "repeat_idx",
    "dur_ratio_step",
    "rel_exec_pos",
    "n_pred_after",
    "n_pred_absent",
    "rec_n_steps",
    "rec_repeat_frac",
    "order_violation",
    "step_id_freq",
]
# Bloque one-hot que se conserva completo (χ² de activity_name significativo).
FINAL_SELECTED_PREFIXES: tuple[str, ...] = ("activity_name_",)


class FeatureSet(NamedTuple):
    X_train: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.Series
    y_test: pd.Series
    pipeline: Pipeline


def prepare_steps(
    steps: pd.DataFrame, video_info: pd.DataFrame, graphs: dict[str, dict]
) -> pd.DataFrame:
    """Tabla cruda de pasos -> pasos ejecutados con todas las características sin aprendizaje."""
    return executed_steps(add_step_features(steps, video_info, graphs))


def build_features(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    video_info: pd.DataFrame,
    task_graphs: dict[str, dict],
    select: bool = True,
) -> FeatureSet:
    """X e y de train y test con las decisiones del avance 2; el pipeline se ajusta solo con train.

    `train` y `test` son tablas crudas de pasos (salida de `split_steps`). Solo se usan los pasos
    ejecutados. Los índices de X/y son los de la tabla de entrada, así que la grabación de cada
    fila (para GroupKFold) es `train.loc[X_train.index, "recording_id"]`.
    Con `select=False` se devuelven todas las características construidas (46 columnas).
    """
    tr = prepare_steps(train, video_info, task_graphs)
    te = prepare_steps(test, video_info, task_graphs)
    pipeline = make_preprocessor(
        numeric=NUMERIC,
        transforms=FINAL_TRANSFORMS,
        scaler=FINAL_SCALER,
        high_card=FINAL_HIGH_CARD,
        select=FINAL_SELECTED if select else None,
        select_prefixes=FINAL_SELECTED_PREFIXES if select else (),
    )
    y_train = tr[TARGET].astype(int)
    y_test = te[TARGET].astype(int)
    X_train = pipeline.fit_transform(tr, y_train)
    X_test = pipeline.transform(te)
    return FeatureSet(X_train, X_test, y_train, y_test, pipeline)
