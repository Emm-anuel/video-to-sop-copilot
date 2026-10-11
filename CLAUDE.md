# CLAUDE.md · video-to-sop-copilot

Guía para Claude (y para cualquier persona del equipo) al trabajar en este repositorio.
El plan detallado, el roadmap y los riesgos viven en @docs/plan/plan.md. Este archivo
solo contiene reglas estables; si algo de aquí contradice al plan, avisa antes de actuar.

## 1. Qué es el proyecto

**AI Co-Pilot Video-to-SOP (SOPVID).** Proyecto Integrador TC5035 · MNA · Tec de Monterrey · Equipo 51.
Patrocinador: Alignity IQ Edge, bajo NDA. Cierre del trimestre: 13 de diciembre de 2026.

Convierte videos de operación narrados por un experto en conocimiento consultable al segundo
exacto. Columna vertebral del MVP (centrada en la voz):

```
video → transcripción con timestamps → pasos indexados → búsqueda y chat → reproducir desde el segundo
```

El sistema se construye **desde cero**: el código del POC del patrocinador no se entregó
(ADR-001, pendiente de confirmación escrita). El POC solo es referencia funcional.

## 2. Reglas que no se rompen

1. **NDA: nada del cliente entra al repo.** Ni videos, audio, SOPs, capturas, transcripciones ni
   fragmentos. Tampoco en tests, fixtures, notebooks, logs ni mensajes de commit. El material del
   cliente se referencia por identificador y vive en el almacenamiento aprobado. Desarrollo con
   datasets públicos y videos grabados por el equipo. Rostros de trabajadores = dato personal (LFPDPPP).
2. **Costo cero.** Sin servicios de pago ni APIs con tokens. Pesos abiertos servidos localmente.
3. **Secretos solo en `.env` (no versionado).** `.env.example` lleva nombres y valores de ejemplo.
   No relajes el `.gitignore`; solo agrega reglas.
4. **El LLM nunca escribe un timestamp.** Todo minuto/segundo sale del índice (para segmentar, el LLM
   elige números de segmento, no tiempos). Toda respuesta y todo
   paso citan su segundo; sin evidencia suficiente, la respuesta es "no encontré".
5. **Alcance cerrado.** No implementes lo diferido (sección 4) sin un ADR aprobado. Si una tarea
   parece requerirlo, detente y pregunta.
6. **Regresión primero.** Nada nuevo entra si rompe una prueba existente.
7. **No modifiques entregables ya entregados** en `docs/entregables/` (p. ej. `Avance1.51.ipynb`).

## 3. Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11, FastAPI + Uvicorn, SQLAlchemy 2 + Alembic, pydantic-settings |
| Base de datos | PostgreSQL 16 + pgvector (vectores) + búsqueda de texto completo en español |
| Contenedores | Docker Compose, versiones fijadas, configuración por variables de entorno |
| Transcripción | faster-whisper (timestamps por palabra, VAD) |
| Embeddings | MiniLM multilingüe |
| LLM | Ollama `0.40.2` en Docker (profile `llm`), cliente httpx propio con JSON Schema, sin frameworks. Desarrollo (GPU de 8 GB): `gemma4:e4b-it-q4_K_M` con flash attention; producción pendiente de la GPU de 24 GB ([ADR-006](docs/adr/ADR-006-llm-local.md)). Usos: segmentación en pasos ([ADR-010](docs/adr/ADR-010-segmentacion-pasos-llm.md)) y chat RAG |
| ML académico | pandas, scikit-learn, LightGBM |
| Frontend | Angular (componentes standalone, sin librerías de estado); entra en la semana 3 |
| Calidad | pytest, ruff, GitHub Actions |

Colab T4 solo como worker de GPU para transcribir por lotes; el sistema corre local con Docker.

## 4. Fuera de alcance (diferido, requiere ADR)

V-JEPA 2 y análisis de fotogramas · grafo multi-video de orden parcial · voz y copiloto en vivo
(Producto B) · lentes/diadema · multi-inquilino, rol auditor, cifrado en reposo · attentive probes.

"Si sobra tiempo", en este orden: borrador de SOP trazable → aprobación humana con versión →
roles cargador/administrador y bitácora → carga de PDF → aclarador con LLM.

## 5. Estructura del repositorio

```
src/sopvid/            paquete instalable (src layout)
  plataforma/          config, base de datos, API FastAPI
  percepcion/          ingesta, transcripción, segmentación en pasos
  lenguaje/            búsqueda híbrida, chat RAG, SOP
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

> Estado al 11 oct 2026:
> - **En `main`:** andamiaje F0 (API con `GET /health`, Postgres + pgvector vía Alembic, tests, CI) y
>   `features/` para los avances 1 y 2 con sus notebooks.
> - **En la rama `feat/llm-spike` (sin fusionar):** cliente del LLM (`lenguaje/llm.py`), servicio Ollama
>   en Docker, estado del LLM en `/health`, ADR-006 con su benchmark y el prototipo de segmentación
>   (`percepcion/segmentacion.py`, ADR-010).
> - **Sin código todavía:** ingesta y transcripción (`percepcion/`); búsqueda, chat y SOP (`lenguaje/`).
> - **Pendiente con el patrocinador:** en 8 GB `gemma4:e4b` sobre-segmenta, `qwen3.5:9b` segmenta mejor pero
>   no es Gemma 4 (NDA cl. 1); falta probar `gemma4:26b-a4b` con la GPU de 24 GB (ver ADR-006 y ADR-010).

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
- No modificar `Avance1.51.ipynb`; `tests/test_features_avance1.py` vigila que el paquete reproduzca
  sus resultados (se salta si no hay datos descargados).
- Metodología: CRISP-ML(Q). Cada decisión de procesamiento se justifica en el notebook.
- **Tarea de ML de los avances 2–5 ([ADR-009](docs/adr/ADR-009-tarea-ml.md)):** `has_errors` sobre
  CaptainCook4D. El clasificador de inicio de paso NO es tarea académica: se probó el 10 oct con
  CrossTask, HT-Step + ASR de HowTo100M y HT-Step + `.vtt` completos, y las etiquetas públicas no
  siguen a la narración (marcan la acción visual). El código de esa exploración vive en la rama
  `avance2-inicio-paso`; no traigas más de él sin un ADR nuevo. Excepción: `features/pasos.py` y
  `scripts/preparar_htstep*.py` ya están en `main` y se conservan para reutilizarlos al detectar
  inicios de paso (`scripts/evaluar_segmentacion.py` usa `pasos.label_phrases` para el F1 en tiempo).
  No los borres.

## 8. Convenciones

- Commits en formato Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`), en español.
- Ramas por tarea y PR hacia `main`; cada tarea como issue con responsable.
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
