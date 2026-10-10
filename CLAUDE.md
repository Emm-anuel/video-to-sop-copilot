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
4. **El LLM nunca escribe un timestamp.** Todo minuto/segundo sale del índice. Toda respuesta y todo
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
| LLM | Modelo abierto local vía Ollama (familia Gemma 4 si cabe en el hardware) |
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
tests/                 pytest
frontend/              Angular (reservado)
notebooks/             exploración libre
data/                  solo README y .gitkeep en git; el contenido se ignora
docs/
  adr/                 Architecture Decision Records (ADR-NNN-titulo.md)
  plan/plan.md         plan vigente, roadmap, riesgos, preguntas
  entregables/Semana N/  entregables académicos oficiales
  arquitectura/, literatura/
```

> Estado al 10 oct 2026: andamiaje F0 en `main` (API con `GET /health`, Postgres + pgvector vía Alembic,
> tests, CI en verde); `docker compose up` verificado localmente. `features/` implementado para los
> avances 1 y 2 (`data.py`, `preprocessing.py`, `engineering.py`), aún sin commit, igual que el
> notebook del avance 2. `percepcion/` y `lenguaje/` siguen vacíos.

## 6. Comandos

| Acción | Make | PowerShell (Windows) |
|---|---|---|
| Levantar API + Postgres | `make up` | `docker compose up -d --build` |
| Detener (conserva datos) | `make down` | `docker compose down` |
| Logs | `make logs` | `docker compose logs -f` |
| Migrar | `make migrate` | `docker compose exec api alembic upgrade head` |
| Tests (base arriba y migrada) | `make test` | `pytest` |
| Lint | `make lint` | `ruff check . ; ruff format --check .` |
| Formatear | `make format` | `ruff check --fix . ; ruff format .` |
| Paquete para notebooks | — | `python -m venv .venv ; .venv\Scripts\activate ; pip install -e .[dev]` |
| Ejecutar un entregable | — | `jupyter nbconvert --to notebook --execute --inplace "docs/entregables/Semana N/AvanceN.51.ipynb"` |

Salud del sistema: `GET http://localhost:8000/health` → `{"status":"ok","db":"ok"}`.
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
- **Tarea de ML de los avances 2–5 (ADR-009, decidido 10 oct):** `has_errors` sobre CaptainCook4D.
  El clasificador de inicio de paso NO es tarea académica: se descartó porque los subtítulos de
  CrossTask ya no están disponibles. En el producto, la segmentación en pasos es heurística hasta
  tener videos propios anotados. Ver `docs/plan/estado.md`.

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
