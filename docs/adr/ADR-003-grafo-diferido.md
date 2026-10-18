# ADR-003 · Diferir el grafo multi-video; un SOP es una lista ordenada de pasos

- **Estado:** Aprobado
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** patrocinador (documento SOP V1.0, 16 oct 2026), equipo

---

## Contexto

El NDA (cl. 1) y el brief proponen consolidar varios videos de un procedimiento en un grafo de tareas de
orden parcial. El documento SOP V1.0 define el SOP como una lista de pasos en orden (esquema de la
sección 10) y compara un video contra un SOP a la vez.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Grafo de orden parcial multi-video | Admite pasos intercambiables | Requiere varios videos por procedimiento y un algoritmo de fusión |
| B · Lista ordenada por SOP | Es el esquema del documento; el orden se revisa con código | Dos pasos intercambiables cuentan como *Fuera de orden* |

## Decisión

**B.** Un SOP es una lista ordenada de pasos con el esquema de la sección 10 del documento. El orden se
revisa con la subsecuencia creciente más larga de los pares emparejados (ADR-012).

## Consecuencias

- **Positivas:** un SOP generado sirve sin conversión para validar otros videos.
- **Negativas / riesgos:** pasos que en la práctica pueden ir en cualquier orden se reportan como fuera
  de orden; el supervisor puede marcarlos como falso positivo (RF-21).
- **Seguimiento:** la propuesta PR-03 del documento (proponer cambios al SOP) es el camino hacia un
  orden aprendido de varios videos.

## Referencias

- Documento SOP V1.0, secciones 5.3 y 10; NDA cl. 1; ADR-012.
