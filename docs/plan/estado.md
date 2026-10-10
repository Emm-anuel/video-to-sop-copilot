# Estado del proyecto · 10 oct 2026

Resumen para el equipo y el asesor. El plan completo está en [plan.md](plan.md).

## Lo que ya está hecho

**Académico**
- **Avance 1 (entregado):** análisis exploratorio de **CaptainCook4D** (videos públicos de personas
  cocinando, con los pasos anotados). Variable objetivo: **`has_errors`** (si un paso se hizo con
  error); 29 % de los pasos tienen error.
- **Avance 2 (listo para revisión, sin commit):** ingeniería de características en
  `docs/entregables/Semana 4/Avance2.51.ipynb`. Corre de principio a fin sin errores (~20 s). Las
  justificaciones están marcadas como borrador y la conclusión (sección C) la redacta el equipo a
  partir de la lista de hallazgos.
  - Se modelan solo los pasos que sí se ejecutaron (2,987 en entrenamiento; 24.9 % con error). Los
    omitidos se excluyen porque el 98.2 % son error *Missing Step* y revelarían la etiqueta.
  - Características nuevas con evidencia: duración relativa a la típica de su paso (el 10 % más
    rápido tiene 41 % de error), inversiones de orden según el grafo de la receta (71.6 % de error
    contra 23.5 %) y posición del paso. Huecos y traslapes con los pasos vecinos no aportan.
  - Selección: de 46 columnas quedan 35. PCA no se usa (necesita 12 de 19 componentes para el 90 % y
    empeora el AUC-PR).
  - El código vive en `sopvid.features`; `build_features` es la entrada del avance 3.

**Planeación**
- **Diagnóstico y plan del proyecto** ([plan.md](plan.md)). El código del POC del patrocinador no se
  entregó, así que se construye desde cero, con alcance reducido a la "columna de voz":
  video → transcripción → pasos → búsqueda y chat que lleva al segundo exacto.

**Repositorio**
- **F0 en `main` (commits del 10 oct, CI en verde):** paquete `src/sopvid`, API con `/health`,
  Postgres + pgvector, Docker, tests, CI, `CONTRIBUTING.md` e índice de ADRs con plantilla.
  `docker compose up` verificado localmente.
- **Sin commit todavía:** `sopvid.features` (datos, preprocesamiento del avance 1 e ingeniería del
  avance 2) con sus tests, el notebook del avance 2, `CLAUDE.md` y `docs/plan/`.

## Decisiones del 10 oct

1. **Se evaluó cambiar la tarea de ML** a un *clasificador de inicio de paso* (detectar dónde empieza
   cada paso en la narración de un video), porque es más útil para el producto.
2. **Se intentó con CrossTask.** Las anotaciones de pasos se descargaron (2,750 videos), pero los
   subtítulos ya no están disponibles (el servidor responde 403) y los videos ya no están en YouTube.
   Sin narración, el clasificador no se puede entrenar.
3. **Decisión (ADR-009):**
   - **Materia:** se sigue con `has_errors` en CaptainCook4D, en continuidad con el avance 1.
   - **Producto:** la segmentación en pasos será heurística (palabras de transición como "primero",
     "ahora", "después", más pausas). El clasificador de inicio de paso se entrenará después con
     videos propios del equipo, en español, y se validará con ellos.
4. **Avance 2:** solo pasos ejecutados; todo se ajusta con entrenamiento, y validación y prueba se
   aplican sin mirar sus etiquetas.

## Decisiones abiertas del avance 2

- **`rec_duration` (duración del video).** Es la característica con más peso: sin ella el AUC-PR baja
  de 0.571 a 0.485. Pero refleja sobre todo el diseño del dataset (a algunos participantes se les
  pidió cometer errores, y esos videos son más cortos), y eso no se transferiría a la planta. Se
  conservó, marcada como riesgo. Propuesta: reportar el avance 3 con y sin las características de
  grabación.
- **`duration`.** Se eliminó por no tener relación individual con el error, pero junto con la
  duración relativa recupera el AUC-PR que pierde la selección (0.553 → 0.571). Se evaluará en el
  avance 3 con métodos de envoltura o embebidos.

## Lo que falta

| Cuándo | Qué |
|---|---|
| **Urgente** | **El repositorio en GitHub es público** y el README dice que es privado (NDA). Cambiarlo a privado y agregar al asesor como colaborador si hace falta |
| **Dom 11 oct, 23:59** | **Avance 2:** revisar y reescribir las justificaciones, redactar la conclusión, decidir sobre `rec_duration` y entregar |
| Esta semana | Commit de `sopvid.features`, del avance 2, de `CLAUDE.md` y del plan |
| Lun 12 oct | Correo al patrocinador: confirmar que no entregará el código y autorizar partir de cero |
| Mar 13 oct | Correo al asesor: alcance ajustado, reparto real del trabajo y la pregunta de abajo |
| Vie 16 oct | Reunión con el patrocinador |
| Dom 18 oct | Avance 3 (baseline), a partir de `build_features` |

## Resumen en dos frases

> El avance 2 sigue con `has_errors` sobre CaptainCook4D, en continuidad con el avance 1. Evaluamos
> cambiar a un clasificador de inicio de paso, que le serviría más al producto, pero el dataset que lo
> hacía posible (CrossTask) ya no publica los subtítulos; ese clasificador lo entrenaremos después con
> videos propios.

**Pregunta para el asesor:** ¿Aceptaría que, a partir del avance 3, cambiemos la tarea al clasificador
de inicio de paso si para entonces tenemos datos, dado que es lo que el producto necesita?
