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
`Embedder` (CPU, pesos en `EMBEDDER_CACHE_DIR`) y `similitud`; la fusión, el húngaro y los
umbrales llegan en S3. `sop_markdown.py` convierte un SOP de referencia en Markdown o TXT al
esquema `SOP` (RF-03) con código, sin LLM, según la plantilla de
[docs/contrato/plantilla_sop.md](../../../docs/contrato/plantilla_sop.md); PDF, Word y texto libre
con Gemma 4 quedan para S5. Búsqueda, chat y la redacción del SOP siguen reservados. La
extensión `vector` ya queda habilitada en la base desde la primera migración.
