# sopvid.percepcion

Frente de **percepción**: convierte un video en pasos con marca de tiempo.

| Etapa | Qué hace | Tecnología prevista |
|---|---|---|
| Ingesta | Recibe el video (archivo, cámara, teléfono) tras una misma interfaz y extrae el audio | ffmpeg |
| Transcripción | Texto con marcas de tiempo por segmento y palabra | faster-whisper |
| Segmentación | Agrupa la transcripción en pasos indexados (inicio/fin en segundos) | heurísticas + scikit-learn/LightGBM |

**Estado:** reservado. Fuera del alcance de la fase F0; no hay código todavía.

> El video y el audio del cliente **nunca** se guardan dentro del repo (ver [data/README.md](../../../data/README.md)). En desarrollo se usan datasets públicos bajo `data/raw/` o `media/`, ambas rutas ignoradas por Git.
