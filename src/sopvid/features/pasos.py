"""Clasificador de inicio de paso (avances 2–5): tabla de frases etiquetada.

Datos (preparados por `scripts/preparar_htstep.py` en `data/interim/htstep/`, no versionados):

- `asr_htstep.parquet`: frases de la narración (ASR de HowTo100M) con `vid`, `start_second`, `text`.
- `pasos_htstep.parquet`: pasos de HT-Step con `vid`, `activity`, `subset`, `duration`, `step_id`,
  `start`, `end`, `partial`.

Una fila por frase. La etiqueta `es_inicio_paso` vale 1 si un inicio de paso de HT-Step cae a
≤ `tol` segundos del inicio de la frase **y** esa frase es la más cercana a ese inicio. Cada inicio
marca a lo sumo una frase; una frase puede recibir varios inicios.
"""

from pathlib import Path

import numpy as np
import pandas as pd

VID = "vid"
TARGET = "es_inicio_paso"
TEST_SUBSET = "val_seen"  # conjunto de prueba sellado (partición oficial de HT-Step)
TOLERANCIAS = (2, 4, 6)


def htstep_dir() -> Path:
    """`data/interim/htstep` en la raíz del proyecto."""
    from sopvid.plataforma.config import PROJECT_ROOT

    return PROJECT_ROOT / "data" / "interim" / "htstep"


def load_htstep(path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lee `asr_htstep.parquet` y `pasos_htstep.parquet`."""
    path = path or htstep_dir()
    asr = pd.read_parquet(path / "asr_htstep.parquet")
    pasos = pd.read_parquet(path / "pasos_htstep.parquet")
    return asr, pasos


def build_phrase_table(asr: pd.DataFrame, pasos: pd.DataFrame) -> pd.DataFrame:
    """Una fila por frase, en orden dentro de cada video.

    - `idx`: posición de la frase en el video (0, 1, ...). Las frases con el mismo
      `start_second` conservan el orden en que vienen en la transcripción.
    - `t_inicio`: `start_second`; `t_fin`: `start_second` de la frase siguiente o, para la
      última, la duración del video según HT-Step.
    - Se agregan `activity`, `subset` y `duration` del video.
    """
    videos = pasos.drop_duplicates(VID).set_index(VID)[["activity", "subset", "duration"]]
    d = asr.rename(columns={"start_second": "t_inicio"}).copy()
    d["_orden"] = np.arange(len(d))
    d = d.sort_values([VID, "t_inicio", "_orden"], kind="stable").drop(columns="_orden")
    d["idx"] = d.groupby(VID).cumcount()
    d = d.join(videos, on=VID)
    d["t_fin"] = d.groupby(VID)["t_inicio"].shift(-1).astype(float).fillna(d["duration"])
    cols = [VID, "idx", "t_inicio", "t_fin", "text", "activity", "subset", "duration"]
    return d[cols].reset_index(drop=True)


def _window(tol: float | None, antes: float | None, despues: float | None) -> tuple[float, float]:
    if tol is not None:
        return float(tol), float(tol)
    if antes is None or despues is None:
        raise ValueError("indica `tol` o bien `antes` y `despues`")
    return float(antes), float(despues)


def assign_step_starts(
    frases: pd.DataFrame,
    pasos: pd.DataFrame,
    tol: float | None = None,
    *,
    antes: float | None = None,
    despues: float | None = None,
) -> pd.DataFrame:
    """Frase asignada a cada inicio de paso.

    Ventana: el inicio de la frase `t` debe cumplir `-antes <= t - inicio_paso <= despues`
    (`tol` equivale a `antes = despues = tol`). Dentro de la ventana gana la frase más cercana;
    en empate de distancia, la de menor `idx`. En una ventana simétrica esto es exactamente
    "la frase más cercana, si está a <= tol segundos".

    Devuelve una fila por paso con `dist` (|t - inicio| de la frase más cercana dentro de la
    ventana, o de la más cercana en general si ninguna cae dentro), `fila` (posición de la frase
    en `frases`, -1 si no hay) y `asignado`. `frases` debe venir de `build_phrase_table`.
    """
    antes, despues = _window(tol, antes, despues)
    t = frases["t_inicio"].to_numpy(dtype=float)
    starts = pasos["start"].to_numpy(dtype=float)
    bounds = frases.groupby(VID, sort=False).indices  # vid -> posiciones (contiguas y ordenadas)
    filas = np.full(len(pasos), -1, dtype=np.int64)
    dist = np.full(len(pasos), np.inf)
    asignado = np.zeros(len(pasos), dtype=bool)

    for vid, pos in pasos.groupby(VID, sort=False).indices.items():
        if vid not in bounds:
            continue
        rows = bounds[vid]
        tv = t[rows]
        s = starts[pos]
        n = len(tv)
        # candidatas: la primera frase del último segundo <= s, y la primera frase con t > s
        right = np.searchsorted(tv, s, side="right")
        left = np.searchsorted(tv, tv[np.clip(right - 1, 0, n - 1)], side="left")
        cand_l = np.where(right > 0, left, -1)
        cand_r = np.where(right < n, right, -1)
        d_l = np.where(cand_l >= 0, s - tv[np.clip(cand_l, 0, None)], np.inf)  # >= 0
        d_r = np.where(cand_r >= 0, tv[np.clip(cand_r, 0, n - 1)] - s, np.inf)  # > 0
        ok_l, ok_r = d_l <= antes, d_r <= despues
        # dentro de la ventana: la más cercana (empate -> la anterior); si ninguna, la más cercana
        use_l = np.where(ok_l & ok_r, d_l <= d_r, ok_l | (~ok_r & (d_l <= d_r)))
        best = np.where(use_l, cand_l, cand_r)
        filas[pos] = np.where(best >= 0, rows[np.clip(best, 0, None)], -1)
        dist[pos] = np.where(use_l, d_l, d_r)
        asignado[pos] = (ok_l | ok_r) & (best >= 0)

    out = pasos[[VID, "step_id", "start", "end", "partial"]].copy()
    out["dist"] = dist
    out["fila"] = filas
    out["asignado"] = asignado
    return out


def label_phrases(
    frases: pd.DataFrame,
    pasos: pd.DataFrame,
    tol: float | None = None,
    *,
    antes: float | None = None,
    despues: float | None = None,
) -> pd.Series:
    """`es_inicio_paso` (0/1) por frase: 1 si al menos un inicio de paso le fue asignado."""
    asig = assign_step_starts(frases, pasos, tol, antes=antes, despues=despues)
    marcadas = np.unique(asig.loc[asig["asignado"], "fila"].to_numpy())
    y = np.zeros(len(frases), dtype=np.int8)
    y[marcadas] = 1
    return pd.Series(y, index=frases.index, name=TARGET)


def random_step_starts(pasos: pd.DataFrame, seed: int = 51) -> pd.DataFrame:
    """Mismos pasos con el inicio uniforme al azar en [0, duración]: referencia de azar."""
    rng = np.random.default_rng(seed)
    return pasos.assign(start=rng.uniform(0, pasos["duration"].to_numpy()))


def tolerance_report(
    frases: pd.DataFrame,
    pasos: pd.DataFrame,
    windows: dict[str, tuple[float, float]] | None = None,
    seed: int = 51,
) -> pd.DataFrame:
    """Por ventana: tasa de positivos, inicios sin frase y comparación contra inicios al azar.

    `señal_%` = 1 − positivos_azar / positivos_reales: fracción de positivos que no se explica por
    la densidad de frases (si los inicios cayeran al azar, se obtendría `% positivos (azar)`).
    """
    windows = windows or {f"±{t} s": (t, t) for t in TOLERANCIAS}
    azar = random_step_starts(pasos, seed)
    rows = []
    for name, (antes, despues) in windows.items():
        asig = assign_step_starts(frases, pasos, antes=antes, despues=despues)
        n_pos = int(label_phrases(frases, pasos, antes=antes, despues=despues).sum())
        n_azar = int(label_phrases(frases, azar, antes=antes, despues=despues).sum())
        n_asig = int(asig["asignado"].sum())
        rows.append(
            {
                "ventana": name,
                "frases_positivas": n_pos,
                "% positivos": 100 * n_pos / len(frases),
                "% positivos (azar)": 100 * n_azar / len(frases),
                "señal_%": 100 * (1 - n_azar / n_pos) if n_pos else np.nan,
                "inicios_sin_frase": len(asig) - n_asig,
                "% inicios sin frase": 100 * (len(asig) - n_asig) / len(asig),
                "inicios que comparten frase": n_asig - n_pos,
            }
        )
    return pd.DataFrame(rows).set_index("ventana")


def split_by_video(frases: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """`train` y `test` (= `val_seen`, sellado) según la partición oficial, por video."""
    is_test = frases["subset"] == TEST_SUBSET
    train, test = frases[~is_test], frases[is_test]
    if set(train[VID]) & set(test[VID]):
        raise ValueError("Hay videos con frases en train y en test")
    return {"train": train, "test": test}
