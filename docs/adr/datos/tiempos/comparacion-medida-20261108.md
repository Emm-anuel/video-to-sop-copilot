# Medida actual contra «hasta el siguiente paso» (8 nov)

Datos: `datos/tiempos/tiempos-20261108-1630.json` (los mismos tramos de Gemma, sin volver a correr nada). SOP con 0.5 min por paso, ±20 %.

- **Actual:** t_fin − t_inicio del paso del video ya fusionado.
- **Hasta el siguiente:** del inicio del paso al inicio del siguiente paso del video (par, *Sobra*, intro o cierre: lo que venga), pausa incluida; el último paso del video, hasta su t_fin. Es lo mismo que «terminar donde empieza el *Sobra* o el cierre que haya en medio».
- **Anotado:** del inicio anotado a mano del paso al inicio anotado de lo siguiente.

## Resumen

| Video | Error medio abs., actual (s) | Error medio abs., siguiente (s) | Excede por corrida (actual → siguiente) |
|---|---|---|---|
| video_a | 9.5 | 4.0 | [] → []; [] → []; [] → [] |
| video_b | 5.2 | 0.6 | [] → []; [] → []; [] → [] |
| video_c | 8.3 | 7.8 | [1] → [1]; [1] → [1]; [1] → [1] |

## video_a · 1

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 15.8 | 9.6 | 15.8 | -6.2 | +0.0 | menor | menor |
| 2 ↔ 3 | 18.0 | 11.1 | 18.0 | -6.9 | +0.0 | menor | menor |
| 3 ↔ 6 | 17.6 | 7.0 | 12.7 | -10.6 | -4.9 | menor | menor |
| 4 ↔ 9 | 24.4 | 12.3 | 19.2 | -12.2 | -5.2 | menor | menor |
| 5 ↔ 10 | 18.7 | 12.9 | 18.7 | -5.8 | +0.0 | menor | menor |

## video_a · 2

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 15.8 | 9.6 | 15.8 | -6.2 | +0.0 | menor | menor |
| 2 ↔ 3 | 18.0 | 11.1 | 18.0 | -6.9 | +0.0 | menor | menor |
| 3 ↔ 6 | 17.6 | 7.0 | 12.7 | -10.6 | -4.9 | menor | menor |
| 4 ↔ 8 | 24.4 | 3.0 | 3.6 | -21.5 | -20.9 | menor | menor |
| 5 ↔ 10 | 18.7 | 12.9 | 18.7 | -5.8 | +0.0 | menor | menor |
| 6 ↔ 12 | 21.3 | 2.9 | 3.4 | -18.4 | -17.9 | menor | menor |

## video_a · 3

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 15.8 | 9.6 | 15.8 | -6.2 | +0.0 | menor | menor |
| 2 ↔ 3 | 18.0 | 11.1 | 18.0 | -6.9 | +0.0 | menor | menor |
| 3 ↔ 6 | 17.6 | 7.0 | 12.7 | -10.6 | -4.9 | menor | menor |
| 4 ↔ 9 | 24.4 | 12.3 | 19.2 | -12.2 | -5.2 | menor | menor |
| 5 ↔ 10 | 18.7 | 12.9 | 18.7 | -5.8 | +0.0 | menor | menor |

## video_b · 1

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 14.7 | 9.5 | 14.7 | -5.2 | +0.0 | menor | menor |
| 3 ↔ 3 | 18.2 | 12.4 | 18.2 | -5.9 | +0.0 | menor | menor |
| 4 ↔ 4 | 24.2 | 16.7 | 24.2 | -7.5 | +0.0 | menor | en_tiempo |
| 5 ↔ 6 | 25.1 | 27.5 | 27.5 | +2.4 | +2.4 | en_tiempo | en_tiempo |

## video_b · 2

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 14.7 | 9.5 | 14.7 | -5.2 | +0.0 | menor | menor |
| 3 ↔ 3 | 18.2 | 12.4 | 18.2 | -5.9 | +0.0 | menor | menor |
| 4 ↔ 4 | 24.2 | 16.7 | 24.2 | -7.5 | +0.0 | menor | en_tiempo |
| 5 ↔ 6 | 25.1 | 27.5 | 27.5 | +2.4 | +2.4 | en_tiempo | en_tiempo |

## video_b · 3

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 14.7 | 9.5 | 14.7 | -5.2 | +0.0 | menor | menor |
| 3 ↔ 3 | 18.2 | 12.4 | 18.2 | -5.9 | +0.0 | menor | menor |
| 4 ↔ 4 | 24.2 | 16.7 | 24.2 | -7.5 | +0.0 | menor | en_tiempo |
| 5 ↔ 6 | 25.1 | 27.5 | 27.5 | +2.4 | +2.4 | en_tiempo | en_tiempo |

## video_c · 1

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 71.2 | 61.0 | 61.4 | -10.2 | -9.8 | excede | excede |
| 2 ↔ 4 | 15.4 | 30.2 | 32.2 | +14.7 | +16.8 | en_tiempo | en_tiempo |
| 3 ↔ 3 | 20.0 | 25.6 | 30.3 | +5.6 | +10.2 | en_tiempo | en_tiempo |
| 4 ↔ 5 | 29.0 | 9.1 | 11.9 | -19.9 | -17.1 | menor | menor |
| 5 ↔ 7 | 19.1 | 22.4 | 22.4 | +3.3 | +3.3 | menor | menor |
| 6 ↔ 6 | 23.0 | 20.6 | 22.8 | -2.4 | -0.2 | menor | menor |

## video_c · 2

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 71.2 | 61.0 | 61.4 | -10.2 | -9.8 | excede | excede |
| 2 ↔ 4 | 15.4 | 10.6 | 14.6 | -4.9 | -0.8 | menor | menor |
| 3 ↔ 3 | 20.0 | 25.6 | 30.3 | +5.6 | +10.2 | en_tiempo | en_tiempo |
| 4 ↔ 6 | 29.0 | 9.1 | 11.9 | -19.9 | -17.1 | menor | menor |
| 5 ↔ 8 | 19.1 | 22.4 | 22.4 | +3.3 | +3.3 | menor | menor |
| 6 ↔ 7 | 23.0 | 20.6 | 22.8 | -2.4 | -0.2 | menor | menor |

## video_c · 3

| SOP ↔ video | Anotado (s) | Actual (s) | Hasta el siguiente (s) | Error actual (s) | Error siguiente (s) | Estado actual | Estado siguiente |
|---|---|---|---|---|---|---|---|
| 1 ↔ 2 | 71.2 | 61.0 | 61.4 | -10.2 | -9.8 | excede | excede |
| 2 ↔ 4 | 15.4 | 10.6 | 14.6 | -4.9 | -0.8 | menor | menor |
| 3 ↔ 3 | 20.0 | 25.6 | 30.3 | +5.6 | +10.2 | en_tiempo | en_tiempo |
| 4 ↔ 6 | 29.0 | 9.1 | 11.9 | -19.9 | -17.1 | menor | menor |
| 5 ↔ 8 | 19.1 | 22.4 | 22.4 | +3.3 | +3.3 | menor | menor |
| 6 ↔ 7 | 23.0 | 20.6 | 22.8 | -2.4 | -0.2 | menor | menor |

