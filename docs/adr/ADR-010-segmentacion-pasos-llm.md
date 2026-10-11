# ADR-010 · Segmentar la narración en pasos con un LLM local que elige segmentos, más corrección del experto

- **Estado:** Propuesto
- **Fecha:** 2026-10-10
- **Autores:** Emmanuel Merida
- **Decisores:** equipo + patrocinador (relacionado con ADR-002 y ADR-008)

---

## Contexto

El MVP necesita "pasos indexados con minuto y segundo": cortar la transcripción del experto en pasos.
El 10 oct se comprobó que no hay etiquetas públicas que sigan a la narración (ver
[ADR-009](ADR-009-tarea-ml.md)), así que entrenar un clasificador supervisado ahora no es viable. Los
videos industriales tendrán audio ruidoso, jerga y pasos que el experto no anuncia con palabras
clave. El brief y el NDA piden que el sistema aprenda de la corrección humana (HITL) en segundos.
Restricciones: costo cero, modelos abiertos locales, y la regla de que **el LLM nunca escribe un
timestamp**.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Heurística (transiciones "primero/ahora/después" + pausas) | Simple, rápida, explicable, sin GPU | No ve pasos sin palabra clave; frágil con jerga |
| B · Clasificador supervisado de inicio de paso | Rápido, calibrado, se reentrena en segundos | Sin etiquetas sobre narración hoy (ADR-009) |
| C · LLM local que **elige entre segmentos numerados** | Entiende contexto y jerga; tolera errores sueltos de ASR; sin entrenamiento | Más lento; necesita GPU para ir rápido; transcripciones largas por bloques; menos determinista |

## Decisión

**C con A como respaldo, dentro de un ciclo HITL:**

1. La transcripción (faster-whisper, tiempo por palabra) se divide en **segmentos de habla
   numerados** por pausas; el tiempo de cada segmento vive en el índice.
2. Un LLM local (vía Ollama, ADR-006) recibe los segmentos numerados, las etiquetas del video
   (máquina, área, proceso) y responde **solo números de segmento** donde empieza cada paso, con un
   nombre corto. Los tiempos se toman del índice; números inválidos se descartan.
3. Si el LLM no está disponible o falla la validación, se usa la heurística A.
4. El experto confirma o mueve los cortes en la Pantalla 1. Cada corrección se guarda con quién,
   cuándo y sobre qué evidencia.
5. Las correcciones se reutilizan (a) como **ejemplos en el prompt** del mismo cliente y (b) como
   **etiquetas** para un clasificador ligero (opción B) cuando haya suficientes.

## Consecuencias

- **Positivas:** segmentación útil desde el primer video sin datos etiquetados; cumple la regla de
  timestamps; implementa el aprendizaje por corrección del brief sobre la voz (sin V-JEPA 2);
  produce el conjunto de datos propietario de correcciones.
- **Negativas / riesgos:** latencia y dependencia de GPU; calidad sujeta al ASR en planta ruidosa (el
  LLM no recupera lo que no se transcribió: eso se ataca con VAD, un modelo Whisper mayor y
  vocabulario del cliente); prompts y versiones del modelo deben fijarse para reproducibilidad.
- **Seguimiento (F2):** con videos propios anotados a mano (inicio de paso **según la narración**),
  comparar A vs C vs C + ejemplos de correcciones con F1 de fronteras a ±k s y error de timestamp.
  El clasificador ligero (B) solo se construye si hace falta: copiloto en vivo, servidor sin GPU o
  necesidad de probabilidades calibradas para decidir cuándo preguntar.

## Prototipo y resultados preliminares (11 oct 2026)

Prototipo en `src/sopvid/percepcion/segmentacion.py`: el LLM recibe los segmentos numerados y las
etiquetas, y responde solo `[{"segmento_id", "titulo"}]` con JSON Schema. Validación: ids que
existen, orden creciente, sin duplicados. Los tiempos se toman del segmento elegido. Si el LLM
falla o la propuesta es inválida, se usa la heurística (marcador de transición en las 3 primeras
palabras o pausa ≥ 3 s, con al menos 2 segmentos entre cortes; parámetros fijados de antemano) y
el camino queda registrado.

Evaluación con `scripts/evaluar_segmentacion.py` sobre **3 transcripciones inventadas** (30 pasos
marcados a mano; una sin ninguna palabra de transición). RTX 2070 SUPER de 8 GB, Ollama 0.40.2 con
flash attention, temperatura 0, 3 repeticiones por combinación (mediana). Datos crudos en
[datos/segmentacion/fase4.json](datos/segmentacion/fase4.json). **Resultado indicativo (n=3).**

| Método | Capas en GPU | F1 ±1 segmento | F1 ±2 s | Falsos positivos | No detectados | s por transcripción |
|---|---|---|---|---|---|---|
| Heurística | — | 0.667 | 0.456 | 8 | 11 | < 0.01 |
| `gemma4:e4b-it-q4_K_M` (prompt v1) | 43/43 | 0.741 | 0.691 | 21 | 0 | 5.2 |
| `gemma4:12b-it-qat` (prompt v1) | **37/49** | 0.763 | 0.763 | 17 | 1 | 49.8 |
| `qwen3.5:9b-q4_K_M` (prompt v1) | **32/33** | **0.947** | **0.842** | 0 | 3 | 6.2 |

- Las 36 + 9 llamadas al LLM dieron JSON válido y pasaron la validación: ninguna cayó a la heurística.
- Los Gemma 4 **sobre-segmentan**, sobre todo sin palabras de transición: en la transcripción del
  filtro hidráulico (9 pasos) `e4b` propone 20 y `12b` 19. `qwen3.5` casi no tiene falsos positivos;
  sus errores son pasos fusionados.
- `gemma4:12b-it-qat` no cabe en 8 GB (37/49 capas en GPU, 6,247 MiB de VRAM) y tarda ~50 s por
  transcripción; mejora poco a `e4b`.

### Prompt v2 (regla de aclaraciones): probado y descartado

Tras el benchmark de ADR-006, donde todos los errores eran pasos de más, se probó agregar al prompt:
*"No marques como paso nuevo las aclaraciones, advertencias, ejemplos, anécdotas ni comentarios que
el técnico hace dentro de un paso"*.

| Modelo | Prompt | F1 ±1 segmento | Falsos positivos | No detectados |
|---|---|---|---|---|
| `gemma4:e4b-it-q4_K_M` | v1 | 0.741 | 21 | 0 |
| | v2 | 0.741 | 21 | 0 |
| `qwen3.5:9b-q4_K_M` | v1 | 0.947 | 0 | 3 |
| | v2 | 0.852 | 5 | 4 |

No redujo los falsos positivos de `e4b` y empeoró a `qwen3.5` (fusiona más pasos en una transcripción
y parte de más en otra). **Se descarta como valor por defecto**: el prototipo usa v1;
`regla_aclaraciones=True` queda como opción para futuras pruebas.

## Pendiente con el patrocinador

- **En 8 GB, `gemma4:e4b` sobre-segmenta** (F1 0.74; 21 pasos de más en 30 reales). Es útil como
  borrador para que el experto corrija, pero no como segmentación final.
- **`qwen3.5:9b` segmenta mejor** (F1 0.95, sin pasos de más) y tarda ~6 s por transcripción aunque
  no cabe completo en 8 GB, **pero no es Gemma 4**: el NDA (cl. 1) pide Gemma 4 como base. Usarlo
  requiere aprobación escrita del patrocinador.
- **`gemma4:12b-it-qat` no resuelve el problema en 8 GB**: no cabe (37/49 capas), tarda ~50 s por
  transcripción y solo sube el F1 a 0.76.
- **Propuesta:** con la GPU de 24 GB confirmada, medir `gemma4:26b-a4b-it-qat` con
  `scripts/evaluar_segmentacion.py` (mismas transcripciones, prompt v1) y decidir entre Gemma 4 mayor
  y pedir la excepción para `qwen3.5`. Mientras tanto, desarrollo sigue con `gemma4:e4b` (ADR-006).

## Referencias

- Brief §9 (narración), §10 (tres bucles HITL), criterio "aprendizaje demostrado"; NDA cl. 1.
- ADR-002 (voz como fuente principal), ADR-006 (LLM local), ADR-008 (HITL), ADR-009.
