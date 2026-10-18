# ADR-005 · Conservar PostgreSQL de F0 en lugar de SQLite

- **Estado:** Aprobado por el equipo
- **Fecha:** 2026-10-17
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

F0 ya levanta PostgreSQL 16 (imagen `pgvector/pgvector:0.8.7-pg16-bookworm`) con Alembic, tests y CI. La
arquitectura de referencia del documento SOP V1.0 usa SQLite en `/data/app.db`, pero su sección 10 dice
"no obligatorio ni limitativo".

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · SQLite en un volumen | Un contenedor menos; lo que sugiere el documento | Rehacer la base, las migraciones y el CI de F0 |
| B · PostgreSQL 16 de F0 | Ya funciona; JSONB para análisis y reportes; pgvector listo para la versión 2 | Un servicio más en el compose |

## Decisión

**B.** Las cinco tablas del documento (`sops`, `videos`, `reportes`, `palabras`, `busquedas`) se crean
en PostgreSQL con Alembic. Los análisis, reportes y SOP se guardan como JSONB.

## Consecuencias

- **Positivas:** no se pierde trabajo; RNF-09 (persistencia tras reinicio) ya se cumple con el volumen.
- **Negativas / riesgos:** `docker compose up` levanta un servicio más; el README debe explicar cómo
  respaldar el volumen.
- **Seguimiento:** si la búsqueda exacta no cumple RNF-02 (< 1 s con 50 videos), indexar
  `palabra_normalizada`.

## Referencias

- Documento SOP V1.0, sección 10; `docker-compose.yml`; `migrations/`.
