# Architecture Decision Records (ADR)

Registro de las decisiones de arquitectura del proyecto. Cada decisión relevante (qué se conserva, qué se reescribe, qué tecnología se adopta, qué deuda se tolera) se documenta en un ADR antes de implementarse.

## Índice

| ADR | Título | Estado | Fecha |
|---|---|---|---|
| [ADR-001](ADR-001-herencia.md) | Herencia del código: qué se conserva y qué se reescribe | Propuesto | _[completar]_ |
| [ADR-002](ADR-002-voz-fuente-principal.md) | Usar la voz como fuente principal y los fotogramas solo como descripción | Aprobado (documento SOP V1.0) | 2026-10-17 |
| [ADR-003](ADR-003-grafo-diferido.md) | Diferir el grafo multi-video; un SOP es una lista ordenada de pasos | Aprobado (documento SOP V1.0) | 2026-10-17 |
| [ADR-004](ADR-004-alcance-1-0.md) | Acotar la versión 1.0 a 29 Debe, 4 Debería y 2 Podría | Propuesto; se informa el 19 oct | 2026-10-17 |
| [ADR-005](ADR-005-postgresql.md) | Conservar PostgreSQL de F0 en lugar de SQLite | Aprobado por el equipo | 2026-10-17 |
| [ADR-006](ADR-006-llm-local.md) | LLM local servido con Ollama en Docker: Gemma 4 E4B. Desde el 17 oct también describe fotogramas | Propuesto | 2026-10-11 |
| [ADR-008](ADR-008-revision-humana.md) | Mantener la revisión humana dentro de 1.0; dejar roles, firmas y versiones fuera | Aprobado (documento SOP V1.0) | 2026-10-17 |
| [ADR-009](ADR-009-tarea-ml.md) | Mantener `has_errors` como tarea de ML académica | Aprobado por el equipo; falta el asesor | 2026-10-10 |
| [ADR-010](ADR-010-segmentacion-pasos-llm.md) | Segmentar la narración en pasos con un LLM local que elige segmentos. En 1.0 extrae los pasos del video (RF-13); ampliado el 19 oct con `PasoVideo`, cita verificada y contrato de análisis | Propuesto | 2026-10-10 |
| [ADR-011](ADR-011-costo-cero-local.md) | Ejecutar todo local y a costo cero (opción B) | Aprobado | 2026-10-17 |
| [ADR-012](ADR-012-emparejamiento-cascada.md) | Emparejar pasos con una cascada MiniLM → Gemma 4 | Propuesto | 2026-10-17 |
| [ADR-013](ADR-013-fusion-sobresegmentacion.md) | Fusionar pasos consecutivos del video antes de emparejar | Propuesto | 2026-10-17 |
| [ADR-014](ADR-014-hardware-referencia.md) | Usar la PC del equipo como hardware de referencia y correr los modelos en secuencia | Aprobado por el equipo | 2026-10-17 |

Los ADR-002, 003 y 008 se aprueban con el documento "Requerimientos técnicos y funcionales de proyecto
SOP V1.0", escrito por el patrocinador (16 oct 2026), que deja fuera de la versión 1.0 lo que el NDA
(cl. 1) nombraba. Plan vigente: [docs/plan/plan.md](../plan/plan.md).

### Previstos (aún sin archivo)

| ADR | Decisión | Aprueba | Estado |
|---|---|---|---|
| ADR-007 | Frontend en Angular, desde cero, servido por FastAPI | Equipo | Confirmado por el documento SOP V1.0; falta el archivo |

## Cómo crear un ADR

1. Copia [0000-plantilla.md](0000-plantilla.md) como `ADR-NNN-slug.md` con el siguiente número libre.
2. Llénalo con estado **Propuesto** y ábrelo en un Pull Request.
3. Al aprobarse, cambia el estado a **Aprobado** y actualiza la tabla de arriba.
4. Un ADR aprobado no se edita en su decisión: si cambia, se crea uno nuevo que lo **reemplaza** y se marca el anterior como _Reemplazado por ADR-XXX_.
