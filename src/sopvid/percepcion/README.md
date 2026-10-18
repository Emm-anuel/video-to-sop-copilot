# sopvid.percepcion

Frente de **percepción**: convierte un video en pasos con marca de tiempo.

| Etapa | Qué hace | Tecnología prevista |
|---|---|---|
| Ingesta | Recibe el video (archivo, cámara, teléfono) tras una misma interfaz y extrae el audio | ffmpeg |
| Transcripción | Texto con marcas de tiempo por segmento y palabra | faster-whisper |
| Pasos del video (RF-13) | Convierte el análisis del video en pasos con nombre, descripción, responsable, tiempos, cita, fuente y confianza, sin ver el SOP | LLM local que elige el segmento donde empieza cada paso y redacta el resto; heurística de transiciones y pausas como respaldo ([ADR-010](../../../docs/adr/ADR-010-segmentacion-pasos-llm.md)) |

## Contrato

La salida del pipeline de video es un `Analisis` y la extracción devuelve `PasoVideo`, ambos en
[sopvid/contrato.py](../contrato.py). El JSON Schema del análisis está en
[docs/contrato/analisis.schema.json](../../../docs/contrato/analisis.schema.json) y se regenera con
`python scripts/exportar_contrato.py`. Hay un ejemplo inventado en
[tests/fixtures/analisis_ejemplo.json](../../../tests/fixtures/analisis_ejemplo.json).

## `segmentacion.py`

| Función | Qué hace |
|---|---|
| `segmentar(analisis, llm, etiquetas=None)` | Punto de entrada: LLM con hasta 3 intentos (RNF-07) y, si falla, la heurística. Devuelve `Segmentacion` con `list[PasoVideo]`, el camino usado y los intentos |
| `construir_mensajes` | Prompt con los segmentos numerados y las etiquetas opcionales: sin tiempos y sin SOP |
| `construir_pasos` | Valida la respuesta del LLM (`PropuestaPaso`) y arma `PasoVideo` con tiempos del índice |
| `verificar_cita` | Confianza y fuente según dónde aparece la cita: en el paso, en otra parte o en ninguna (RNF-06) |
| `normalizar_responsable`, `rol_mencionado` | Responsable dicho en el audio o "No identificado"; si el rol no se dice, la confianza baja un nivel (ADR-008) |
| `segmentar_heuristica` | Respaldo sin LLM, siempre con confianza baja |
| `cargar_transcripcion_prueba`, `f1_fronteras`, `segmentos_de_inicio` | Evaluación con las transcripciones de prueba (`scripts/evaluar_segmentacion.py`) |

Reglas que el código hace cumplir: el LLM nunca escribe un tiempo (un campo de tiempo invalida la
propuesta), toda cita se verifica contra la transcripción y los mensajes de error y del log nunca
copian texto de la transcripción.

**Estado:** la extracción de pasos del video (RF-13) está implementada y probada con un LLM simulado
(cobertura del 100 %). La evaluación del 18 oct con `gemma4:e4b` da F1 0.645 contra 0.741 de la
Fase 4; la mejora pendiente está en la sección "Ampliación 19 oct (RF-13)" de ADR-010. Ingesta y
transcripción todavía no tienen código (ver el [plan](../../../docs/plan/plan.md)).

> El modelo académico de `has_errors` (avances 2–5, `sopvid.features`) es la base de las futuras advertencias del copiloto. Solo usa información que este frente puede producir de un video segmentado: tiempos, orden y tipo de paso.

> El video y el audio del cliente **nunca** se guardan dentro del repo (ver [data/README.md](../../../data/README.md)). En desarrollo se usan datasets públicos bajo `data/raw/` o `media/`, ambas rutas ignoradas por Git.
