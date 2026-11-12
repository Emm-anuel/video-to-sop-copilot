# sopvid.percepcion

Frente de **percepción**: convierte un video en pasos con marca de tiempo.

| Etapa | Qué hace | Tecnología prevista |
|---|---|---|
| Ingesta | Recibe el video (archivo, cámara, teléfono) tras una misma interfaz; mide la duración y extrae el audio en mp3 mono a 16 kHz (`medios.py`) | ffmpeg |
| Transcripción (RF-09, RF-10) | Idioma con confianza (o fijado a mano) y texto con tiempo por segmento y por palabra; TXT que se escribe mientras avanza (`transcripcion.py`) | faster-whisper |
| Análisis del video | Une ingesta y transcripción en un `Analisis` validado del contrato, con avance por etapa (`pipeline.py`, `scripts/analizar_video.py`) | — |
| Ficha de contexto (RF-12) | Actividad, tema, lugar, horario, propósito, resumen, personas y equipos del video, cada dato con su evidencia (`contexto.py`) | LLM local con citas que el código verifica contra la transcripción |
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
| `tiene_imagen(video)` | Hay una pista de video que no es una portada (`attached_pic`) |
| `extraer_cuadro(video, t, destino, lado_px)` | JPEG del cuadro en `t`, con el lado mayor de `lado_px` (sin agrandar); temporal `.part` y renombre |
| `luma_maxima(video, t)` / `imagen_visible(video, duracion_s)` | Luma máxima de un cuadro (`signalstats`) y si alguno de 5 cuadros parejos pasa de `UMBRAL_NEGRO`: sin pista o todo negro, no hay imagen |

ffmpeg y ffprobe se llaman con lista de argumentos, sin `shell=True`, con tope `FFMPEG_TIMEOUT_S`
(300 s por defecto). Errores, todos de `ErrorMedios`: `MedioInvalido` (no existe, ffmpeg no lo lee,
sin pista de audio), `FfmpegNoDisponible` y `FfmpegTiempoAgotado`. Con `-v error`, ffmpeg no
imprime los metadatos del archivo. Las rutas de destino se arman bajo `MEDIA_DIR` (`media/` por
defecto, ignorada por Git). Las pruebas (`tests/test_medios.py`) generan su propio video con
`lavfi` y se saltan si ffmpeg no está instalado.

## `transcripcion.py`

| Pieza | Qué hace |
|---|---|
| `Transcriptor` (Protocol) | `transcribir(audio, idioma=None, al_segmento=None) -> Transcripcion` |
| `TranscriptorWhisper(settings=None, fabrica=None)` | faster-whisper con tiempo por palabra, VAD, temperatura 0, beam 5 y sin condicionar en el texto previo (RNF-07). Carga el modelo en cada llamada y lo libera al terminar (ADR-014). Con `idioma` lo fuerza (`fijado_a_mano=True`); si no, usa el detectado y su probabilidad. Con dispositivo `auto`, si cuda falla antes del primer segmento repite en CPU con un aviso |
| `Transcripcion` | Idioma, segmentos del contrato, duración del audio, modelo, dispositivo y compute type **con los que corrió**, segundos de proceso y `respaldo_cpu` |
| `normalizar(crudos)` | Segmentos de faster-whisper → `Segmento` del contrato: ids desde 0, sin vacíos ni espacios sobrantes, sin solaparse (recorta el inicio al fin del anterior), palabras no decrecientes y dentro del segmento, tiempos ≥ 0 en milisegundos |
| `escritor_txt(ruta)` | Context manager que da el callback `al_segmento`: una línea `[mm:ss] texto` por segmento, con flush (RF-10) |
| `elegir_dispositivo` | `auto` → cuda si hay GPU; compute `auto` → float16 en cuda, int8 en cpu |

Configuración: `WHISPER_MODELO`, `WHISPER_DISPOSITIVO`, `WHISPER_COMPUTE_TYPE`,
`WHISPER_CACHE_DIR`. Perfiles CPU y gpu, GPU en Windows y Docker: [docs/dev/transcripcion.md](../../../docs/dev/transcripcion.md).
Los logs solo llevan conteos, tiempos e idioma. Las pruebas simulan el modelo; la marcada `lento`
usa el audio de `SOPVID_AUDIO_PRUEBA` (fuera del repo).

## `pipeline.py`

`analizar_video(video, video_id, idioma, transcriptor, trabajo_dir, al_avanzar=None) -> Analisis`:
duración → audio → transcripción, y valida el resultado con `Analisis.model_validate` antes de
devolverlo. Deja en `trabajo_dir` el `audio.mp3` y el `transcripcion.txt`, que se escribe mientras
avanza. `duracion_s` va en milisegundos, como los tiempos de la transcripción, y lo que Whisper
deja más allá del final del video (inicio y fin de segmentos y palabras) se recorta a ella. `fotogramas` va vacía: las imágenes se describen después, con Gemma ya cargado (`fotogramas.py`).

- El transcriptor se inyecta (RNF-14); el pipeline no crea modelos.
- `al_avanzar(etapa, porcentaje)`: avance global entero que nunca retrocede y solo se informa
  cuando cambia. `duracion` 0 → `audio` 5 → `transcripcion` 15–95 (según el fin de cada segmento)
  → `listo` 100, que solo llega con el `Analisis` validado.

`scripts/analizar_video.py VIDEO [--salida DIR] [--idioma es] [--video-id N] [--sobrescribir]`
escribe `analisis.json`, el TXT y el audio en `MEDIA_DIR/<nombre del video>/` (o en `--salida`).
Si ya hay un `analisis.json`, sale con código 1 sin procesar nada, salvo con `--sobrescribir`. El
JSON entra tal cual a `segmentacion.segmentar` y después al emparejamiento.

## `miniaturas.py` (RF-11, ADR-024)

La miniatura por paso, siempre, con ffmpeg y sin modelo: una por fila del reporte con segundo y
una por paso del SOP generado, en `media/videos/<id>/miniaturas/t<ms>.jpg`. `GET /videos/{id}/thumb`
reusa la guardada a ≤ 1 s (`TOLERANCIA_S`, RNF-03) o saca una nueva; el reporte saca cada fila en
su segundo exacto. Sin imagen visible, la carpeta lleva la marca `SIN_IMAGEN` y el resultado el
aviso informativo `sin_imagen` (no vuelve provisional el reporte).

## `fotogramas.py` (RF-11, ADR-024)

Descripción opcional (apagada por defecto) de N imágenes repartidas de forma pareja, antes de la
ficha y en la misma carga de Gemma. N = pasos del SOP (validar) o duración × `PASOS_POR_MIN`
(generar), entre `FOTOGRAMAS_MIN` y `FOTOGRAMAS_MAX` (≤ 20, ADR-002); `contexto.py` no tiene tope
propio. Lotes de `FOTOGRAMAS_LOTE` imágenes en `chat_en_flujo` con el prompt
`lenguaje/prompts/fotogramas_v1.md` y un esquema con solo `i`, `descripcion`, `equipos`,
`personas` (conteo), `texto_visible` y `riesgos`; hasta 3 intentos por lote. El código pone `t` y
`archivo`, ordena por `t` y descarta índices fuera del lote, repetidos o sin descripción. Un lote
fallido o un Ollama caído dejan el aviso `imagenes_incompletas` y el análisis sigue. Si Ollama
responde sin memoria (VRAM o RAM), el lote baja a la mitad y se reintenta una vez; los lotes
siguientes van con ese tamaño. `FOTOGRAMAS_LOTE` es la palanca para equipos con menos memoria.
Los JPEG (fotogramas y miniaturas) salen de una sola llamada a ffmpeg por tanda (`extraer_cuadros`).

## `contexto.py`

`generar_contexto(analisis, cliente_llm) -> ResultadoContexto`: la ficha de contexto (RF-12) con
Gemma 4 y el prompt versionado `lenguaje/prompts/contexto_v2.md` (la v1 se conserva). Corre después de la
transcripción y antes de los pasos del video, en la misma ventana de Gemma (`validar`, o sola en
modo generar).

- Entrada: los segmentos con su número (`[s=N]`) y el idioma; si el análisis trae fotogramas,
  también cada uno con el suyo (`[f=N]`, desde 1 y por posición) y la sección del prompt que
  explica cómo citarlos. Sin fotogramas ni el prompt ni el esquema los mencionan
  (`ESQUEMA_CONTEXTO` frente a `ESQUEMA_CONTEXTO_FOTOGRAMAS`). Nunca el SOP ni tiempos.
- El modelo escribe valores y citas; el código pone fuente, confianza y segundo (regla 4): cita
  encontrada → "audio" y el inicio del primer segmento donde aparece, con confianza "alta" si
  tiene de 4 a 25 palabras y "media" si tiene 2 o 3 (menos de 2, inferido); fotograma que existe
  → "visual", "media" y su `t`; nada → "inferido", "baja" y sin `t`. El resumen va "inferido" y
  "media". Una persona sin cita verificada ni fotograma se descarta (`Persona.t` es obligatorio).
- Llamada en flujo: primer token en `LLM_TIMEOUT_S`, `LLM_INACTIVIDAD_S` sin tokens, tope total
  `LLM_TIMEOUT_CONTEXTO_S` (600 s); hasta 3 intentos solo por JSON inválido. Nunca lanza: la
  ficha va vacía con `motivo`, y `aviso_contexto` da el aviso "contexto_sin_generar".
- `ResultadoContexto` trae intentos, tokens de entrada y de salida, espera al primer token,
  tokens/s, segundos, fotogramas en la entrada, citas no verificadas y personas descartadas.

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
Fase 4; la mejora pendiente está en la sección "Ampliación 19 oct (RF-13)" de ADR-010. Del video al `Analisis`
ya están la duración y el audio (`medios.py`), la transcripción con idioma (`transcripcion.py`) y
su unión con avance por etapa (`pipeline.py`, `scripts/analizar_video.py`); faltan la subida y
los fotogramas (ver el [plan](../../../docs/plan/plan.md)).

> El modelo académico de `has_errors` (avances 2–5, `sopvid.features`) es la base de las futuras advertencias del copiloto. Solo usa información que este frente puede producir de un video segmentado: tiempos, orden y tipo de paso.

> El video y el audio del cliente **nunca** se guardan dentro del repo (ver [data/README.md](../../../data/README.md)). En desarrollo se usan datasets públicos bajo `data/raw/` o `media/`, ambas rutas ignoradas por Git.
