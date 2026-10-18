# ADR-002 · Usar la voz como fuente principal y los fotogramas solo como descripción

- **Estado:** Aprobado
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** patrocinador (documento SOP V1.0, 16 oct 2026), equipo

---

## Contexto

El NDA (cl. 1) y el brief proponen V-JEPA 2 con attentive probes para percibir acciones en video. En la
junta del 3 oct el patrocinador dijo que "hoy el camino es la voz", y en la del 16 oct que el trabajo es
"analizar la voz y cazar la palabra con la imagen", no "digerir videos". Su documento SOP V1.0 pide
describir fotogramas (RF-11) y no menciona percepción de acciones.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · V-JEPA 2 por segmento | Lo que nombra el NDA; ve acciones sin narración | Entrenar probes sin datos etiquetados; GPU; semanas de trabajo |
| B · Voz + descripción de fotogramas con un VLM | Lo que pide el documento; un solo modelo (Gemma 4 E4B, ADR-006) | No detecta acciones que el operador no narra |
| C · Solo voz | Lo más simple | No cumple RF-11 |

## Decisión

**B.** Un paso cuenta como hecho si el operador lo narra o si se ve en el video (sección 5 del
documento). Se describen hasta 20 fotogramas con Gemma 4 E4B: equipos, personas visibles, texto legible
y riesgos. V-JEPA 2 queda diferido.

## Consecuencias

- **Positivas:** cumple RF-11 sin un modelo extra; la imagen confirma equipos, EPP y riesgos.
- **Negativas / riesgos:** un paso que no se narra y se ve poco puede quedar como *Falta*.
- **Seguimiento:** ablación con y sin fotogramas en los experimentos del paper (plan §8).

## Referencias

- Documento "Requerimientos técnicos y funcionales de proyecto SOP V1.0", secciones 2, 5 y 6.
- NDA cl. 1; brief §9; ADR-006.
