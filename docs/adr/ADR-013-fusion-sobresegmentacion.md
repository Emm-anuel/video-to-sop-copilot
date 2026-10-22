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
las citas de ambos. Solo aplica con SOP; al generar un SOP los pasos del video se usan tal cual.

## Consecuencias

- **Positivas:** menos *Sobra* falsos sin cambiar de modelo.
- **Negativas / riesgos:** dos pasos del SOP muy parecidos y seguidos podrían fusionarse mal; se
  revisa con el video C.
- **Seguimiento:** medir *Sobra* falsos con y sin fusión en los videos A–D.
  `fusionar` implementada en 972abc6, con el umbral en la configuración (`UMBRAL_FUSION`) y el
  registro `Fusion` (números originales, paso del SOP, citas y cosenos) para el reporte y el paper.

## Referencias

- ADR-010 (resultados de la Fase 4), ADR-012, documento SOP V1.0 sección 14.
