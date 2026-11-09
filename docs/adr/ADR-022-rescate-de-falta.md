# ADR-022 · Rescatar un *Falta* en los fragmentos contiguos del video

- **Estado:** Propuesto (9 nov). Prototipo medido en una copia aparte; no está en `feat/s5` (el
  diff, fuera de git, en `data/interim/rescate-prototipo.patch`).
- **Fecha:** 2026-11-09
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

Con el mismo video A y el mismo SOP, el reporte salía a veces amarillo (83.33 %): el paso 6 del
SOP quedaba en *Falta*. Pasó en 2 de 6 corridas el 8 nov y en 4 de 10 en el diagnóstico del 9
nov. El criterio del MVP (plan §5.1) pide A verde y sin *Falta* en todas las corridas.

Diagnóstico (`scripts/diagnosticar_juez.py`; datos en `data/interim/juez/`, fuera de git):

1. **El juez es determinista.** Los mensajes exactos de una llamada, enviados 10 veces a Gemma
   (5 con el modelo cargado y 5 descargándolo antes), dieron 10 respuestas idénticas byte a byte.
   En 16 corridas, ninguna entrada repetida dio una salida distinta.
2. **Lo que cambia es la entrada al juez, porque la segmentación no es determinista.** Con
   temperatura 0 y `SEMILLA` fija, `segmentar` dio 9 salidas distintas en 9 llamadas con el mismo
   `Analisis` (de 14 a 17 pasos), con o sin descargar el modelo y con o sin la ficha antes. La
   explicación más probable es que, en salidas largas, las operaciones en punto flotante de la
   GPU no salen idénticas; las respuestas cortas del juez no se desvían.
3. **El amarillo sale cuando Gemma parte en fragmentos el tramo del paso 6.** "Abro la llave",
   "purgo el aire", "ya sale solo agua", "suelto el botón", "reviso la unión", "el manómetro
   marca 4 bar": ninguno, solo, se parece lo bastante al paso del SOP, y la fusión (ADR-013) no
   los une porque el paso del SOP más parecido de cada fragmento se desvía ("purgo el aire" empata
   con el paso 3, que también usa el botón rojo). Entonces:
   - el húngaro le da al paso 6 el fragmento "Con la llave de la carcasa aflojo el vaso girando a
     la izquierda" (del paso 4; coseno 0.666–0.681), y el juez, con razón, responde
     *no_corresponde* → *Falta*;
   - o le da "Purgo el aire con el botón rojo" (0.696–0.715), y el juez responde *Parcial* →
     91.67 %, verde.

   | Corrida (9 nov) | Par que llega al juez | Coseno | Narración que ve el juez | Veredicto |
   |---|---|---|---|---|
   | 4 | SOP 6 ↔ «Purgado del sistema» (112.5–115.3 s) | 0.696 | «Purgo el aire con el botón rojo. Sale aire.» | *Parcial* («omite abrir la llave y revisar fugas») |
   | 2 | SOP 6 ↔ «Desmontaje del cartucho usado» (68.5–71.5 s) | 0.674 | «Con la llave de la carcasa aflojo el vaso girando a la izquierda.» | *no_corresponde* |

## Opciones consideradas

Costos por par en la zona gris: una llamada al juez tarda ≈ 1.2 s en GPU (≈ 500 tokens de entrada
y ≈ 83 de salida, medido) y, estimado con las tasas de ADR-018 (55 tokens/s de lectura y 16 de
generación), ≈ 14 s en CPU. MiniLM corre siempre en CPU.

| Opción | Efecto sobre el caso | Costo | Veredicto |
|---|---|---|---|
| Votación de 3 llamadas del juez | Ninguno: el juez es determinista y tres llamadas con la misma entrada dan el mismo voto; con temperatura > 0 votaría sobre ruido. Además, el juez acierta con lo que recibe | +2 llamadas por par en zona gris: +2.4 s GPU, +28 s CPU | No |
| Temperatura 0 | Ya está (`llm.py`: `temperature` 0 y `SEMILLA`); no evita la variación de la segmentación | — | Ya aplicada |
| Calibrar `UMBRAL_ALTO` / `UMBRAL_BAJO` (`calibrar_umbrales.py`) | No hay umbral que dé el par correcto. Con `UMBRAL_ALTO` ≤ 0.66, el par equivocado (0.666–0.681) pasaría a *Cumple* sin juez: verde, pero con la cita de otro paso. Con `UMBRAL_BAJO` ≥ 0.69, se rompe sin juez: el mismo *Falta*. El candidato correcto (el tramo completo) no existe antes del húngaro | Ninguno en tiempo; riesgo en D y B | No resuelve |
| Votar o repetir la segmentación | Atacaría la causa, pero cuesta una segmentación más por voto y no garantiza fronteras buenas (también puede ser mala de forma estable) | +15–20 s GPU y +100 s o más CPU por segmentación | No |
| **Rescatar el *Falta* en los fragmentos contiguos** | Arma el candidato que falta (el tramo completo) solo cuando un paso del SOP queda en *Falta*, y deja que los umbrales y el juez decidan con el tramo completo | MiniLM sobre las ventanas (< 0.5 s CPU); a lo más una llamada al juez por *Falta* rescatado en zona gris (≈ 1.2 s GPU, ≈ 14 s CPU) | **Propuesta** |

## Decisión propuesta

Después del juez y antes de `orden` (`emparejar`), para cada paso del SOP en *Falta*:

1. **Anclas:** el par del paso anterior del SOP y el del siguiente (Cumple, Parcial o sin
   revisar). Se exige al menos uno: sin pares (otro procedimiento, video D) no se rescata nada.
2. **Región:** los pasos del video entre esas dos anclas (desde el principio o hasta el final si
   falta una). De ahí solo los *Sobra*, que no están en ningún par.
3. **Ventanas:** cada grupo de *Sobra* contiguos se prueba completo y por partes (todas las
   subventanas contiguas), unido como en la fusión (`_unir`). Se elige la de mayor coseno MiniLM
   con el paso del SOP.
4. **Decisión con los umbrales de siempre:** si llega a `UMBRAL_BAJO`, la ventana se une en un solo
   paso del video (con su registro `Fusion`) y se repite una vez húngaro → umbrales → juez. Así,
   con ≥ `UMBRAL_ALTO` es *Cumple*, y en la zona gris el juez decide leyendo la narración de todo
   el tramo.
5. Un fragmento rescatado no se vuelve a usar para otro *Falta*. No hay umbrales nuevos.

En la implementación final, los juicios ya hechos se reusan (misma entrada, mismo veredicto: el
juez es determinista) y solo se llama al juez para el par rescatado.

## Medición del prototipo (9 nov)

Copia aparte (`git worktree` sin rama, en `data/interim/`), con los `analisis.json` de A–D y Gemma
en la GPU.

- **Las 4 segmentaciones grabadas que dieron amarillo**, vueltas a emparejar con el rescate y el
  juez real: las 4 pasan de 83.33 % a **100 %**. El paso 6 queda *Cumple* con el tramo
  110.0–125.2 s, que empieza en el inicio anotado a mano (110.0 s). Las 6 de control no cambian.
- **Corridas completas con `validar`:**

  | Video | Corridas | Resultado | Criterio |
  |---|---|---|---|
  | A (`medir_mvp`) | 6 | 6/6 verde, 91.67–100 %, sin *Falta* | pasa |
  | B (`medir_mvp`) | 3 | 3/3: *Falta* en 2 y 6, la *Sobra* agregada; 66.67 % | pasa (sin cambios) |
  | C (`medir_afinidad`, `medir_tiempos`) | 3 + 3 | 75 %; *Fuera de orden* 2 y 5; *distinto* el 4; *excede* el 1 | pasa (sin cambios) |
  | D (`medir_afinidad`) | 3 | afinidad 19–20, detenida; al continuar, 6 *Falta* | pasa (sin cambios) |
  | A (`diagnosticar_juez`) | 10 | 10/10 al 100 %, el paso 6 *Cumple* sin juez (coseno 0.80–0.88) | pasa |

  **En ninguna de las 16 corridas completas de A se activó el rescate**: ninguna segmentación
  partió el paso 6 lo bastante para dejarlo en *Falta*, y ni siquiera hubo pares en la zona gris.
  Sin el rescate, 10 corridas iguales del mismo día dieron 6 pares en la zona gris y 4 amarillos.
  Es la variación de la segmentación, esta vez a favor: **el 16/16 en verde no prueba el rescate
  por sí solo**. Lo prueba el experimento controlado de arriba (las mismas 4 segmentaciones que
  fallaron pasan a 100 %). En B evaluó los dos *Falta* reales y no rescató ninguno: el 2 no tiene
  fragmentos entre sus anclas y para el 6 solo queda el cierre, con coseno < 0.55.

## Consecuencias

- **Positivas:** ataca la causa visible (el candidato correcto no existe) sin depender de que la
  segmentación sea estable, sin umbrales nuevos y sin llamadas extra salvo en el caso que se
  rescata. Junta en un solo paso la evidencia que hoy queda dispersa en *Sobra*, así que también
  mejora la cita y el segundo de la fila y la medida del tiempo (ADR-021).
- **Negativas / riesgos:** un *Falta* real seguido de fragmentos que se parecen al paso del SOP
  podría rescatarse por error si la ventana llega a `UMBRAL_ALTO` (sin juez); en la zona gris lo
  decide el juez con la narración completa. Requiere pruebas con un video que omita un paso con
  fragmentos parecidos alrededor. Cambia la tabla del reporte: menos *Sobra* falsos.
- **Seguimiento:** si se aprueba, implementarlo en `emparejamiento.py` con pruebas sin LLM (A
  partido, B con sus *Falta*, D sin anclas), reusar los juicios y medir A–D otra vez.

## Referencias

- ADR-010 (segmentación), ADR-012 (cascada y juez), ADR-013 (fusión; absorción pendiente),
  ADR-016 (intro y cierre), ADR-018 (CPU y GPU), ADR-021 (tiempos).
