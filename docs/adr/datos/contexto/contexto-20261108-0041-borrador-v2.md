# Ficha de contexto en CPU y en GPU · 2026-11-08 00:43

- Commit `d7c22e2d346a672da10de010f9304b62c9267c8f` en `feat/contexto` · 6 archivo(s) sin commit. Prompt(s) `contexto_v1`, `contexto_v2`, LLM `gemma4:e4b-it-q4_K_M`, GPU: NVIDIA GeForce RTX 2070 SUPER.
- Gemma se descarga antes de cada corrida: la espera al primer token incluye la carga.
- Fotogramas en la entrada: 0 en todas las corridas (RF-11 aún no existe).

## Corridas

| Video | Entrada | Prompt | Config | # | Whisper | Gemma | Tokens entrada | Tokens salida | Primer token (s) | Tokens/s | Ficha (s) | Total (s) | Intentos | Personas | Datos con cita |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| video_a | analisis | contexto_v1 | gpu | 1 | — | gpu | 1114 | 290 | 7.99 | 85.17 | 11.39 | 11.4 | 1 | 1 | 4/6 |
| video_a | analisis | contexto_v1 | gpu | 2 | — | gpu | 1114 | 289 | 5.95 | 86.77 | 9.3 | 9.3 | 1 | 1 | 4/6 |
| video_a | analisis | contexto_v1 | gpu | 3 | — | gpu | 1114 | 290 | 6.08 | 83.68 | 9.55 | 9.6 | 1 | 1 | 4/6 |
| video_a | analisis | contexto_v2 | gpu | 1 | — | gpu | 1210 | 313 | 6.03 | 87.09 | 9.62 | 9.6 | 1 | 1 | 3/6 |
| video_a | analisis | contexto_v2 | gpu | 2 | — | gpu | 1210 | 314 | 6.09 | 84.91 | 9.79 | 9.8 | 1 | 1 | 3/6 |
| video_a | analisis | contexto_v2 | gpu | 3 | — | gpu | 1210 | 312 | 6.33 | 87.33 | 9.91 | 9.9 | 1 | 1 | 3/6 |
| video_b | analisis | contexto_v1 | gpu | 1 | — | gpu | 984 | 284 | 5.88 | 82.1 | 9.33 | 9.3 | 1 | 1 | 2/6 |
| video_b | analisis | contexto_v1 | gpu | 2 | — | gpu | 984 | 284 | 5.92 | 82.37 | 9.37 | 9.4 | 1 | 1 | 2/6 |
| video_b | analisis | contexto_v1 | gpu | 3 | — | gpu | 984 | 285 | 5.97 | 82.48 | 9.44 | 9.4 | 1 | 1 | 2/6 |
| video_b | analisis | contexto_v2 | gpu | 1 | — | gpu | 1080 | 326 | 6.12 | 70.23 | 10.78 | 10.8 | 1 | 1 | 3/6 |
| video_b | analisis | contexto_v2 | gpu | 2 | — | gpu | 1080 | 307 | 6.17 | 79.4 | 10.04 | 10 | 1 | 1 | 3/6 |
| video_b | analisis | contexto_v2 | gpu | 3 | — | gpu | 1080 | 307 | 6.25 | 79.47 | 10.11 | 10.1 | 1 | 1 | 3/6 |

## Por versión del prompt (promedio de las corridas; 5 datos sin el resumen)

| Video | Config | Prompt | Corridas | Con valor | Inferidos | Alta | Media | Lugar | Tokens salida | Ficha (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| video_a | gpu | contexto_v1 | 3 | 4 | 0 | 2 | 2 | Línea de enjuague (audio, media); Línea de enjuague (audio, media); Línea de enjuague (audio, media) | 290 | 10.1 |
| video_a | gpu | contexto_v2 | 3 | 3 | 0 | 3 | 0 | —; —; — | 313 | 9.8 |
| video_b | gpu | contexto_v1 | 3 | 2 | 0 | 2 | 0 | —; —; — | 284 | 9.4 |
| video_b | gpu | contexto_v2 | 3 | 3 | 0 | 3 | 0 | —; —; — | 313 | 10.3 |

Las fichas completas están en el .json de esta medición.
