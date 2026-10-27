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
| Transcripción | faster-whisper `large-v3-turbo` en GPU (float16) o `small` en CPU (int8); tiempo por palabra, VAD, detección de idioma |
| LLM y visión | Ollama `0.40.2` en Docker (profile `llm`), cliente httpx propio con JSON Schema, sin frameworks. `gemma4:e4b-it-q4_K_M` con flash attention ([ADR-006](docs/adr/ADR-006-llm-local.md)) para todo: convertir SOP sin plantilla (S5, [ADR-015](docs/adr/ADR-015-sop-plantilla-markdown.md)), describir fotogramas, ficha de contexto, pasos del video ([ADR-010](docs/adr/ADR-010-segmentacion-pasos-llm.md)), juez de pares dudosos y redacción del SOP |
| Emparejamiento | `paraphrase-multilingual-MiniLM-L12-v2` + algoritmo húngaro (scipy); umbrales 0.55 / 0.75 en configuración (ADR-012) |
| Lectura de SOP y PDF | pdfplumber, python-docx · ReportLab, qrcode |
| ML académico | pandas, scikit-learn, LightGBM |
| Frontend | Angular (componentes standalone, sin librerías de estado), servido por FastAPI; vistas `/carga` y `/buscar` con clave de acceso por variable de entorno |
| Calidad | pytest, ruff, GitHub Actions |

Hardware de referencia (ADR-014): RTX 2070 SUPER de 8 GB, i7-10700K, 32 GB de RAM. faster-whisper y
Gemma 4 no caben juntos en la GPU: las etapas corren en secuencia, con un modelo cargado a la vez.
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
frontend/              Angular (reservado)
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

> Estado al 19 oct 2026:
> - **En `main`:** andamiaje F0 (API con `GET /health`, Postgres + pgvector vía Alembic, tests, CI) y
>   `features/` para los avances 1 y 2 con sus notebooks.
> - **De `feat/llm-spike`, ya fusionada en `main` (merge `936af6f`):** cliente del LLM (`lenguaje/llm.py`), servicio Ollama
>   en Docker, estado del LLM en `/health`, ADR-006 con su benchmark y el prototipo de segmentación
>   (`percepcion/segmentacion.py`, ADR-010). Se reutilizan en 1.0.
> - **Lectura del SOP en Markdown/TXT:** con código, sin LLM, según la plantilla de
>   `docs/contrato/plantilla_sop.md` (`lenguaje/sop_markdown.py`, `scripts/convertir_sop.py`,
>   ADR-015). PDF y Word siguen pendientes (S5).
> - **Tablas del modelo de datos (sección 10):** las cinco (`sops`, `videos`, `reportes`,
>   `palabras`, `busquedas`) en `plataforma/modelos.py` y la migración `0002`; `sops.codigo` es
>   una columna generada. La lógica de publicar y buscar sigue pendiente (S6).
> - **Ingesta de audio y transcripción (25 oct, en `main`):**
>   `percepcion/medios.py` (duración con ffprobe, audio mp3 mono 16 kHz con ffmpeg) y
>   `percepcion/transcripcion.py` (RF-09 idioma con confianza o fijado a mano; RF-10 tiempo por
>   segmento y por palabra, TXT `[mm:ss]` en vivo). faster-whisper con GPU corre en el host, desde el
>   venv con el extra `gpu`; en Docker, solo CPU (`small`; seguimiento en ADR-014,
>   `docs/dev/transcripcion.md`).
> - **Emparejamiento en `main`:** `clasificar`, `orden` y `emparejar` (`lenguaje/emparejamiento.py`):
>   cascada completa (ADR-012, ADR-013). Juez Gemma 4 de la zona gris (27 oct) en `lenguaje/juez.py`,
>   con el prompt versionado en `lenguaje/prompts/`; cita verificada contra la narración del paso y
>   respaldo en `zona_gris` ("sin revisar") si Ollama no responde. El punto 4 de ADR-012 (EPP en
>   pares ≥ 0.75) queda diferido con RF-18. El texto vectorizado del paso del video lleva su cita
>   (27 oct, ADR-012); la intro y el cierre del operador se marcan y no cuentan como *Sobra*
>   (ADR-016). Diagnóstico de A y B: `scripts/diagnosticar_emparejamiento.py`.
> - **Análisis y API de videos (25 oct):** `percepcion/pipeline.py` (`analizar_video`: duración →
>   audio → transcripción → `Analisis` validado) y `scripts/analizar_video.py`. API:
>   `POST /videos` (subida simple, RF-06 del MVP), `GET /videos/{id}`, `…/transcripcion.txt` (en
>   vivo) y `…/analisis`, con una cola de un trabajador (`plataforma/procesamiento.py`). El
>   `Analisis` se guarda sin migración (idioma completo y segmentos en `videos.transcripcion`). La
>   demo corre la API en el host con la GPU (`docs/dev/api.md`); en Docker, Whisper en CPU.
> - **Sin código todavía:** fotogramas y subida por partes (`percepcion/`, S5); lectura del
>   SOP en PDF y Word, reporte, SOP generado, PDF y búsqueda (`lenguaje/`); frontend.
> - **Modelo:** `gemma4:e4b` sobre-segmenta; se mitiga fusionando pasos consecutivos antes de emparejar
>   (ADR-013). `qwen3.5:9b` segmenta mejor pero no es Gemma 4 (NDA cl. 1): solo como comparación en
>   experimentos, nunca como valor por defecto sin aprobación escrita.

## 6. Comandos

| Acción | Make | PowerShell (Windows) |
|---|---|---|
| Levantar API + Postgres | `make up` | `docker compose up -d --build` |
| Levantar con el LLM (requiere GPU NVIDIA) | — | `docker compose --profile llm up -d --build` |
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

Salud del sistema: `GET http://localhost:8000/health` → `{"status":"ok","db":"ok","llm":"ok"}`; sin el
profile `llm`, `"llm":"no_disponible"` y la API sigue sana. Detalles del LLM en `docs/dev/llm.md`.
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
