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

## Actualización 17 oct 2026 (documento SOP V1.0)

- En la versión 1.0 este método extrae los **pasos del video** (RF-13) **sin mostrarle el SOP al
  modelo** (sección 5.3 del documento). Además de `segmento_id` y `titulo`, el LLM devuelve
  descripción, responsable y la cita textual; los tiempos siguen saliendo de los segmentos.
- La corrección del experto se hace sobre el reporte (RF-21) y sobre el SOP generado (RF-26), no en una
  "Pantalla 1" de pasos.
- La sobre-segmentación de `gemma4:e4b` produciría pasos *Sobra* falsos. Mitigación (ADR-013): antes
  de emparejar, se fusionan pasos consecutivos del video cuyo mejor paso del SOP es el mismo.
- El seguimiento de F2 se hace con los videos de prueba A–E grabados y anotados por el equipo.

## Ampliación 19 oct (RF-13)

Implementado en la rama `feat/pasos-video`. El contrato vive en
[src/sopvid/contrato.py](../../src/sopvid/contrato.py) y el esquema de entrada en
[docs/contrato/analisis.schema.json](../contrato/analisis.schema.json), generado con
`python scripts/exportar_contrato.py` (un test falla si deja de coincidir con el modelo).

### Esquema de salida: `PropuestaPaso` → `PasoVideo`

- **Entrada:** `Analisis` (versión 1 del contrato): `video_id`, `duracion_s`, `idioma`,
  `transcripcion` (segmentos con `id`, `t_inicio`, `t_fin`, `texto` y `palabras`) y `fotogramas`.
  Campos extra prohibidos, tiempos ≥ 0, ids de segmento estrictamente crecientes y segmentos sin
  solaparse.
- **Lo que responde el LLM:** `list[PropuestaPaso]` con `segmento_id`, `nombre`, `descripcion`,
  `responsable` y `cita`. El JSON Schema del parámetro `format` de Ollama se genera desde Pydantic y
  se aplana (sin `$ref`). Con Ollama 0.40.2 funcionan el esquema plano y el que lleva `$ref`; se usa
  el plano por robustez. Cualquier campo extra, por ejemplo un `t_inicio`, invalida la propuesta.
- **Lo que devuelve `segmentar(analisis, llm, etiquetas=None)`:** `Segmentacion` con
  `list[PasoVideo]` (`numero`, `nombre`, `descripcion`, `responsable`, `t_inicio`, `t_fin`, `cita`,
  `fuente`, `confianza`) por el LLM y por la heurística, más `metodo`, `motivo_respaldo`, `modelo` e
  `intentos`. Las etiquetas son opcionales: la ficha de contexto llega en S5.
- **Sin SOP:** ninguna función de la extracción tiene un parámetro para el SOP. Un test revisa que
  ningún mensaje enviado al LLM, ni en los reintentos, contenga texto de un SOP de prueba ni números
  con formato de tiempo.

### Regla de tiempos

Todos los tiempos salen del índice de la transcripción, nunca del LLM:

- `t_inicio`: el del segmento elegido.
- `t_fin`: el del último segmento antes del inicio del siguiente paso; para el último paso, el del
  último segmento de la transcripción.
- `numero`: la posición del paso, desde 1.

### Confianza por cita (RNF-06)

La cita y la transcripción se normalizan igual que en la heurística (minúsculas, sin acentos ni
puntuación, espacios colapsados) y la cita se busca como secuencia contigua de palabras completas.

| Dónde aparece la cita | `confianza` | `fuente` |
|---|---|---|
| En los segmentos del paso (puede cruzar de un segmento al siguiente) | alta | audio |
| En otra parte de la transcripción (incluye una cita que cruza la frontera del paso) | media | audio |
| En ninguna parte, o cita vacía | baja | inferido |

`visual` queda reservado para la evidencia de fotogramas (S5).

### Regla de responsable (ADR-008, sin diarización)

- El rol se recorta y se capitaliza (se conservan siglas). Un valor vacío o de relleno
  ("desconocido", "n/a", "ninguno"…) pasa a "No identificado".
- Si el sustantivo del rol (por ejemplo "operador" en "Operador de turno") no se dice en los
  segmentos del paso ni en la introducción (lo anterior al primer paso), el rol se conserva pero la
  confianza del paso baja un nivel: alta → media, media → baja. La comparación tolera género y
  número (técnico/técnica, supervisor/supervisores). "No identificado" no baja nada.

### Reintentos (RNF-07)

- Hasta 3 llamadas. Si la propuesta no pasa la validación o el JSON viene roto, se reenvía la
  conversación con la respuesta anterior como "assistant" (si se pudo leer) y un "user" con el
  motivo resumido: campo, tipo de error e ids, nunca texto de la transcripción.
- Temperatura 0 y semilla 42 en todas las llamadas.
- Si Ollama no responde o rechaza la petición, se va directo a la heurística, sin reintentar.
- `Segmentacion.intentos` registra las llamadas hechas.

### Heurística de respaldo

Mismos cortes que en la Fase 4: marcadores de transición y pausas ≥ 3 s, con los mismos parámetros.
Se verificó que reproduce los cortes guardados en `fase4.json`. Ahora devuelve `PasoVideo` con la
misma regla de tiempos:

- **nombre:** las primeras palabras del primer segmento.
- **descripción:** el texto del paso recortado a unos 300 caracteres.
- **responsable:** "No identificado".
- **cita:** hasta 15 palabras del primer segmento.
- **fuente y confianza:** siempre `audio` y `baja`.

### Resultados contra la Fase 4 (18 oct 2026)

`gemma4:e4b-it-q4_K_M`, prompt v1 ampliado (cortes + descripción, responsable y cita), 43/43 capas
en GPU, flash attention, Ollama 0.40.2, temperatura 0, 3 repeticiones (mediana). Datos crudos en
[datos/segmentacion/pasos_video.json](datos/segmentacion/pasos_video.json). **Resultado indicativo
(n=3 + 1).**

| Mismas 3 transcripciones | F1 ±1 segmento | F1 ±2 s | Falsos positivos | No detectados | Pasos sin redactar | s por transcripción |
|---|---|---|---|---|---|---|
| Fase 4 (prompt de 2 campos) | **0.741** | 0.691 | 21 | 0 | — | 5.2 |
| RF-13 (prompt de 5 campos) | **0.645** | 0.602 | 33 | 0 | 0 de 9 corridas | 18.9 |
| RF-13 opción A, todo o nada | **0.741** | 0.691 | 21 | 0 | **100 %** (9 de 9 corridas) | 55.3 |
| RF-13 opción A corregida | **0.741** | 0.691 | 21 | 0 | **0 %** (0 de 151 pasos) | 29.5 |

| Transcripción | Método | F1 ±1 segmento | % alta / media / baja | Intentos (fronteras + redacción) | Caídas a la heurística | s |
|---|---|---|---|---|---|---|
| cambio_cuchilla | Fase 4 | 0.800 | — | — | — | 5.3 |
| | RF-13 | 0.615 | 4 / 96 / 0 | 1.00 | 0 | 23.4 |
| | RF-13 opción A, todo o nada | 0.800 | 0 / 0 / 100 | 1.00 + 3.00 | 0 | 55.3 |
| | RF-13 opción A corregida | 0.800 | 6 / 94 / 0 | 1.00 + 1.00 | 0 | 53.3 |
| cambio_filtro_hidraulico | Fase 4 | 0.581 | — | — | — | 5.9 |
| | RF-13 | 0.581 | 42 / 58 / 0 | 1.00 | 0 | 18.9 |
| | RF-13 opción A, todo o nada | 0.581 | 0 / 0 / 100 | 1.00 + 3.00 | 0 | 61.5 |
| | RF-13 opción A corregida | 0.581 | 5 / 95 / 0 | 1.00 + 1.33 | 0 | 29.5 |
| limpieza_cip_tanque | Fase 4 | 0.900 | — | — | — | 2.8 |
| | RF-13 | 0.783 | 14 / 86 / 0 | 1.00 | 0 | 11.5 |
| | RF-13 opción A, todo o nada | 0.900 | 0 / 0 / 100 | 1.00 + 3.00 | 0 | 23.7 |
| | RF-13 opción A corregida | 0.900 | 100 / 0 / 0 | 1.00 + 1.00 | 0 | 11.1 |
| analisis_ejemplo | RF-13 | 0.632 | 100 / 0 / 0 | 1.00 | 0 | 11.7 |
| | RF-13 opción A, todo o nada | 0.571 | 0 / 0 / 100 | 1.00 + 3.00 | 0 | 49.9 |
| | RF-13 opción A corregida | 0.571 | 0 / 100 / 0 | 1.00 + 1.00 | 0 | 21.6 |

**De dónde viene la diferencia:**

- **El entorno no cambió.** El prompt de 2 campos, corrido el mismo día con el mismo modelo,
  reproduce la Fase 4: 0.800 / 0.581 / 0.900.
- **La caída viene del prompt ampliado.** Al redactar cinco campos por paso, el modelo parte más:
  30 inicios en lugar de 18 en la cuchilla y 14 en lugar de 11 en el CIP. Sigue sin perder pasos
  reales, escribe de 3 a 4 veces más tokens y tarda unas 4 veces más.
- **La confianza `media` no viene de las citas.** Antes del ajuste por responsable, el 100 % de las
  citas es literal. Lo que baja la confianza es que el modelo escribe "Operador", el ejemplo del
  prompt, aunque nadie lo diga en el audio. En `analisis_ejemplo` la narradora dice su rol, y por eso
  sale 100 % `alta`.
- **El largo de la cita no se cumple siempre.** En el filtro, 14 de 21 citas quedaron fuera de 4 a
  15 palabras; todavía no se exige.

**Opciones, pendientes de decisión:**

- **A · Dos llamadas (recomendada).** Una para las fronteras, con el prompt de 2 campos que mide
  0.74, y otra para redactar descripción, responsable y cita con los rangos ya fijados por código.
  En la segunda se quita el ejemplo de rol que ancla "Operador".
- **B · Una llamada con dos bloques.** El esquema pide primero los inicios y después la redacción.
- **C · Dejarlo así y confiar en la fusión de ADR-013.** Solo ayuda cuando hay SOP.

**Opción A, implementada y medida (18 oct):**

- **Las fronteras se recuperan.** La primera llamada usa el prompt v1 sin cambios y da los mismos
  cortes que la Fase 4: F1 0.741 en las tres transcripciones, con 21 falsos positivos. En
  `analisis_ejemplo` baja de 0.632 a 0.571.
- **La redacción falló en las 12 corridas.** Tras 3 intentos, todos los pasos quedaron sin redactar
  (nombre = título, cita vacía, confianza `baja`). Ninguna corrida cayó a la heurística. Las
  causas, según el log:
  - El modelo copia el segmento entero como cita: 16 a 22 palabras, contra el máximo de 15 que exige
    la validación.
  - Al reintentar, el historial crece (respuesta anterior + corrección) y la salida se corta
    (`done_reason=length`) en las transcripciones largas: cuchilla, 60 segmentos; filtro, 29.
  - La validación es de todo o nada: una sola cita larga invalida los demás pasos.
- **Tarda más:** 23 a 62 s por transcripción, contra 12 a 23 s de la llamada única. Pesan la segunda
  llamada y sus reintentos.

**Correcciones aplicadas a la opción A (18 oct):**

1. La redacción se valida paso por paso: los pasos válidos se usan y solo los que fallan quedan sin
   redactar (`Segmentacion.pasos_sin_redactar`).
2. Una cita literal de más de 15 palabras se recorta por código a sus primeras 15
   (`recortar_cita`): sigue siendo literal y se verifica igual. Menos de 4 palabras sigue siendo
   inválida.
3. El reintento envía el prompt original más un mensaje con solo los pasos pendientes y su motivo,
   sin la respuesta anterior, así que el contexto no crece.

**Opción A corregida, medida (18 oct):** fila "RF-13 opción A corregida". Las corridas de la versión
anterior siguen en `pasos_video.json` con la etiqueta "opción A (todo o nada)".

- **Fronteras:** las mismas de la Fase 4 (F1 0.741, 21 falsos positivos).
- **Redacción:** funciona. Se redactaron los 151 pasos de las tres transcripciones y los 45 de
  `analisis_ejemplo`; solo una corrida necesitó reintentar un paso.
- **Tiempo:** 11 a 53 s por transcripción, contra 12 a 23 s de la llamada única.
- **Confianza:** el 74 % de los pasos queda en `media` (100 % en `analisis_ejemplo`). La revisión del
  ejemplo muestra dos problemas nuevos, ajenos a las correcciones:
  - **El modelo confunde el número de paso con el número de segmento.** Para el paso *n* cita el
    segmento `[n]`: el paso 3 (segmentos 6–8) cita el segmento 3. Las citas son literales, pero de
    otra parte del video, y por eso quedan en `media`. Viene de que el prompt de redacción muestra
    los segmentos con su número entre corchetes, y esos números chocan con los de los pasos.
  - **Sin ejemplo de rol, el modelo pone "No identificado" casi siempre**, aunque la narradora diga
    su puesto en la introducción ("técnica de mantenimiento"). Además, una vez escribió su nombre
    ("Laura") en lugar del puesto. Un nombre de trabajador es un dato personal (LFPDPPP).

**Pendiente de decisión:**

1. Quitar los números de segmento del prompt de redacción: cada paso solo con su texto, sin `[n]`.
2. Pedir el responsable como puesto, nunca como nombre de persona. Si quien narra dice su puesto en la
   introducción y describe los pasos en primera persona, ese puesto es el responsable.

El ADR sigue **Propuesto** hasta medir esas dos correcciones con `scripts/evaluar_segmentacion.py`.
