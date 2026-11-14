# AI Co-Pilot Video-to-SOP

Valida videos de operación contra su Procedimiento Operativo Estándar (SOP), redacta el SOP cuando no existe y permite buscar al segundo exacto. Todo corre local, con modelos abiertos y costo cero.

> **Propiedad y confidencialidad.** El código fuente, la arquitectura, las lógicas de
> flujo y los prompts de este proyecto son propiedad de Alignity IQ Edge / Dr. Jose
> Jacobo Eluani Vázquez, bajo el NDA del 1 de septiembre de 2026 (cl. 3.1 y 3.2). La
> entrega final se hace en el repositorio que designe el patrocinador (cl. 8).
>
> **Nada del cliente entra a este repositorio** (cl. 5): ni videos, ni SOP, ni
> transcripciones, ni capturas, ni datos identificables, ni siquiera fragmentos. El
> material del cliente se referencia por identificador y vive en el almacenamiento
> aprobado. El desarrollo usa datasets públicos y video grabado por el equipo. En video
> de planta aparecen rostros de trabajadores: dato personal bajo la LFPDPPP.

---

## 1. Descripción

Aplicación web que analiza el video de un operador narrando su trabajo, según el documento **"Requerimientos técnicos y funcionales de proyecto SOP V1.0"** del patrocinador (16 oct 2026):

1. **Validar contra un SOP.** Indica qué pasos faltan, sobran o cambian de orden, y si coinciden las personas, los tiempos y el contexto. Entrega un reporte con porcentaje de cumplimiento, semáforo y PDF; cada hallazgo enlaza al segundo del video.
2. **Crear el SOP desde el video.** Si no hay SOP, lo redacta en español (cuadro resumen, tabla de pasos, palabras clave) para corregirlo, guardarlo en la biblioteca y descargarlo en PDF.
3. **Buscar.** Una vista tipo chat busca una palabra o frase en los videos publicados y salta al segundo exacto.

**Primer hito: MVP de validación (8 nov 2026).** Un video y un SOP en Markdown entran; sale el reporte de pasos (Cumple, Parcial, Falta, Sobra, Fuera de orden) con el porcentaje y el segundo de cada hallazgo. Solo voz. Después se agregan el SOP generado, personas y tiempos, fotogramas, PDF y búsqueda ([plan §5.1](docs/plan/plan.md#51-mvp-de-validación-hito-del-8-nov)).

> **Estado del MVP (7 nov 2026).** El camino completo funciona por la API y en la web: en `/nuevo` se suben el SOP y el video, y la pantalla del reporte (RF-20) muestra el semáforo, la tabla paso a paso y el video al lado, que salta al segundo de cada fila. Medido con `scripts/medir_mvp.py` (3 repeticiones por video, [informe](docs/adr/datos/mvp/mvp-20261107-1113.md)): el video **B** pasa 3/3 (*Falta* en los pasos 2 y 6, la limpieza de la carcasa como *Sobra*, 66.7 %, rojo) y el **A** pasa 2/3 (91.7 % y 100 %, verde; en la otra corrida Gemma dejó un paso sin redactar). Gemma no es determinista aun con temperatura 0, así que para la demo se muestran reportes ya procesados. Detalle en [docs/plan/estado.md](docs/plan/estado.md).

El código se construye desde cero: el código del POC no se entregó y el patrocinador indicó seguir con la arquitectura propia (13 oct 2026). Ver [ADR-001](docs/adr/ADR-001-herencia.md) y el [plan](docs/plan/plan.md).

Proyecto Integrador (TC5035) · Maestría en Inteligencia Artificial Aplicada · Tecnológico de Monterrey.

## 2. Equipo

| Integrante | Matrícula | Frente |
|---|---|---|
| Emmanuel Merida | A01795858 | Modelos: lectura del SOP, contexto, pasos, emparejamiento, reporte, SOP generado, PDF · avances académicos |
| Sara Castillo | A01224696 | Video y web: subida, transcripción, fotogramas, pantallas en Angular, búsqueda |

Marie Kate Palau (A01705711) dejó el equipo en octubre de 2026; el alcance se acotó a dos personas.

Asesor: Dr. Gerardo Jesús Camacho González · Patrocinador: Dr. Jose Jacobo Eluani Vázquez (Alignity IQ Edge) · jeluani@tec.mx

## 3. Arquitectura de referencia

| Etapa | Qué hace | Tecnología (local) |
|---|---|---|
| Subida y medios | Video en partes de 16 MB; audio, fotogramas y miniaturas | FastAPI, ffmpeg |
| Voz | Idioma y transcripción con tiempo por palabra | faster-whisper |
| Visión | Describe hasta 20 fotogramas: equipos, personas, texto, riesgos | Gemma 4 E4B (Ollama) |
| Lenguaje | Convierte el SOP, arma el contexto, extrae los pasos del video y redacta el SOP | Gemma 4 E4B con JSON Schema |
| Comparación | Empareja pasos del SOP y del video; revisa orden, personas y tiempos | MiniLM multilingüe + algoritmo húngaro; Gemma 4 solo en casos dudosos |
| Salidas | Reporte y SOP en PDF con QR al segundo; TXT, SRT, JSON | ReportLab, qrcode |
| Búsqueda | Coincidencia exacta sin acentos ni plurales simples | Índice de palabras en PostgreSQL |

Hardware de referencia: GPU NVIDIA de 8 GB (RTX 2070 SUPER), 32 GB de RAM. Detalle y decisiones en [docs/plan/plan.md](docs/plan/plan.md) y [docs/adr/](docs/adr/).

Dominios de IA: voz, visión y lenguaje (multimodal), con modelos pequeños locales.

## 4. Estructura del repositorio

Paquete Python instalable `sopvid` (src layout) y frontend en Angular. Estado al 10 nov 2026 (cierre de S5), en `main`:

- **Validación de punta a punta (MVP).** `POST /sops` convierte y guarda el SOP; `POST /videos` con su `sop_id` transcribe, segmenta en pasos con Gemma 4, empareja con MiniLM y deja el reporte en `GET /videos/{id}/reporte`. `POST /videos/{id}/validar` repite solo la validación, sin Whisper (ADR-019). `GET /videos/{id}/video` entrega el video con `Range` (206) para que el reproductor salte a cualquier segundo. Rutas en [docs/dev/api.md](docs/dev/api.md).
- **Frontend Angular 22** (`frontend/`): `/nuevo` (subir SOP y video) y `/videos/:id/reporte` (RF-20: semáforo, resumen, tabla con cita y segundo, video que salta al segundo de cada fila, avance mientras procesa y la sección "Cómo se obtuvo", con dónde corrió cada modelo, la GPU y los tiempos). Detalle en [frontend/README.md](frontend/README.md).
- **GPU opcional (ADR-018).** Todo corre en CPU; con GPU NVIDIA, Whisper y Gemma la usan. `scripts/levantar.ps1` detecta la GPU y levanta el compose que corresponde.
- **Semana 5.** SOP en PDF y Word; ficha de contexto (RF-12); afinidad y personas (RF-15, RF-17, ADR-020); tiempos (RF-16, ADR-021); rescate de *Falta* (ADR-022); SOP generado desde el video (RF-22 a 25 y 27, ADR-023). Medición de cierre: `scripts/medir_s5.py` ([informe](docs/adr/datos/s5/medicion-s5-20261110-1311.md)).
- **Medición del MVP** con repeticiones y el commit registrado (`scripts/medir_mvp.py`).
- `features/` para los avances académicos (CaptainCook4D).

Lo que sigue: fotogramas y subida por partes, editor del SOP generado (RF-26), PDF del reporte y del SOP, descargas y búsqueda.

```
├── README.md
├── CONTRIBUTING.md             # ramas, PRs, commits y reglas de datos/NDA
├── .env.example                # variables con valores de EJEMPLO (sin secretos)
├── pyproject.toml              # paquete sopvid, dependencias fijadas (extras ml, notebooks, dev), ruff y pytest
├── Dockerfile                  # imagen de la API (Python 3.11)
├── docker-compose.yml          # API + PostgreSQL 16 con pgvector + frontend (web); Ollama con el profile "llm"
├── Makefile                    # up, down, logs, migrate, test, lint, format
├── alembic.ini
├── .github/workflows/ci.yml    # ruff + pytest con Postgres en cada push y PR
├── src/sopvid/
│   ├── plataforma/
│   │   ├── config.py           # settings (pydantic-settings, lee .env)
│   │   ├── db.py               # engine, sesión y Base de SQLAlchemy
│   │   ├── hardware.py         # GPU detectada y dónde corre cada modelo (ADR-018)
│   │   ├── procesamiento.py    # cola de un trabajador: análisis y validación (RF-14, 19)
│   │   └── api/                # FastAPI: main.py, health.py, sops.py, videos.py
│   ├── percepcion/             # subida, ffmpeg, transcripción, fotogramas y pasos del video
│   ├── lenguaje/               # cliente del LLM, SOP, emparejamiento, reporte y búsqueda exacta
│   └── features/               # datos de CaptainCook4D, preprocesamiento (avance 1) e ingeniería de características (avance 2)
├── migrations/                 # Alembic; 0001 habilita la extensión vector
├── tests/                      # pytest: API, base, percepción, lenguaje, validación y features; fixtures de SOP y reporte
├── scripts/                    # levantar.ps1, convertir_sop.py, analizar_video.py, medir_mvp.py, calibrar_umbrales.py…
├── frontend/                   # Angular 22: /nuevo y /videos/:id/reporte (RF-20); ver frontend/README.md
├── notebooks/                  # exploración libre
├── data/                       # data card y reglas de datos (README.md); datos ignorados por Git
└── docs/
    ├── adr/                    # Architecture Decision Records (índice + plantilla); datos/ con las mediciones
    ├── contrato/               # esquemas JSON (SOP, análisis, reporte) y plantilla del SOP en Markdown
    ├── dev/                    # guías: api.md, llm.md, transcripcion.md
    ├── entregables/            # Semana N/AvanceN.51.ipynb (importan sopvid)
    └── plan/                   # plan vigente (plan.md) y estado del proyecto (estado.md)
```

## 5. Cómo levantar el proyecto

Requisitos: Docker Desktop (con Compose v2) y Git. Para desarrollo y notebooks, además Python 3.11.

### Opción A: Docker (API + base + frontend)

```bash
git clone <URL-del-repo>
cd video-to-sop-copilot
cp .env.example .env                     # PowerShell: Copy-Item .env.example .env
docker compose up -d --build             # levanta Postgres, la API y el frontend (la API espera a que la base esté sana)
docker compose exec api alembic upgrade head   # migraciones (habilita pgvector)
curl http://localhost:8000/health        # {"status":"ok","db":"ok","llm":"no_disponible"}
```

LLM local opcional (Ollama con GPU NVIDIA): `docker compose --profile llm up -d`; con él arriba,
`/health` informa `"llm":"ok"`. Detalles en [docs/dev/llm.md](docs/dev/llm.md). La validación
necesita el LLM: sin Ollama, el video termina en `error` con "LLM no disponible".

En Windows, `scripts/levantar.ps1` hace lo mismo y decide solo si usa la GPU (ADR-018): si hay GPU
NVIDIA y Docker tiene el runtime `nvidia`, suma `docker-compose.gpu.yml` y Gemma corre en la GPU; si
no, todo corre en CPU, con el mismo resultado pero más lento. La API dentro de Docker sigue en CPU.

```powershell
.\scripts\levantar.ps1              # api + base + frontend + Ollama, con GPU si hay
.\scripts\levantar.ps1 -Build       # reconstruye la imagen de la api
.\scripts\levantar.ps1 -SinLLM      # api + base + frontend, sin Ollama
.\scripts\levantar.ps1 -Plan        # dice qué haría, sin levantar nada
.\scripts\levantar.ps1 -Detener     # detiene todo, conserva datos y modelos
```

En PowerShell, la comprobación equivalente es `Invoke-RestMethod http://localhost:8000/health`. La documentación interactiva de la API queda en <http://localhost:8000/docs>.

El frontend (Angular con `ng serve`, servicio `web`) queda en <http://localhost:4200> y se recarga solo al guardar un archivo de `frontend/`: no hace falta otra terminal ni Node instalado. El primer arranque tarda unos minutos (`npm ci`); los siguientes solo reinstalan si cambia `package-lock.json`. Los errores de compilación se ven con `docker compose logs -f web`. Detalles en [frontend/README.md](frontend/README.md).

> **Puerto 5432.** La base se publica en `POSTGRES_PORT` (5432 por defecto). Si tienes otro Postgres local, apágalo antes o cambia `POSTGRES_PORT` en tu `.env`. Los datos viven en el volumen `sopvid_pgdata`: `docker compose down` los conserva y `docker compose down -v` los borra.

### Opción B: venv local (tests, lint y notebooks)

La base sigue corriendo en Docker y el código corre en tu máquina, contra `localhost`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1             # bash: source .venv/bin/activate
pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu   # solo CPU, antes que lo demás
pip install -e ".[dev]"                  # editable: los notebooks hacen `import sopvid`
docker compose up -d db                  # solo la base
alembic upgrade head
pytest
```

`torch` (lo usa MiniLM para emparejar pasos) va primero y desde el índice CPU de PyTorch, con la misma versión que `pyproject.toml`: queda `torch 2.13.0+cpu` y `pip install -e` ya no lo reemplaza. En Windows el wheel de PyPI también es solo CPU; en Linux arrastraría CUDA (varios GB). Los pesos de MiniLM (~470 MB) se descargan la primera vez a `EMBEDDER_CACHE_DIR` (por defecto `models/embedder`, ignorada por Git).

Para los notebooks de `docs/entregables/`, selecciona el kernel del `.venv`. `sopvid` encuentra el `.env` de la raíz aunque el notebook corra en una subcarpeta. Las anotaciones públicas de CaptainCook4D se descargan solas a `DATA_DIR` (por defecto `data/raw/captaincook4d`, ignorada por Git) la primera vez que se ejecuta un avance.

Para comprobar que un entregable corre de principio a fin:

```powershell
jupyter nbconvert --to notebook --execute --inplace "docs/entregables/Semana 4/Avance2.51.ipynb"
```

Los tests de `tests/test_features_avance1.py` comparan contra los resultados del avance 1 y se saltan si los datos no están descargados (por ejemplo, en CI).

### Opción C: frontend (Angular) en el host

Sin Docker para el frontend (la opción A ya lo levanta en el servicio `web`).
Requisito: Node 24 LTS (`^24.15.0`) y npm; Angular 22 se usa con `npx`, sin instalar nada global.
La API no tiene CORS: `ng serve` reenvía `/api` a `API_URL` (por defecto `http://localhost:8000`) con `frontend/proxy.conf.js`.

```powershell
# API en el host (con GPU si hay), desde la raíz y con el .venv activo; o la de Docker (opción A)
uvicorn sopvid.plataforma.api.main:app --host 127.0.0.1 --port 8000
# en otra terminal
cd frontend
npm install
npx ng serve                # http://localhost:4200 → /nuevo
npx ng test --watch=false   # Vitest con jsdom, sin navegador
```

Para probar: en `/nuevo`, sube `tests/fixtures/sop_filtro_agua.md` y un video; al aceptarlo, la
página pasa al reporte, que muestra el avance cada 3 s hasta que está listo. Los tipos del reporte se
generan desde `docs/contrato/reporte.schema.json` con `npm run tipos`. Detalle en
[frontend/README.md](frontend/README.md).

### Whisper en CPU o GPU

Whisper usa `large-v3-turbo` en CPU y en GPU (ADR-018, `WHISPER_MODELO_CPU`); otro modelo deja el
aviso `transcripcion_no_referencia`. Corre en cualquier máquina (`WHISPER_DISPOSITIVO=auto`,
`WHISPER_COMPUTE_TYPE=auto`: float16 en GPU, int8 en CPU); para usar la GPU desde el host hace falta
`pip install -e ".[gpu]"`, y en Docker la API transcribe en CPU. Si el `WHISPER_COMPUTE_TYPE` pedido
solo existe en GPU (`float16`, `bfloat16`…) y Whisper termina en CPU, se cambia por int8 en lugar de
fallar, y `/health` lo avisa. Detalle en [docs/dev/transcripcion.md](docs/dev/transcripcion.md).

### Medir el MVP

`scripts/medir_mvp.py` comprueba el criterio del MVP (plan §5.1) con repeticiones: transcribe cada
video una vez y repite la validación (`--repeticiones`, 3 por defecto), porque Gemma no es
determinista. Registra el commit, los modelos, los umbrales y dónde corrió cada uno. Necesita el
entorno activo y Ollama arriba:

```powershell
python scripts/medir_mvp.py --sop tests/fixtures/sop_filtro_agua.md `
    --anotacion media/anotacion_ab.json --repeticiones 3 `
    video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4
```

El informe queda en `data/interim/mvp/` (ignorada por Git); con `--docs`, también en
`docs/adr/datos/mvp/`, solo con números de paso, segundos y estados. Sale con 0 si todo pasa, 1 si
alguna corrida no pasa y 2 si alguna no es válida. Los videos A y B viven fuera de Git (NDA).

### Escribir un SOP de referencia (Markdown o TXT)

Un SOP en Markdown o TXT se convierte con código, sin LLM, si sigue la plantilla
[docs/contrato/plantilla_sop.md](docs/contrato/plantilla_sop.md) ([ADR-015](docs/adr/ADR-015-sop-plantilla-markdown.md)).
Solo son obligatorios `# Título` y `## Pasos` (con `### 1. Nombre` o una lista `1. Nombre`); el resumen, los roles, el equipo, los riesgos y "En caso de falla" son opcionales. Hay un ejemplo completo en [tests/fixtures/sop_filtro_agua.md](tests/fixtures/sop_filtro_agua.md) y uno mínimo en [tests/fixtures/sop_filtro_agua_simple.txt](tests/fixtures/sop_filtro_agua_simple.txt).

```powershell
python scripts/convertir_sop.py mi_sop.md --salida data/interim/mi_sop.json   # JSON del esquema SOP
python scripts/convertir_sop.py mi_sop.txt > mi_sop.json                      # sin --salida: a la salida estándar
```

El archivo se lee en UTF-8. Las advertencias (numeración, claves desconocidas, tiempos…) salen en la salida de errores y no detienen la conversión. Si falta el título o los pasos, el script sale con código 1 y dice el formato esperado. Un SOP del cliente nunca se copia al repo (NDA): se convierte desde el almacenamiento aprobado. PDF, Word y texto libre se convierten con Gemma 4 en S5.

### Targets del Makefile y su equivalente en PowerShell

| `make` | PowerShell (desde la raíz, con el `.venv` activo para test/lint) |
|---|---|
| `make up` | `docker compose up -d --build` |
| `make up-gpu` | `$env:API_URL_WEB="http://host.docker.internal:8000"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d db ollama web; Remove-Item Env:API_URL_WEB` (la API en el host con la GPU, `docs/dev/api.md`) |
| `make down` | `docker compose down` |
| `make logs` | `docker compose logs -f` |
| `make migrate` | `docker compose exec api alembic upgrade head` |
| `make test` | `pytest` |
| `make lint` | `ruff check . ; ruff format --check .` |
| `make format` | `ruff check --fix . ; ruff format .` |

Objetivo de reproducibilidad: clonar y ejecutar un solo script debe reproducir la demo en ≤ 30 minutos en una máquina limpia.

## 6. Datos y privacidad

- El desarrollo se hace con **datasets públicos** y **datos sintéticos o grabados por el equipo** (ver `data/README.md`).
- **Ningún video, SOP o dato identificable del cliente entra al repositorio**, ni siquiera fragmentos, capturas o transcripciones. Se referencia por identificador; el contenido vive en el almacenamiento aprobado por el patrocinador.
- En video de planta pueden aparecer rostros de trabajadores: es dato personal y se trata conforme a la LFPDPPP, con anonimización cuando el caso lo permita.

## 7. Entregables

| Semana | Entregable | Ubicación |
|---|---|---|
| 1 | Planteamiento del proyecto + ADR-001 | `docs/entregables/Semana 1/`, `docs/adr/` |
| 2 | Avance 0. Propuesta y firma de convenios | `docs/entregables/` |
| 3 | Avance 1. Análisis exploratorio (CaptainCook4D) · entregado | `docs/entregables/Semana 3/Avance1.51.ipynb` |
| 4 | Avance 2. Ingeniería de características · entregado | `docs/entregables/Semana 4/Avance2.51.ipynb` |
| 5 | Avance 3. Baseline · entregado | `docs/entregables/Semana 5/Avance3.51.ipynb` |
| 6 | Avance 4. Modelos alternativos · entregado | `docs/entregables/Semana 6/Avance4.51.ipynb` |
| 7 | Avance 5. Ensambles y modelo final · generado y ejecutado | `docs/entregables/Semana 7/Avance5.51.ipynb` |
| 8 | Avance 6. Producto de difusión | `docs/entregables/` |
| 9 | Avance 7. Resumen ejecutivo | `docs/entregables/` |

## 8. Gobernanza

- Rama principal protegida; una rama por tarea; nunca push directo a ramas protegidas.
- Todo cambio entra por Pull Request revisado por un integrante distinto al autor, con CI en verde.
- Commits convencionales: `tipo(alcance): descripción corta`.
- **Sin secretos en el repo**: `.env.example` solo lleva nombres de variables y valores de ejemplo para desarrollo local. Nada de contraseñas reales, tokens ni llaves.
- Los entregables ya entregados en `docs/entregables/` no se modifican.
- Nada de binarios pesados, modelos grandes ni video en el repo.

## 9. Propiedad intelectual

Todo el contenido de este repositorio está sujeto al Acuerdo de Confidencialidad y Cesión de Propiedad Intelectual firmado con Alignity IQ Edge / Dr. Jose Jacobo Eluani Vázquez.
