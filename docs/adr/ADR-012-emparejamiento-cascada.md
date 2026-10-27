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
  el % de pares que irían al LLM) implementada en a027ad2. `orden` (punto 5: subsecuencia
  creciente más larga en O(n log n) sobre los Cumple y zona gris ordenados por `t_inicio`; en
  empate, la que deja fuera lo más tardío del video) y `emparejar` (fusionar → asignar →
  clasificar → orden) implementadas en f2c65bc: **la cascada completa, sin el juez Gemma 4**.
  *Fuera de orden* quedó como marca (`fuera_de_orden` con posición esperada y observada), no como
  estado, para que un paso pueda ser *Cumple* y estar fuera de orden. **Juez de la zona gris
  (punto 3), 27 oct:** `lenguaje/juez.py` (`Juez`, `JuezGemma`, `aplicar_juez`), con el prompt
  versionado en `lenguaje/prompts/juez_zona_gris_v1.md`. Recibe el paso del SOP, el del video y
  la narración de ese paso, cortada por palabra (un segmento de Whisper que cruza la frontera
  no deja entrar texto del vecino); el coseno no va en el prompt. Devuelve un `Juicio` con
  veredicto, justificación y una cita que el código verifica contra la narración (regla 4).
  Salida JSON restringida, `SEMILLA`, hasta 3 intentos ante JSON roto o cita inventada. Si no
  hay respuesta válida u Ollama no responde, el par queda en `zona_gris` con un juicio de
  respaldo y llega al reporte como "sin revisar"; si Ollama está caído, no se le vuelve a llamar
  en esa corrida. "no_corresponde" rompe el par en *Falta* + *Sobra*. `emparejar` corre `orden`
  una sola vez, después del juez, y `orden` revisa también los *Parcial*.
  `ResumenClasificacion.juez` cuenta los veredictos; `pares_llm` sigue siendo la métrica del
  paper. **Punto 4 diferido:** la revisión de EPP y puntos de validación en los pares ≥
  `UMBRAL_ALTO` (que podría bajar un *Cumple* a *Parcial*) queda fuera de 1.0 junto con RF-18
  (CLAUDE.md §4); hasta entonces, esos pares quedan *Cumple* sin LLM. Pendiente: medir el juez
  con los videos A y B y calibrar los umbrales.

## Referencias

- Documento SOP V1.0, secciones 5.3 y 19; paper DAAO (orquestación por dificultad); MiniLM
  (arXiv 2002.10957); ADR-013.
