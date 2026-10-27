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
`Embedder` (CPU, pesos en `EMBEDDER_CACHE_DIR`) y `similitud`; `texto_para_embeber` arma
"nombre. descripción" para un paso del SOP y "nombre. descripción. cita" para uno del video
(la cita trae las palabras que dijo el operador; ADR-012). `fusionar`
([ADR-013](../../../docs/adr/ADR-013-fusion-sobresegmentacion.md)) une los pasos consecutivos del
video que caen en el mismo paso del SOP (coseno ≥ `UMBRAL_FUSION`) y devuelve el registro
`Fusion` de qué pasos originales se unieron. `asignar` elige las parejas SOP–video con el
algoritmo húngaro (`Par`, más los índices sin pareja; en empate, la asignación que respeta el
orden). `clasificar` da a cada paso un estado preliminar con los umbrales de la configuración
(`Clasificacion`: un `ResultadoPaso` por paso y su resumen): un par con similitud <
`UMBRAL_BAJO` se rompe en *Falta* (SOP) y *Sobra* (video); de `UMBRAL_BAJO` a `UMBRAL_ALTO`
queda en `zona_gris`, estado interno pendiente del juez Gemma 4; desde `UMBRAL_ALTO`, *Cumple*. Tiempo, cita y confianza salen solo del paso del video (sin cita,
confianza "baja"); el resumen cuenta los estados y el % de pares que irían al LLM. `orden`
revisa el orden con código (regla 5): ordena los Cumple, Parcial y zona_gris por `t_inicio` y calcula la
subsecuencia creciente más larga de `indice_sop` (O(n log n); en empate, la que deja fuera lo
que aparece más tarde en el video). Los demás reciben la marca `fuera_de_orden` (no es un
estado: un paso puede ser Cumple y estar fuera de orden) con su posición esperada y observada.
`emparejar(sop, pasos_video, juez=..., transcripcion=...)` encadena la cascada completa
(fusionar → similitud sobre los pasos fusionados → asignar → clasificar → juez → orden; el SOP
se vectoriza una vez) y devuelve `ResultadoEmparejamiento`; `EmparejadorMiniLM` la ofrece
detrás de la interfaz `Emparejador` (`afinidad` llega en S5). Sin juez, la zona gris queda como
`zona_gris`. Los umbrales (`UMBRAL_BAJO`, `UMBRAL_ALTO`, `UMBRAL_FUSION`) viven en la
configuración.

`juez.py` es el juez Gemma 4 de la zona gris (ADR-012, punto 3). `Juez` es la interfaz y
`JuezGemma` la cumple con `llm.py` (JSON Schema, temperatura 0, `SEMILLA`). El prompt vive en
`prompts/juez_zona_gris_v1.md` (un prompt nuevo es un archivo nuevo). El juez recibe el paso del
SOP, el del video y su narración (`narracion_de`: las palabras de la transcripción que empiezan
dentro del paso, no los segmentos completos), y devuelve un `Juicio`: *Cumple*, *Parcial* o
"no_corresponde", con justificación y una cita que el código verifica contra esa narración
(regla 4). El coseno no va en el prompt. Una respuesta inválida (JSON roto, cita inventada) se
reintenta hasta 3 veces; si no hay respuesta válida u Ollama no responde, el par queda en
`zona_gris` con un juicio de respaldo ("sin revisar" en el reporte). `aplicar_juez` aplica las
decisiones a una `Clasificacion` ("no_corresponde" rompe el par en *Falta* + *Sobra*) y, si
Ollama está caído, deja de llamarlo durante esa corrida.

`sop_markdown.py` (RF-03, [ADR-015](../../../docs/adr/ADR-015-sop-plantilla-markdown.md)) convierte
un SOP de referencia en Markdown o TXT al contrato `SOP` con código, sin LLM, según la plantilla
de [docs/contrato/plantilla_sop.md](../../../docs/contrato/plantilla_sop.md). `convertir_sop`
devuelve el SOP y las advertencias con tipo y línea; `ErrorSOP` si falta el título o los pasos, o
un paso no tiene nombre. `sop_a_markdown` escribe un SOP con la misma plantilla (sin metadatos:
la fuente de verdad es el JSON). Desde la terminal: `python scripts/convertir_sop.py ARCHIVO
[--salida RUTA]`. PDF, Word y texto libre con Gemma 4 quedan para S5.

Búsqueda, chat y la redacción del SOP siguen reservados. La extensión `vector` ya queda
habilitada en la base desde la primera migración.
