# ADR-011 · Ejecutar todo local y a costo cero (opción B)

- **Estado:** Aprobado
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** patrocinador (junta del 16 oct 2026), equipo

---

## Contexto

La arquitectura de referencia del documento SOP V1.0 usa OpenAI (whisper-1 y GPT-4o-mini) y su sección
8.1 deja al equipo elegir entre API, mini LLMs locales o híbrido. En la junta del 16 oct el equipo
propuso AWS Transcribe (~USD 1.40 por hora de video) y el patrocinador lo rechazó: "es cero gastos", ni
con dinero del equipo ni de la empresa. El producto final vive en el servidor del cliente para que no
pague APIs, y los videos y la voz son del cliente.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Solo API | Mejor calidad; imagen pequeña | Tiene costo; los videos salen a terceros |
| B · Solo modelos locales | Costo cero; privacidad; reproducible; sin internet | Menor calidad; necesita GPU |
| C · Híbrida | Calidad alta a bajo costo | Sigue teniendo costo |

## Decisión

**B.** Transcripción con faster-whisper, lenguaje y visión con Gemma 4 E4B en Ollama (ADR-006) y
emparejamiento con MiniLM (ADR-012), todo en la misma máquina. No se usa ninguna API externa, tampoco
para pruebas.

## Consecuencias

- **Positivas:** RNF-15 se cumple con USD 0 por video; RNF-10 no requiere clave de OpenAI; RNF-07 no
  depende de que un proveedor cambie su modelo.
- **Negativas / riesgos:** más riesgo de pasos inventados o mal emparejados (RNF-04 a 06); se mitiga con
  la cascada, JSON Schema, la cita verificada por código y la revisión humana.
- **Seguimiento:** reportar la calidad obtenida como resultado, como pidió el patrocinador.

## Referencias

- Documento SOP V1.0, secciones 7, 8 y 8.1; transcripción de la junta del 16 oct 2026; ADR-006.
