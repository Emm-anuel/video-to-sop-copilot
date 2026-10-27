# ADR-013 · Fusionar pasos consecutivos del video antes de emparejar

- **Estado:** Propuesto
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

En ADR-010, `gemma4:e4b-it-q4_K_M` propuso 21 pasos de más sobre 30 reales (F1 0.74); casi no omitió
pasos. En la validación, cada paso de más del video que no empareja saldría como *Sobra*, y el video B
de prueba exige exactamente un *Sobra*.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Cambiar a `qwen3.5:9b` | Casi sin pasos de más | No es Gemma 4 (NDA cl. 1): requiere aprobación escrita |
| B · Ajustar el prompt | Sin código extra | El prompt v2 de ADR-010 no redujo los falsos positivos |
| C · Fusionar pasos consecutivos que caen en el mismo paso del SOP | Corrige el error más frecuente con código determinista | Puede unir dos pasos reales parecidos |

## Decisión

**C.** Antes del algoritmo húngaro (ADR-012), los pasos consecutivos del video cuyo paso del SOP más
parecido es el mismo, con parecido ≥ 0.55, se unen en uno: el inicio del primero, el fin del último y
la cita y el responsable del original más parecido a ese paso del SOP, para que la cita siga
apareciendo tal cual en la transcripción (regla 4 de CLAUDE.md). Las citas de todos los originales,
y los responsables si no coinciden, quedan en el registro de la fusión. Solo aplica con SOP; al
generar un SOP los pasos del video se usan tal cual.

## Consecuencias

- **Positivas:** menos *Sobra* falsos sin cambiar de modelo.
- **Negativas / riesgos:** dos pasos del SOP muy parecidos y seguidos podrían fusionarse mal; se
  revisa con el video C.
- **Seguimiento:** medir *Sobra* falsos con y sin fusión en los videos A–D.
  `fusionar` implementada en 972abc6, con el umbral en la configuración (`UMBRAL_FUSION`) y el
  registro `Fusion` (números originales, paso del SOP, citas y cosenos) para el reporte y el paper.
  Después se ajustó para no unir citas ni responsables: el paso fusionado conserva los del original
  más parecido y `Fusion.responsables_distintos` guarda los que no coinciden.
- **Pendiente: absorber fragmentos (27 oct, no implementado).** El diagnóstico de A y B
  (`scripts/diagnosticar_emparejamiento.py`) dejó en A cuatro *Sobra* que son fragmentos de un
  paso cuyo mejor paso del SOP se desvía, así que esta fusión (mismo mejor paso del SOP) no los
  une: 7 "Ahora retiro la carcasa" y 8 "aflojo el vaso" (tramo de SOP 4; mejores SOP 2 y 5), y
  con el texto con cita de ADR-012, 11 "abro la llave de paso" y 12 "purgo el aire" (tramo de
  SOP 6; 12 empata en 0.72 entre SOP 3 y SOP 6). No bajan el porcentaje (los *Sobra* no restan),
  pero retrasan la evidencia: SOP 3 sale en 00:54.2 y la anotación dice 00:49.2; SOP 4 en
  01:12.1 contra 01:06.9; y SOP 6, desde el texto con cita, en 01:55.8 contra 01:50.0 (antes,
  con 11–14 fusionados, caía en 01:50.0). Se evaluó a mano, sobre la matriz de cosenos y sin
  correr `emparejar`, una regla de absorción: un *Sobra* se une al paso emparejado vecino si la
  pausa es ≤ 1.5 s y su coseno con el paso del SOP de ese vecino pasa un umbral.
  - Umbral 0.55: absorbe A 8, 11 y 12, pero también el *Sobra* real de B ("limpiar la carcasa",
    a 0.3 s de "coloco el cartucho nuevo", 0.63 con SOP 5).
  - Umbral 0.65: salva el de B por 0.02 (0.63), un margen calibrado sobre dos videos.
  - A 7 (0.50 con SOP 4) no se absorbe con ningún umbral que salve a B.

  Alternativa sin medir: que el juez de ADR-012 decida si un fragmento es parte del paso
  vecino (más llamadas a Gemma 4; requiere ADR). **Se retoma con los videos C–E.**

## Referencias

- ADR-010 (resultados de la Fase 4), ADR-012, documento SOP V1.0 sección 14.
