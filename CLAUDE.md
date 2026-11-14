# CLAUDE.md · video-to-sop-copilot

Guía para Claude (y para cualquier persona del equipo) al trabajar en este repositorio.
El plan detallado, el roadmap y los riesgos viven en @docs/plan/plan.md. Este archivo
solo contiene reglas estables; si algo de aquí contradice al plan, avisa antes de actuar.

## 1. Qué es el proyecto

**AI Co-Pilot Video-to-SOP (SOPVID).** Proyecto Integrador TC5035 · MNA · Tec de Monterrey · Equipo 51.
Patrocinador: Alignity IQ Edge, bajo NDA. Cierre del trimestre: 13 de diciembre de 2026.

Versión 1.0 según el documento **"Requerimientos técnicos y funcionales de proyecto SOP V1.0"** del
patrocinador (16 oct 2026). Una app web, local y en Docker, que analiza el video de un operador
narrando su trabajo y:

1. **Lo valida contra un SOP:** pasos que faltan, sobran o cambian de orden; personas; tiempos;
   contexto. Reporte con porcentaje, semáforo y PDF.
2. **Genera el SOP desde el video** si no existe, en español, editable y guardable en la biblioteca.
3. **Busca por coincidencia exacta** en los videos publicados y salta al segundo exacto.

```
video → audio + fotogramas → transcripción con tiempos → contexto → pasos del video (sin ver el SOP)
      → con SOP: emparejar y reporte · sin SOP: redactar SOP → PDF → publicar → búsqueda exacta
```

Requerimientos con ID (RF-01 a RF-37, RNF-01 a RNF-16): el documento del patrocinador. Alcance y
decisiones: @docs/plan/plan.md.

**Primer hito: MVP de validación (8 nov 2026, plan §5.1).** Video + SOP en TXT/Markdown → transcripción
→ pasos del video → emparejamiento → reporte con porcentaje y segundo, solo con voz. Hasta que los
videos de prueba A y B den el resultado esperado, prioriza ese camino sobre fotogramas, PDF, búsqueda o
pantallas adicionales.

El sistema se construye **desde cero**: el código del POC del patrocinador no se entregó
(ADR-001, pendiente de confirmación escrita). El POC solo es referencia funcional.

## 2. Reglas que no se rompen

1. **NDA: nada del cliente entra al repo.** Ni videos, audio, SOPs, capturas, transcripciones ni
   fragmentos. Tampoco en tests, fixtures, notebooks, logs ni mensajes de commit. El material del
   cliente se referencia por identificador y vive en el almacenamiento aprobado. Desarrollo con
   datasets públicos y videos grabados por el equipo. Rostros de trabajadores = dato personal (LFPDPPP).
2. **Costo cero (ADR-011).** Sin servicios de pago ni APIs con tokens, tampoco "solo para probar":
   ni OpenAI, ni AWS Transcribe, ni Bedrock. Pesos abiertos servidos localmente. Lo pidió el
   patrocinador el 16 oct aunque su documento de referencia mencione GPT-4o-mini y whisper-1.
3. **Secretos solo en `.env` (no versionado).** `.env.example` lleva nombres y valores de ejemplo.
   No relajes el `.gitignore`; solo agrega reglas.
4. **El LLM nunca escribe un timestamp.** Todo minuto/segundo sale de la transcripción (para
   segmentar, el LLM elige números de segmento, no tiempos). Todo hallazgo y todo paso traen una cita
   y su segundo; el código verifica que la cita exista en la transcripción. Sin evidencia, el dato
   queda vacío o como inferido con confianza baja.
5. **Los pasos del video se extraen sin mostrarle el SOP al modelo** (sección 5.3 del documento).
   El orden se revisa con código, no con el LLM.
6. **Alcance cerrado.** No implementes lo diferido (sección 4) sin un ADR aprobado. Si una tarea
   parece requerirlo, detente y pregunta.
7. **Regresión primero.** Nada nuevo entra si rompe una prueba existente.
8. **No modifiques entregables ya entregados** en `docs/entregables/` (p. ej. `Avance1.51.ipynb`).

## 3. Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11, FastAPI + Uvicorn, SQLAlchemy 2 + Alembic, pydantic-settings |
| Base de datos | PostgreSQL 16 (imagen con pgvector, ADR-005). Tablas del documento: `sops`, `videos`, `reportes`, `palabras`, `busquedas`; análisis y reportes como JSONB. pgvector queda para la búsqueda semántica de la versión 2 |
| Contenedores | Docker Compose, versiones fijadas, configuración por variables de entorno |
| Medios | ffmpeg: duración, audio mp3 mono 16 kHz, fotogramas (máx. 20), miniaturas |
| Transcripción | faster-whisper `large-v3-turbo`, el mismo modelo en CPU (int8) y en GPU (float16) (ADR-018, `WHISPER_MODELO_CPU`); otro modelo da el aviso `transcripcion_no_referencia`. Tiempo por palabra, VAD, detección de idioma |
| LLM y visión | Ollama `0.40.2` en Docker (profile `llm`), cliente httpx propio con JSON Schema, sin frameworks. `gemma4:e4b-it-q4_K_M` con flash attention ([ADR-006](docs/adr/ADR-006-llm-local.md)) para todo: convertir SOP sin plantilla (S5, [ADR-015](docs/adr/ADR-015-sop-plantilla-markdown.md)), describir fotogramas, ficha de contexto, pasos del video ([ADR-010](docs/adr/ADR-010-segmentacion-pasos-llm.md)), juez de pares dudosos y redacción del SOP |
| Emparejamiento | `paraphrase-multilingual-MiniLM-L12-v2` + algoritmo húngaro (scipy); umbrales 0.55 / 0.75 en configuración (ADR-012) |
| Lectura de SOP y PDF | pdfplumber, python-docx · ReportLab, qrcode |
| ML académico | pandas, scikit-learn, LightGBM |
| Frontend | Angular (componentes standalone, sin librerías de estado), servido por FastAPI; vistas `/carga` y `/buscar` con clave de acceso por variable de entorno. En desarrollo, `ng serve` en el servicio `web` de compose (puerto 4200) con proxy `/api` → la API según `API_URL` (`frontend/proxy.conf.js`; la API no tiene CORS). MVP: `frontend/README.md` |
| Calidad | pytest, ruff, GitHub Actions |

Hardware de referencia (ADR-014): RTX 2070 SUPER de 8 GB, i7-10700K, 32 GB de RAM. faster-whisper y
Gemma 4 no caben juntos en la GPU: las etapas corren en secuencia, con un modelo cargado a la vez.
**CPU de base, GPU opcional (ADR-018; el modelo de Whisper se decidió el 8 nov):** nada exige
tarjeta de video; si hay GPU, solo acelera. La GPU cambia dónde corre cada modelo, nunca cuál
(RNF-07): Whisper es `large-v3-turbo` en los dos, Gemma 4 el mismo. Cada reporte guarda dónde
corrió cada modelo en `metadatos.dispositivos` (`plataforma/hardware.py`, `LLM_DISPOSITIVO`).
Colab ya no forma parte del flujo; solo es respaldo si la GPU local falla.

## 4. Fuera de alcance (diferido, requiere ADR)

Lo de la columna "Fuera del alcance" del documento SOP V1.0: vista de administrador, usuarios y
permisos · versiones del SOP, aprobación y firmas · grabar video en la app · editar o recortar video ·
reconocimiento facial · traducir el SOP · integración con ERP, SharePoint o sistemas de calidad. Además:
V-JEPA 2 y attentive probes · grafo multi-video · diarización (PR-04) · búsqueda semántica (PR-08) ·
chat RAG y el aclarador que pregunta antes de responder · voz y copiloto en vivo (Producto B) ·
cualquier API de pago. RF-28 (diagrama de flujo, glosario) queda fuera de 1.0.

Si sobra tiempo, en este orden: RF-18 (EPP y puntos de validación) → RF-21 (aceptado / falso
positivo) → propuestas PR-01 y PR-02 del documento.

## 5. Estructura del repositorio

```
src/sopvid/            paquete instalable (src layout)
  plataforma/          config, base de datos, API FastAPI
  percepcion/          subida, ffmpeg, transcripción, fotogramas, pasos del video
  lenguaje/            cliente del LLM, lectura y redacción del SOP, emparejamiento, reporte, búsqueda exacta
  features/            limpieza e ingeniería de características (avances y pipeline)
migrations/            Alembic
scripts/               benchmark del LLM, evaluación de segmentación, preparación de datos
tests/                 pytest
  fixtures/            solo datos inventados por el equipo o públicos (nunca del cliente)
frontend/              Angular (pantallas del MVP y quién hace qué: frontend/README.md)
notebooks/             exploración libre
data/                  solo README y .gitkeep en git; el contenido se ignora
docs/
  adr/                 Architecture Decision Records (ADR-NNN-titulo.md)
    datos/             resultados crudos que respaldan los ADR (benchmarks, evaluaciones)
  dev/                 guías de desarrollo (p. ej. llm.md: levantar Ollama y verificar la GPU)
  plan/plan.md         plan vigente, roadmap, riesgos, preguntas
  entregables/Semana N/  entregables académicos oficiales
  arquitectura/, literatura/
```

> Estado al 13 nov 2026 (resumen semanal en `docs/plan/estado.md`):
> - **En `main`:** andamiaje F0 (API con `GET /health`, Postgres + pgvector vía Alembic, tests, CI) y
>   `features/` para los avances 1 y 2 con sus notebooks.
> - **De `feat/llm-spike`, ya fusionada en `main` (merge `936af6f`):** cliente del LLM (`lenguaje/llm.py`), servicio Ollama
>   en Docker, estado del LLM en `/health`, ADR-006 con su benchmark y el prototipo de segmentación
>   (`percepcion/segmentacion.py`, ADR-010). Se reutilizan en 1.0.
> - **Lectura del SOP:** con código, sin LLM, según la plantilla de
>   `docs/contrato/plantilla_sop.md` (`lenguaje/sop_markdown.py`, `scripts/convertir_sop.py`,
>   ADR-015). PDF y Word (7 nov, rama `feat/sop-pdf-word`): `lenguaje/lectura_sop.py` saca el
>   texto y prueba la plantilla; si no la sigue (también un .md o .txt), Gemma 4
>   (`prompts/sop_texto_libre_v3.md`, una cita verificada por paso, `num_ctx` según el largo).
>   `POST /sops` es asíncrono: 202 y `GET /sops/{id}/estado`; la conversión corre en el
>   trabajador, con prioridad sobre el siguiente video, en flujo con corte por inactividad
>   (`ClienteLLM.chat_en_flujo`). Un SOP adjunto a `POST /videos` (RF-02) sigue el mismo camino.
>   `sops.metodo`, `sops.advertencias`, `sops.estado` y `sops.error`: migraciones `0003` y `0004`.
> - **Tablas del modelo de datos (sección 10):** las cinco (`sops`, `videos`, `reportes`,
>   `palabras`, `busquedas`) en `plataforma/modelos.py` y las migraciones `0002` a `0004`;
>   `sops.codigo` es una columna generada. La lógica de publicar y buscar sigue pendiente (S6).
> - **Ingesta de audio y transcripción (25 oct, en `main`):**
>   `percepcion/medios.py` (duración con ffprobe, audio mp3 mono 16 kHz con ffmpeg) y
>   `percepcion/transcripcion.py` (RF-09 idioma con confianza o fijado a mano; RF-10 tiempo por
>   segmento y por palabra, TXT `[mm:ss]` en vivo). faster-whisper con GPU corre en el host, desde el
>   venv con el extra `gpu`; en Docker, solo CPU (`large-v3-turbo` int8 desde el 8 nov; seguimiento en ADR-014,
>   `docs/dev/transcripcion.md`).
> - **Emparejamiento en `main`:** `clasificar`, `orden` y `emparejar` (`lenguaje/emparejamiento.py`):
>   cascada completa (ADR-012, ADR-013). Juez Gemma 4 de la zona gris (27 oct) en `lenguaje/juez.py`,
>   con el prompt versionado en `lenguaje/prompts/`; cita verificada contra la narración del paso y
>   respaldo en `zona_gris` ("sin revisar") si Ollama no responde. El punto 4 de ADR-012 (EPP en
>   pares ≥ 0.75) queda diferido con RF-18. El texto vectorizado del paso del video lleva su cita
>   (27 oct, ADR-012); la intro y el cierre del operador se marcan y no cuentan como *Sobra*
>   (ADR-016). Diagnóstico de A y B: `scripts/diagnosticar_emparejamiento.py`.
> - **Porcentaje y semáforo (RF-19, 27 oct):** `lenguaje/reporte.py` (`porcentaje` del
>   `ResultadoEmparejamiento` según §5.6 y `semaforo` con `SEMAFORO_VERDE`/`SEMAFORO_AMARILLO`
>   en `Settings`).
> - **Validación en la API (27 oct, ADR-017 y ADR-019):** `POST /sops` (RF-03) y `GET /sops/{id}`
>   (`plataforma/api/sops.py`); `POST /videos` con `sop_id` en modo validar; el `Procesador`
>   encadena análisis → `lenguaje/validacion.py` (`segmentar` → `emparejar` con `JuezGemma` →
>   porcentaje) y guarda `reportes` y `videos.pasos_video`; `GET /videos/{id}/reporte`
>   (`ReporteValidacion` en el contrato, `docs/contrato/reporte.schema.json`) y
>   `POST /videos/{id}/validar` (repite la validación sin Whisper si Ollama estaba caído).
>   `ClienteLLM.descargar()` suelta el modelo de Ollama al terminar (GPU o CPU). Ejemplos para la
>   pantalla: `tests/fixtures/reporte_ejemplo*.json` (`scripts/ejemplo_reporte.py`).
> - **Análisis y API de videos (25 oct):** `percepcion/pipeline.py` (`analizar_video`: duración →
>   audio → transcripción → `Analisis` validado) y `scripts/analizar_video.py`. API:
>   `POST /videos` (subida simple, RF-06 del MVP), `GET /videos/{id}`, `…/transcripcion.txt` (en
>   vivo) y `…/analisis`, con una cola de un trabajador (`plataforma/procesamiento.py`). El
>   `Analisis` se guarda sin migración (idioma completo y segmentos en `videos.transcripcion`). La
>   demo corre la API en el host con la GPU (`docs/dev/api.md`); en Docker, Whisper en CPU.
> - **Calibración de umbrales (31 oct, Sara):** `scripts/calibrar_umbrales.py` prueba la rejilla de
>   umbrales del emparejamiento con la anotación a mano y deja el informe en
>   `docs/adr/datos/emparejamiento/` al correrse. Todavía no se ha corrido: se corre con C–E para no
>   sobreajustar a A y B.
> - **Ramas unidas (1 nov, merge `58a31ac`):** la validación se implementó dos veces en paralelo; quedó
>   la de `143a06f` (`lenguaje/validacion.py`). El ADR-017 de Sara (validar en el mismo trabajo)
>   conserva su número y el "validar sin LLM" pasó a ADR-019. Antes de empezar una pieza, toma su
>   issue y revisa `main`.
> - **CPU de base (1 nov, ADR-018):** `docker-compose.yml` ya no exige GPU; medido el 27 oct, sin GPU
>   A y B dan el resultado correcto pero tardan 159–223 s (no cumple RNF-01). Gemma no es
>   determinista: con temperatura 0, 1 de 3 corridas mueve una frontera (A dio 100 / 83.3 / 100 %).
> - **Video para el reproductor (7 nov, `a40b124`):** `GET /videos/{id}/video` entrega el archivo con
>   soporte de `Range` (206) para saltar al segundo (RF-20).
> - **Frontend (7 nov):** Emmanuel crea la base de Angular y la pantalla `/nuevo` (subir SOP y video);
>   Sara hace la pantalla del reporte (`/videos/:id/reporte`, RF-20) sobre esa base, reemplazando un
>   componente provisional. Detalle, contrato y reglas de presentación: `frontend/README.md`.
> - **Ficha de contexto (7 nov, rama `feat/contexto`, RF-12):** `percepcion/contexto.py` con
>   Gemma 4 (`prompts/contexto_v2.md`; v1 se conserva) después de la transcripción y antes de los pasos, en la
>   misma carga del modelo; cita verificada por dato y por persona, y fuente, confianza y segundo
>   puestos por el código. Se guarda en `videos.contexto` solo si se generó (si no, NULL y aviso
>   `contexto_sin_generar`); `GET /videos/{id}/contexto`. Los fotogramas ([f=N]) entran solo si
>   existen. Medición CPU/GPU: `scripts/medir_contexto.py`, seguimiento en ADR-018.
> - **Afinidad y personas (8 nov, rama `feat/afinidad-roles`, ADR-020):** `lenguaje/afinidad.py`
>   (RF-17) y `lenguaje/personas.py` (RF-15), solo MiniLM y código. Afinidad < `AFINIDAD_MIN` detiene
>   la validación tras la ficha con `proceso="afinidad_baja"` (migración `0005`);
>   `POST /videos/{id}/validar?continuar=true` sigue. Roles por núcleo y complemento; *distinto*
>   solo con una persona distinguible. Umbrales nuevos en `Settings`, sin calibrar. Medición:
>   `scripts/medir_afinidad.py` (A–D pasan).
> - **Tiempos (8 nov, rama `feat/s5`, ADR-021):** `lenguaje/tiempos.py`, solo código. Si el operador
>   narra la duración (verbo de duración de una lista cerrada, ES/EN), esa gana siempre (§5.5); si
>   no, la medida del paso fusionado hasta el inicio del siguiente paso del video (pausa incluida).
>   ±`TOLERANCIA_TIEMPO`; solo *excede* cuenta en `pasos_fuera_de_tiempo`. Total y horario
>   (`UMBRAL_HORARIO`, sin calibrar). Medición:
>   `scripts/medir_tiempos.py` (C: 1 *excede* en el paso 1). `/nuevo` acepta PDF y Word con la
>   conversión asíncrona (`frontend/README.md`).
> - **Rescate y RNF-07 (9 nov, rama `feat/s5`, ADR-022):** un *Falta* se busca en los *Sobra*
>   contiguos entre sus pares vecinos (`emparejamiento.rescatar`; ventana ≥ `UMBRAL_ALTO` y siempre
>   con el juez; `Fusion.rescate`, `FilaReporte.rescatado`). La segmentación de Gemma no es
>   determinista: `videos.pasos_video` la guarda (`SegmentacionGuardada`) y repetir la validación la
>   reusa (`?segmentar=true` la vuelve a pedir). Con la misma segmentación el porcentaje se
>   reproduce; la redacción del juez puede variar. A: 91.67–100 % con segmentaciones nuevas (ADR-018).
> - **Cierre de S5 (10 nov, `scripts/medir_s5.py`,
>   [informe](docs/adr/datos/s5/medicion-s5-20261110-1311.md)):** con GPU, A–E pasan la §14 en
>   14/14 corridas y RNF-01 se cumple (3.0 min estimados para 10 min); sin GPU, A pasa, E falla por
>   un valor sin traducir y RNF-01 no se cumple (15–21 min). SOP generado (RF-22 a 25, 27) en
>   `lenguaje/sop_generado.py` (ADR-023); RF-26 solo el endpoint.
> - **Imágenes (10–11 nov, rama `feat/s5-pantallas`, ADR-024, RF-11):** miniatura por paso
>   siempre, con ffmpeg y sin modelo (`percepcion/miniaturas.py`, `GET /videos/{id}/thumb?t=`,
>   aviso informativo `sin_imagen` que no vuelve provisional el reporte). Descripción con Gemma
>   opcional y apagada (`FOTOGRAMAS_DESCRIBIR`, `analizar_imagenes` en `POST /videos`):
>   `percepcion/fotogramas.py`, N imágenes parejas antes de la ficha (pasos del SOP o duración ×
>   `PASOS_POR_MIN`, de 4 a 20), lotes de 8 (`prompts/fotogramas_v1.md`), aviso
>   `imagenes_incompletas`; `metadatos.imagenes` en el reporte y en `sops.generacion`.
>   `GET /videos/estimacion` avisa del tiempo extra con y sin GPU; nunca bloquea.
> - **Editor del SOP (11 nov, rama `feat/s5-pantallas`, RF-26 y RF-04, ADR-025):** `frontend/src/app/sop/`
>   (`SopEditor` en `/videos/:id/sop` y `/sops/:id`; unir, reordenar y quitar con deshacer; lógica pura en
>   `edicion.ts`). `revisado` en `Dato`, `Riesgo`, `Falla`, `PuntoClave` y `PasoSOP`; `PUT /sops/{id}`
>   pone al día la duración total sin pisar la narrada. RNF-05 de un SOP editado:
>   `scripts/medir_sop_generado.py --sop-editado clave=sop_id|json`. Corregir un SOP no detiene el video: se revalida con `POST /videos/{id}/validar`.
> - **Biblioteca y Nuevo análisis (12 nov, rama `feat/s5-pantallas`, RF-05 y RF-07):** `GET /sops`
>   (listos y en la biblioteca, con videos validados) y `DELETE /sops/{id}` (204; 409 explicado si
>   un video o reporte lo usa, nunca en cascada). `/sops` (`frontend/src/app/biblioteca/`) y
>   `/nuevo` con tres modos, consentimiento (RNF-16) y la casilla de imágenes: duración leída en el
>   navegador, `GET /videos/estimacion` (ahora con `sin_imagen` y `analizar_imagenes_defecto`) y
>   `analizar_imagenes` siempre en `POST /videos`. La lista de videos (pantalla 6) pasa a S6.
> - **Procesando (12 nov, rama `feat/s5-pantallas`, RF-08):** `/videos/:id/procesando`
>   (`frontend/src/app/procesando/`); el avance sale de un solo servicio (`frontend/src/app/avance/`:
>   sondeo de 1.5 s, finales, reintento con espera creciente y la única tabla de etapas), que
>   también usan el reporte y el SOP generado. `/nuevo` navega ahí. `videos.analizar_imagenes`
>   (migración `0007`) guarda la casilla ya resuelta, e `imagenes_hechas`/`imagenes_total` la
>   cuenta exacta por lote; `GET /videos/{id}` devuelve las tres.
> - **Subida por partes y AVI (12 nov, rama `feat/s5-pantallas`, RF-06):** `POST /uploads`,
>   `PUT /uploads/{id}?offset=N`, `GET` y `DELETE /uploads/{id}` (`plataforma/api/subidas.py`);
>   el armado vive en disco, sin tabla (`percepcion/subidas.py`, `media/subidas/<id>/`), con
>   limpieza por edad (`SUBIDA_CADUCIDAD_H`) al arrancar y en cada `POST /uploads`. `POST /videos`
>   acepta `upload_id` además de `archivo`, con los mismos campos, y valida con ffprobe. `/nuevo`
>   sube siempre por partes (`frontend/src/app/subida/`). AVI se acepta y se analiza; el navegador no
>   lo reproduce: el reporte y el editor lo dicen y ofrecen descargarlo (remux a MP4: issue de S6).
> - **Cierre de S5 (13 nov, [informe](docs/adr/datos/s5/medicion-s5-20261113-0021.md)):** recorrido
>   completo desde la pantalla (capturas en `docs/adr/datos/s5/pantallas/`) y medición en tres
>   tandas intercaladas con la GPU enfriada a ≤ 50 °C (`medir_s5.py --informe` las une con
>   `unir_tandas`): con GPU e imágenes apagadas, A–E 14/14 y RNF-01 3.2 min para 10 min (3.4–3.9
>   con la carga de MiniLM que paga el primer video tras arrancar; "Cuánto tardó" no la suma, #20);
>   MVP sin regresión. Issues #7–#10 cerrados. Del recorrido: las descripciones de imágenes no
>   aportan y además inventan objetos que llegan al SOP generado (RNF-06, ADR-024, #16), así que
>   **la demo del modo generar va sin imágenes** (13 nov); la estimación de imágenes se queda corta (#17); el SOP
>   convertido no se puede marcar revisado sin editarlo (#18); sin GPU, Nuevo no avisa del tiempo
>   total y la subida no reanuda sola al volver la red (#19).
> - **Sin código todavía (S6):** pantalla `/videos`, PDF del reporte y del SOP con QR (RF-29, 30),
>   descargas (RF-31), búsqueda (RF-32 a 37), juicios del juez guardados, Docker en máquina limpia.
> - **Modelo:** `gemma4:e4b` sobre-segmenta; se mitiga fusionando pasos consecutivos antes de emparejar
>   (ADR-013). `qwen3.5:9b` segmenta mejor pero no es Gemma 4 (NDA cl. 1): solo como comparación en
>   experimentos, nunca como valor por defecto sin aprobación escrita.

## 6. Comandos

| Acción | Make | PowerShell (Windows) |
|---|---|---|
| Levantar API + Postgres + frontend (4200) | `make up` | `docker compose up -d --build` |
| Levantar con el LLM, GPU si hay (recomendado) | — | `.\scripts\levantar.ps1 -Build` (`-Plan` solo muestra qué haría; `-Cpu` fuerza CPU) |
| Levantar con el LLM (CPU, cualquier equipo) | — | `docker compose --profile llm up -d --build` |
| Levantar con el LLM en GPU NVIDIA (ADR-018) | — | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d --build` |
| Postgres, Ollama en GPU y frontend, API en el host (demo y mediciones, `docs/dev/api.md`) | `make up-gpu` | `$env:API_URL_WEB="http://host.docker.internal:8000"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d db ollama web; Remove-Item Env:API_URL_WEB` |
| Detener (conserva datos) | `make down` | `docker compose down` |
| Detener también el LLM (conserva modelos) | — | `docker compose --profile llm down` |
| Logs | `make logs` | `docker compose logs -f` |
| Migrar | `make migrate` | `docker compose exec api alembic upgrade head` |
| Tests (base arriba y migrada) | `make test` | `pytest` |
| Lint | `make lint` | `ruff check . ; ruff format --check .` |
| Formatear | `make format` | `ruff check --fix . ; ruff format .` |
| Paquete para notebooks | — | `python -m venv .venv ; .venv\Scripts\activate ; pip install -e .[dev]` |
| Ejecutar un entregable | — | `jupyter nbconvert --to notebook --execute --inplace "docs/entregables/Semana N/AvanceN.51.ipynb"` |
| Benchmark del LLM / evaluar segmentación | — | `python scripts/benchmark_llm.py --tabla` · `python scripts/evaluar_segmentacion.py --tabla` |
| Medir CPU contra GPU con A y B (ADR-018) | — | `python scripts/medir_dispositivos.py --help` |
| Medir la ficha de contexto en CPU y GPU (ADR-018) | — | `python scripts/medir_contexto.py --config gpu --config cpu video_a=…analisis.json` |
| Medir Whisper en CPU contra la referencia (ADR-018) | — | `python scripts/medir_whisper.py --sop … video_a=…mp4` |
| Medir afinidad y personas con los videos A–D (ADR-020) | — | `python scripts/medir_afinidad.py --sop … --sop-extra … --anotacion … video_a=…` |
| Calibrar los umbrales / diagnosticar el emparejamiento | — | `python scripts/calibrar_umbrales.py --sop … --anotacion … video_a=… video_b=…` · `python scripts/diagnosticar_emparejamiento.py …` |

Salud del sistema: `GET http://localhost:8000/health` → `{"status":"ok","db":"ok","llm":"ok",
"dispositivos":{...}}`; sin el profile `llm`, `"llm":"no_disponible"` y la API sigue sana.
`dispositivos` dice qué GPU ve la API, dónde transcribe Whisper, la política de Gemma
(`LLM_DISPOSITIVO`) y avisos si la configuración no cuadra con el equipo (ADR-018). Detalles del LLM en `docs/dev/llm.md`.
Desde el host usa `http://127.0.0.1:11434` para Ollama: en Windows, `localhost` pierde ~2 s por conexión.
Dependencias fijadas en `pyproject.toml` (Python 3.11); agrega nuevas con versión exacta.

## 7. Notebooks y entregables académicos

- Entregable oficial: `docs/entregables/Semana N/AvanceN.51.ipynb`. Debe ejecutarse de principio a fin
  sin errores antes de entregarse.
- Los notebooks **importan** de `sopvid.features`; no copian funciones entre notebooks.
- Datos de los avances: anotaciones públicas de **CaptainCook4D** (licencia MIT), descargadas en tiempo
  de ejecución desde un commit fijo a `DATA_DIR` (por defecto `data/raw/captaincook4d`) y nunca
  versionadas. Incluyen los grafos de tareas de las 24 recetas (`task_graphs/`). Objetivo: `has_errors`.
- `sopvid.features`: `data` (descarga y tabla a nivel paso), `preprocessing` (partición oficial y
  preprocesamiento del avance 1, sin cambios de lógica) y `engineering` (avance 2). La entrada de los
  avances 3–5 es `engineering.build_features(train, test, video_info=..., task_graphs=...)`.
- Decisiones del avance 2 que siguen vigentes: se modelan solo los **pasos ejecutados** (los omitidos
  son *Missing Step* por definición y filtrarían la etiqueta); todo lo que aprende de los datos se
  ajusta solo con train dentro de un `Pipeline`, y las estadísticas por categoría se calculan fuera de
  pliegue con `GroupKFold` por grabación. La validación cruzada siempre se agrupa por `recording_id`, y
  el AUC-PR se reporta junto con la proporción de positivos (0.249 en train).
- No modificar `Avance1.51.ipynb` ni `Avance2.51.ipynb`; `tests/test_features_avance1.py` vigila que el paquete reproduzca
  sus resultados (se salta si no hay datos descargados).
- Metodología: CRISP-ML(Q). Cada decisión de procesamiento se justifica en el notebook.
- **Tarea de ML de los avances 2–5 ([ADR-009](docs/adr/ADR-009-tarea-ml.md)):** `has_errors` sobre
  CaptainCook4D. El clasificador de inicio de paso NO es tarea académica: se probó el 10 oct con
  CrossTask, HT-Step + ASR de HowTo100M y HT-Step + `.vtt` completos, y las etiquetas públicas no
  siguen a la narración (marcan la acción visual). El código de esa exploración está en el commit
  `30f2b40` (ya en `main`, tag `exploracion-inicio-paso`), no en la rama `avance2-inicio-paso`; no
  lo retomes ni lo amplíes sin un ADR nuevo. Excepción: `features/pasos.py` y
  `scripts/preparar_htstep*.py` ya están en `main` y se conservan para reutilizarlos al detectar
  inicios de paso (`scripts/evaluar_segmentacion.py` usa `pasos.label_phrases` para el F1 en tiempo).
  No los borres.

## 8. Convenciones

- Commits en formato Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`), en español.
- Los cambios pueden ir directo a `main` con commits convencionales y el CI en verde; las ramas
  por tarea (y su PR) son opcionales. Cada tarea como issue con responsable.
- Decisiones de arquitectura o de alcance → ADR en `docs/adr/` con estado (Propuesto / Aceptado / Reemplazado).
- Código y comentarios en español o inglés, pero consistentes dentro de cada módulo; nombres de
  dominio en español (`paso`, `video`, `segmento`).
- Tipado en funciones públicas y docstrings breves.

## 9. Cómo trabajar aquí

- Antes de crear archivos o mover carpetas, muestra el árbol propuesto y espera confirmación.
- Mueve archivos con `git mv`; no borres sin preguntar.
- Si dudas de una versión de dependencia, elige la conservadora y dilo.
- Al terminar una tarea: qué cambiaste, qué verificaste (comandos ejecutados) y qué quedó pendiente.
- Nunca hagas commit ni push sin que te lo pidan.
