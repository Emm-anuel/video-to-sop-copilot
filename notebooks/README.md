# notebooks

Espacio de **exploración libre**: pruebas rápidas, borradores y experimentos. Nada de aquí se considera entregable.

- Los entregables oficiales van en `docs/entregables/Semana N/AvanceN.51.ipynb`.
- Esos notebooks **importan `sopvid`** en lugar de copiar código: instala el paquete en modo editable con `pip install -e ".[dev]"` (ver la sección 5 del [README](../README.md)).
- Si algo de un notebook se va a reutilizar, se mueve a `src/sopvid/features/` con su test.
- Limpia las salidas antes de hacer commit si contienen rutas locales, y **nunca** guardes en un notebook capturas, transcripciones ni fragmentos del material del cliente (ver [data/README.md](../data/README.md)).
