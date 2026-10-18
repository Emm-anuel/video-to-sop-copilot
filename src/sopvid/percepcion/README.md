# sopvid.percepcion

Frente de **percepción**: convierte un video en pasos con marca de tiempo.

| Etapa | Qué hace | Tecnología prevista |
|---|---|---|
| Ingesta | Recibe el video (archivo, cámara, teléfono) tras una misma interfaz y extrae el audio | ffmpeg |
| Transcripción | Texto con marcas de tiempo por segmento y palabra | faster-whisper |
| Segmentación | Agrupa la transcripción en pasos indexados (inicio/fin en segundos) | LLM local que elige el segmento donde empieza cada paso; heurística de transiciones y pausas como respaldo ([ADR-010](../../../docs/adr/ADR-010-segmentacion-pasos-llm.md)) |

**Estado:** `segmentacion.py` es el prototipo de ADR-010 (los tiempos de cada paso salen del
segmento elegido, nunca del LLM); se evalúa con `scripts/evaluar_segmentacion.py`. Ingesta y
transcripción empiezan en la fase F1 (semana del 12 oct, ver el [plan](../../../docs/plan/plan.md)).

> El modelo académico de `has_errors` (avances 2–5, `sopvid.features`) es la base de las futuras advertencias del copiloto. Solo usa información que este frente puede producir de un video segmentado: tiempos, orden y tipo de paso.

> El video y el audio del cliente **nunca** se guardan dentro del repo (ver [data/README.md](../../../data/README.md)). En desarrollo se usan datasets públicos bajo `data/raw/` o `media/`, ambas rutas ignoradas por Git.
