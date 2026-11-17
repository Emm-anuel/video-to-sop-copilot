# Variantes del texto vectorizado del paso del video (#11)

`scripts/diagnosticar_emparejamiento.py --variantes-texto`. Cascada sin juez (fusión → húngaro → umbrales → orden → marco) con las segmentaciones guardadas en la base (`videos.pasos_video`, ADR-022): todas las variantes ven los mismos pasos; solo MiniLM y código, sin Gemma. Autocomprobación: la variante a reproduce `emparejar(juez=None)` y la b, `emparejar` con el texto sin cita, en cada caso.

- Commit `f8edb228d9866b93fbb79ee0215b0591805ed52c` en `feat/s6` · cambios sin commit: 7
- Embedder `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` · umbrales 0.55 / 0.75 · fusión 0.55 · idioma del SOP para la variante d: `es`
- Verdad: el tramo anotado a mano (`media/anotacion_ab.json`) con el que más se encima cada paso del video; en un SOP generado, el tramo del punto medio de cada paso en el video de origen y, si es la misma grabación, además encimarse en el tiempo.
- Etiqueta por paso del SOP: **bien** (aceptado ≥ alto con el par correcto, o sin pareja y ausente de verdad), **mal** (aceptado con par equivocado, o sin pareja estando presente), **juez** (zona gris con el par correcto) o **juez✗** (zona gris con un par equivocado). Rango bien < juez < juez✗ = mal; «graves» = pasos que bajan de rango respecto de a, «mejoras» = los que suben.

## Variantes

- **a**: nombre + descripción + cita (actual)
- **b**: nombre + descripción, sin cita
- **c0.20**: vector 0.80·(sin cita) + 0.20·(cita)
- **c0.35**: vector 0.65·(sin cita) + 0.35·(cita)
- **c0.50**: vector 0.50·(sin cita) + 0.50·(cita)
- **d**: cita solo si el idioma del video es el del SOP (es)
- **e**: max(coseno con cita, coseno sin cita)
- **f**: e si el idioma del video no es el del SOP (es); si lo es, a

## Casos

| Caso | Grupo | Video | Formato | Idioma | Pasos del video | Pasos del SOP |
|---|---|---|---|---|---|---|
| a1226 | A×ref | 1226 | lista | es | 14 | 6 |
| a1688 | A×ref | 1688 | lista | es | 14 | 6 |
| a1743 | A×ref | 1743 | lista | es | 14 | 6 |
| a1745 | A×ref | 1745 | lista | es | 15 | 6 |
| a1855 | A×ref | 1855 | lista | es | 15 | 6 |
| a2071 | A×ref | 2071 | lista | es | 8 | 6 |
| a3954 | A×ref | 3954 | lista | es | 14 | 6 |
| a6213 | A×ref | 6213 | llm | es | 15 | 6 |
| a6972 | A×ref | 6972 | llm | es | 15 | 6 |
| a8275 | A×ref | 8275 | llm | es | 15 | 6 |
| a9696 | A×ref | 9696 | llm | es | 18 | 6 |
| b1227 | B×ref | 1227 | lista | es | 7 | 6 |
| b1687 | B×ref | 1687 | lista | es | 7 | 6 |
| b1689 | B×ref | 1689 | lista | es | 7 | 6 |
| b1744 | B×ref | 1744 | lista | es | 7 | 6 |
| b1799 | B×ref | 1799 | lista | es | 7 | 6 |
| b1800 | B×ref | 1800 | lista | es | 7 | 6 |
| b1801 | B×ref | 1801 | lista | es | 7 | 6 |
| c5037 | C×ref | 5037 | lista | es | 9 | 6 |
| c6214 | C×ref | 6214 | llm | es | 10 | 6 |
| c9536 | C×ref | 9536 | llm | es | 9 | 6 |
| c9537 | C×ref | 9537 | llm | es | 9 | 6 |
| c9687 | C×ref | 9687 | llm | es | 9 | 6 |
| c9692 | C×ref | 9692 | llm | es | 8 | 6 |
| c9693 | C×ref | 9693 | llm | es | 9 | 6 |
| c9694 | C×ref | 9694 | llm | es | 9 | 6 |
| d5038 | D×ref | 5038 | lista | es | 10 | 6 |
| d6215 | D×ref | 6215 | llm | es | 10 | 6 |
| d9688 | D×ref | 9688 | llm | es | 10 | 6 |
| e6971 | E×ref | 6971 | llm | en | 17 | 6 |
| e8658 | E×ref | 8658 | llm | en | 18 | 6 |
| e8659 | E×ref | 8659 | llm | en | 18 | 6 |
| e9689 | E×ref | 9689 | llm | en | 18 | 6 |
| e9690 | E×ref | 9690 | llm | en | 18 | 6 |
| e9691 | E×ref | 9691 | llm | en | 18 | 6 |
| e6971-8158 | E×SOP-8158 | 6971 | llm | en | 17 | 15 |
| e8658-8158 | E×SOP-8158 | 8658 | llm | en | 18 | 15 |
| e8659-8158 | E×SOP-8158 | 8659 | llm | en | 18 | 15 |
| e9689-8158 | E×SOP-8158 | 9689 | llm | en | 18 | 15 |
| e9690-8158 | E×SOP-8158 | 9690 | llm | en | 18 | 15 |
| e9691-8158 | E×SOP-8158 | 9691 | llm | en | 18 | 15 |
| e6971-9299 | E×SOP-9299 | 6971 | llm | en | 17 | 6 |
| e8658-9299 | E×SOP-9299 | 8658 | llm | en | 18 | 6 |
| e8659-9299 | E×SOP-9299 | 8659 | llm | en | 18 | 6 |
| e9689-9299 | E×SOP-9299 | 9689 | llm | en | 18 | 6 |
| e9690-9299 | E×SOP-9299 | 9690 | llm | en | 18 | 6 |
| e9691-9299 | E×SOP-9299 | 9691 | llm | en | 18 | 6 |
| e6971-6314 | E×SOP-6314 | 6971 | llm | en | 17 | 14 |
| e8658-6314 | E×SOP-6314 | 8658 | llm | en | 18 | 14 |
| e8659-6314 | E×SOP-6314 | 8659 | llm | en | 18 | 14 |
| e9689-6314 | E×SOP-6314 | 9689 | llm | en | 18 | 14 |
| e9690-6314 | E×SOP-6314 | 9690 | llm | en | 18 | 14 |
| e9691-6314 | E×SOP-6314 | 9691 | llm | en | 18 | 14 |
| a1226-6314 | A×SOP-6314 | 1226 | lista | es | 14 | 14 |
| a1688-6314 | A×SOP-6314 | 1688 | lista | es | 14 | 14 |
| a1743-6314 | A×SOP-6314 | 1743 | lista | es | 14 | 14 |
| a1745-6314 | A×SOP-6314 | 1745 | lista | es | 15 | 14 |
| a1855-6314 | A×SOP-6314 | 1855 | lista | es | 15 | 14 |
| a2071-6314 | A×SOP-6314 | 2071 | lista | es | 8 | 14 |
| a3954-6314 | A×SOP-6314 | 3954 | lista | es | 14 | 14 |
| a6213-6314 | A×SOP-6314 | 6213 | llm | es | 15 | 14 |
| a6972-6314 | A×SOP-6314 | 6972 | llm | es | 15 | 14 |
| a8275-6314 | A×SOP-6314 | 8275 | llm | es | 15 | 14 |
| a9696-6314 | A×SOP-6314 | 9696 | llm | es | 18 | 14 |

## Resumen por grupo y variante (respecto de a)

| Grupo | Var. | Segm. | Cambios de zona | Graves | Mejoras | Transiciones | Equivocados que suben | Pares al juez | Sobra | % sin juez | Fusión cambia | Citas de representante |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A×ref | a | 11 | 0 | 0 | 0 | – | 0 | 4 | 50 | 83.33–100 (media 93.9) | 0 | 0 |
| A×ref | b | 11 | 12 | 12 | 0 | bien→juez 5, bien→juez✗ 2, bien→mal 5 | 2 | 11 | 38 | 50–83.33 (media 75.8) | 9 | 0 |
| A×ref | c0.20 | 11 | 8 | 7 | 1 | bien→juez 7, juez→bien 1 | 0 | 10 | 46 | 66.67–100 (media 84.8) | 5 | 0 |
| A×ref | c0.35 | 11 | 3 | 2 | 1 | bien→juez 2, juez→bien 1 | 0 | 5 | 50 | 83.33–100 (media 92.4) | 1 | 0 |
| A×ref | c0.50 | 11 | 3 | 2 | 1 | bien→juez 2, juez→bien 1 | 0 | 5 | 54 | 83.33–100 (media 92.4) | 3 | 0 |
| A×ref | d | 11 | 0 | 0 | 0 | – | 0 | 4 | 50 | 83.33–100 (media 93.9) | 0 | 0 |
| A×ref | e | 11 | 0 | 0 | 0 | – | 0 | 4 | 40 | 83.33–100 (media 93.9) | 7 | 0 |
| A×ref | f | 11 | 0 | 0 | 0 | – | 0 | 4 | 50 | 83.33–100 (media 93.9) | 0 | 0 |
| B×ref | a | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| B×ref | b | 7 | 6 | 6 | 0 | bien→juez 6 | 0 | 13 | 0 | 41.67–58.33 (media 44.1) | 0 | 0 |
| B×ref | c0.20 | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| B×ref | c0.35 | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| B×ref | c0.50 | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| B×ref | d | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| B×ref | e | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| B×ref | f | 7 | 0 | 0 | 0 | – | 0 | 7 | 0 | 58.33 | 0 | 0 |
| C×ref | a | 8 | 0 | 0 | 0 | – | 0 | 13 | 4 | 50–66.67 (media 56.3) | 0 | 0 |
| C×ref | b | 8 | 11 | 10 | 1 | bien→juez 10, juez→bien 1 | 0 | 22 | 4 | 33.33–50 (media 37.5) | 0 | 0 |
| C×ref | c0.20 | 8 | 0 | 0 | 1 | mal→bien 1 | 0 | 13 | 5 | 50–66.67 (media 56.3) | 1 | 0 |
| C×ref | c0.35 | 8 | 0 | 0 | 1 | mal→bien 1 | 0 | 13 | 5 | 50–66.67 (media 56.3) | 1 | 0 |
| C×ref | c0.50 | 8 | 1 | 1 | 1 | bien→juez 1, mal→bien 1 | 0 | 14 | 5 | 50–66.67 (media 54.2) | 1 | 5 |
| C×ref | d | 8 | 0 | 0 | 0 | – | 0 | 13 | 4 | 50–66.67 (media 56.3) | 0 | 0 |
| C×ref | e | 8 | 1 | 0 | 1 | juez→bien 1 | 0 | 12 | 4 | 50–66.67 (media 58.3) | 0 | 0 |
| C×ref | f | 8 | 0 | 0 | 0 | – | 0 | 13 | 4 | 50–66.67 (media 56.3) | 0 | 0 |
| D×ref | a | 3 | 0 | 0 | 0 | – | 0 | 10 | 10 | 0 | 0 | 0 |
| D×ref | b | 3 | 2 | 1 | 1 | bien→juez✗ 1, juez✗→bien 1 | 1 | 10 | 12 | 0 | 0 | 0 |
| D×ref | c0.20 | 3 | 4 | 4 | 0 | bien→juez✗ 4 | 4 | 14 | 8 | 0 | 0 | 0 |
| D×ref | c0.35 | 3 | 2 | 2 | 0 | bien→juez✗ 2 | 2 | 12 | 7 | 0 | 0 | 0 |
| D×ref | c0.50 | 3 | 3 | 3 | 0 | bien→juez✗ 3 | 3 | 13 | 6 | 0 | 0 | 0 |
| D×ref | d | 3 | 0 | 0 | 0 | – | 0 | 10 | 10 | 0 | 0 | 0 |
| D×ref | e | 3 | 2 | 2 | 0 | bien→juez✗ 2 | 2 | 12 | 10 | 0 | 0 | 0 |
| D×ref | f | 3 | 0 | 0 | 0 | – | 0 | 10 | 10 | 0 | 0 | 0 |
| E×ref | a | 6 | 0 | 0 | 0 | – | 0 | 24 | 37 | 16.67–50 (media 33.3) | 0 | 0 |
| E×ref | b | 6 | 10 | 2 | 8 | bien→mal 1, juez→bien 8, juez→mal 1 | 0 | 15 | 30 | 50–66.67 (media 52.8) | 6 | 0 |
| E×ref | c0.20 | 6 | 10 | 1 | 9 | bien→juez 1, juez→bien 9 | 0 | 16 | 30 | 50–66.67 (media 55.6) | 6 | 0 |
| E×ref | c0.35 | 6 | 14 | 1 | 13 | bien→juez 1, juez→bien 13 | 0 | 12 | 26 | 50–83.33 (media 66.7) | 6 | 0 |
| E×ref | c0.50 | 6 | 11 | 0 | 11 | juez→bien 11 | 0 | 13 | 24 | 50–66.67 (media 63.9) | 6 | 0 |
| E×ref | d | 6 | 10 | 2 | 8 | bien→mal 1, juez→bien 8, juez→mal 1 | 0 | 15 | 30 | 50–66.67 (media 52.8) | 6 | 0 |
| E×ref | e | 6 | 8 | 0 | 8 | juez→bien 8 | 0 | 16 | 30 | 50–66.67 (media 55.6) | 6 | 0 |
| E×ref | f | 6 | 8 | 0 | 8 | juez→bien 8 | 0 | 16 | 30 | 50–66.67 (media 55.6) | 6 | 0 |
| E×SOP-8158 | a | 6 | 0 | 0 | 0 | – | 0 | 18 | 6 | 60–80 (media 73.3) | 0 | 0 |
| E×SOP-8158 | b | 6 | 25 | 2 | 23 | bien→juez 2, juez→bien 17, mal→bien 4, mal→juez 2 | 0 | 5 | 0 | 80–100 (media 94.4) | 0 | 0 |
| E×SOP-8158 | c0.20 | 6 | 26 | 2 | 24 | bien→juez 2, juez→bien 18, mal→bien 1, mal→juez 5 | 0 | 7 | 0 | 86.67–100 (media 92.2) | 0 | 0 |
| E×SOP-8158 | c0.35 | 6 | 24 | 0 | 24 | juez→bien 18, mal→bien 1, mal→juez 5 | 0 | 5 | 0 | 93.33–100 (media 94.4) | 0 | 0 |
| E×SOP-8158 | c0.50 | 6 | 24 | 0 | 24 | juez→bien 18, mal→bien 1, mal→juez 5 | 0 | 5 | 0 | 93.33–100 (media 94.4) | 0 | 0 |
| E×SOP-8158 | d | 6 | 25 | 2 | 23 | bien→juez 2, juez→bien 17, mal→bien 4, mal→juez 2 | 0 | 5 | 0 | 80–100 (media 94.4) | 0 | 0 |
| E×SOP-8158 | e | 6 | 23 | 0 | 23 | juez→bien 17, mal→bien 4, mal→juez 2 | 0 | 3 | 0 | 86.67–100 (media 96.7) | 0 | 0 |
| E×SOP-8158 | f | 6 | 23 | 0 | 23 | juez→bien 17, mal→bien 4, mal→juez 2 | 0 | 3 | 0 | 86.67–100 (media 96.7) | 0 | 0 |
| E×SOP-9299 | a | 6 | 0 | 0 | 0 | – | 0 | 13 | 22 | 50–66.67 (media 63.9) | 0 | 0 |
| E×SOP-9299 | b | 6 | 9 | 4 | 7 | bien→juez 2, juez→bien 7, juez→juez✗ 2 | 2 | 8 | 18 | 66.67–83.33 (media 77.8) | 6 | 0 |
| E×SOP-9299 | c0.20 | 6 | 13 | 3 | 11 | bien→juez 2, juez→bien 11, juez→juez✗ 1 | 1 | 4 | 17 | 66.67–100 (media 88.9) | 6 | 0 |
| E×SOP-9299 | c0.35 | 6 | 11 | 1 | 11 | juez→bien 11, juez→juez✗ 1 | 1 | 2 | 17 | 83.33–100 (media 94.4) | 6 | 0 |
| E×SOP-9299 | c0.50 | 6 | 12 | 0 | 12 | juez→bien 12 | 0 | 1 | 20 | 83.33–100 (media 97.2) | 6 | 0 |
| E×SOP-9299 | d | 6 | 9 | 4 | 7 | bien→juez 2, juez→bien 7, juez→juez✗ 2 | 2 | 8 | 18 | 66.67–83.33 (media 77.8) | 6 | 0 |
| E×SOP-9299 | e | 6 | 7 | 2 | 7 | juez→bien 7, juez→juez✗ 2 | 2 | 6 | 15 | 83.33 | 6 | 0 |
| E×SOP-9299 | f | 6 | 7 | 2 | 7 | juez→bien 7, juez→juez✗ 2 | 2 | 6 | 15 | 83.33 | 6 | 0 |
| E×SOP-6314 | a | 6 | 0 | 0 | 0 | – | 0 | 18 | 6 | 64.29–78.57 (media 71.4) | 0 | 0 |
| E×SOP-6314 | b | 6 | 27 | 3 | 24 | bien→juez 3, juez→bien 18, mal→bien 4, mal→juez 2 | 0 | 5 | 0 | 85.71–100 (media 94.0) | 0 | 0 |
| E×SOP-6314 | c0.20 | 6 | 26 | 2 | 24 | bien→juez 2, juez→bien 18, mal→bien 1, mal→juez 5 | 0 | 7 | 0 | 85.71–100 (media 91.7) | 0 | 0 |
| E×SOP-6314 | c0.35 | 6 | 26 | 2 | 24 | bien→juez 2, juez→bien 18, mal→bien 1, mal→juez 5 | 0 | 7 | 0 | 85.71–100 (media 91.7) | 0 | 0 |
| E×SOP-6314 | c0.50 | 6 | 22 | 0 | 21 | juez→bien 16, mal→bien 1, mal→juez 4, mal→juez✗ 1 | 1 | 7 | 1 | 85.71–92.86 (media 91.7) | 0 | 0 |
| E×SOP-6314 | d | 6 | 27 | 3 | 24 | bien→juez 3, juez→bien 18, mal→bien 4, mal→juez 2 | 0 | 5 | 0 | 85.71–100 (media 94.0) | 0 | 0 |
| E×SOP-6314 | e | 6 | 24 | 0 | 24 | juez→bien 18, mal→bien 4, mal→juez 2 | 0 | 2 | 0 | 92.86–100 (media 97.6) | 0 | 0 |
| E×SOP-6314 | f | 6 | 24 | 0 | 24 | juez→bien 18, mal→bien 4, mal→juez 2 | 0 | 2 | 0 | 92.86–100 (media 97.6) | 0 | 0 |
| A×SOP-6314 | a | 11 | 0 | 0 | 0 | – | 0 | 75 | 10 | 7.14–35.71 (media 25.0) | 0 | 0 |
| A×SOP-6314 | b | 11 | 46 | 31 | 13 | bien→juez 15, bien→mal 1, juez→bien 7, juez→juez✗ 4, juez→mal 11, mal→bien 2, mal→juez 4, mal→juez✗ 6 | 10 | 82 | 11 | 7.14–35.71 (media 20.5) | 3 | 1 |
| A×SOP-6314 | c0.20 | 11 | 23 | 14 | 4 | bien→juez 10, bien→mal 1, juez→mal 3, mal→juez 4, mal→juez✗ 5 | 5 | 91 | 7 | 0–35.71 (media 16.9) | 3 | 0 |
| A×SOP-6314 | c0.35 | 11 | 11 | 9 | 4 | bien→juez 9, juez✗→juez 2, mal→juez 2 | 0 | 86 | 8 | 7.14–28.57 (media 19.2) | 0 | 0 |
| A×SOP-6314 | c0.50 | 11 | 10 | 3 | 8 | bien→juez 2, juez→mal 1, juez✗→juez 2, mal→juez 6, mal→juez✗ 1 | 1 | 83 | 7 | 7.14–28.57 (media 23.4) | 3 | 0 |
| A×SOP-6314 | d | 11 | 0 | 0 | 0 | – | 0 | 75 | 10 | 7.14–35.71 (media 25.0) | 0 | 0 |
| A×SOP-6314 | e | 11 | 18 | 5 | 9 | bien→mal 1, juez→bien 7, juez→juez✗ 2, juez→mal 2, mal→bien 1, mal→juez 1, mal→juez✗ 6 | 8 | 73 | 8 | 7.14–42.86 (media 27.6) | 3 | 0 |
| A×SOP-6314 | f | 11 | 0 | 0 | 0 | – | 0 | 75 | 10 | 7.14–35.71 (media 25.0) | 0 | 0 |

## Pasos que cambian respecto de a

Zona/etiqueta (coseno del par) por variante; solo los pasos del SOP con algún cambio de zona o etiqueta. «cc» = mejor coseno de un paso original correcto.

### a1226 (A×ref, video 1226)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.81 ✓ (cc 0.81) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) |
| 4 | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.91 ✓ (cc 0.79) | aceptado/bien 0.90 ✓ (cc 0.79) | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.91 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) |

### a1688 (A×ref, video 1688)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.82 ✓ (cc 0.82) | sin pareja/mal 0.51 ✓ (cc 0.51) | gris/juez 0.65 ✓ (cc 0.65) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) |

### a1743 (A×ref, video 1743)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.82 ✓ (cc 0.82) | sin pareja/mal 0.51 ✓ (cc 0.51) | gris/juez 0.65 ✓ (cc 0.65) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) |

### a1745 (A×ref, video 1745)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.86 ✓ (cc 0.86) | sin pareja/mal 0.53 ✓ (cc 0.53) | gris/juez 0.66 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.86 ✓ (cc 0.86) |

### a1855 (A×ref, video 1855)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.84 ✓ (cc 0.84) | sin pareja/mal 0.51 ✗ (cc 0.50) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) |

### a3954 (A×ref, video 3954)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.85 ✓ (cc 0.85) | gris/juez 0.58 ✓ (cc 0.55) | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 2 | aceptado/bien 0.89 ✓ (cc 0.89) | gris/juez✗ 0.69 ✗ (cc 0.93) | aceptado/bien 0.92 ✓ (cc 0.92) | aceptado/bien 0.90 ✓ (cc 0.90) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.93 ✓ (cc 0.93) | aceptado/bien 0.89 ✓ (cc 0.89) |

### a6213 (A×ref, video 6213)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.84 ✓ (cc 0.84) | sin pareja/mal 0.51 ✗ (cc 0.50) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) |

### a6972 (A×ref, video 6972)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.81 ✓ (cc 0.81) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) |

### a8275 (A×ref, video 8275)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.85 ✓ (cc 0.85) | gris/juez 0.58 ✓ (cc 0.55) | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 2 | aceptado/bien 0.89 ✓ (cc 0.89) | gris/juez✗ 0.69 ✗ (cc 0.93) | aceptado/bien 0.92 ✓ (cc 0.92) | aceptado/bien 0.90 ✓ (cc 0.90) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.93 ✓ (cc 0.93) | aceptado/bien 0.89 ✓ (cc 0.89) |

### a9696 (A×ref, video 9696)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.81 ✓ (cc 0.81) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) |
| 4 | aceptado/bien 0.79 ✓ (cc 0.71) | aceptado/bien 0.80 ✓ (cc 0.72) | aceptado/bien 0.81 ✓ (cc 0.72) | aceptado/bien 0.78 ✓ (cc 0.71) | gris/juez 0.72 ✓ (cc 0.70) | aceptado/bien 0.79 ✓ (cc 0.71) | aceptado/bien 0.80 ✓ (cc 0.72) | aceptado/bien 0.79 ✓ (cc 0.71) |
| 6 | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.88 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.73) | aceptado/bien 0.85 ✓ (cc 0.73) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.72 ✓ (cc 0.72) |

### b1227 (B×ref, video 1227)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) |

### b1687 (B×ref, video 1687)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### b1689 (B×ref, video 1689)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### b1744 (B×ref, video 1744)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### b1799 (B×ref, video 1799)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### b1801 (B×ref, video 1801)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### c5037 (C×ref, video 5037)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) |
| 6 | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |

### c6214 (C×ref, video 6214)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.75 ✓ (cc 0.75) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.75 ✓ (cc 0.75) | gris/juez 0.71 ✓ (cc 0.71) |
| 6 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### c9536 (C×ref, video 9536)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) |
| 6 | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |

### c9537 (C×ref, video 9537)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 2 | aceptado/mal 0.88 ✗ (cc 0.91) | aceptado/mal 0.87 ✗ (cc 0.92) | aceptado/bien 0.92 ✓ (cc 0.92) | aceptado/bien 0.91 ✓ (cc 0.91) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/mal 0.88 ✗ (cc 0.91) | aceptado/mal 0.88 ✗ (cc 0.92) | aceptado/mal 0.88 ✗ (cc 0.91) |
| 6 | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |

### c9687 (C×ref, video 9687)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |

### c9692 (C×ref, video 9692)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.81 ✓ (cc 0.81) |
| 6 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### c9693 (C×ref, video 9693)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |

### c9694 (C×ref, video 9694)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### d5038 (D×ref, video 5038)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 5 | sin pareja/bien 0.54 ✗ (cc –) | sin pareja/bien 0.52 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) | sin pareja/bien 0.52 ✗ (cc –) | gris/juez✗ 0.56 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) |

### d6215 (D×ref, video 6215)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 2 | gris/juez✗ 0.57 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) | gris/juez✗ 0.57 ✗ (cc –) | gris/juez✗ 0.59 ✗ (cc –) | gris/juez✗ 0.59 ✗ (cc –) | gris/juez✗ 0.57 ✗ (cc –) | gris/juez✗ 0.57 ✗ (cc –) | gris/juez✗ 0.57 ✗ (cc –) |
| 5 | sin pareja/bien 0.53 ✗ (cc –) | sin pareja/bien 0.49 ✗ (cc –) | gris/juez✗ 0.55 ✗ (cc –) | gris/juez✗ 0.59 ✗ (cc –) | gris/juez✗ 0.61 ✗ (cc –) | sin pareja/bien 0.53 ✗ (cc –) | sin pareja/bien 0.53 ✗ (cc –) | sin pareja/bien 0.53 ✗ (cc –) |
| 6 | sin pareja/bien 0.55 ✗ (cc –) | gris/juez✗ 0.56 ✗ (cc –) | gris/juez✗ 0.55 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) | sin pareja/bien 0.52 ✗ (cc –) | sin pareja/bien 0.55 ✗ (cc –) | gris/juez✗ 0.56 ✗ (cc –) | sin pareja/bien 0.55 ✗ (cc –) |

### d9688 (D×ref, video 9688)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 5 | sin pareja/bien 0.53 ✗ (cc –) | sin pareja/bien 0.49 ✗ (cc –) | gris/juez✗ 0.55 ✗ (cc –) | gris/juez✗ 0.59 ✗ (cc –) | gris/juez✗ 0.61 ✗ (cc –) | sin pareja/bien 0.53 ✗ (cc –) | sin pareja/bien 0.53 ✗ (cc –) | sin pareja/bien 0.53 ✗ (cc –) |
| 6 | sin pareja/bien 0.55 ✗ (cc –) | sin pareja/bien 0.52 ✗ (cc –) | gris/juez✗ 0.55 ✗ (cc –) | sin pareja/bien 0.54 ✗ (cc –) | sin pareja/bien 0.52 ✗ (cc –) | sin pareja/bien 0.55 ✗ (cc –) | gris/juez✗ 0.56 ✗ (cc –) | sin pareja/bien 0.55 ✗ (cc –) |

### e6971 (E×ref, video 6971)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.79 ✓ (cc 0.67) | aceptado/bien 0.80 ✓ (cc 0.70) | aceptado/bien 0.82 ✓ (cc 0.71) | aceptado/bien 0.79 ✓ (cc 0.71) | aceptado/bien 0.79 ✓ (cc 0.67) | aceptado/bien 0.79 ✓ (cc 0.69) | aceptado/bien 0.79 ✓ (cc 0.69) |

### e8658 (E×ref, video 8658)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.79 ✓ (cc 0.79) | sin pareja/mal 0.51 ✗ (cc 0.51) | gris/juez 0.62 ✓ (cc 0.62) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | sin pareja/mal 0.51 ✗ (cc 0.51) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |
| 3 | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.86 ✓ (cc 0.86) |
| 4 | gris/juez 0.63 ✓ (cc 0.63) | aceptado/bien 0.76 ✓ (cc 0.61) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.77 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.61) | aceptado/bien 0.76 ✓ (cc 0.63) | aceptado/bien 0.76 ✓ (cc 0.63) |

### e8659 (E×ref, video 8659)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.75 ✓ (cc 0.75) |
| 4 | gris/juez 0.68 ✓ (cc 0.68) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.78 ✓ (cc 0.68) | aceptado/bien 0.81 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.69) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.78 ✓ (cc 0.68) | aceptado/bien 0.78 ✓ (cc 0.68) |
| 6 | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.78 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.70 ✓ (cc 0.70) |

### e9689 (E×ref, video 9689)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | gris/juez 0.72 ✓ (cc 0.72) | sin pareja/mal 0.51 ✗ (cc 0.43) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.73 ✓ (cc 0.73) | sin pareja/mal 0.51 ✗ (cc 0.43) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.72 ✓ (cc 0.72) |
| 3 | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.86 ✓ (cc 0.86) |
| 4 | gris/juez 0.65 ✓ (cc 0.65) | aceptado/bien 0.76 ✓ (cc 0.62) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.77 ✓ (cc 0.67) | aceptado/bien 0.76 ✓ (cc 0.67) | aceptado/bien 0.76 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.65) | aceptado/bien 0.76 ✓ (cc 0.65) |
| 6 | gris/juez 0.67 ✓ (cc 0.67) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.82 ✓ (cc 0.73) | aceptado/bien 0.81 ✓ (cc 0.73) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.73 ✓ (cc 0.73) |

### e9690 (E×ref, video 9690)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.75 ✓ (cc 0.75) |
| 4 | gris/juez 0.63 ✓ (cc 0.63) | aceptado/bien 0.76 ✓ (cc 0.61) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.80 ✓ (cc 0.66) | aceptado/bien 0.77 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.61) | aceptado/bien 0.76 ✓ (cc 0.63) | aceptado/bien 0.76 ✓ (cc 0.63) |

### e9691 (E×ref, video 9691)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.75 ✓ (cc 0.75) |
| 4 | gris/juez 0.68 ✓ (cc 0.68) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.78 ✓ (cc 0.68) | aceptado/bien 0.81 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.69) | aceptado/bien 0.77 ✓ (cc 0.65) | aceptado/bien 0.78 ✓ (cc 0.68) | aceptado/bien 0.78 ✓ (cc 0.68) |

### e6971-8158 (E×SOP-8158, video 6971)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | sin pareja/mal 0.54 ✓ (cc 0.54) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) |
| 7 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 15 | gris/juez 0.65 ✓ (cc 0.65) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) |

### e8658-8158 (E×SOP-8158, video 8658)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.62 ✓ (cc 0.62) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) |
| 5 | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) |
| 6 | sin pareja/mal 0.42 ✗ (cc 0.29) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) |
| 7 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 8 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) |
| 11 | gris/juez 0.60 ✓ (cc 0.60) | aceptado/bien 0.91 ✓ (cc 0.91) | aceptado/bien 0.90 ✓ (cc 0.90) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.91 ✓ (cc 0.91) | aceptado/bien 0.91 ✓ (cc 0.91) | aceptado/bien 0.91 ✓ (cc 0.91) |
| 15 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |

### e8659-8158 (E×SOP-8158, video 8659)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | sin pareja/mal 0.45 ✗ (cc 0.31) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 15 | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.83 ✓ (cc 0.83) |

### e9689-8158 (E×SOP-8158, video 9689)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.59 ✓ (cc 0.59) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |
| 5 | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) |
| 6 | sin pareja/mal 0.42 ✗ (cc 0.29) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) |
| 7 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 11 | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) |
| 15 | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.74 ✓ (cc 0.74) |

### e9690-8158 (E×SOP-8158, video 9690)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | sin pareja/mal 0.45 ✗ (cc 0.31) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 8 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) |
| 15 | gris/juez 0.63 ✓ (cc 0.63) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.83 ✓ (cc 0.83) |

### e9691-8158 (E×SOP-8158, video 9691)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | sin pareja/mal 0.45 ✗ (cc 0.31) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 15 | gris/juez 0.63 ✓ (cc 0.63) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.83 ✓ (cc 0.83) |

### e6971-9299 (E×SOP-9299, video 6971)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | gris/juez 0.68 ✓ (cc 0.68) | aceptado/bien 0.95 ✓ (cc 0.72) | aceptado/bien 0.94 ✓ (cc 0.74) | aceptado/bien 0.90 ✓ (cc 0.74) | aceptado/bien 0.84 ✓ (cc 0.71) | aceptado/bien 0.95 ✓ (cc 0.72) | aceptado/bien 0.95 ✓ (cc 0.72) | aceptado/bien 0.95 ✓ (cc 0.72) |
| 6 | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.72 ✓ (cc 0.72) |

### e8658-9299 (E×SOP-9299, video 8658)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.61 ✓ (cc 0.61) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) |
| 4 | gris/juez 0.61 ✓ (cc 0.61) | aceptado/bien 0.77 ✓ (cc 0.68) | aceptado/bien 0.84 ✓ (cc 0.69) | aceptado/bien 0.81 ✓ (cc 0.67) | aceptado/bien 0.75 ✓ (cc 0.64) | aceptado/bien 0.77 ✓ (cc 0.68) | aceptado/bien 0.84 ✓ (cc 0.68) | aceptado/bien 0.84 ✓ (cc 0.68) |
| 5 | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.90 ✓ (cc 0.75) | aceptado/bien 0.89 ✓ (cc 0.75) | aceptado/bien 0.86 ✓ (cc 0.74) | aceptado/bien 0.82 ✓ (cc 0.72) | aceptado/bien 0.90 ✓ (cc 0.75) | aceptado/bien 0.90 ✓ (cc 0.75) | aceptado/bien 0.90 ✓ (cc 0.75) |
| 6 | gris/juez 0.67 ✓ (cc 0.67) | gris/juez✗ 0.70 ✗ (cc 0.65) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez✗ 0.70 ✗ (cc 0.65) | gris/juez✗ 0.70 ✗ (cc 0.67) | gris/juez✗ 0.70 ✗ (cc 0.67) |

### e8659-9299 (E×SOP-9299, video 8659)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | gris/juez 0.66 ✓ (cc 0.66) | aceptado/bien 0.88 ✓ (cc 0.72) | aceptado/bien 0.87 ✓ (cc 0.71) | aceptado/bien 0.83 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.64) | aceptado/bien 0.88 ✓ (cc 0.72) | aceptado/bien 0.88 ✓ (cc 0.72) | aceptado/bien 0.88 ✓ (cc 0.72) |
| 6 | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) |

### e9689-9299 (E×SOP-9299, video 9689)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.68 ✓ (cc 0.68) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.58 ✓ (cc 0.58) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |
| 4 | gris/juez 0.64 ✓ (cc 0.64) | aceptado/bien 0.77 ✓ (cc 0.68) | aceptado/bien 0.84 ✓ (cc 0.69) | aceptado/bien 0.81 ✓ (cc 0.67) | aceptado/bien 0.76 ✓ (cc 0.64) | aceptado/bien 0.77 ✓ (cc 0.68) | aceptado/bien 0.84 ✓ (cc 0.68) | aceptado/bien 0.84 ✓ (cc 0.68) |
| 6 | gris/juez 0.63 ✓ (cc 0.63) | gris/juez✗ 0.70 ✗ (cc 0.65) | gris/juez✗ 0.70 ✗ (cc 0.66) | gris/juez✗ 0.68 ✗ (cc 0.68) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez✗ 0.70 ✗ (cc 0.65) | gris/juez✗ 0.70 ✗ (cc 0.65) | gris/juez✗ 0.70 ✗ (cc 0.65) |

### e9690-9299 (E×SOP-9299, video 9690)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | gris/juez 0.61 ✓ (cc 0.61) | aceptado/bien 0.80 ✓ (cc 0.72) | aceptado/bien 0.86 ✓ (cc 0.71) | aceptado/bien 0.82 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.64) | aceptado/bien 0.80 ✓ (cc 0.72) | aceptado/bien 0.86 ✓ (cc 0.72) | aceptado/bien 0.86 ✓ (cc 0.72) |
| 6 | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) |

### e9691-9299 (E×SOP-9299, video 9691)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | gris/juez 0.66 ✓ (cc 0.66) | aceptado/bien 0.88 ✓ (cc 0.72) | aceptado/bien 0.87 ✓ (cc 0.71) | aceptado/bien 0.83 ✓ (cc 0.69) | aceptado/bien 0.78 ✓ (cc 0.64) | aceptado/bien 0.88 ✓ (cc 0.72) | aceptado/bien 0.88 ✓ (cc 0.72) | aceptado/bien 0.88 ✓ (cc 0.72) |
| 6 | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.71 ✓ (cc 0.71) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.71 ✓ (cc 0.71) |

### e6971-6314 (E×SOP-6314, video 6971)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 5 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.82 ✓ (cc 0.82) |
| 6 | sin pareja/mal 0.54 ✓ (cc 0.54) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) |
| 7 | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) |
| 8 | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 9 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |

### e8658-6314 (E×SOP-6314, video 8658)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.58 ✓ (cc 0.58) | aceptado/bien 0.80 ✓ (cc 0.80) | aceptado/bien 0.80 ✓ (cc 0.80) |
| 5 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 6 | sin pareja/mal 0.45 ✗ (cc 0.29) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) |
| 7 | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) |
| 9 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |
| 11 | gris/juez 0.61 ✓ (cc 0.61) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.88 ✓ (cc 0.88) |

### e8659-6314 (E×SOP-6314, video 8659)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | sin pareja/mal 0.46 ✗ (cc 0.31) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) |
| 9 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |

### e9689-6314 (E×SOP-6314, video 9689)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.55 ✓ (cc 0.55) | gris/juez 0.67 ✓ (cc 0.67) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.55 ✓ (cc 0.55) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |
| 5 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.86 ✓ (cc 0.86) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.85 ✓ (cc 0.85) |
| 6 | sin pareja/mal 0.43 ✗ (cc 0.29) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez✗ 0.58 ✗ (cc 0.58) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) | gris/juez 0.68 ✓ (cc 0.68) |
| 7 | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) |
| 9 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |

### e9690-6314 (E×SOP-6314, video 9690)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 5 | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.80 ✓ (cc 0.80) | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) | aceptado/bien 0.84 ✓ (cc 0.84) |
| 6 | sin pareja/mal 0.46 ✗ (cc 0.31) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) |
| 9 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |
| 14 | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.85 ✓ (cc 0.85) | gris/juez 0.70 ✓ (cc 0.70) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |

### e9691-6314 (E×SOP-6314, video 9691)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 6 | sin pareja/mal 0.46 ✗ (cc 0.31) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.62 ✓ (cc 0.62) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.89 ✓ (cc 0.89) | aceptado/bien 0.88 ✓ (cc 0.88) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) | aceptado/bien 0.87 ✓ (cc 0.87) |
| 9 | gris/juez 0.69 ✓ (cc 0.69) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |

### a1226-6314 (A×SOP-6314, video 1226)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |
| 5 | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.75 ✓ (cc 0.75) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) |
| 7 | aceptado/bien 0.81 ✓ (cc 0.81) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.85 ✓ (cc 0.85) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.81 ✓ (cc 0.81) |
| 10 | sin pareja/mal 0.53 ✗ (cc 0.46) | gris/juez✗ 0.62 ✗ (cc 0.45) | gris/juez✗ 0.61 ✗ (cc 0.47) | sin pareja/mal 0.52 ✗ (cc 0.47) | sin pareja/mal 0.51 ✗ (cc 0.46) | sin pareja/mal 0.53 ✗ (cc 0.46) | gris/juez✗ 0.62 ✗ (cc 0.46) | sin pareja/mal 0.53 ✗ (cc 0.46) |
| 11 | gris/juez 0.58 ✓ (cc 0.58) | sin pareja/mal 0.54 ✓ (cc 0.54) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.58 ✓ (cc 0.58) |

### a1688-6314 (A×SOP-6314, video 1688)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.75 ✓ (cc 0.75) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |
| 2 | gris/juez 0.70 ✓ (cc 0.70) | sin pareja/mal 0.40 ✗ (cc 0.72) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.67 ✓ (cc 0.67) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.70 ✓ (cc 0.70) |
| 5 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) |
| 6 | gris/juez 0.66 ✓ (cc 0.66) | gris/juez✗ 0.61 ✗ (cc 0.65) | gris/juez 0.57 ✓ (cc 0.64) | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.62 ✓ (cc 0.62) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.57 ✓ (cc 0.66) | gris/juez 0.66 ✓ (cc 0.66) |
| 7 | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.63 ✓ (cc 0.65) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 8 | sin pareja/mal 0.34 ✗ (cc 0.64) | gris/juez 0.67 ✓ (cc 0.67) | sin pareja/mal 0.35 ✗ (cc 0.63) | sin pareja/mal 0.34 ✗ (cc 0.59) | sin pareja/mal 0.32 ✗ (cc 0.54) | sin pareja/mal 0.34 ✗ (cc 0.64) | sin pareja/mal 0.35 ✗ (cc 0.67) | sin pareja/mal 0.34 ✗ (cc 0.64) |
| 10 | sin pareja/mal 0.53 ✗ (cc 0.48) | gris/juez✗ 0.62 ✗ (cc 0.49) | gris/juez✗ 0.61 ✗ (cc 0.50) | sin pareja/mal 0.52 ✗ (cc 0.50) | sin pareja/mal 0.51 ✗ (cc 0.49) | sin pareja/mal 0.53 ✗ (cc 0.48) | gris/juez✗ 0.62 ✗ (cc 0.49) | sin pareja/mal 0.53 ✗ (cc 0.48) |
| 11 | gris/juez 0.56 ✓ (cc 0.56) | sin pareja/mal 0.51 ✓ (cc 0.51) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.56 ✓ (cc 0.56) |

### a1743-6314 (A×SOP-6314, video 1743)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.75 ✓ (cc 0.75) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |
| 2 | gris/juez 0.70 ✓ (cc 0.70) | sin pareja/mal 0.40 ✗ (cc 0.72) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.67 ✓ (cc 0.67) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.70 ✓ (cc 0.70) |
| 5 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) |
| 6 | gris/juez 0.66 ✓ (cc 0.66) | gris/juez✗ 0.61 ✗ (cc 0.65) | gris/juez 0.57 ✓ (cc 0.64) | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.62 ✓ (cc 0.62) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.57 ✓ (cc 0.66) | gris/juez 0.66 ✓ (cc 0.66) |
| 7 | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.63 ✓ (cc 0.65) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.83 ✓ (cc 0.83) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 8 | sin pareja/mal 0.33 ✗ (cc 0.64) | gris/juez 0.67 ✓ (cc 0.67) | sin pareja/mal 0.34 ✗ (cc 0.63) | sin pareja/mal 0.32 ✗ (cc 0.59) | sin pareja/mal 0.29 ✗ (cc 0.54) | sin pareja/mal 0.33 ✗ (cc 0.64) | sin pareja/mal 0.35 ✗ (cc 0.67) | sin pareja/mal 0.33 ✗ (cc 0.64) |
| 10 | sin pareja/mal 0.53 ✗ (cc 0.46) | gris/juez✗ 0.62 ✗ (cc 0.46) | gris/juez✗ 0.61 ✗ (cc 0.48) | sin pareja/mal 0.52 ✗ (cc 0.48) | sin pareja/mal 0.51 ✗ (cc 0.47) | sin pareja/mal 0.53 ✗ (cc 0.46) | gris/juez✗ 0.62 ✗ (cc 0.46) | sin pareja/mal 0.53 ✗ (cc 0.46) |
| 11 | gris/juez 0.57 ✓ (cc 0.57) | sin pareja/mal 0.52 ✓ (cc 0.52) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.57 ✓ (cc 0.57) |

### a1745-6314 (A×SOP-6314, video 1745)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.65 ✓ (cc 0.65) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) | aceptado/bien 0.79 ✓ (cc 0.79) |
| 2 | gris/juez 0.71 ✓ (cc 0.71) | sin pareja/mal 0.49 ✗ (cc 0.72) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.67 ✓ (cc 0.67) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.71 ✓ (cc 0.71) |
| 5 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) |
| 6 | gris/juez 0.62 ✓ (cc 0.62) | gris/juez✗ 0.73 ✗ (cc 0.60) | gris/juez 0.60 ✓ (cc 0.61) | gris/juez 0.62 ✓ (cc 0.61) | gris/juez 0.57 ✓ (cc 0.61) | gris/juez 0.62 ✓ (cc 0.62) | gris/juez✗ 0.73 ✗ (cc 0.62) | gris/juez 0.62 ✓ (cc 0.62) |
| 9 | sin pareja/mal 0.53 ✗ (cc 0.56) | gris/juez 0.62 ✓ (cc 0.62) | sin pareja/mal 0.53 ✗ (cc 0.61) | sin pareja/mal 0.52 ✗ (cc 0.58) | sin pareja/mal 0.49 ✗ (cc 0.54) | sin pareja/mal 0.53 ✗ (cc 0.56) | sin pareja/mal 0.53 ✗ (cc 0.62) | sin pareja/mal 0.53 ✗ (cc 0.56) |
| 10 | sin pareja/mal – ✗ (cc 0.46) | gris/juez✗ 0.56 ✗ (cc 0.42) | gris/juez✗ 0.56 ✗ (cc 0.45) | sin pareja/mal – ✗ (cc 0.47) | gris/juez✗ 0.56 ✗ (cc 0.47) | sin pareja/mal – ✗ (cc 0.46) | gris/juez✗ 0.56 ✗ (cc 0.46) | sin pareja/mal – ✗ (cc 0.46) |
| 11 | sin pareja/mal 0.53 ✓ (cc 0.53) | gris/juez✗ 0.56 ✗ (cc 0.41) | sin pareja/mal 0.48 ✓ (cc 0.48) | sin pareja/mal 0.53 ✓ (cc 0.53) | gris/juez 0.57 ✓ (cc 0.57) | sin pareja/mal 0.53 ✓ (cc 0.53) | sin pareja/mal 0.53 ✓ (cc 0.53) | sin pareja/mal 0.53 ✓ (cc 0.53) |
| 12 | gris/juez 0.66 ✓ (cc 0.66) | gris/juez✗ 0.56 ✗ (cc 0.63) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.65 ✓ (cc 0.65) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez✗ 0.56 ✗ (cc 0.66) | gris/juez 0.66 ✓ (cc 0.66) |
| 14 | gris/juez 0.58 ✓ (cc 0.58) | sin pareja/mal 0.45 ✓ (cc 0.45) | sin pareja/mal 0.42 ✓ (cc 0.51) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.58 ✓ (cc 0.58) |

### a1855-6314 (A×SOP-6314, video 1855)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) |
| 7 | sin pareja/mal – ✗ (cc 0.54) | sin pareja/mal 0.48 ✓ (cc 0.53) | sin pareja/mal 0.53 ✓ (cc 0.53) | sin pareja/mal – ✗ (cc 0.56) | gris/juez 0.58 ✓ (cc 0.58) | sin pareja/mal – ✗ (cc 0.54) | sin pareja/mal 0.54 ✓ (cc 0.54) | sin pareja/mal – ✗ (cc 0.54) |
| 8 | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.73 ✓ (cc 0.73) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) |

### a2071-6314 (A×SOP-6314, video 2071)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 5 | gris/juez✗ 0.73 ✗ (cc 0.69) | gris/juez✗ 0.73 ✗ (cc 0.66) | gris/juez✗ 0.73 ✗ (cc 0.70) | gris/juez 0.71 ✓ (cc 0.71) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez✗ 0.73 ✗ (cc 0.69) | gris/juez✗ 0.73 ✗ (cc 0.69) | gris/juez✗ 0.73 ✗ (cc 0.69) |
| 7 | aceptado/bien 0.76 ✓ (cc 0.76) | sin pareja/mal 0.35 ✗ (cc 0.58) | sin pareja/mal 0.41 ✗ (cc 0.69) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.76 ✓ (cc 0.76) | sin pareja/mal 0.46 ✗ (cc 0.76) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 8 | sin pareja/mal – ✗ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.74 ✓ (cc 0.74) | sin pareja/mal – ✗ (cc 0.69) | sin pareja/mal – ✗ (cc 0.63) | sin pareja/mal – ✗ (cc 0.71) | aceptado/bien 0.77 ✓ (cc 0.77) | sin pareja/mal – ✗ (cc 0.71) |
| 9 | sin pareja/mal 0.49 ✗ (cc 0.58) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.61 ✓ (cc 0.61) | sin pareja/mal 0.42 ✗ (cc 0.57) | sin pareja/mal – ✗ (cc 0.52) | sin pareja/mal 0.49 ✗ (cc 0.58) | gris/juez 0.64 ✓ (cc 0.64) | sin pareja/mal 0.49 ✗ (cc 0.58) |
| 11 | gris/juez 0.57 ✓ (cc 0.57) | sin pareja/mal – ✗ (cc 0.53) | sin pareja/mal – ✗ (cc 0.56) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.57 ✓ (cc 0.57) | sin pareja/mal – ✗ (cc 0.57) | gris/juez 0.57 ✓ (cc 0.57) |
| 13 | gris/juez✗ 0.61 ✗ (cc 0.64) | gris/juez✗ 0.57 ✗ (cc 0.62) | gris/juez✗ 0.61 ✗ (cc 0.64) | gris/juez 0.65 ✓ (cc 0.65) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez✗ 0.61 ✗ (cc 0.64) | gris/juez✗ 0.61 ✗ (cc 0.64) | gris/juez✗ 0.61 ✗ (cc 0.64) |

### a3954-6314 (A×SOP-6314, video 3954)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.75 ✓ (cc 0.75) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |
| 5 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) |
| 6 | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.55 ✓ (cc 0.55) | sin pareja/mal 0.52 ✓ (cc 0.53) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.56 ✓ (cc 0.56) |
| 11 | sin pareja/mal 0.55 ✓ (cc 0.55) | sin pareja/mal 0.47 ✓ (cc 0.47) | sin pareja/mal 0.53 ✓ (cc 0.53) | gris/juez 0.56 ✓ (cc 0.56) | gris/juez 0.59 ✓ (cc 0.59) | sin pareja/mal 0.55 ✓ (cc 0.55) | sin pareja/mal 0.55 ✓ (cc 0.55) | sin pareja/mal 0.55 ✓ (cc 0.55) |

### a6213-6314 (A×SOP-6314, video 6213)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.77 ✓ (cc 0.77) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.69 ✓ (cc 0.69) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.77 ✓ (cc 0.77) |
| 6 | gris/juez 0.66 ✓ (cc 0.68) | gris/juez 0.60 ✓ (cc 0.68) | sin pareja/mal 0.23 ✗ (cc 0.66) | gris/juez 0.67 ✓ (cc 0.65) | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.66 ✓ (cc 0.68) | sin pareja/mal 0.24 ✗ (cc 0.68) | gris/juez 0.66 ✓ (cc 0.68) |
| 7 | sin pareja/mal – ✗ (cc 0.54) | sin pareja/mal 0.35 ✗ (cc 0.50) | sin pareja/mal 0.53 ✓ (cc 0.53) | sin pareja/mal – ✗ (cc 0.56) | gris/juez 0.58 ✓ (cc 0.58) | sin pareja/mal – ✗ (cc 0.54) | sin pareja/mal 0.54 ✓ (cc 0.54) | sin pareja/mal – ✗ (cc 0.54) |
| 10 | sin pareja/mal 0.17 ✗ (cc 0.46) | gris/juez✗ 0.65 ✗ (cc 0.45) | gris/juez✗ 0.63 ✗ (cc 0.47) | sin pareja/mal 0.18 ✗ (cc 0.47) | sin pareja/mal 0.19 ✗ (cc 0.47) | sin pareja/mal 0.17 ✗ (cc 0.46) | gris/juez✗ 0.65 ✗ (cc 0.46) | sin pareja/mal 0.17 ✗ (cc 0.46) |
| 11 | gris/juez 0.57 ✓ (cc 0.57) | sin pareja/mal 0.50 ✓ (cc 0.50) | gris/juez 0.55 ✓ (cc 0.55) | gris/juez 0.58 ✓ (cc 0.58) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.57 ✓ (cc 0.57) | gris/juez 0.57 ✓ (cc 0.57) |
| 14 | gris/juez 0.66 ✓ (cc 0.66) | sin pareja/mal 0.45 ✓ (cc 0.60) | gris/juez 0.64 ✓ (cc 0.64) | gris/juez 0.65 ✓ (cc 0.65) | gris/juez 0.67 ✓ (cc 0.67) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.66 ✓ (cc 0.66) |

### a6972-6314 (A×SOP-6314, video 6972)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 4 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |
| 5 | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) | gris/juez 0.66 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.76 ✓ (cc 0.76) |
| 7 | aceptado/bien 0.78 ✓ (cc 0.78) | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.64 ✓ (cc 0.67) | gris/juez 0.75 ✓ (cc 0.75) | aceptado/bien 0.81 ✓ (cc 0.81) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) | aceptado/bien 0.78 ✓ (cc 0.78) |
| 8 | sin pareja/mal 0.35 ✗ (cc 0.68) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.73 ✓ (cc 0.73) | sin pareja/mal 0.34 ✗ (cc 0.68) | sin pareja/mal 0.31 ✗ (cc 0.62) | sin pareja/mal 0.35 ✗ (cc 0.68) | sin pareja/mal 0.38 ✗ (cc 0.76) | sin pareja/mal 0.35 ✗ (cc 0.68) |
| 10 | sin pareja/mal 0.53 ✗ (cc 0.48) | sin pareja/mal 0.49 ✓ (cc 0.49) | sin pareja/mal 0.27 ✗ (cc 0.51) | sin pareja/mal 0.52 ✗ (cc 0.51) | sin pareja/mal 0.51 ✗ (cc 0.49) | sin pareja/mal 0.53 ✗ (cc 0.48) | gris/juez✗ 0.62 ✗ (cc 0.49) | sin pareja/mal 0.53 ✗ (cc 0.48) |
| 11 | gris/juez 0.59 ✓ (cc 0.59) | sin pareja/mal 0.34 ✗ (cc 0.56) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.62 ✓ (cc 0.62) | gris/juez 0.63 ✓ (cc 0.63) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.59 ✓ (cc 0.59) |

### a8275-6314 (A×SOP-6314, video 8275)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 1 | aceptado/bien 0.75 ✓ (cc 0.75) | gris/juez 0.61 ✓ (cc 0.61) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.74 ✓ (cc 0.74) | aceptado/bien 0.76 ✓ (cc 0.76) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) | aceptado/bien 0.75 ✓ (cc 0.75) |
| 5 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) |
| 11 | sin pareja/mal 0.53 ✗ (cc 0.56) | sin pareja/mal 0.52 ✗ (cc 0.51) | sin pareja/mal 0.32 ✗ (cc 0.56) | sin pareja/mal 0.34 ✗ (cc 0.59) | gris/juez 0.61 ✓ (cc 0.61) | sin pareja/mal 0.53 ✗ (cc 0.56) | sin pareja/mal 0.53 ✗ (cc 0.56) | sin pareja/mal 0.53 ✗ (cc 0.56) |
| 12 | sin pareja/mal 0.40 ✓ (cc 0.61) | sin pareja/mal 0.37 ✓ (cc 0.60) | gris/juez 0.60 ✓ (cc 0.60) | gris/juez 0.59 ✓ (cc 0.59) | gris/juez 0.58 ✓ (cc 0.58) | sin pareja/mal 0.40 ✓ (cc 0.61) | sin pareja/mal 0.40 ✓ (cc 0.61) | sin pareja/mal 0.40 ✓ (cc 0.61) |

### a9696-6314 (A×SOP-6314, video 9696)

| SOP | a | b | c0.20 | c0.35 | c0.50 | d | e | f |
|---|---|---|---|---|---|---|---|---|
| 5 | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.70 ✓ (cc 0.70) | gris/juez 0.66 ✓ (cc 0.66) | gris/juez 0.72 ✓ (cc 0.72) | aceptado/bien 0.76 ✓ (cc 0.76) | gris/juez 0.72 ✓ (cc 0.72) |
| 6 | aceptado/bien 0.76 ✓ (cc 0.66) | gris/juez 0.68 ✓ (cc 0.63) | aceptado/bien 0.76 ✓ (cc 0.65) | aceptado/bien 0.78 ✓ (cc 0.69) | aceptado/bien 0.79 ✓ (cc 0.71) | aceptado/bien 0.76 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.66) | aceptado/bien 0.76 ✓ (cc 0.66) |
| 8 | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.79 ✓ (cc 0.79) | gris/juez 0.74 ✓ (cc 0.74) | gris/juez 0.65 ✓ (cc 0.65) | aceptado/bien 0.77 ✓ (cc 0.77) | aceptado/bien 0.82 ✓ (cc 0.82) | aceptado/bien 0.77 ✓ (cc 0.77) |

## Caída del coseno del par correcto por la cita (b − a > 0.2)

| Caso | Paso del SOP | a (con cita) | b (sin cita) | b − a |
|---|---|---|---|---|
| e6971-8158 | 6 | 0.538 | 0.893 | +0.355 |
| e6971-8158 | 9 | 0.757 | 0.959 | +0.202 |
| e8658-8158 | 6 | 0.287 | 0.682 | +0.395 |
| e8658-8158 | 9 | 0.757 | 0.959 | +0.202 |
| e8658-8158 | 11 | 0.596 | 0.913 | +0.317 |
| e8659-8158 | 6 | 0.307 | 0.755 | +0.448 |
| e8659-8158 | 9 | 0.757 | 0.959 | +0.202 |
| e8659-8158 | 15 | 0.617 | 0.833 | +0.216 |
| e9689-8158 | 6 | 0.287 | 0.682 | +0.395 |
| e9689-8158 | 9 | 0.757 | 0.959 | +0.202 |
| e9690-8158 | 6 | 0.307 | 0.755 | +0.448 |
| e9690-8158 | 9 | 0.757 | 0.959 | +0.202 |
| e9690-8158 | 15 | 0.627 | 0.830 | +0.203 |
| e9691-8158 | 6 | 0.307 | 0.755 | +0.448 |
| e9691-8158 | 9 | 0.757 | 0.959 | +0.202 |
| e9691-8158 | 15 | 0.627 | 0.830 | +0.203 |
| e6971-6314 | 6 | 0.538 | 0.893 | +0.355 |
| e8658-6314 | 6 | 0.287 | 0.682 | +0.395 |
| e8658-6314 | 11 | 0.610 | 0.882 | +0.272 |
| e8659-6314 | 6 | 0.307 | 0.755 | +0.448 |
| e9689-6314 | 6 | 0.287 | 0.682 | +0.395 |
| e9690-6314 | 6 | 0.307 | 0.755 | +0.448 |
| e9691-6314 | 6 | 0.307 | 0.755 | +0.448 |

## Control de causa: cita de Whisper contra la corregida (fixture del equipo)

| Par | sin cita | whisper | corregida_en | whisper_es | corregida_es |
|---|---|---|---|---|---|
| e6 | 0.755 | 0.307 | 0.513 | 0.741 | 0.798 |
| e6_ref | 0.582 | 0.314 | 0.429 | 0.587 | 0.660 |
| e9 | 0.959 | 0.757 | 0.757 | 0.952 | 0.952 |
| e11 | 0.893 | 0.753 | 0.697 | 0.871 | 0.825 |
| e15 | 0.833 | 0.617 | 0.624 | 0.850 | 0.843 |

