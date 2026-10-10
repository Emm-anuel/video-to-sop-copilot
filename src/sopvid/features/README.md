# sopvid.features

Limpieza de datos e ingeniería de características **reutilizables** desde dos lugares:

1. Los notebooks de los avances (`docs/entregables/Semana N/AvanceN.51.ipynb`), que hacen `import sopvid.features`.
2. El pipeline del sistema (`sopvid.percepcion`, `sopvid.lenguaje`).

Regla: si una transformación aparece en un notebook y el pipeline la va a necesitar, se mueve aquí como función pura con su test en `tests/`. Así, lo que se reporta en un avance y lo que corre en producción es el mismo código.

**Estado:** reservado. Fuera del alcance de la fase F0; no hay código todavía.
