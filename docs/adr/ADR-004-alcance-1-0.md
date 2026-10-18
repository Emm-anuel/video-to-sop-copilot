# ADR-004 · Acotar la versión 1.0 a 29 Debe, 4 Debería y 2 Podría

- **Estado:** Propuesto
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** equipo; se informa al patrocinador el 19 oct 2026

---

## Contexto

El documento SOP V1.0 tiene 37 requerimientos funcionales: 29 *Debe*, 6 *Debería* y 2 *Podría* según
su propio conteo (en la tabla aparecen 3 *Podría*: RF-16, RF-28 y RF-35). El patrocinador aclaró que no
es necesario terminarlos todos. El equipo es de dos personas, y una de ellas lleva los avances
académicos hasta el 1 nov.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Solo los 29 *Debe* | Lo mínimo | El video de prueba C evalúa tiempos (RF-16, *Podría*) |
| B · *Debe* + los *Debería* y *Podría* que evalúan las pruebas o son baratos | Cubre los 5 videos de prueba | Más trabajo |
| C · Los 37 | Completo | No cabe en el tiempo |

## Decisión

**B.** Entran los 29 *Debe*; de los *Debería*, RF-04, RF-25, RF-31 y RF-37; de los *Podría*, RF-16
(tiempos) y RF-35 (unir resultados a menos de 3 s). RF-18 y RF-21 entran solo si la validación está
estable el 8 nov. RF-28 (diagrama de flujo, glosario, preguntas pendientes) queda fuera.

## Consecuencias

- **Positivas:** los 5 videos de prueba (sección 14) se pueden evaluar completos.
- **Negativas / riesgos:** sin RF-18 la validación no revisa EPP paso por paso; sin RF-21 no se marcan
  falsos positivos en la app.
- **Seguimiento:** revisión en el checkpoint del 8 nov. Responsable y semana por requerimiento en
  `docs/plan/plan.md` §5.

## Referencias

- Documento SOP V1.0, secciones 2, 4 y 14; plan §5.
