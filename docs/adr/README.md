# Architecture Decision Records (ADR)

Registro de las decisiones de arquitectura del proyecto. Cada decisión relevante (qué se conserva, qué se reescribe, qué tecnología se adopta, qué deuda se tolera) se documenta en un ADR antes de implementarse.

## Índice

| ADR | Título | Estado | Fecha |
|---|---|---|---|
| [ADR-001](ADR-001-herencia.md) | Herencia del código: qué se conserva y qué se reescribe | Propuesto | _[completar]_ |

## Cómo crear un ADR

1. Copia [0000-plantilla.md](0000-plantilla.md) como `ADR-NNN-slug.md` con el siguiente número libre.
2. Llénalo con estado **Propuesto** y ábrelo en un Pull Request.
3. Al aprobarse, cambia el estado a **Aprobado** y actualiza la tabla de arriba.
4. Un ADR aprobado no se edita en su decisión: si cambia, se crea uno nuevo que lo **reemplaza** y se marca el anterior como _Reemplazado por ADR-XXX_.
