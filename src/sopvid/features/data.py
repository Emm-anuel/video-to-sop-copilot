"""Descarga de las anotaciones públicas de CaptainCook4D y construcción de la tabla a nivel paso.

Lógica copiada de `docs/entregables/Semana 3/Avance1.51.ipynb` (secciones 2 y 3) sin cambios;
solo se reemplazaron las variables globales del notebook por parámetros.
Licencia de los datos: MIT (repositorio CaptainCook4D/annotations).
"""

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

COMMIT = "a8a920a3293c4db27099a20ddbe3a3a9be1283e3"
BASE_URL = f"https://raw.githubusercontent.com/CaptainCook4D/annotations/{COMMIT}"

FILES = [
    "annotation_json/complete_step_annotations.json",
    "annotation_json/error_annotations.json",
    "metadata/video_information.csv",
    "data_splits/recordings_data_split_combined.json",
]

# Renombrado de los metadatos de video usado en el avance 1 (`meta`).
VIDEO_META_RENAME = {
    "environment_id": "env_meta",
    "person_id": "person_meta",
    "duration(sec)": "video_duration_s",
    "duration(min)": "video_duration_min",
}


@dataclass(frozen=True)
class RawData:
    complete: dict
    errors_raw: list
    video_info: pd.DataFrame
    splits: dict


def default_data_dir() -> Path:
    """`DATA_DIR` del `.env` (por defecto `data/raw/captaincook4d` en la raíz del repo)."""
    from sopvid.plataforma.config import get_settings

    return get_settings().data_path


def fetch(rel_path: str, raw_dir: Path) -> Path:
    """Descarga un archivo una sola vez y lo reutiliza desde la caché local."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / Path(rel_path).name
    if not dest.exists():
        urllib.request.urlretrieve(f"{BASE_URL}/{rel_path}", dest)
    return dest


def load_raw(raw_dir: Path | None = None) -> RawData:
    """Descarga (si hace falta) y lee los cuatro archivos del commit fijo."""
    raw_dir = raw_dir or default_data_dir()
    paths = {Path(f).stem: fetch(f, raw_dir) for f in FILES}
    return RawData(
        complete=json.loads(paths["complete_step_annotations"].read_text()),
        errors_raw=json.loads(paths["error_annotations"].read_text()),
        video_info=pd.read_csv(paths["video_information"]),
        splits=json.loads(paths["recordings_data_split_combined"].read_text()),
    )


def count_misaligned(complete: dict, errors_raw: list) -> int:
    """Pasos cuyo `step_id` o `start_time` no coincide entre ambas fuentes (avance 1: 0)."""
    err_by_rec = {r["recording_id"]: r for r in errors_raw}
    misaligned = 0
    for rec_id, rec in complete.items():
        e_steps = err_by_rec[rec_id]["step_annotations"]
        if len(e_steps) != len(rec["steps"]):
            misaligned += 1
        for s, e in zip(rec["steps"], e_steps, strict=False):
            if s["step_id"] != e["step_id"] or s["start_time"] != e["start_time"]:
                misaligned += 1
    return misaligned


def build_step_table(complete: dict, errors_raw: list) -> pd.DataFrame:
    """Tabla a nivel paso: una fila por paso anotado, con etiquetas de error (avance 1, §3)."""
    # --- Nivel paso: anotaciones de pasos ---
    step_rows = []
    for rec_id, rec in complete.items():
        for order, s in enumerate(rec["steps"]):
            step_rows.append(
                {
                    "recording_id": rec_id,
                    "activity_id": rec["activity_id"],
                    "activity_name": rec["activity_name"],
                    "person_id": rec["person_id"],
                    "environment": rec["environment"],
                    "step_order": order,
                    "step_id": s["step_id"],
                    "description": s["description"],
                    "start_time": s["start_time"],
                    "end_time": s["end_time"],
                    "has_errors": s["has_errors"],
                }
            )
    steps = pd.DataFrame(step_rows)

    # --- Nivel paso: anotaciones de error (misma secuencia) ---
    err_by_rec = {r["recording_id"]: r for r in errors_raw}
    err_rows = []
    for rec_id, rec in complete.items():
        e_steps = err_by_rec[rec_id]["step_annotations"]
        for order, (_s, e) in enumerate(zip(rec["steps"], e_steps, strict=False)):
            err_rows.append(
                {
                    "recording_id": rec_id,
                    "step_order": order,
                    "error_tags": [x["tag"] for x in e.get("errors", [])],
                }
            )
    steps = steps.merge(pd.DataFrame(err_rows), on=["recording_id", "step_order"], how="left")

    # Verbo de la acción: la descripción tiene el formato "Verbo-Instrucción completa"
    steps["verb"] = steps["description"].str.split("-").str[0].str.strip().str.lower()

    # Categorías de error como columnas binarias (multi-etiqueta)
    error_tags = sorted({t for tags in steps["error_tags"] for t in tags})
    for tag in error_tags:
        steps["err_" + tag.lower().replace(" ", "_")] = steps["error_tags"].apply(
            lambda ts, tag=tag: int(tag in ts)
        )
    steps["n_error_tags"] = steps["error_tags"].str.len()

    # Bandera de error a nivel grabación según la anotación oficial
    rec_is_error = {r["recording_id"]: r["is_error"] for r in errors_raw}
    steps["recording_has_errors"] = steps["recording_id"].map(rec_is_error)
    return steps


def task_graph_file(activity_name: str) -> str:
    """Nombre del archivo del grafo de una receta: "Mug Cake" -> "task_graphs/mugcake.json"."""
    return f"task_graphs/{activity_name.lower().replace(' ', '')}.json"


def load_task_graphs(activity_names, raw_dir: Path | None = None) -> dict[str, dict]:
    """Grafo de dependencias de cada receta (mismo commit fijo); se agrega en el avance 2.

    Formato: `{"steps": {"<step_id>": "<descripción>"}, "edges": [[antes, después], ...]}`,
    con los nodos 0 = START y el último = END.
    """
    raw_dir = (raw_dir or default_data_dir()) / "task_graphs"
    graphs = {}
    for name in sorted(set(activity_names)):
        path = fetch(task_graph_file(name), raw_dir)
        graphs[name] = json.loads(path.read_text())
    return graphs


def error_tag_columns(steps: pd.DataFrame) -> list[str]:
    """Columnas `err_*` (una por categoría de error), en el orden de la tabla."""
    return [c for c in steps.columns if c.startswith("err_")]


def video_meta(video_info: pd.DataFrame) -> pd.DataFrame:
    """Metadatos de video con los nombres de columna del avance 1."""
    return video_info.rename(columns=VIDEO_META_RENAME)
