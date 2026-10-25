# sopvid.percepcion

Frente de **percepción**: convierte un video en pasos con marca de tiempo.

| Etapa | Qué hace | Tecnología prevista |
|---|---|---|
| Ingesta | Recibe el video (archivo, cámara, teléfono) tras una misma interfaz; mide la duración y extrae el audio en mp3 mono a 16 kHz (`medios.py`) | ffmpeg |
| Transcripción | Texto con marcas de tiempo por segmento y palabra | faster-whisper |
| Pasos del video (RF-13) | Convierte el análisis del video en pasos con nombre, descripción, responsable, tiempos, cita, fuente y confianza, sin ver el SOP | LLM local que elige el segmento donde empieza cada paso y redacta el resto; heurística de transiciones y pausas como respaldo ([ADR-010](../../../docs/adr/ADR-010-segmentacion-pasos-llm.md)) |

## Contrato

La salida del pipeline de video es un `Analisis` y la extracción devuelve `PasoVideo`, ambos en
[sopvid/contrato.py](../contrato.py). El JSON Schema del análisis está en
[docs/contrato/analisis.schema.json](../../../docs/contrato/analisis.schema.json) y se regenera con
`python scripts/exportar_contrato.py`. Hay un ejemplo inventado en
[tests/fixtures/analisis_ejemplo.json](../../../tests/fixtures/analisis_ejemplo.json).

## `medios.py`

| Función | Qué hace |
|---|---|
| `duracion(video, timeout_s=None)` | Duración en segundos según ffprobe |
| `extraer_audio(video, destino, timeout_s=None)` | Audio en mp3 mono a 16 kHz (64 kbps). Escribe en un temporal `.part` (por eso pasa `-f mp3`) y lo renombra al terminar; crea la carpeta y sobrescribe |

ffmpeg y ffprobe se llaman con lista de argumentos, sin `shell=True`, con tope `FFMPEG_TIMEOUT_S`
(300 s por defecto). Errores, todos de `ErrorMedios`: `MedioInvalido` (no existe, ffmpeg no lo lee,
sin pista de audio), `FfmpegNoDisponible` y `FfmpegTiempoAgotado`. Con `-v error`, ffmpeg no
imprime los metadatos del archivo. Las rutas de destino se arman bajo `MEDIA_DIR` (`media/` por
defecto, ignorada por Git). Las pruebas (`tests/test_medios.py`) generan su propio video con
`lavfi` y se saltan si ffmpeg no está instalado.

## `segmentacion.py`

| Función | Qué hace |
|---|---|
| `segmentar(analisis, llm, etiquetas=None)` | Punto de entrada. Por defecto, opción A de ADR-010: una llamada para las fronteras y otra para la redacción, cada una con hasta 3 intentos (RNF-07). Si fallan las fronteras, usa la heurística. La redacción se valida paso por paso: el reintento pide solo los pasos que faltan o fallaron, y los que nunca se logran conservan su frontera sin redactar. Devuelve `Segmentacion` con `list[PasoVideo]`, el camino usado y los intentos de cada llamada |
| `construir_mensajes_fronteras` | Llamada 1: el prompt v1 de la Fase 4 (`PropuestaFrontera`: segmento y título). Sin tiempos y sin SOP |
| `construir_mensajes_redaccion` | Llamada 2: los pasos ya fijados, para redactar descripción, responsable y una cita de 4 a 15 palabras (`RedaccionPaso`; una cita más larga se recorta con `recortar_cita`). Los segmentos van sin número, para que no se confundan con los pasos; el responsable se pide como puesto, nunca como nombre, y sin ejemplos de rol |
| `construir_mensajes`, `construir_pasos` | Llamada única (`dos_llamadas=False`, descartada como valor por defecto): cortes y redacción a la vez; `construir_pasos` arma `PasoVideo` con tiempos del índice |
| `verificar_cita` | Confianza y fuente según dónde aparece la cita: en el paso, en otra parte o en ninguna (RNF-06) |
| `normalizar_responsable`, `rol_mencionado` | Responsable dicho en el audio o "No identificado"; si el rol no se dice, la confianza baja un nivel (ADR-008) |
| `segmentar_heuristica` | Respaldo sin LLM, siempre con confianza baja |
| `cargar_transcripcion_prueba`, `f1_fronteras`, `segmentos_de_inicio` | Evaluación con las transcripciones de prueba (`scripts/evaluar_segmentacion.py`) |

Reglas que el código hace cumplir: el LLM nunca escribe un tiempo (un campo de tiempo invalida la
propuesta), toda cita se verifica contra la transcripción y los mensajes de error y del log nunca
copian texto de la transcripción.

**Estado:** la extracción de pasos del video (RF-13) está implementada y probada con un LLM simulado
(cobertura del 100 %). La evaluación del 18 oct con `gemma4:e4b` da F1 0.645 contra 0.741 de la
Fase 4; la mejora pendiente está en la sección "Ampliación 19 oct (RF-13)" de ADR-010. De la ingesta ya
están la duración y el audio (`medios.py`); la subida y la transcripción todavía no tienen código (ver el [plan](../../../docs/plan/plan.md)).

> El modelo académico de `has_errors` (avances 2–5, `sopvid.features`) es la base de las futuras advertencias del copiloto. Solo usa información que este frente puede producir de un video segmentado: tiempos, orden y tipo de paso.

> El video y el audio del cliente **nunca** se guardan dentro del repo (ver [data/README.md](../../../data/README.md)). En desarrollo se usan datasets públicos bajo `data/raw/` o `media/`, ambas rutas ignoradas por Git.
