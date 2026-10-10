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

## Referencias

- Brief §9 (narración), §10 (tres bucles HITL), criterio "aprendizaje demostrado"; NDA cl. 1.
- ADR-002 (voz como fuente principal), ADR-006 (LLM local), ADR-008 (HITL), ADR-009.
