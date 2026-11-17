# RNF-01 a RNF-07 al cierre de S6 (16 nov 2026)

Sin mediciones nuevas: cada valor sale de un informe que ya está en el repo. Los criterios están
parafraseados del documento SOP V1.0, que no entra al repo (NDA). "Sin medir" quiere decir que
ningún informe da el número que pide el criterio.

| RNF | Criterio | Valor | ¿Cumple? | Informe |
|---|---|---|---|---|
| RNF-01 | Procesar un video de 10 min en menos de 5 min | **Con GPU:** peor caso de 2.9 min estimados para 10 min (E, 15 nov, MiniLM ya cargado); 3.4–3.9 min sumando la carga de MiniLM que paga el primer video tras arrancar (13 nov). **Sin GPU:** C tardó 422 s en el recorrido (factor 2.1, ~21 min para 10 min) | **Con GPU, sí. Sin GPU, no** | [medicion-s5-20261115-0043](emparejamiento/medicion-s5-20261115-0043.md) (tiempos) · [medicion-s5-20261113-0021](../s5/medicion-s5-20261113-0021.md) (carga de MiniLM y CPU) |
| RNF-02 | Búsqueda exacta en menos de 1 s con 50 videos | p95 de punta a punta de 19.54 ms (50 videos, 16 300 palabras) y de 32.54 ms (50 videos, 76 020 palabras) | **Sí** | [medicion-busqueda-20261115-2214](busqueda/medicion-busqueda-20261115-2214.md) |
| RNF-03 | El segundo de cada resultado y de cada enlace, a ±1 s | Búsqueda: 10 de 10 en las dos corridas. PDF: 5 QR de A contra el cronómetro a cuadro, diferencia ≤ 0.2 s | **Sí** | [medicion-busqueda-20261115-2214](busqueda/medicion-busqueda-20261115-2214.md) · [pdf/verificacion.md](pdf/verificacion.md) |
| RNF-04 | Al menos 85 % de los estados como los asigna una persona | Sin medir como porcentaje: la calibración contra la anotación a mano (`scripts/calibrar_umbrales.py`) todavía no se corre. Lo que hay: A–D dan los estados esperados de la §14 en 12/12 corridas | **Sin medir** | [medicion-s5-20261115-0043](emparejamiento/medicion-s5-20261115-0043.md) (§14, A–D) |
| RNF-05 | Al menos 80 % de los pasos del SOP generado correctos | E: 15/15 pasos (100 %) por tramos en las 3 corridas del 15 nov y en las 2 del 13 nov | **Sí, con el criterio por tramos de `medir_s5.py`** (ver nota) | [medicion-s5-20261115-0043](emparejamiento/medicion-s5-20261115-0043.md) · [medicion-s5-20261113-0021](../s5/medicion-s5-20261113-0021.md) |
| RNF-06 | No inventar: cada dato con su evidencia en el video | Sin medir como porcentaje. El código verifica cada cita contra la transcripción (regla 4). Con las imágenes **prendidas**, las descripciones inventan objetos que llegan al SOP generado sin cita (#16): la demo va con ellas apagadas | **Sin medir** (con imágenes prendidas, no cumple) | [medicion-s5-20261113-0021](../s5/medicion-s5-20261113-0021.md) (lectura y riesgos) |
| RNF-07 | El mismo video da el mismo resultado | Con la segmentación guardada, A·1 regenerado da el mismo porcentaje y la misma huella (91.67 % el 15 nov, 100 % el 13 nov). Con una segmentación nueva, A varía de 91.67 a 100 % (siempre verde y sin *Falta*), y su afinidad de 71 a 75 | **Sí, con la segmentación guardada** (ADR-022); con una nueva, no | [medicion-s5-20261115-0043](emparejamiento/medicion-s5-20261115-0043.md) · [medicion-s5-20261113-0021](../s5/medicion-s5-20261113-0021.md) |

## Notas

- **RNF-01** se mide con el tiempo que espera la persona. La extrapolación a 10 min es lineal y
  sobrestima un poco (las cargas en frío no crecen con el video). No incluye la descarga de los
  pesos en una máquina nueva: eso se mide con la prueba en máquina limpia (S7).
- **RNF-05:** el criterio por tramos de `medir_s5.py` compara cada paso del SOP generado con los
  tramos anotados de E. ADR-023 (9–10 nov) usó otra medida, contra el SOP de referencia: 50–60 %,
  porque la agrupación juntaba de más. Las dos medidas no son iguales; la de ADR-023 no se ha
  repetido desde entonces. Además, en 1 de 3 corridas del 15 nov, E falla la §14 por un valor del
  equipo de operación sin traducir, aunque su RNF-05 sea 15/15.
- **MVP al cierre** (16 nov, `f366905`, sin cambios sin commit): A 3/3 en verde sin *Falta*, B 3/3
  con *Falta* en 2 y 6 ([mvp-20261116-2156](../mvp/mvp-20261116-2156.md)). No es un RNF; es la
  regresión del camino de validación.
