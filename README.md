# AI Co-Pilot Video-to-SOP

Valida videos de operación contra su Procedimiento Operativo Estándar (SOP), redacta el SOP cuando no existe y permite buscar al segundo exacto. Todo corre local, con modelos abiertos y costo cero.

> **Repositorio privado.** El código y la arquitectura son propiedad de Alignity IQ Edge conforme al NDA firmado. No es público y no se comparte fuera del equipo, el asesor y el patrocinador.

---

## 1. Descripción

Aplicación web que analiza el video de un operador narrando su trabajo, según el documento **"Requerimientos técnicos y funcionales de proyecto SOP V1.0"** del patrocinador (16 oct 2026):

1. **Validar contra un SOP.** Indica qué pasos faltan, sobran o cambian de orden, y si coinciden las personas, los tiempos y el contexto. Entrega un reporte con porcentaje de cumplimiento, semáforo y PDF; cada hallazgo enlaza al segundo del video.
2. **Crear el SOP desde el video.** Si no hay SOP, lo redacta en español (cuadro resumen, tabla de pasos, palabras clave) para corregirlo, guardarlo en la biblioteca y descargarlo en PDF.
3. **Buscar.** Una vista tipo chat busca una palabra o frase en los videos publicados y salta al segundo exacto.

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

Paquete Python instalable `sopvid` (src layout). Estado al 17 oct 2026: **fase F0** cerrada (API y base vacía funcionando con `docker compose up`), `features/` implementado para los avances académicos 1 y 2, y en la rama `feat/llm-spike` el cliente del LLM con Ollama y el prototipo de segmentación en pasos. El resto de la versión 1.0 está por construir.

```
├── README.md
├── CONTRIBUTING.md             # ramas, PRs, commits y reglas de datos/NDA
├── .env.example                # variables con valores de EJEMPLO (sin secretos)
├── pyproject.toml              # paquete sopvid, dependencias fijadas (extras ml, notebooks, dev), ruff y pytest
├── Dockerfile                  # imagen de la API (Python 3.11)
├── docker-compose.yml          # API + PostgreSQL 16 con pgvector; Ollama con el profile "llm"
├── Makefile                    # up, down, logs, migrate, test, lint, format
├── alembic.ini
├── .github/workflows/ci.yml    # ruff + pytest con Postgres en cada push y PR
├── src/sopvid/
│   ├── plataforma/
│   │   ├── config.py           # settings (pydantic-settings, lee .env)
│   │   ├── db.py               # engine, sesión y Base de SQLAlchemy
│   │   └── api/                # FastAPI: main.py, health.py (GET /health)
│   ├── percepcion/             # subida, ffmpeg, transcripción, fotogramas y pasos del video
│   ├── lenguaje/               # cliente del LLM, SOP, emparejamiento, reporte y búsqueda exacta
│   └── features/               # datos de CaptainCook4D, preprocesamiento (avance 1) e ingeniería de características (avance 2)
├── migrations/                 # Alembic; 0001 habilita la extensión vector
├── tests/                      # /health, conexión a la base y sopvid.features
├── frontend/                   # Angular (entra en la semana 3 del roadmap)
├── notebooks/                  # exploración libre
├── data/                       # data card y reglas de datos (README.md); datos ignorados por Git
└── docs/
    ├── adr/                    # Architecture Decision Records (índice + plantilla)
    ├── entregables/            # Semana N/AvanceN.51.ipynb (importan sopvid)
    └── plan/                   # plan vigente (plan.md) y estado del proyecto (estado.md)
```

## 5. Cómo levantar el proyecto

Requisitos: Docker Desktop (con Compose v2) y Git. Para desarrollo y notebooks, además Python 3.11.

### Opción A: Docker (API + base)

```bash
git clone <URL-del-repo>
cd video-to-sop-copilot
cp .env.example .env                     # PowerShell: Copy-Item .env.example .env
docker compose up -d --build             # levanta Postgres y la API (la API espera a que la base esté sana)
docker compose exec api alembic upgrade head   # migraciones (habilita pgvector)
curl http://localhost:8000/health        # {"status":"ok","db":"ok","llm":"no_disponible"}
```

LLM local opcional (Ollama con GPU NVIDIA): `docker compose --profile llm up -d`; con él arriba,
`/health` informa `"llm":"ok"`. Detalles en [docs/dev/llm.md](docs/dev/llm.md).

En PowerShell, la comprobación equivalente es `Invoke-RestMethod http://localhost:8000/health`. La documentación interactiva de la API queda en <http://localhost:8000/docs>.

> **Puerto 5432.** La base se publica en `POSTGRES_PORT` (5432 por defecto). Si tienes otro Postgres local, apágalo antes o cambia `POSTGRES_PORT` en tu `.env`. Los datos viven en el volumen `sopvid_pgdata`: `docker compose down` los conserva y `docker compose down -v` los borra.

### Opción B: venv local (tests, lint y notebooks)

La base sigue corriendo en Docker y el código corre en tu máquina, contra `localhost`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1             # bash: source .venv/bin/activate
pip install -e ".[dev]"                  # editable: los notebooks hacen `import sopvid`
docker compose up -d db                  # solo la base
alembic upgrade head
pytest
```

Para los notebooks de `docs/entregables/`, selecciona el kernel del `.venv`. `sopvid` encuentra el `.env` de la raíz aunque el notebook corra en una subcarpeta. Las anotaciones públicas de CaptainCook4D se descargan solas a `DATA_DIR` (por defecto `data/raw/captaincook4d`, ignorada por Git) la primera vez que se ejecuta un avance.

Para comprobar que un entregable corre de principio a fin:

```powershell
jupyter nbconvert --to notebook --execute --inplace "docs/entregables/Semana 4/Avance2.51.ipynb"
```

Los tests de `tests/test_features_avance1.py` comparan contra los resultados del avance 1 y se saltan si los datos no están descargados (por ejemplo, en CI).

### Targets del Makefile y su equivalente en PowerShell

| `make` | PowerShell (desde la raíz, con el `.venv` activo para test/lint) |
|---|---|
| `make up` | `docker compose up -d --build` |
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
| 5–7 | Avances 3–5 (baseline, modelos, ensambles) · 18 oct, 25 oct y 1 nov | `docs/entregables/Semana N/` |
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
