# ADR-022 · Rescatar un *Falta* en los fragmentos contiguos del video

- **Estado:** Aprobado por el equipo (9 nov), con tres condiciones (sección "Decisión").
  Implementado en `lenguaje/emparejamiento.py` (`rescatar`).
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
| **Rescatar el *Falta* en los fragmentos contiguos** | Arma el candidato que falta (el tramo completo) solo cuando un paso del SOP queda en *Falta*, y el juez decide con la narración de todo el tramo | MiniLM sobre las ventanas (< 0.5 s CPU); una llamada al juez por cada ventana que llega a `UMBRAL_ALTO` (≈ 1.2 s GPU, ≈ 14 s CPU) | **Elegida** |

## Decisión

Aprobada el 9 nov con tres condiciones: (a) todo par rescatado pasa por el juez, aunque el
coseno llegue a `UMBRAL_ALTO`; (b) las segmentaciones que dieron amarillo quedan como fixtures de
regresión sin LLM, más una prueba adversaria; (c) el reporte marca el paso rescatado.

`rescatar` (`lenguaje/emparejamiento.py`) corre en `emparejar` después del juez y antes de
`orden`, solo si hay juez. Para cada paso del SOP en *Falta*:

1. **Anclas:** el par del paso anterior del SOP y el del siguiente (Cumple, Parcial o sin
   revisar). Se exige al menos uno: sin pares (otro procedimiento, video D) no se rescata nada.
2. **Región:** los pasos del video entre esas dos anclas (desde el principio o hasta el final si
   falta una). De ahí solo los *Sobra* no usados en otro rescate.
3. **Ventanas:** cada subventana de *Sobra* contiguos, unida como en la fusión (`_unir`, con el
   original más parecido al paso del SOP como representante). Gana la de mayor coseno MiniLM.
4. **Evidencia fuerte y juez:** solo una ventana con coseno ≥ `UMBRAL_ALTO` va al juez (condición
   a), con la narración de toda la ventana. *Cumple* o *Parcial* la rescatan; *no_corresponde* la
   descarta y el paso sigue en *Falta*. Si Ollama no responde, el par queda sin revisar
   (zona_gris) y el reporte, provisional (ADR-019). Una ventana en la zona gris **no** se rescata:
   en la prueba adversaria es justo lo que separa "purgo el aire" (parecido, pero incompleto) del
   paso entero. Esto endurece la propuesta del prototipo, que rescataba desde `UMBRAL_BAJO`: el
   juez real califica *Parcial* un fragmento como "purgo el aire con el botón rojo", porque purgar
   es parte del paso 6.
5. **Sin volver a emparejar:** la ventana se une en un solo paso del video y solo cambian esa fila
   y esos *Sobra*. Los demás pares y sus juicios se conservan; el juez solo se llama para la
   ventana.
6. **Marcas (condición c):** `Fusion.rescate`, `FilaReporte.rescatado` y
   `ResumenClasificacion.rescatados`. Cada llamada del rescate suma 1 a `pares`, a `pares_llm` y
   al veredicto en `resumen.juez`, aunque el juez la rechace.

No hay umbrales nuevos. Pruebas: `tests/test_rescate.py` (lógica, con un vectorizador por
palabras clave y un juez guionado) y `tests/test_rescate_fixtures.py` (condición b): las 4
segmentaciones reales de A que dieron amarillo y el caso adversario, con los vectores de MiniLM y
los juicios de Gemma grabados en `tests/fixtures/rescate.json` (`scripts/grabar_rescate.py`).

- **Las 4 de A** pasan de 83.33 % a **91.67 % (verde)**. El paso 6 queda *Parcial*, con el
  tramo 110.0–125.2 s (cinco fragmentos, coseno 0.87–0.92), que empieza en el inicio anotado
  a mano. El juez: "abrió la llave, purgó
  el aire y revisó la unión con toalla; omite la validación del manómetro en 4 bar". La ventana
  de mayor coseno deja fuera el fragmento "el manómetro marca 4 bar", que sí se dijo. Elegir la
  ventana más larga sobre `UMBRAL_ALTO` lo incluiría, pero podría tragarse fragmentos de otro
  paso; se queda el criterio conservador.
- **Adversario:** B (omite los pasos 2 y 6) con "purgo el aire", "ya sale solo agua" y "suelto el
  botón" de A insertados después del paso 5. La mejor ventana para el paso 6 queda bajo
  `UMBRAL_ALTO`: no va al juez y el paso 6 sigue en *Falta* (66.67 %, *Falta* en 2 y 6).

## Riesgo para RNF-07 (mismo porcentaje en dos corridas)

El plan (§7) cubre RNF-07 con "temperatura 0, semilla 42, versiones fijadas". No alcanza: la
segmentación de Gemma no es determinista ni con eso (9 salidas distintas en 9 llamadas), y el
porcentaje de A varió entre 83.33, 91.67 y 100 % en el mismo equipo. El rescate quita el caso que
lo bajaba a amarillo, pero dos corridas pueden seguir dando 91.67 y 100 %. MiniLM corre en CPU y
da lo mismo; el juez, con la misma entrada, dio el mismo veredicto en todas las comparaciones (su
redacción no siempre, ver abajo).

**Implementado el 9 nov (decisión del equipo):**

1. `videos.pasos_video` guarda la segmentación completa (`SegmentacionGuardada`: pasos antes de
   fusionar, método y modelo). Las filas anteriores (una lista sin método) no se reusan.
2. Repetir la validación (`POST /videos/{id}/validar`, ADR-019) la reusa en lugar de volver a
   llamar a Gemma; `?segmentar=true` la vuelve a pedir. Una de la heurística de respaldo o con
   pasos sin redactar se vuelve a pedir siempre (para eso existe ADR-019). El reporte lo marca en
   `metadatos.segmentacion_reusada`.
3. RNF-07 se mide en dos niveles (`scripts/medir_reproducibilidad.py`; resultados en ADR-018,
   seguimiento del 9 nov):
   - **Reproducibilidad del reporte:** de cada validación, dos regeneraciones con su segmentación
     y su ficha. El porcentaje fue el de la original en las 30 regeneraciones. Las dos
     regeneraciones salieron idénticas entre sí en A 6/6, B 3/3, C 3/3 y D 2/3.
   - **Estabilidad del análisis:** con segmentación nueva, A da 91.67–100 % (verde 6/6); B, C y D,
     un solo valor.

**Hallazgo: la redacción del juez no es determinista aunque la entrada sea la misma.** En D, dos
regeneraciones (mismos pasos, misma narración, la misma secuencia de llamadas tras cargar el
modelo) dieron dos justificaciones distintas para el mismo par, con el mismo veredicto. Y entre la
validación original y su regeneración cambió la justificación del paso 6 de A, con el mismo
veredicto: en la original, el juez corre después de la ficha y la segmentación en la misma carga de
Gemma. La prueba del 9 nov (10 llamadas idénticas, 10 respuestas iguales) era una sola llamada
corta repetida; con varias llamadas seguidas no se sostiene. No se vio cambiar un veredicto, pero
no está garantizado.

**Siguiente propuesta (sin implementar; requiere decisión):** guardar también los juicios de la
validación y, al regenerar con la misma segmentación, reusar el juicio de cada par cuya entrada no
cambió, en lugar de volver a llamar al juez. Así el reporte regenerado saldría idéntico, y RNF-07
quedaría atado solo a la segmentación (que se guarda) y a MiniLM (determinista en CPU).

## Medición con A–D (9 nov)

Código de `feat/s5` (commit del rescate), Gemma 4 en la GPU, los `analisis.json` de cada video
(Whisper `large-v3-turbo`).

| Video | Script | Corridas | Resultado | Criterio |
|---|---|---|---|---|
| A | `medir_mvp` ([datos](datos/mvp/mvp-20261109-0101.md)) | 6 | 6/6 verde (91.67–100 %), sin *Falta* | pasa |
| A | `medir_tiempos` | 3 | 91.67 / 100 / 91.67 %, verde | — |
| B | `medir_mvp` ([datos](datos/mvp/mvp-20261109-0104.md)) | 3 | 3/3: *Falta* exactamente en 2 y 6, la *Sobra* agregada; 66.67 % | pasa (sin cambios) |
| C | `medir_afinidad` ([datos](datos/afinidad/afinidad-20261109-0108.md)) | 3 | afinidad 97; *Fuera de orden* 2 y 5; *distinto* el 4; 75 % | pasa (sin cambios) |
| C | `medir_tiempos` ([datos](datos/tiempos/tiempos-20261109-0111.md)) | 3 | *excede* solo el paso 1; 75–83.33 % | pasa (sin cambios) |
| D | `medir_afinidad` | 3 | afinidad 19–20, detenida; al continuar, 6 *Falta* | pasa (sin cambios) |

- **Meta cumplida: A 6/6 en verde** con `medir_mvp` (y 3/3 más con `medir_tiempos`), sin empeorar
  B, C ni D.
- **Pero el rescate no se activó en ninguna de las 24 corridas completas** (no hay una sola línea
  "Rescate de Falta" en el log): en ninguna Gemma dejó el paso 6 en *Falta*. El verde de hoy no
  prueba el rescate por sí solo, igual que en el prototipo. Lo prueba la regresión con las 4
  segmentaciones reales que sí dejaban el paso 6 en *Falta* (`tests/test_rescate_fixtures.py`):
  pasan de 83.33 % a 91.67 %, y el adversario sigue en *Falta*.
- El rescate no tocó B ni D: los *Falta* reales de B no tienen una ventana que llegue a
  `UMBRAL_ALTO`, y D no tiene anclas.

### Prototipo (antes de las condiciones)

Copia aparte (`git worktree` sin rama, en `data/interim/`), con el rescate desde `UMBRAL_BAJO` y
repitiendo húngaro → juez: las 4 segmentaciones que dieron amarillo pasaban a 100 % (el paso 6
*Cumple* sin juez). Con `validar`: A 6/6 y 10/10 en verde, B 3/3, C 3/3 y D 3/3 sin cambios. En
esas 16 corridas de A el rescate no se activó (Gemma no partió el paso 6); el 16/16 no probaba el
rescate por sí solo.

## Consecuencias

- **Positivas:** ataca la causa visible (el candidato correcto no existe) sin depender de que la
  segmentación sea estable, sin umbrales nuevos y con una sola llamada extra al juez, solo cuando
  hay qué rescatar (≈ 1.2 s en GPU, ≈ 14 s en CPU). Junta en un solo paso la evidencia que quedaba
  dispersa en *Sobra*: mejora la cita, el segundo y la medida del tiempo de la fila (ADR-021), y
  quita *Sobra* falsos de la tabla.
- **Negativas / riesgos:** un *Falta* real con fragmentos muy parecidos al paso completo
  (coseno ≥ `UMBRAL_ALTO`) depende del juez para no rescatarse. La ventana de mayor coseno puede
  dejar fuera un fragmento final del paso (el manómetro en A), y el juez da *Parcial*. RNF-07 sigue
  en riesgo por la segmentación (sección anterior).
- **Seguimiento:** reusar los juicios al regenerar (sección RNF-07); un video que omita un paso con
  fragmentos casi completos alrededor, para probar al juez en ese borde.

## Referencias

- ADR-010 (segmentación), ADR-012 (cascada y juez), ADR-013 (fusión; absorción pendiente),
  ADR-016 (intro y cierre), ADR-018 (CPU y GPU), ADR-021 (tiempos).
