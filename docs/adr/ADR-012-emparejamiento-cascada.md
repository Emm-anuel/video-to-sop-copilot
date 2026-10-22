# ADR-012 · Emparejar pasos con una cascada MiniLM → Gemma 4

- **Estado:** Propuesto
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

La validación contra un SOP (RF-14) empareja los pasos del SOP con los pasos extraídos del video y
clasifica cada uno como *Cumple*, *Parcial*, *Falta*, *Sobra* o *Fuera de orden*. La referencia del
documento pide que lo haga GPT-4o-mini; con costo cero, el LLM local es más lento y menos confiable. El
documento sugiere MiniLM multilingüe para emparejar y el algoritmo húngaro con la subsecuencia
creciente más larga (sección 19). La meta es RNF-04: al menos 85 % de los estados como los asigna una
persona.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Solo MiniLM + húngaro | Milisegundos; determinista | No distingue *Cumple* de *Parcial* |
| B · Gemma 4 como juez de todos los pares | Entiende matices | Lento con muchos pasos; menos reproducible |
| C · Cascada: MiniLM decide lo claro, Gemma 4 solo la zona gris | Rápida y reproducible donde se puede; LLM donde hace falta | Dos umbrales que calibrar |

## Decisión

**C.**

1. Parecido coseno MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`) entre nombre y descripción de cada
   paso del SOP y del video; el algoritmo húngaro elige la asignación.
2. Parecido < 0.55: sin pareja (*Falta* en el SOP, *Sobra* en el video), sin LLM.
3. De 0.55 a 0.75: Gemma 4 decide *Cumple*, *Parcial* o no corresponde, con justificación y cita.
4. ≥ 0.75: pareja aceptada; Gemma 4 solo revisa si falta un punto de validación o EPP (*Parcial*).
5. El orden se revisa con código: la subsecuencia creciente más larga queda en orden; el resto, *Fuera
   de orden*.

Los umbrales viven en la configuración (RNF-14).

## Consecuencias

- **Positivas:** la mayoría de los pares se resuelve sin LLM; es el experimento central del paper.
- **Negativas / riesgos:** umbrales mal calibrados mueven pares a la categoría equivocada.
- **Seguimiento:** calibrar con los videos A–D anotados a mano; comparar A, B y C en el paper.
  Base S2 (`Embedder`, `similitud`) implementada en ca82b10; cascada completa en S3–S4.
  `asignar` (húngaro con `maximize=True`; en empate, la asignación más cercana al orden, la de
  menor suma de (i − j)²) implementada en 83793f3. `clasificar` (puntos 2–4 sin LLM: bajo
  `UMBRAL_BAJO` el par se rompe en *Falta* + *Sobra*; la zona gris queda marcada como estado
  interno `zona_gris` para el juez de S4; desde `UMBRAL_ALTO`, *Cumple* provisional; resumen con
  el % de pares que irían al LLM) implementada en a027ad2.

## Referencias

- Documento SOP V1.0, secciones 5.3 y 19; paper DAAO (orquestación por dificultad); MiniLM
  (arXiv 2002.10957); ADR-013.
