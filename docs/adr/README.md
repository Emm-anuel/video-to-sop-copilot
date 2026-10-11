# Architecture Decision Records (ADR)

Registro de las decisiones de arquitectura del proyecto. Cada decisión relevante (qué se conserva, qué se reescribe, qué tecnología se adopta, qué deuda se tolera) se documenta en un ADR antes de implementarse.

## Índice

| ADR | Título | Estado | Fecha |
|---|---|---|---|
| [ADR-001](ADR-001-herencia.md) | Herencia del código: qué se conserva y qué se reescribe | Propuesto | _[completar]_ |
| [ADR-006](ADR-006-llm-local.md) | LLM local servido con Ollama en Docker: Gemma 4 E4B en desarrollo, Gemma 4 mayor en producción si hay GPU de 24 GB | Propuesto | 2026-10-11 |
| [ADR-009](ADR-009-tarea-ml.md) | Mantener `has_errors` como tarea de ML académica | Aprobado por el equipo; falta el asesor | 2026-10-10 |
| [ADR-010](ADR-010-segmentacion-pasos-llm.md) | Segmentar la narración en pasos con un LLM local que elige segmentos, más corrección del experto | Propuesto | 2026-10-10 |

### Previstos (aún sin archivo)

Identificados en el [plan](../plan/plan.md#adrs). Cada uno se redacta con la plantilla antes de implementarse o cuando se tenga la aprobación correspondiente.

| ADR | Decisión | Aprueba | Estado |
|---|---|---|---|
| ADR-002 | Voz como fuente principal; V-JEPA 2 y fotogramas diferidos | Patrocinador (escrito) | Pendiente |
| ADR-003 | Grafo multi-video diferido; un video = lista ordenada de pasos | Patrocinador (escrito) | Pendiente |
| ADR-004 | Alcance ajustado por capacidad del equipo | Asesor + patrocinador | Pendiente |
| ADR-005 | PostgreSQL + pgvector en lugar del disco temporal de Colab | Equipo | Pendiente (implementado en F0) |
| ADR-007 | Frontend en Angular, desde cero | Equipo + patrocinador | Pendiente |
| ADR-008 | SOP y revisión humana opcionales; HITL de tres bucles fuera del MVP | Patrocinador (escrito) | Pendiente |

## Cómo crear un ADR

1. Copia [0000-plantilla.md](0000-plantilla.md) como `ADR-NNN-slug.md` con el siguiente número libre.
2. Llénalo con estado **Propuesto** y ábrelo en un Pull Request.
3. Al aprobarse, cambia el estado a **Aprobado** y actualiza la tabla de arriba.
4. Un ADR aprobado no se edita en su decisión: si cambia, se crea uno nuevo que lo **reemplaza** y se marca el anterior como _Reemplazado por ADR-XXX_.
