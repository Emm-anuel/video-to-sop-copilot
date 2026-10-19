# Estado del proyecto · 17 oct 2026

Resumen para el equipo y el asesor. El plan completo está en [plan.md](plan.md).

## Qué cambió esta semana

- **13 oct:** el patrocinador pidió seguir con la arquitectura propia y llevarla hacia modelos pequeños.
- **16 oct, junta con el patrocinador:** entregó el documento **"Requerimientos técnicos y funcionales
  de proyecto SOP V1.0"** (37 requerimientos) y fijó **costo cero**: nada de servicios de pago, ni con
  dinero del equipo ni de la empresa. Todo el producto será local en el servidor del cliente. Le
  interesa publicar un paper con los resultados de los modelos pequeños. Pidió priorizar la
  calificación y seguir los entregables de Canvas.
- **17 oct:** se reescribió el plan para la versión 1.0 del documento (validar video contra SOP,
  generar SOP y búsqueda exacta). Decisiones en [plan.md §2](plan.md#2-decisiones).

## Lo que ya está hecho

**Académico**
- Avances 1 y 2 entregados (`has_errors` sobre CaptainCook4D; `build_features` listo para el avance 3).

**Repositorio**
- **`main`:** F0 (API con `/health`, Postgres 16 con pgvector vía Alembic, Docker, tests, CI) y
  `sopvid.features`.
- **`feat/llm-spike` (fusionada en `main`, merge `936af6f`):** cliente del LLM, Ollama 0.40.2 en Docker, benchmark de modelos
  (ADR-006) y prototipo de segmentación por segmentos numerados (ADR-010). Ambos se reutilizan en 1.0:
  el cliente para todas las tareas de Gemma 4 y la segmentación para extraer los pasos del video (RF-13).

**Hardware de referencia (ADR-014):** PC de Emmanuel con RTX 2070 SUPER de 8 GB, i7-10700K, 32 GB de
RAM, SSD con ~199 GB libres, Windows 11, WSL2 y Docker 29.8.

## Lo que falta

| Cuándo | Qué |
|---|---|
| **Dom 18 oct, 23:59** | **Avance 3** (baseline) desde `build_features` |
| Lun 19 oct | Junta con Jorge: informar decisiones y preguntar la fecha de la demo ([plan §10](plan.md#10-para-la-junta-del-lunes-19-oct)) |
| S2 | ✓ `feat/llm-spike` fusionada a `main` (merge `936af6f`); repo privado; tablas `videos`, `sops`, `reportes`; grabar videos A–E |
| Dom 25 oct | Avance 4 |
| Dom 1 nov | Avance 5 |
| Dom 8 nov | ✓ **MVP de validación**: video + SOP en Markdown → reporte con segundo; pasan los videos A y B ([plan §5.1](plan.md#51-mvp-de-validación-hito-del-8-nov)) |
| Dom 15 nov | ✓ SOP generado, personas, tiempos y afinidad: pasan los videos C, D y E |
| Dom 22 nov | ✓ App completa en Docker en máquina limpia |

## Resumen en dos frases

> El patrocinador fijó el producto 1.0 (validar videos contra su SOP o generarlo, y buscar al segundo
> exacto) y pidió costo cero, así que todo corre local con Gemma 4 E4B, faster-whisper y MiniLM en una
> GPU de 8 GB. Los avances académicos siguen con `has_errors`, y los experimentos del producto alimentan
> un paper sobre modelos pequeños locales.
