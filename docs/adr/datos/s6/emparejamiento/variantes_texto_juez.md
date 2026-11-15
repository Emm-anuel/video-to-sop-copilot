# Emparejamiento con el juez real por EMPAREJAR_TEXTO (#11, ADR-026)

`scripts/diagnosticar_emparejamiento.py --variantes-texto --juez`: `emparejar` de producción (fusión, húngaro, umbrales, juez Gemma 4 de la zona gris y rescate) con la segmentación guardada, una vez por valor de `EMPAREJAR_TEXTO`.

- Commit `f8edb228d9866b93fbb79ee0215b0591805ed52c` · LLM `gemma4:e4b-it-q4_K_M` · cambios sin commit: 7

## e8658-9299 (E×SOP-9299, video 8658)

- **cita**: 75.0 %, conteo {'Cumple': 3, 'Parcial': 3, 'Falta': 0, 'Sobra': 4, 'zona_gris': 0}, al juez 3 ({'Cumple': 0, 'Parcial': 3, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0
- **max_si_otro_idioma**: 91.67 %, conteo {'Cumple': 5, 'Parcial': 1, 'Falta': 0, 'Sobra': 0, 'zona_gris': 0}, al juez 1 ({'Cumple': 0, 'Parcial': 1, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0

| SOP | cita | max_si_otro_idioma |
|---|---|---|
| 1 | Cumple [3] ✓ 0.80 | Cumple [3] ✓ 0.80 |
| 2 | Cumple [4] ✓ 0.81 | Cumple [4] ✓ 0.81 |
| 3 | Cumple [5, 6, 7] ✓ 0.91 | Cumple [5, 6] ✓ 0.81 |
| 4 | Parcial [10] ✓ 0.61, juez: Parcial | Cumple [8, 9, 10] ✓ 0.84 |
| 5 | Parcial [12] ✓ 0.70, juez: Parcial | Cumple [11, 12, 13] ✓ 0.90 |
| 6 | Parcial [14] ✓ 0.67, juez: Parcial | Parcial [7] ✗ 0.70, juez: Parcial |

## e9689-9299 (E×SOP-9299, video 9689)

- **cita**: 83.33 %, conteo {'Cumple': 4, 'Parcial': 2, 'Falta': 0, 'Sobra': 3, 'zona_gris': 0}, al juez 2 ({'Cumple': 0, 'Parcial': 2, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0
- **max_si_otro_idioma**: 91.67 %, conteo {'Cumple': 5, 'Parcial': 1, 'Falta': 0, 'Sobra': 0, 'zona_gris': 0}, al juez 1 ({'Cumple': 0, 'Parcial': 1, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0

| SOP | cita | max_si_otro_idioma |
|---|---|---|
| 1 | Cumple [3] ✓ 0.78 | Cumple [3] ✓ 0.78 |
| 2 | Cumple [4] ✓ 0.81 | Cumple [4] ✓ 0.81 |
| 3 | Cumple [5, 6, 7] ✓ 0.89 | Cumple [5, 6] ✓ 0.79 |
| 4 | Parcial [10] ✓ 0.64, juez: Parcial | Cumple [8, 9, 10] ✓ 0.84 |
| 5 | Cumple [12, 13] ✓ 0.80 | Cumple [11, 12, 13] ✓ 0.90 |
| 6 | Parcial [14] ✓ 0.63, juez: Parcial | Parcial [7] ✗ 0.70, juez: Parcial |

## e9691-9299 (E×SOP-9299, video 9691)

- **cita**: 83.33 %, conteo {'Cumple': 4, 'Parcial': 2, 'Falta': 0, 'Sobra': 4, 'zona_gris': 0}, al juez 2 ({'Cumple': 0, 'Parcial': 2, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0
- **max_si_otro_idioma**: 91.67 %, conteo {'Cumple': 5, 'Parcial': 1, 'Falta': 0, 'Sobra': 4, 'zona_gris': 0}, al juez 1 ({'Cumple': 0, 'Parcial': 1, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0

| SOP | cita | max_si_otro_idioma |
|---|---|---|
| 1 | Cumple [3] ✓ 0.81 | Cumple [3] ✓ 0.81 |
| 2 | Cumple [4] ✓ 0.81 | Cumple [4] ✓ 0.81 |
| 3 | Cumple [5, 6, 7] ✓ 0.89 | Cumple [5, 6] ✓ 0.80 |
| 4 | Parcial [10] ✓ 0.66, juez: Parcial | Cumple [8, 9, 10] ✓ 0.88 |
| 5 | Cumple [12, 13] ✓ 0.80 | Cumple [11, 12, 13] ✓ 0.92 |
| 6 | Parcial [15] ✓ 0.68, juez: Parcial | Parcial [17] ✓ 0.71, juez: Parcial |

## e8659-8158 (E×SOP-8158, video 8659)

- **cita**: 93.33 %, conteo {'Cumple': 14, 'Parcial': 0, 'Falta': 1, 'Sobra': 1, 'zona_gris': 0}, al juez 2 ({'Cumple': 2, 'Parcial': 0, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0
- **max_si_otro_idioma**: 100.0 %, conteo {'Cumple': 15, 'Parcial': 0, 'Falta': 0, 'Sobra': 0, 'zona_gris': 0}, al juez 0 ({'Cumple': 0, 'Parcial': 0, 'no_corresponde': 0, 'respaldo': 0}), rescatados 0

| SOP | cita | max_si_otro_idioma |
|---|---|---|
| 1 | Cumple [3] ✓ 0.79 | Cumple [3] ✓ 0.79 |
| 2 | Cumple [4] ✓ 0.82 | Cumple [4] ✓ 0.82 |
| 3 | Cumple [5] ✓ 0.80 | Cumple [5] ✓ 0.82 |
| 4 | Cumple [6] ✓ 0.90 | Cumple [6] ✓ 0.90 |
| 5 | Cumple [7] ✓ 0.81 | Cumple [7] ✓ 0.90 |
| 6 | Falta – ✗ – | Cumple [8] ✓ 0.76 |
| 7 | Cumple [9] ✓ 0.72, juez: Cumple | Cumple [9] ✓ 0.85 |
| 8 | Cumple [10] ✓ 0.80 | Cumple [10] ✓ 0.87 |
| 9 | Cumple [11] ✓ 0.76 | Cumple [11] ✓ 0.96 |
| 10 | Cumple [12] ✓ 0.80 | Cumple [12] ✓ 0.91 |
| 11 | Cumple [13] ✓ 0.75 | Cumple [13] ✓ 0.89 |
| 12 | Cumple [14] ✓ 0.89 | Cumple [14] ✓ 0.92 |
| 13 | Cumple [15] ✓ 0.88 | Cumple [15] ✓ 0.88 |
| 14 | Cumple [16] ✓ 0.82 | Cumple [16] ✓ 0.82 |
| 15 | Cumple [17] ✓ 0.62, juez: Cumple | Cumple [17] ✓ 0.83 |

