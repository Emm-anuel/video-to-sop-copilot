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
umbrales llegan en S3. Búsqueda, chat y SOP siguen reservados. La
extensión `vector` ya queda habilitada en la base desde la primera migración.
