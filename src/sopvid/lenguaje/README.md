# sopvid.lenguaje

Frente de **lenguaje**: a partir de los pasos indexados, encuentra, conversa y redacta.

| Capacidad | Qué hace | Tecnología prevista |
|---|---|---|
| Búsqueda híbrida | Combina texto completo (Postgres) y similitud de embeddings (pgvector) y devuelve el paso con su segundo exacto | MiniLM multilingüe + pgvector |
| Chat RAG | Responde con evidencia citada (video + segundo) | LLM local vía Ollama |
| SOP | Redacta el procedimiento con cada paso ligado a su evidencia | LLM local vía Ollama |

**Estado:** `llm.py` es el cliente del LLM local (Ollama, `/api/chat` con JSON Schema); cómo
levantarlo en [docs/dev/llm.md](../../../docs/dev/llm.md). La segmentación en pasos que lo usa
vive en `sopvid.percepcion.segmentacion`. `emparejamiento.py` tiene la base de MiniLM (ADR-012):
`Embedder` (CPU, pesos en `EMBEDDER_CACHE_DIR`) y `similitud`; `texto_para_embeber` arma el
mismo texto ("nombre. descripción") para un paso del SOP y uno del video. `fusionar`
([ADR-013](../../../docs/adr/ADR-013-fusion-sobresegmentacion.md)) une los pasos consecutivos del
video que caen en el mismo paso del SOP (coseno ≥ `UMBRAL_FUSION`) y devuelve el registro
`Fusion` de qué pasos originales se unieron. `asignar` elige las parejas SOP–video con el
algoritmo húngaro (`Par`, más los índices sin pareja; en empate, la asignación que respeta el
orden). `clasificar` da a cada paso un estado preliminar con los umbrales de la configuración
(`Clasificacion`: un `ResultadoPaso` por paso y su resumen): un par con similitud <
`UMBRAL_BAJO` se rompe en *Falta* (SOP) y *Sobra* (video); de `UMBRAL_BAJO` a `UMBRAL_ALTO`
queda en `zona_gris`, estado interno pendiente del juez Gemma 4 (S4); desde `UMBRAL_ALTO`,
*Cumple* provisional. Tiempo, cita y confianza salen solo del paso del video (sin cita,
confianza "baja"); el resumen cuenta los estados y el % de pares que irían al LLM. `orden`
revisa el orden con código (regla 5): ordena los Cumple y zona_gris por `t_inicio` y calcula la
subsecuencia creciente más larga de `indice_sop` (O(n log n); en empate, la que deja fuera lo
que aparece más tarde en el video). Los demás reciben la marca `fuera_de_orden` (no es un
estado: un paso puede ser Cumple y estar fuera de orden) con su posición esperada y observada.
`emparejar(sop, pasos_video)` encadena la cascada completa sin juez (fusionar → similitud sobre
los pasos fusionados → asignar → clasificar → orden; el SOP se vectoriza una vez) y devuelve
`ResultadoEmparejamiento`; `EmparejadorMiniLM` la ofrece detrás de la interfaz `Emparejador`
(`afinidad` llega en S5). Los umbrales (`UMBRAL_BAJO`, `UMBRAL_ALTO`, `UMBRAL_FUSION`) viven en
la configuración; el juez Gemma 4 de la zona gris llega en S4.

`sop_markdown.py` (RF-03, [ADR-015](../../../docs/adr/ADR-015-sop-plantilla-markdown.md)) convierte
un SOP de referencia en Markdown o TXT al contrato `SOP` con código, sin LLM, según la plantilla
de [docs/contrato/plantilla_sop.md](../../../docs/contrato/plantilla_sop.md). `convertir_sop`
devuelve el SOP y las advertencias con tipo y línea; `ErrorSOP` si falta el título o los pasos, o
un paso no tiene nombre. `sop_a_markdown` escribe un SOP con la misma plantilla (sin metadatos:
la fuente de verdad es el JSON). Desde la terminal: `python scripts/convertir_sop.py ARCHIVO
[--salida RUTA]`. PDF, Word y texto libre con Gemma 4 quedan para S5.

Búsqueda, chat y la redacción del SOP siguen reservados. La extensión `vector` ya queda
habilitada en la base desde la primera migración.
