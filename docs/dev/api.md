# API de videos (desarrollo y demo)

Subida de un video completo (RF-06 del MVP; la subida por partes es de S5), análisis en una cola
de un trabajador (un modelo en GPU a la vez, ADR-014) y consulta del avance, el TXT en vivo
(RF-10) y el `Analisis` del contrato. Código: `sopvid.plataforma.api.videos` y
`sopvid.plataforma.procesamiento`.

| Método y ruta | Qué hace |
|---|---|
| `POST /videos` | Multipart: `archivo` (mp4, mov, mkv o webm), `titulo`, `modo` (`validar` o `generar`) e `idioma` opcional (ISO 639-1, lo fija). Responde **202** con `{"id", "proceso": "en_cola"}` y `Location: /videos/<id>`. 415 si la extensión no está permitida, 422 si el formulario no es válido, 413 si pasa de `SUBIDA_MAX_MB` (1024 por defecto) |
| `GET /videos/{id}` | `proceso` (`en_cola`, `procesando`, `listo`, `error`), `etapa` (`duracion`, `audio`, `transcripcion`, `listo`), `progreso` (0–100), duración, idioma y `error` |
| `GET /videos/{id}/transcripcion.txt` | El TXT tal como va, `[mm:ss] texto` por línea. 200 vacío si la transcripción no ha empezado |
| `GET /videos/{id}/analisis` | El `Analisis` validado cuando `proceso` es `listo`; si no, **409** con el proceso actual |

Todas las rutas con `{id}` responden 404 si el video no existe.

## Dónde queda cada cosa

- Archivos: `MEDIA_DIR/videos/<id>/` con `video.<ext>` (nunca el nombre original), `audio.mp3` y
  `transcripcion.txt`. En el host, `media/` (ignorada por git); en Docker, el volumen `media`
  (`/app/media`).
- Base: la fila de `videos`. `duracion`, `idioma` (código) y `fotogramas` van en sus columnas; en
  `transcripcion` (JSONB) va `{"version_contrato", "idioma": {codigo, confianza, fijado_a_mano},
  "segmentos": [...]}`. `GET …/analisis` rearma el `Analisis` y lo valida.
- Si algo falla, `proceso="error"` y `error` explica la causa sin texto del video (p. ej.
  `video.mp4: el video no tiene pista de audio` o `falló la etapa transcripcion (RuntimeError)`).

La cola vive en memoria: al arrancar, la API pasa a `error` ("interrumpido por reinicio") los videos
que quedaron en `en_cola` o `procesando`. Se vuelven a subir.

## Probar con curl

```powershell
curl.exe -F archivo=@video_a.mp4 -F "titulo=Cambio de filtro" -F modo=validar -F idioma=es http://127.0.0.1:8000/videos
# {"id":12,"proceso":"en_cola"}
curl.exe http://127.0.0.1:8000/videos/12                    # avance
curl.exe http://127.0.0.1:8000/videos/12/transcripcion.txt  # TXT en vivo
curl.exe -o analisis.json http://127.0.0.1:8000/videos/12/analisis
```

`analisis.json` es el mismo que escribe `scripts/analizar_video.py` y entra tal cual a
`segmentacion.segmentar`. También se puede probar desde `http://127.0.0.1:8000/docs`.

## En Docker (solo CPU)

`docker compose up -d --build` levanta `db` y `api`. En el contenedor Whisper corre en CPU con el
perfil por defecto (`small`, int8): la imagen no tiene acceso a la GPU (seguimiento en ADR-014,
`docs/dev/transcripcion.md`). Sirve para probar el flujo; no para medir RNF-01.

## API en el host con la GPU (así corre la demo)

La API corre desde el venv de Windows, con faster-whisper en la RTX 2070 SUPER, contra el Postgres
de compose.

1. Requisitos: venv con `pip install -e ".[dev,gpu]"` (ver `docs/dev/transcripcion.md`) y ffmpeg
   en el PATH (`winget install Gyan.FFmpeg`).
2. Solo la base en Docker, sin la `api` del contenedor (ocupa el puerto 8000):

   ```powershell
   docker compose up -d db
   docker compose stop api        # si estaba arriba
   alembic upgrade head           # desde el venv; usa POSTGRES_HOST=localhost del .env
   ```

3. Perfil gpu en `.env` (o en la sesión de PowerShell):

   ```
   WHISPER_MODELO=large-v3-turbo
   WHISPER_DISPOSITIVO=cuda
   WHISPER_COMPUTE_TYPE=float16
   HF_HUB_OFFLINE=1               # cuando el modelo ya está descargado en models/whisper
   ```

4. Levantar la API con **un solo proceso** (la cola y la GPU son de ese proceso; no uses
   `--workers` ni `--reload`):

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
