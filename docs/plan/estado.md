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

1. **Se evaluó cambiar la tarea de ML** a un *clasificador de inicio de paso* (detectar en qué frase
   de la narración empieza cada paso), porque es lo que el producto necesita. Se probaron tres fuentes:
   - **CrossTask:** los subtítulos ya no se pueden descargar (403) y los videos ya no están en YouTube.
   - **HT-Step + ASR de HowTo100M** (16,636 videos): la transcripción está submuestreada
     (~60 palabras/min); ~74 % de los positivos se explicarían por azar.
   - **HT-Step + subtítulos `.vtt` completos** (130 videos, 137 palabras/min): la etiqueta casi no se
     distingue del azar. **Causa:** HT-Step marca cuándo empieza la acción en pantalla, no cuándo lo
     anuncia el narrador.
2. **Decisión (ADR-009):** los avances 2–5 siguen con **`has_errors`** sobre CaptainCook4D. El código
   de la exploración queda en la rama `avance2-inicio-paso`.
3. **Decisión propuesta (ADR-010):** en el producto, un **LLM local** propone dónde empieza cada paso
   eligiendo entre segmentos numerados (los tiempos salen del índice; el LLM nunca escribe tiempos),
   con la heurística de palabras clave y pausas como respaldo. El **experto corrige** en la Pantalla 1
   y cada corrección se guarda: sirve como ejemplo para el LLM y, más adelante, como etiqueta para un
   clasificador ligero. Así se implementa sobre la voz el aprendizaje por corrección que piden el brief
   y el NDA.
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

> El avance 2 sigue con `has_errors` sobre CaptainCook4D, en continuidad con el avance 1. Probamos un
> clasificador de inicio de paso con tres datasets públicos y ninguno sirve, porque sus etiquetas marcan
> la acción visual y no lo que dice el narrador; en el producto, los pasos los propondrá un LLM local y
> el experto los corregirá.

**Para el asesor:** se documentó la exploración en ADR-009. Pregunta: ¿le parece bien mantener
`has_errors` en los avances 3–5, o prefiere que el modelo académico se conecte al producto (por ejemplo,
entrenando el clasificador con etiquetas generadas por el LLM y validadas a mano)?
