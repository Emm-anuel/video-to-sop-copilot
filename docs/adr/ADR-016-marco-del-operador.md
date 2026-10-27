# ADR-016 · Marcar la intro y el cierre del operador en vez de contarlos como Sobra

- **Estado:** Aprobado por el equipo; falta confirmar con el patrocinador cómo se muestran
- **Fecha:** 2026-10-27
- **Autores:** Emmanuel Merida
- **Decisores:** equipo; el patrocinador confirma la presentación en el reporte

---

## Contexto

El operador abre y cierra su narración con frases que no son pasos del procedimiento ("el
manómetro marca menos de 2 bar, así que toca cambiarlo", "Listo"). Gemma 4 las extrae como pasos
del video (RF-13, sin ver el SOP) y, como no emparejan con ningún paso del SOP, salen como *Sobra*.

El diagnóstico de los videos A y B (`scripts/diagnosticar_emparejamiento.py`, 27 oct) lo midió:

- En A, 2 de los 5 *Sobra* son el marco del operador: la intro (00:01.4) y el paso final
  (02:05.5), que termina en el cierre anotado.
- En B, con el juez, salen Falta 2 y 6 (lo esperado) y dos *Sobra*: la intro (00:03.5) y "limpiar
  la carcasa" (01:14.1), que es el *Sobra* real del guion. El criterio del MVP pide exactamente
  1 *Sobra* (plan §5.1).

Un *Sobra* real puede caer en cualquier parte del video, así que la regla no puede depender solo
de la posición sin dejar rastro: si se equivoca, el paso tiene que seguir a la vista.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Marca con código tras emparejar: un *Sobra* que empieza antes del primer paso emparejado o después del último lleva `marco_operador` ("intro" o "cierre") y no cuenta como *Sobra* | Determinista, sin LLM ni volver a segmentar; arregla A y B (medido); el paso sigue en el resultado con su cita y su segundo | Un paso extra real al principio o al final queda marcado como marco |
| B · Que Gemma 4 marque la intro y el cierre al segmentar (ADR-010) | Usa el contenido, no la posición | Cambia el prompt y obliga a volver a segmentar y a medir ADR-010; sin medición todavía |
| C · Borrar esos pasos | El reporte queda limpio | Pierde evidencia; un error no se puede revisar (ADR-008) |

## Decisión

**A.** Después de emparejar, del juez y del orden, `marcar_marco` revisa los *Sobra*: el que empieza
antes del primer paso emparejado (Cumple, Parcial o zona_gris) lleva `marco_operador = "intro"`, y
el que empieza después del último, `"cierre"`. Siguen en la clasificación como *Sobra*, con su
cita, su segundo y su confianza, pero no cuentan en `conteo["Sobra"]`: el resumen los cuenta
aparte (`ResumenClasificacion.marco_operador`). Sin ningún paso emparejado no se marca nada. La
marca se recalcula desde cero, como `orden`.

## Consecuencias

- **Positivas:** con el juez y el texto con cita (ADR-012), B da 2 *Falta* y 1 *Sobra* y A queda
  en 100 % sin *Falta*; ninguna intro ni cierre se pierde.
- **Negativas / riesgos:** un paso extra real hecho antes del primer paso del SOP o después del
  último se marca como intro o cierre y deja de contar como *Sobra*. Por eso es una marca y no un
  borrado: el reporte lo muestra con su cita y su segundo.
- **Pendiente:** confirmar con el patrocinador si la intro y el cierre deben aparecer en el
  reporte (aparte, como "marco del operador") o ignorarse. La marca permite las dos: el reporte
  decide si los lista o los filtra, sin cambiar el emparejamiento.
- **Seguimiento:** revisar con los videos C–E que ningún *Sobra* real quede marcado; si pasa,
  evaluar la opción B.

## Referencias

- ADR-008 (revisión humana), ADR-010 (pasos del video), ADR-012 (cascada y texto con cita),
  ADR-013 (fusión); plan §5.1 (criterio del MVP) y §7 (videos de prueba).
