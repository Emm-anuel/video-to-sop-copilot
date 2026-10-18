# ADR-008 · Mantener la revisión humana dentro de 1.0; dejar roles, firmas y versiones fuera

- **Estado:** Aprobado
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** patrocinador (documento SOP V1.0, 16 oct 2026), equipo

---

## Contexto

El brief y el NDA proponen un HITL de tres bucles, varios roles y aprobación con versión. El documento
SOP V1.0 pide que una persona corrija lo que propone la IA (RF-04, RF-21, RF-26) y deja fuera la vista
de administrador, el control de versiones del SOP, la aprobación con firmas y el reconocimiento de
personas por rostro.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · HITL de tres bucles, roles y versiones | Lo del brief | Fuera del alcance del documento |
| B · Corrección humana en tres puntos, sin roles ni versiones | Lo que pide el documento | Sin trazabilidad de quién aprobó |

## Decisión

**B.** El supervisor corrige el SOP convertido antes de comparar (RF-04), edita el SOP generado
(RF-26) y, si entra, marca hallazgos como aceptados o falsos positivos (RF-21). Dos vistas con clave de
acceso por variable de entorno, sin cuentas. Las personas del video se identifican por lo que dicen y
su rol, sin diarización (PR-04 queda para la versión 2).

## Consecuencias

- **Positivas:** la IA nunca decide sola; cumple RNF-06 junto con la cita obligatoria.
- **Negativas / riesgos:** con varias voces que no se nombran, el responsable queda como *No
  identificado*.
- **Seguimiento:** PR-06 y PR-07 del documento (versiones y aprobación) en la versión 2.

## Referencias

- Documento SOP V1.0, secciones 2, 3 y 16; brief §10; NDA cl. 1.
