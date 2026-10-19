# ADR-015 · Convertir el SOP de referencia con una plantilla y un parser; Gemma 4 solo sin plantilla

- **Estado:** Propuesto
- **Fecha:** 2026-10-19
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

El documento SOP V1.0 (§5.1) pide un LLM para convertir el SOP de referencia al esquema de su
sección 10. ADR-006 lo dejó como uno de los usos de Gemma 4. Pero el MVP de validación (8 nov,
plan §5.1) solo necesita SOP en TXT o Markdown escritos por el equipo (RF-03). Los SOP del
cliente, en PDF o Word (RF-01 y RF-02), llegan en S5.

Un SOP convertido a medias contamina todo lo que viene después: un paso de más o de menos sale
en el reporte como *Falta* o *Sobra*. Las pruebas de regresión (regla 7) necesitan una conversión
que dé siempre lo mismo y que corra en CI sin Ollama ni GPU (ADR-014). También hay que respetar el
costo cero (ADR-011) y el NDA: los errores y el log no pueden citar texto del SOP.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Gemma 4 para todo | Acepta cualquier formato desde el primer día | No es determinista; ocupa la GPU, que se comparte con faster-whisper; las pruebas necesitan Ollama; puede inventar o fusionar pasos |
| B · Plantilla + parser con código; Gemma 4 solo para texto libre, PDF y Word en S5 | Determinista y probado sin Ollama; cubre el MVP; deja RF-01 y RF-02 para cuando hagan falta | Hay que escribir los SOP del MVP en la plantilla; dos caminos de entrada que mantener |
| C · Solo plantilla | Lo más simple | No cumple RF-01 ni RF-02: los SOP del cliente en PDF o Word no entran |

## Decisión

**B.** Un SOP en Markdown o TXT que sigue `docs/contrato/plantilla_sop.md` se convierte con
código, sin LLM (`sopvid.lenguaje.sop_markdown.convertir_sop`), al contrato `sopvid.contrato.SOP`.
La plantilla solo exige "# Título" y "## Pasos". Lo que no aparece queda vacío, nunca inventado.
Las desviaciones menores (numeración, claves desconocidas, tiempos, nombres que no empiezan en
infinitivo) se corrigen o se ignoran y quedan como advertencias con tipo y línea. Sin título, sin
pasos o con un paso sin nombre, la conversión falla con un mensaje que dice el formato esperado.
`sop_a_markdown` escribe un SOP con la misma plantilla, y `scripts/convertir_sop.py` convierte un
archivo a JSON.

Gemma 4 convierte solo los SOP sin plantilla (texto libre, PDF y Word) en S5. Su salida se
valida contra el mismo contrato `SOP`; el diseño de ese camino se decide al implementarlo.

## Consecuencias

- **Positivas:** la conversión es determinista, se prueba sin Ollama ni base de datos y cuesta
  cero. Un SOP fuera de plantilla falla con un mensaje claro en lugar de convertirse a medias. Los
  errores, las advertencias y el log citan números de paso y de línea, no texto del SOP. Las
  advertencias tienen un tipo estable, para agruparlas en la pantalla de corrección (RF-04).
- **Negativas / riesgos:** los SOP del MVP se escriben a mano en la plantilla. La plantilla no
  tiene cómo escapar sus separadores (":", ",", ";", "Paso:" y "Control:" en un riesgo).
  `sop_a_markdown` no lleva los metadatos (confianza, fuente, tiempos) ni los puntos y palabras
  clave: para eso, la fuente de verdad es el JSON.
- **Seguimiento:** en S5, al implementar RF-01 y RF-02, se mide cuántos SOP reales (por
  identificador, sin copiarlos al repo) siguen la plantilla y cuántos necesitan a Gemma 4. Se
  decide entonces si la salida del LLM pasa por la misma revisión humana (RF-04).

## Referencias

- Documento SOP V1.0, §5.1 y §10; plan §5.1 (MVP de validación).
- RF-01 a RF-05; ADR-004, ADR-006 (usos de Gemma 4), ADR-011, ADR-014.
- `docs/contrato/plantilla_sop.md`, `src/sopvid/lenguaje/sop_markdown.py`,
  `scripts/convertir_sop.py`, `tests/test_sop_markdown.py`.
