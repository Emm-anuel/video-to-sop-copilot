# ADR-026 · Texto vectorizado del paso del video: la cita en otro idioma solo puede ayudar

- **Estado:** Propuesto
- **Fecha:** 2026-11-15
- **Autores:** Emmanuel Merida
- **Decisores:** equipo
- **Issue:** #11

---

## Contexto

Desde ADR-012 (27 oct), el paso del video se vectoriza con MiniLM como "nombre. descripción.
cita". La cita entró por una razón medida: en A, "me pongo los guantes de nitrilo" quedaba en la
descripción como "equipo de protección personal" y el par caía a 0.52; con la cita, 0.86.

En E (narrado en inglés por el equipo, con pronunciación no nativa), la cita hunde el coseno. El
paso 6 del SOP generado desde E (SOP-8158, "Retirar carcasa con llave") contra el paso del video
que lo narra (video 8659) da **0.755 sin la cita y 0.307 con ella**. El par pasa de aceptado sin
LLM a sin pareja y fabrica un *Falta* y un *Sobra*. Ocurre en el caso más favorable (el video
contra su propio SOP) y saldría en cualquier demo con un video en inglés.

Dos causas posibles, con arreglos distintos: el **ruido de Whisper** (en E, "wrench" → "grant",
"bowl" → "bolt", "purge" → "pour"; lista en `media/anotacion_ab.json`) o el **idioma** (MiniLM
multilingüe castiga una frase en inglés frente a un SOP en español aunque diga lo mismo).

## Control de causa: es el idioma, no el ruido

`tests/fixtures/emparejamiento_e.json` (del equipo): por cada par, la cita de Whisper, la misma
frase corregida según el guion de E, y la traducción al español escrita a mano de cada una.
Coseno del paso del SOP contra el paso del video (MiniLM real):

| Par | sin cita | cita de Whisper | corregida (inglés) | Whisper traducida (es) | corregida (es) |
|---|---|---|---|---|---|
| e6: SOP-8158 paso 6 | 0.755 | **0.307** | 0.513 | **0.741** | 0.798 |
| e6 contra el SOP de referencia (paso 4) | 0.582 | 0.314 | 0.429 | 0.587 | 0.660 |
| e9: Whisper sin ningún error | 0.959 | 0.757 | 0.757 | 0.952 | 0.952 |
| e11 | 0.893 | 0.753 | 0.697 | 0.871 | 0.825 |
| e15 | 0.833 | 0.617 | 0.624 | 0.850 | 0.843 |

- Corregir el inglés a mano deja el paso 6 en 0.51, lejos de 0.755.
- Traducir al español la misma cita, con los errores de Whisper, lo sube a 0.74.
- En e9 no hay ningún error de transcripción y la cita en inglés le quita 0.20.

El ruido pesa algo (+0.21 en e6 en inglés; ≤ +0.06 en los demás), pero la causa principal es el
idioma. Por eso vale una variante que dependa del idioma.

## Opciones consideradas

Medición sin LLM (`scripts/diagnosticar_emparejamiento.py --variantes-texto`; datos en
[`datos/s6/emparejamiento/variantes_texto.md`](datos/s6/emparejamiento/variantes_texto.md)).
Cascada sin juez (fusión → húngaro → umbrales → orden → marco) con 64 segmentaciones guardadas en
la base (`videos.pasos_video`, ADR-022). Así todas las variantes ven exactamente los mismos pasos:

- A × referencia: 11 segmentaciones.
- B × referencia: 7, todas en el formato anterior a ADR-022 (lista sin método); se usan igual.
- C × referencia: 8; D × referencia: 3.
- E: 6 segmentaciones, cada una contra 4 SOP (la referencia y los SOP generados desde E 8158,
  9299 y 6314).
- Uso cruzado de ADR-023: A × SOP-6314, 11 segmentaciones.

En cada caso, la cascada del script reproduce `emparejar(juez=None)` con la variante a, y
`emparejar` de producción con la f.

Verdad: la anotación a mano. Por paso del SOP, **bien** (aceptado con el par correcto, o sin
pareja y ausente de verdad), **juez** (zona gris con el par correcto), **juez✗** (zona gris con un
par equivocado) o **mal**. "Graves" son los pasos que bajan de rango respecto de la variante
actual (a); "mejoras", los que suben.

| Variante | Graves A–D | Pares al juez A–D | Graves / mejoras E | Pares al juez E | Paso 6 de #11 | Graves A × SOP-6314 |
|---|---|---|---|---|---|---|
| a · nombre + descripción + cita (actual) | 0 | 34 | 0 / 0 | 73 | sin pareja (Falta + Sobra) | 0 |
| b · sin cita | 29 | 56 | 11 / 62 | 33 | aceptado 0.755 | 31 |
| c · vector 0.80·sin + 0.20·cita | 11 | 44 | 8 / 68 | 34 | gris 0.73 | 14 |
| c · 0.65 / 0.35 | 4 | 37 | 4 / 72 | 26 | gris 0.69 | 9 |
| c · 0.50 / 0.50 | 6 | 39 | 0 / 68 | 26 | gris 0.62 | 3 |
| d · cita solo si el idioma coincide | 0 | 34 | 11 / 62 | 33 | aceptado 0.755 | 0 |
| e · max(con cita, sin cita) | 2 | 35 | 2 / 62 | 27 | aceptado 0.755 | 5 |
| **f · e si el idioma difiere; si no, a** | **0** | **34** | **2 / 62** | **27** | **aceptado 0.755** | **0** |

- **b** confirma la razón de ADR-012: sin la cita, A, B y C empeoran (29 pasos).
- **c** no resuelve el paso 6 (queda en zona gris) y daña A o D con cualquier peso.
- **d** pierde en E el paso de los guantes ("nitrile" → "nutrient"): en 2 de 6 segmentaciones de E
  contra la referencia, el paso 1 cae de 0.79 / 0.72 a 0.51 y queda *Falta*. Es justo el caso de
  ADR-012, en inglés, y la cita lo salvaba.
- **e** manda al juez 2 pares equivocados de D (otro procedimiento) y en el uso cruzado sube 8
  pares equivocados a gris o aceptado. Ahí la cita está en el mismo idioma: el máximo no tiene
  por qué ayudar.
- **f** (armada al ver la tabla) toma de e lo que ayuda: el máximo solo cuando el idioma de la
  transcripción no es el del SOP.

## Decisión

**f**, con el Setting `EMPAREJAR_TEXTO` (RNF-14):

- `max_si_otro_idioma` (por defecto): si el idioma de la transcripción (`Analisis.idioma`) no es
  `SOP_IDIOMA`, cada par toma el mayor coseno entre el paso del video con su cita y sin ella. La
  cita en otro idioma solo puede ayudar. En el mismo idioma, o sin idioma, el cálculo es
  exactamente el de `cita`: mismos textos a MiniLM, mismos vectores, mismo resultado.
- `cita`: "nombre. descripción. cita" siempre, como desde ADR-012. Queda de respaldo.

`SOP_IDIOMA=es` (Setting, no constante). En 1.0 los SOP del patrocinador son en español y
traducir el SOP está fuera de alcance (CLAUDE.md §4). Se compara solo el idioma, sin la región
(`es-MX` = `es`).

El máximo se aplica en los tres sitios donde se vectoriza el paso del video: la fusión (ADR-013),
la asignación y el rescate (ADR-022: representante y ventana). La cita que llega al reporte no
cambia: sigue siendo la de Whisper, en el idioma original (regla 4). Solo cambia qué se compara.
Los umbrales no se tocan.

Implementación: `lenguaje/emparejamiento.py` (`cita_en_otro_idioma`, `texto_sin_cita`;
`emparejar`, `fusionar` y `EmparejadorMiniLM` reciben `idioma`); `lenguaje/validacion.py` pasa
`analisis.idioma.codigo`.

## Riesgos

1. **Margen mínimo en el paso 6.** Queda aceptado con **0.755**, a 0.005 de `UMBRAL_ALTO`. Si un
   día baja a la zona gris no se rompe nada: lo decide el juez con el par correcto. **No se mueve
   el umbral por eso.**
2. **SOP-9299 (editado a 6 pasos, #14): evidencia del paso 6 en otro tramo.** En 2 de 6
   segmentaciones (videos 8658 y 9689), con f el par del paso 6 en zona gris deja de ser el
   correcto ("Apertura lenta de la válvula", 188 s) y pasa a ser la despresurización ("I press and
   hold the red button…", 118 s), que corresponde al paso 3 de la referencia. El paso 6 editado
   junta cuatro pasos generados e incluye "Verter el aire con el botón rojo" (el "purge → pour" de
   Whisper hecho texto del SOP). Además, con f ese fragmento ya no se fusiona con el paso 3 del
   SOP. **El juez real (Gemma 4, GPU) no lo rompe en ninguno de los 2 casos**: responde *Parcial*
   ("presiona el botón rojo para liberar aire… omite la verificación de fugas"), igual que daba
   *Parcial* con el par correcto. El estado y el porcentaje del paso 6 no cambian, y el reporte
   sube de 75 / 83.33 % a 91.67 %. Pero **la cita y el segundo del paso 6 salen de otro tramo**
   (2 de 2 juicios). En la segmentación del recorrido (video 9691) el par sigue siendo el correcto
   (datos en [`variantes_texto_juez.md`](datos/s6/emparejamiento/variantes_texto_juez.md)).
3. **La fusión cambia en E.** Con f se unen más fragmentos (en las 6 segmentaciones de E contra la
   referencia y contra SOP-9299); en A–D, ninguna fusión cambia.
4. **`SOP_IDIOMA` fijo.** Un SOP cargado en otro idioma necesitaría su propio idioma (el SOP no
   lo guarda). Además, si Whisper detecta mal el idioma de un video en español, se aplicaría el
   máximo, que en el mismo idioma sube pares equivocados (variante e, uso cruzado).
5. **Solo con videos del equipo.** Un solo video en otro idioma (E) y un solo narrador no nativo.

## Consecuencias

- **Positivas:** el caso de #11 deja de fabricar el *Falta* y el *Sobra* (E × SOP-8158: 100 %, sin
  juez; antes 93.33 % con 2 pares al juez). E manda al juez 27 pares en lugar de 73 en las 24
  combinaciones medidas. A–D, en español, no cambian ni en un bit (pruebas
  `tests/test_emparejar_texto.py` y `tests/test_rescate_fixtures.py`).
- **Negativas:** los riesgos de arriba; en especial, la evidencia del paso 6 de SOP-9299.
- **Seguimiento:**
  - Regresión con el procesador completo (abajo).
  - Otro video en otro idioma, con otro narrador, antes de cerrar el ADR.
  - El riesgo 2 se revisa junto con #14 (el SOP editado).

## Alternativa para S7 (sin implementar): traducir la cita

Traducir la cita al idioma del SOP solo para vectorizarla subiría el paso 6 a 0.74 (control de
causa) y sería más robusto que el máximo: también arreglaría pares donde ni el texto con cita ni
el sin cita llegan. Costo: una llamada más a Gemma por paso del video (o por lote), con su tiempo
en CPU (ADR-018) y sin ser determinista (ADR-022). La cita del reporte seguiría siendo la
original (regla 4).

## Regresión con el procesador completo

Con `EMPAREJAR_TEXTO=max_si_otro_idioma`, GPU (RTX 2070 SUPER), 15 nov:

- **MVP** ([`mvp-20261115-0020.md`](datos/s6/emparejamiento/mvp-20261115-0020.md), A y B ×3):
  pasa 6/6. A: 100 / 91.67 / 100 %, verde y sin *Falta*. B: 66.67 % ×3, *Falta* en 2 y 6 y el
  *Sobra* de la limpieza.
- **§14** ([`medicion-s5-20261115-0043.md`](datos/s6/emparejamiento/medicion-s5-20261115-0043.md),
  tres tandas intercaladas con la GPU enfriada 4 min y a ≤ 50 °C):
  - A–D: 12/12. A da 91.67 / 100 / 91.67 %, dentro de la variación de la segmentación de Gemma
    ya medida (ADR-022); A–D están en español y siguen exactamente el camino de `cita`.
  - E (modo generar): 2/3. La corrida 1 falla por `sin_traducir` (Gemma dejó en inglés un valor
    del equipo de operación); RNF-05 fue 15/15 en las tres. El modo generar no pasa por el
    emparejamiento que cambia este ADR: es la falla ya vista el 12 nov con la narración mal
    transcrita (ADR-024).
  - RNF-01 se cumple (peor caso 2.9 min estimados para 10 min); RNF-07 se reproduce (A·1
    regenerado: mismo porcentaje y huella).
- **Juez real en los casos de E** ([`variantes_texto_juez.md`](datos/s6/emparejamiento/variantes_texto_juez.md)):
  - E × SOP-8158 (#11): 93.33 % → 100 %, sin *Falta* ni *Sobra*, 0 pares al juez (antes 2).
  - E × SOP-9299, segmentaciones 8658 / 9689 / 9691: 75 / 83.33 / 83.33 % → 91.67 % ×3. El
    riesgo 2 está en las dos primeras.

## Referencias

- #11, #14; ADR-012 (cascada y cita en el texto), ADR-013 (fusión), ADR-016 (marco), ADR-018
  (CPU/GPU), ADR-022 (rescate y segmentación guardada), ADR-023 (SOP generado, uso cruzado).
- Datos: [`variantes_texto.md`](datos/s6/emparejamiento/variantes_texto.md),
  [`variantes_texto_juez.md`](datos/s6/emparejamiento/variantes_texto_juez.md).
