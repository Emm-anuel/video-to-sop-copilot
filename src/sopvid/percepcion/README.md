# sopvid.percepcion

Frente de **percepción**: convierte un video en pasos con marca de tiempo.

| Etapa | Qué hace | Tecnología prevista |
|---|---|---|
| Ingesta | Recibe el video (archivo, cámara, teléfono) tras una misma interfaz y extrae el audio | ffmpeg |
| Transcripción | Texto con marcas de tiempo por segmento y palabra | faster-whisper |
| Segmentación | Agrupa la transcripción en pasos indexados (inicio/fin en segundos) | Heurística: palabras de transición ("primero", "ahora", "después") y pausas (ADR-009). Clasificador de inicio de paso más adelante, con videos propios anotados |

**Estado:** reservado; aún no hay código. Empieza en la fase F1 (semana del 12 oct, ver el [plan](../../../docs/plan/plan.md)).

> El modelo académico de `has_errors` (avances 2–5, `sopvid.features`) es la base de las futuras advertencias del copiloto. Solo usa información que este frente puede producir de un video segmentado: tiempos, orden y tipo de paso.

> El video y el audio del cliente **nunca** se guardan dentro del repo (ver [data/README.md](../../../data/README.md)). En desarrollo se usan datasets públicos bajo `data/raw/` o `media/`, ambas rutas ignoradas por Git.
