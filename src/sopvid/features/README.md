# sopvid.features

Limpieza de datos e ingeniería de características **reutilizables** desde dos lugares:

1. Los notebooks de los avances (`docs/entregables/Semana N/AvanceN.51.ipynb`), que hacen `import sopvid.features`.
2. El pipeline del sistema (`sopvid.percepcion`, `sopvid.lenguaje`).

Regla: si una transformación aparece en un notebook y el pipeline la va a necesitar, se mueve aquí como función pura con su test en `tests/`. Así, lo que se reporta en un avance y lo que corre en producción es el mismo código.

| Módulo | Contenido | Origen |
|---|---|---|
| `data.py` | Descarga de CaptainCook4D desde un commit fijo a `DATA_DIR`, tabla a nivel paso y grafos de tareas de las recetas | Avance 1 (§2–3) y avance 2 |
| `preprocessing.py` | Partición oficial, faltantes, consistencia, atípicos, cardinalidad y tabla a nivel grabación | Avance 1 (§4, §5.6 y §8), sin cambios de lógica |
| `engineering.py` | Características de posición, contexto, orden y grabación; transformadores sin fuga; `build_features` | Avance 2 |

Uso típico en el avance 3:

```python
from sopvid.features import data, engineering as fe, preprocessing as pp

raw = data.load_raw()
steps = data.build_step_table(raw.complete, raw.errors_raw)
parts = pp.split_steps(steps, raw.splits)
graphs = data.load_task_graphs(steps["activity_name"].unique())

X_train, X_test, y_train, y_test, pipeline = fe.build_features(
    parts["train"], parts["val"], video_info=raw.video_info, task_graphs=graphs
)
groups = parts["train"].loc[X_train.index, "recording_id"]  # para GroupKFold
```

Los datos se descargan en tiempo de ejecución y **nunca** se versionan (licencia MIT del dataset; ver [data/README.md](../../../data/README.md)).
