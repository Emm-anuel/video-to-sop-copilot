# API de videos (desarrollo y demo)

Subida de un video completo (RF-06 del MVP; la subida por partes es de S5), el SOP de referencia
cuando no existe (RF-03), análisis en una cola de un trabajador (un modelo en GPU a la vez,
ADR-014), la validación contra el SOP con su reporte (RF-14, RF-19, RF-20) y consulta del avance,
el TXT en vivo (RF-10) y el `Analisis` del contrato. Código: `sopvid.plataforma.api.videos`,
`sopvid.plataforma.procesamiento`, `sopvid.plataforma.sops` y `sopvid.plataforma.validacion`.

| Método y ruta | Qué hace |
|---|---|
| `POST /videos` | Multipart: `archivo` (mp4, mov, mkv o webm), `titulo`, `modo` (`validar` o `generar`), `idioma` opcional (ISO 639-1, lo fija) y, con `modo=validar`, el SOP: el archivo `sop` (`.md`, `.markdown` o `.txt`, UTF-8) o un `sop_id` ya guardado. Responde **202** con `{"id", "proceso": "en_cola", "sop_id"}` y `Location: /videos/<id>`. 415 si la extensión del video o del SOP no está permitida, 422 si el formulario no es válido o el SOP no sigue la plantilla, 404 si el `sop_id` no existe, 413 si el video pasa de `SUBIDA_MAX_MB` (1024 por defecto) o el SOP de 2 MB |
| `GET /videos/{id}` | `proceso` (`en_cola`, `procesando`, `listo`, `error`), `etapa` (`duracion`, `audio`, `transcripcion`, `validacion`, `listo`), `progreso` (0–100), duración, idioma y `error` |
| `GET /videos/{id}/transcripcion.txt` | El TXT tal como va, `[mm:ss] texto` por línea. 200 vacío si la transcripción no ha empezado |
| `GET /videos/{id}/analisis` | El `Analisis` validado cuando `proceso` es `listo`; si no, **409** con el proceso actual |
| `GET /videos/{id}/reporte` | El reporte de validación cuando `proceso` es `listo`; si no, **409** con el proceso actual, y **404** si el video no tiene reporte (se subió con `modo=generar` o sin SOP) |

Todas las rutas con `{id}` responden 404 si el video no existe.

## El reporte (`GET /videos/{id}/reporte`)

Es lo que dibuja la pantalla del reporte: cabecera con el porcentaje y el semáforo, y una fila por
paso con su cita y su segundo, para que el reproductor salte ahí.

```json
{
  "version_contrato": 1,
  "video_id": 12,
  "sop_id": 3,
  "sop_titulo": "Cambio de filtro de agua",
  "cumplimiento": 75.0,
  "semaforo": "amarillo",
  "resumen": {"conteo": {"Cumple": 4, "Parcial": 1, "Falta": 1, "Sobra": 0, "zona_gris": 0},
              "pares": 5, "pares_llm": 0, "pct_pares_llm": 0.0, "fuera_de_orden": 0,
              "juez": null, "segundos_juez": null, "marco_operador": 0},
  "faltan": [5],
  "sobran": [],
  "filas": [
    {"orden": 1, "estado": "Cumple", "nombre": "Preparar el filtro", "paso_sop": 1,
     "paso_video": 1, "t_inicio": 0.0, "t_fin": 5.0, "cita": "Primero preparo el filtro nuevo.",
     "confianza": "alta", "similitud": 0.91, "fuera_de_orden": false,
     "marco_operador": null, "justificacion": ""}
  ],
  "pasos_del_video": {"metodo": "llm", "modelo": "gemma4:e4b-it-q4_K_M", "pasos": 7}
}
```

- `cumplimiento` va redondeado a dos decimales (documento SOP V1.0, sección 5.6; en el ejemplo,
  4 Cumple y 1 Parcial sobre 6 pasos del SOP = 75 %): Cumple suma 1,
  Parcial o fuera de orden 0.5, Falta/Sobra/zona_gris 0; el denominador son los pasos del SOP.
- `semaforo`: verde desde 90 %, amarillo desde 70 %, rojo por debajo.
- Las filas van en el orden de la tabla: primero los pasos del SOP y después los *Sobra*.
  `t_inicio` y `t_fin` son el tramo del paso del video; un *Falta* no tiene segundo ni cita.
- Un *Sobra* con `marco_operador` (`intro` o `cierre`, ADR-016) sigue en la tabla con su cita,
  pero no cuenta en `resumen.conteo.Sobra` ni aparece en `sobran`.
- `justificacion` es la del juez de la zona gris (vacía si el par no pasó por él); un estado
  `zona_gris` con juicio de respaldo se muestra como "sin revisar".

## Dónde queda cada cosa

- Archivos: `MEDIA_DIR/videos/<id>/` con `video.<ext>` (nunca el nombre original), `audio.mp3` y
  `transcripcion.txt`. En el host, `media/` (ignorada por git); en Docker, el volumen `media`
  (`/app/media`).
- Base: la fila de `videos`. `duracion`, `idioma` (código) y `fotogramas` van en sus columnas; en
  `transcripcion` (JSONB) va `{"version_contrato", "idioma": {codigo, confianza, fijado_a_mano},
  "segmentos": [...]}`. `GET …/analisis` rearma el `Analisis` y lo valida. Los pasos del video
  quedan en `pasos_video` (JSONB) y el reporte en `reportes` (uno por video, con `cumplimiento`
  en su columna y el JSON completo en `resultado`).
- El SOP convertido se guarda en `sops.contenido` (JSONB); subir dos veces el mismo SOP reutiliza
  la fila, así que `sop_id` no cambia. El archivo original no se copia al volumen de medios.
- Si algo falla, `proceso="error"` y `error` explica la causa sin texto del video (p. ej.
  `video.mp4: el video no tiene pista de audio`, `falló la etapa transcripcion (RuntimeError)` o
  `falló la etapa validacion (ValueError)`). Si falla la validación, el análisis ya quedó
  guardado: `videos.transcripcion` y `videos.pasos_video` siguen ahí.

La cola vive en memoria: al arrancar, la API pasa a `error` ("interrumpido por reinicio") los videos
que quedaron en `en_cola` o `procesando`. Se vuelven a subir.

## Probar con curl

```powershell
curl.exe -F archivo=@video_a.mp4 -F sop=@mi_sop.md -F "titulo=Cambio de filtro" -F modo=validar -F idioma=es http://127.0.0.1:8000/videos
# {"id":12,"proceso":"en_cola","sop_id":3}
curl.exe http://127.0.0.1:8000/videos/12                    # avance
curl.exe http://127.0.0.1:8000/videos/12/transcripcion.txt  # TXT en vivo
curl.exe -o analisis.json http://127.0.0.1:8000/videos/12/analisis
curl.exe -o reporte.json http://127.0.0.1:8000/videos/12/reporte    # 409 mientras no esté listo
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

