# Medición CPU contra GPU · 2026-10-27 19:01

Equipo: Intel64 Family 6 Model 165 Stepping 5, GenuineIntel, 16 núcleos, 31.9 GB de RAM, NVIDIA GeForce RTX 2070 SUPER. Modelo LLM: `gemma4:e4b-it-q4_K_M`. Umbrales sin cambios.

| Config | Whisper | Video | Whisper en | Gemma en | Transcribir s | Segmentar s | Emparejar s | Total s | × tiempo real | 10 min est. | RNF-01 | RAM MB | RAM Ollama MB | VRAM máx MB | % | Criterio | Válida |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cpu | small (int8) | video_a | cpu | cpu | 33.4 | 105.7 | 83.0 | 223.1 | 1.65 | 16.5 min | no cumple | 1520 | — | 2738 | 100.0 verde | pasa | sí |
| cpu | small (int8) | video_b | cpu | cpu | 25.8 | 101.5 | 29.6 | 158.8 | 1.38 | 13.8 min | no cumple | 1828 | — | 2453 | 66.7 rojo | pasa | sí |
| cpu | large-v3-turbo (int8) | video_a | cpu | cpu | 58.8 | 90.4 | 15.8 | 166.0 | 1.23 | 12.3 min | no cumple | 2767 | — | 2671 | 100.0 verde | pasa | sí |
| cpu | large-v3-turbo (int8) | video_b | cpu | cpu | 44.6 | 90.8 | 24.1 | 160.4 | 1.40 | 14.0 min | no cumple | 2667 | — | 2479 | 66.7 rojo | pasa | sí |
| auto | small (float16) | video_a | gpu | gpu | 10.7 | 15.9 | 0.4 | 27.7 | 0.20 | 2.0 min | cumple | 1838 | — | 7186 | 100.0 verde | pasa | sí |
| auto | small (float16) | video_b | gpu | gpu | 6.3 | 17.8 | 5.2 | 30.3 | 0.26 | 2.6 min | cumple | 1988 | — | 7194 | 66.7 rojo | pasa | sí |
| auto | large-v3-turbo (float16) | video_a | gpu | gpu | 7.6 | 44.3 | 2.8 | 55.6 | 0.41 | 4.1 min | cumple | 2205 | — | 7573 | 91.7 verde | pasa | no: aviso pasos_sin_redactar |
| auto | large-v3-turbo (float16) | video_b | gpu | gpu | 6.1 | 13.5 | 3.0 | 23.6 | 0.21 | 2.1 min | cumple | 2373 | — | 7395 | 66.7 rojo | pasa | sí |

## Mismo resultado en cada configuración (RNF-07)

- video_a, Whisper small: igual entre CPU y GPU
- video_a, Whisper large-v3-turbo: DISTINTO (2 resultados) entre CPU y GPU
- video_b, Whisper small: DISTINTO (2 resultados) entre CPU y GPU
- video_b, Whisper large-v3-turbo: igual entre CPU y GPU

Notas: el estimado de 10 min es lineal y sobrestima, porque las cargas en frío de Whisper y Gemma no crecen con el video. La RAM de Ollama solo se ve con Ollama nativo; en Docker queda en «—». La VRAM incluye la del escritorio (ver `vram_base_mb` en el JSON).
