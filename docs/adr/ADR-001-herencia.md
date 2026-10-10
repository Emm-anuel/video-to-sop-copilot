# ADR-001 · Herencia del código: qué se conserva y qué se reescribe

- **Estado:** Propuesto _(pendiente de aprobación del asesor)_
- **Fecha:** _[completar]_
- **Autores:** Marie Kate Palau, Emmanuel Merida, Sara Castillo
- **Decisores:** equipo + asesor (Dr. Gerardo Jesús Camacho González)

> Regla del brief: la Semana 1 es una auditoría, no un arranque. **Nada heredado se descarta sin un ADR aprobado.** Reescribir un módulo sin ADR se trata como incumplimiento de entregable. La deuda técnica que se decide tolerar también se documenta.

---

## Contexto

Este proyecto ya se trabajó un trimestre. El equipo recibe el código como quedó, junto con la documentación de diseño existente. El riesgo conocido es el patrón más costoso en proyectos de continuidad: reescribir lo heredado, consumir la mitad del trimestre y entregar menos que el equipo anterior. Este ADR registra, tras clonar y correr lo heredado, qué se conserva, qué se reescribe y por qué.

## Inventario de módulos heredados

_(Completar tras clonar y ejecutar la base heredada.)_

| Módulo | Qué hace hoy | ¿Corre? | Estado | Decisión | Justificación |
|---|---|---|---|---|---|
| _p. ej. ingesta de video_ | ... | Sí / No / Parcial | Prototipo / Estable / Roto / Sin terminar | Conservar / Reescribir / Tolerar deuda | ... |
| ... | | | | | |

## Inventario de datos disponibles

_(Completar tras revisar lo heredado.)_

- Cantidad de videos y duración total: _[...]_
- Resolución y si tienen audio: _[...]_
- Cuántos SOPs escritos existen y a qué videos corresponden: _[...]_
- Conjunto de validación apartado y sellado (videos + su SOP de referencia): _[identificadores; nadie lo mira hasta la evaluación final]_

## Decisión

_(Redactar tras el análisis. Ejemplos del tipo de decisión que va aquí.)_

1. **Se conserva** _[módulo X]_ porque _[funciona y cubre su responsabilidad]_.
2. **Se reescribe** _[módulo Y]_ porque _[qué hace hoy, por qué no sirve, qué lo reemplaza]_.
3. **Se tolera la deuda técnica** de _[módulo Z]_ de forma consciente, para _[no gastar tiempo ahora]_; se revisará en _[semana]_.

## Consecuencias

- **Positivas:** _[no se arranca de cero; se avanza el problema en lugar de reconstruir]_.
- **Negativas / riesgos:** _[deuda tolerada, módulos frágiles, dependencias]_.
- **Pruebas de regresión:** la columna vertebral se declara estable solo cuando corre reproducible en una máquina limpia y pasa sus pruebas. Ninguna capacidad nueva se integra si rompe una prueba de regresión.

## Notas

- Un comando reproducible que levante lo heredado tal como está: `docker compose up` _(o el comando real; documentarlo)_.
- Este ADR es el entregable de auditoría de la Semana 1 junto con el inventario de módulos y de datos.
