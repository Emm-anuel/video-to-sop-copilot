# API de SOP y videos (desarrollo y demo)

Carga del SOP de referencia (RF-01 a RF-03), subida de un video completo (RF-06 del MVP; la
subida por partes es de S5), conversión del SOP, análisis y validación en una cola de un
trabajador con prioridad (un modelo en memoria a la vez, ADR-014; un SOP va antes que el
siguiente video) y consulta del avance, el TXT en vivo (RF-10), el `Analisis`, la ficha de
contexto (RF-12) y el reporte (RF-14, RF-19). Código: `sopvid.plataforma.api` (`sops`, `videos`), `sopvid.plataforma.procesamiento` y
`sopvid.lenguaje.validacion`.

| Método y ruta | Qué hace |
|---|---|
| `POST /sops` | Multipart: `archivo` (.md, .txt, .pdf o .docx; texto hasta 1 MB, PDF y Word hasta 20 MB). Revisa que se pueda leer y responde **202** con el `EstadoSop` (`docs/contrato/sop_estado.schema.json`, `estado: "en_cola"`) y `Location: /sops/<id>/estado`; la conversión (plantilla o Gemma 4, ADR-015) corre en el trabajador. 415 si la extensión no está permitida, 413 si pasa del límite, 422 si no se puede leer (PDF escaneado, archivo dañado, texto que no es UTF-8) |
| `GET /sops/{id}/estado` | `EstadoSop`: `estado` (`en_cola`, `convirtiendo`, `listo`, `error`), `titulo`, `metodo` (`plantilla` o `llm`) y `advertencias` al terminar, `mensaje` si falló (título de más de 300 caracteres, Ollama caído, conversión que pasó de `LLM_TIMEOUT_SOP_S`…). Consultarlo cada 2 s |
| `GET /sops/{id}` | `{"id", "codigo", "origen", "creado", "metodo", "advertencias", "en_biblioteca", "generacion", "sop"}` con el `SOP` del contrato (`generacion`: cómo se generó desde el video, ADR-023; null en un SOP cargado); **409** con `{"mensaje", "estado", "error"}` mientras no esté listo |
| `PUT /sops/{id}` | Guarda la versión corregida (RF-04, RF-26): el cuerpo es el `SOP` completo del contrato. **422** si no lo cumple (sin pasos, numeración rota, un campo de más) o si el título pasa de 300 caracteres, sin tocar el guardado; **409** si no está listo |
| `POST /sops/{id}/biblioteca` | Guarda el SOP en la biblioteca (RF-27): desde ahí sirve como `sop_id` en `POST /videos`, sin conversión. Responde el `EstadoSop` (`en_biblioteca: true`); idempotente; **409** si no está listo. Los SOP cargados ya están |
| `GET /sops/{id}.md` | El SOP en la plantilla Markdown (`text/markdown`, `sop_a_markdown`); `convertir_sop` lo vuelve a leer con el mismo contenido de la plantilla (la evidencia, los tiempos del video y los puntos y palabras clave solo van en el JSON). **409** si no está listo |
| `POST /videos` | Multipart: `archivo` (mp4, mov, mkv o webm), `titulo`, `modo` (`validar` o `generar`), en modo validar `sop_id` **o** `sop` (archivo del SOP, RF-02; prohibidos con `generar`) e `idioma` opcional (ISO 639-1, lo fija), y `analizar_imagenes` opcional (`true`/`false`: describir imágenes con Gemma antes de la ficha, ADR-024; sin el campo, `FOTOGRAMAS_DESCRIBIR`, apagado por defecto). Responde **202** con `{"id", "proceso": "en_cola", "sop_id"}` y `Location: /videos/<id>`. Un `sop_id` de un SOP generado que no está en la biblioteca da **422**. Con `sop`, el SOP se crea en cola como en `POST /sops` y su estado se consulta en `GET /sops/{sop_id}/estado`; el video lo espera y, si la conversión falla, queda en error con el mensaje del SOP. 415 si la extensión no está permitida, 422 si el formulario no es válido, si el SOP adjunto no se puede leer o si `sop_id` es de un SOP en error, 404 si el SOP no existe, 413 si pasa de `SUBIDA_MAX_MB` (1024 por defecto) |
| `GET /videos/{id}` | `proceso` (`en_cola`, `procesando`, `listo`, `error`), `etapa` (`duracion`, `audio`, `transcripcion`, `fotogramas` si se describen imágenes, `contexto`, `segmentacion`; en modo validar también `emparejamiento`, `reporte`; en modo generar `sop_pasos`, `sop_resumen`, `sop_claves`; al final `listo`), `progreso` (0–100), duración, idioma, `error` y `sop_id` (en modo generar, el SOP generado) |
| `GET /videos/{id}/sop` | El SOP generado (modo generar, RF-22 a RF-25; `SOP` del contrato con la evidencia de cada dato). **409** con `{"mensaje", "proceso", "estado", "error"}` mientras no esté listo; **422** si el video es de modo validar. Las advertencias (`sop_incompleto`…) y `generacion`, en `GET /sops/{sop_id}` |
| `POST /videos/{id}/generar` | Repite la generación del SOP con la transcripción guardada, sin Whisper (ADR-023); reusa la ficha y los pasos del video guardados (RNF-07), salvo `?segmentar=true`. Reescribe el SOP del video salvo que ya esté en la biblioteca: entonces crea uno nuevo. **202**; 422 si el video no es de modo generar; 409 si está en cola o procesando, o si no tiene análisis guardado |
| `GET /videos/{id}/transcripcion.txt` | El TXT tal como va, `[mm:ss] texto` por línea. 200 vacío si la transcripción no ha empezado |
| `GET /videos/{id}/analisis` | El `Analisis` validado cuando `proceso` es `listo`; si no, **409** con el proceso actual |
| `GET /videos/{id}/contexto` | La ficha de contexto (`Contexto`, esquema en `docs/contrato/contexto.schema.json`; ejemplo en `tests/fixtures/contexto_ejemplo.json`). **409** con `{"mensaje", "proceso"}` mientras no se genere: el video sigue en proceso, Ollama falló (en modo validar el reporte lleva el aviso `contexto_sin_generar`) o el video se procesó antes de que existiera la ficha |
| `GET /videos/{id}/reporte` | El `ReporteValidacion` (esquema en `docs/contrato/reporte.schema.json`; ejemplos en `tests/fixtures/reporte_ejemplo*.json`). **409** si no está listo, 404 si el video no tiene reporte (p. ej. modo generar) |
| `GET /videos/{id}/video` | El archivo del video para el reproductor del reporte (RF-20), en cualquier estado (también en cola o en proceso). `Content-Type` según la extensión (`video/mp4`, …) y `Accept-Ranges: bytes`; con `Range` responde **206** con `Content-Range` (`bytes=a-b`, `bytes=a-`, `bytes=-n`) y **416** si el rango no cabe. 404 con `{"mensaje"}` si el archivo no está en disco |
| `GET /videos/{id}/thumb?t=12.5` | La miniatura JPEG del segundo `t` (RF-11, ADR-024; solo ffmpeg). Devuelve la guardada si hay una a ≤ 1 s (RNF-03); si no, la saca y la guarda en `media/videos/<id>/miniaturas/`. `Cache-Control: private, max-age=86400, immutable`. **400** si `t` está fuera de la duración; **404** si el video no existe o no tiene imagen visible (sin pista de video o negro; el reporte lleva el aviso informativo `sin_imagen`) |
| `GET /videos/estimacion?duracion_s=…&modo=validar\|generar&sop_id=…` | Antes de subir: cuántas imágenes se describirían (`imagenes_estimadas`: los pasos del SOP listo o la duración × `PASOS_POR_MIN`, entre 4 y 20), `segundos_extra_gpu` y `segundos_extra_cpu` (N × `SEG_IMAGEN_*`, sin calibrar), `dispositivo` donde correría Gemma, `dispositivo_supuesto` (no se pudo saber y se supuso CPU) y `aviso` listo para la pantalla. Nunca prohíbe: solo informa. 404 si el SOP no existe, 422 si los parámetros no son válidos |
| `POST /videos/{id}/validar` | Repite solo la validación con la transcripción guardada, sin Whisper (ADR-019), y reusa los pasos del video guardados, así que el emparejamiento y el porcentaje salen iguales (RNF-07; la redacción de las justificaciones del juez puede variar); `?segmentar=true` los vuelve a pedir a Gemma (una segmentación de la heurística o incompleta siempre se repite). `?continuar=true` no se detiene por afinidad baja (ADR-020). **202**; 422 si el video no es de modo validar; 409 si está en cola o procesando, o si no tiene análisis guardado |

Todas las rutas con `{id}` responden 404 si el video (o el SOP) no existe.

### Para la pantalla del reporte (RF-20)

La API no tiene CORS. En desarrollo, Angular pasa por un proxy (`frontend/proxy.conf.js`, ya
configurado en `angular.json`) que reenvía `/api` a la API sin el prefijo. El destino sale de
`API_URL`: `http://localhost:8000` con `ng serve` en el host, `http://api:8000` en el servicio
`web` de compose y `http://host.docker.internal:8000` con `make up-gpu` (API en el host):

```js
module.exports = {
  "/api": {
    target: process.env.API_URL || "http://localhost:8000",
    secure: false,
    pathRewrite: { "^/api": "" },
  },
};
```

El reproductor apunta a la ruta del video y salta al segundo de cada hallazgo con el `t_inicio`
de la fila del reporte (sale de la transcripción, regla 4). Como la API acepta `Range`, el
navegador pide solo el tramo que necesita:

```html
<video #reproductor controls preload="metadata" [src]="'/api/videos/' + videoId + '/video'"></video>
```

```ts
irA(fila: FilaReporte): void {
  if (fila.t_inicio == null) return; // un Falta no tiene segundo en el video
  this.reproductor.nativeElement.currentTime = fila.t_inicio;
  this.reproductor.nativeElement.play();
}
```

## Validación (modo validar)

Después de guardar el `Analisis`: revisión de Ollama (`/api/tags`) → ficha de contexto con Gemma
4 (RF-12, `percepcion/contexto.py`) → pasos del video (ADR-010) → fusión, emparejamiento y juez
de la zona gris (ADR-012, ADR-013) → orden y marco del operador (ADR-016) → porcentaje y semáforo
(RF-19). La ficha, los pasos y el juez usan la misma carga de Gemma. El reporte se guarda en
`reportes`, los pasos del video en `videos.pasos_video` y la ficha en `videos.contexto` (solo si
se generó). El avance: el análisis va de 0 a 40, `contexto` 40, `segmentacion` 50,
`emparejamiento` 80, `reporte` 95 y `listo` 100.

## Generación del SOP (modo generar, ADR-023)

Después de guardar el `Analisis` (0 a 40), en una sola carga de Gemma: ficha de contexto
(`contexto` 40) → pasos del video (`segmentacion` 50, en `videos.pasos_video`) → agrupar y
redactar los pasos (`sop_pasos` 65) → cuadro resumen (`sop_resumen` 85) → puntos y palabras
clave (`sop_claves` 92) → `listo` 100. El SOP queda en `sops` con `origen="generado"`,
`en_biblioteca=false`, sus advertencias y `generacion` (llamadas con segundos, tokens de salida y
tokens/s, grupos de pasos del video y dónde corrió Gemma), y `videos.sop_id` apunta a él.

- **Ollama no responde al empezar** o **no hay pasos del video:** `proceso="error"` con un mensaje
  que dice qué hacer; el análisis queda guardado y `POST /videos/{id}/generar` lo repite.
- **Una llamada falla a medias:** el SOP sale con lo que se pudo y la advertencia `sop_incompleto`
  dice qué faltó (la agrupación, pasos sin redactar, el cuadro resumen o las claves). Nunca sin
  pasos.

- **Ollama no responde al empezar:** `proceso="error"` con "LLM no disponible: el análisis quedó
  guardado…". Cuando Ollama responda, `POST /videos/{id}/validar` (ADR-019).
- **Ollama se cae a medias:** el reporte se guarda con `provisional: true` y
  `metadatos.avisos` (`contexto_sin_generar`, `segmentacion_heuristica`, `juez_sin_revisar`,
  `pasos_sin_redactar`). La ficha sin generar queda en NULL y `POST /videos/{id}/validar` la
  vuelve a intentar; si ya estaba guardada, la reusa sin llamar al modelo.
- **Whisper que no es el de referencia** (`large-v3-turbo`, ADR-018; p. ej. quien configure
  `WHISPER_MODELO_CPU=small`): el
  reporte y la ficha llevan el aviso `transcripcion_no_referencia` y el reporte queda provisional.
- Al terminar la etapa del LLM se pide a Ollama que suelte el modelo (`keep_alive: 0`), en GPU o
  en CPU, para que el siguiente Whisper tenga la memoria libre.

## Dónde queda cada cosa

- Archivos: `MEDIA_DIR/videos/<id>/` con `video.<ext>` (nunca el nombre original), `audio.mp3` y
  `transcripcion.txt`. En el host, `media/` (ignorada por git); en Docker, el volumen `media`
  (`/app/media`).
- Base: la fila de `videos`. `duracion`, `idioma` (código) y `fotogramas` van en sus columnas; en
  `transcripcion` (JSONB) va `{"version_contrato", "idioma": {codigo, confianza, fijado_a_mano},
  "segmentos": [...]}`. `GET …/analisis` rearma el `Analisis` y lo valida. Los pasos del video
  quedan en `pasos_video` (JSONB) y el reporte en `reportes` (uno por video, con `cumplimiento`
  en su columna y el JSON completo en `resultado`).
- El archivo original del SOP se guarda en `MEDIA_DIR/sops/<id>/original.<ext>` al recibirlo;
  la conversión deja el SOP del contrato en `sops.contenido` (JSONB), el título, `metodo` y
  `advertencias`, y `sops.estado` pasa de `en_cola` a `convirtiendo` y a `listo` o `error` (con el
  mensaje en `sops.error`).
- Si algo falla, `proceso="error"` y `error` explica la causa sin texto del video (p. ej.
  `video.mp4: el video no tiene pista de audio`, `falló la etapa transcripcion (RuntimeError)` o
  `falló la etapa emparejamiento (ValueError)`). Si falla la validación, el análisis ya quedó
  guardado: `videos.transcripcion` y `videos.pasos_video` siguen ahí.

La cola vive en memoria: al arrancar, la API pasa a `error` ("interrumpido por reinicio") los videos
que quedaron en `en_cola` o `procesando`, y los SOP en `en_cola` o `convirtiendo`. Se vuelven a
subir.

## Probar con curl

```powershell
curl.exe -F archivo=@tests/fixtures/sop_filtro_agua.md http://127.0.0.1:8000/sops
# {"id":3,"codigo":"SOP-0003","estado":"en_cola","titulo":null,"metodo":null,"mensaje":null,"advertencias":[]}
curl.exe http://127.0.0.1:8000/sops/3/estado
# {"id":3,"codigo":"SOP-0003","estado":"listo","titulo":"Cambio del cartucho del filtro de agua","metodo":"plantilla","mensaje":null,"advertencias":[]}
curl.exe -F archivo=@video_a.mp4 -F "titulo=Cambio de filtro" -F modo=validar -F sop_id=3 -F idioma=es http://127.0.0.1:8000/videos
# {"id":12,"proceso":"en_cola"}
curl.exe http://127.0.0.1:8000/videos/12                    # avance
curl.exe http://127.0.0.1:8000/videos/12/transcripcion.txt  # TXT en vivo
curl.exe -o analisis.json http://127.0.0.1:8000/videos/12/analisis
curl.exe -o reporte.json http://127.0.0.1:8000/videos/12/reporte
```

`analisis.json` es el mismo que escribe `scripts/analizar_video.py` y entra tal cual a
`segmentacion.segmentar`. También se puede probar desde `http://127.0.0.1:8000/docs`.

## En Docker (solo CPU)

`docker compose up -d --build` levanta `db` y `api`. En el contenedor Whisper corre en CPU con el
mismo modelo que en GPU (`large-v3-turbo`, int8; ADR-018): la imagen no tiene acceso a la GPU
(seguimiento en ADR-014, `docs/dev/transcripcion.md`). La primera transcripción descarga ~1.6 GB al
volumen `modelos`. Sirve para probar el flujo; no para medir RNF-01.

## API en el host con la GPU (así corre la demo)

La API corre desde el venv de Windows, con faster-whisper en la RTX 2070 SUPER, contra el Postgres
de compose.

1. Requisitos: venv con `pip install -e ".[dev,gpu]"` (ver `docs/dev/transcripcion.md`) y ffmpeg
   en el PATH (`winget install Gyan.FFmpeg`).
2. La base, Ollama con la GPU y el frontend (`web`) en Docker, sin la `api` del contenedor (ocupa el puerto 8000):

   ```powershell
   make up-gpu                    # sin make: ver la línea siguiente
   # $env:API_URL_WEB="http://host.docker.internal:8000"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d db ollama web; Remove-Item Env:API_URL_WEB
   docker compose stop api        # si estaba arriba
   alembic upgrade head           # desde el venv; usa POSTGRES_HOST=localhost del .env
   ```

   Antes de medir con Gemma, confirma que el modelo quedó en la GPU (columna PROCESSOR, ADR-018):

   ```powershell
   docker compose exec ollama ollama ps   # "100% GPU"; si dice CPU sin LLM_DISPOSITIVO=cpu, no midas
   ```

   El modelo solo aparece en la lista mientras está cargado (después de la primera llamada y
   antes de que la etapa lo descargue). Los scripts de medición lo consultan con
   `ClienteLLM.dispositivo_cargado()`.

3. Perfil gpu en `.env` (o en la sesión de PowerShell):

   ```
   WHISPER_MODELO=large-v3-turbo
   WHISPER_DISPOSITIVO=cuda
   WHISPER_COMPUTE_TYPE=float16
   HF_HUB_OFFLINE=1               # cuando el modelo ya está descargado en models/whisper
   ```

4. Levantar la API con **un solo proceso** (la cola, la GPU y el candado de modelo pesado que
   del trabajador son de ese proceso; no uses `--workers` ni `--reload`):

   ```powershell
   uvicorn sopvid.plataforma.api.main:app --host 127.0.0.1 --port 8000
   ```

5. Confirmar la GPU en el log al procesar el primer video:

   ```
   INFO sopvid.percepcion.transcripcion: Whisper large-v3-turbo cargado en cuda/float16 en 3.1 s
   INFO sopvid.plataforma.procesamiento: Video 473 listo: 58.3 s, 9 segmentos
   ```

   Si aparece el aviso "cuda falló antes del primer segmento", corrió en CPU (ver
   `docs/dev/transcripcion.md`). Con `WHISPER_DISPOSITIVO=cuda` no hay respaldo: falla en lugar
   de caer a CPU.

Los archivos quedan en `media/videos/<id>/` del repo (ignorada por git). Medido el 25 oct con la
narración sintética de 58 s: el análisis tardó 6.3 s (carga del modelo incluida).
