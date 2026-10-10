# AI Co-Pilot Video-to-SOP

Generación asistida, verificable y trazable de Procedimientos Operativos Estándar (SOP) a partir de video de operación, con validación humana (Human-in-the-Loop) y despliegue en planta.

> **Repositorio privado.** El código y la arquitectura son propiedad de Alignity IQ Edge conforme al NDA firmado. No es público y no se comparte fuera del equipo, el asesor y el patrocinador.

---

## 1. Descripción

Sistema que convierte video de operación en planta en SOPs escritos, verificables y trazables. Percibe acciones y objetos del video, transcribe la narración del experto, consolida varios videos de un mismo procedimiento en una estructura de pasos, y redacta el SOP en lenguaje natural con cada paso ligado a su evidencia en video.

Es una **segunda iteración**: el equipo parte de una base de código heredada del trimestre anterior y se obliga a mejorarla, no a reescribirla desde cero (ver [ADR-001 · Herencia del código](docs/adr/ADR-001-herencia.md)).

> **Nota:** esta sección se actualizará cuando se apruebe el ADR-001.

Proyecto Integrador (TC5035) · Maestría en Inteligencia Artificial Aplicada · Tecnológico de Monterrey.

## 2. Equipo

| Integrante | Matrícula | Frente |
|---|---|---|
| Marie Kate Palau | A01705711 | _(por acordar en Semana 1)_ |
| Emmanuel Merida | A01795858 | _(por acordar en Semana 1)_ |
| Sara Castillo | A01224696 | _(por acordar en Semana 1)_ |

Asesor: Dr. Gerardo Jesús Camacho González · Patrocinador: Dr. Jose Jacobo Eluani Vázquez (Alignity IQ Edge) · jeluani@tec.mx

## 3. Arquitectura de referencia

| Capa | Pregunta que responde | Tecnología |
|---|---|---|
| 0 · Fuente de video | ¿De dónde llega la imagen? | Abstracción: archivo, cámara fija, teléfono o lentes tras una misma interfaz |
| 1a · Percepción visual | ¿Qué acción ocurre y cuándo? | V-JEPA 2 (attentive probes sobre backbone congelado) |
| 1b · Percepción de audio | ¿Qué explica el experto? | Transcripción con marcas de tiempo (Whisper / Voxtral) |
| 2 · Estructura | ¿Cuál es el procedimiento y en qué orden? | Grafo de tareas de orden parcial |
| 3 · Lenguaje | ¿Cómo se escribe el SOP? ¿Cómo se conversa? | Gemma 4 (pesos abiertos, servible localmente) |
| 4 · Incertidumbre y HITL | ¿Debo preguntar, y qué? | Umbral de confianza + valor esperado de la respuesta |
| 5 · Plataforma | ¿Quién ve y aprueba qué? | Multiusuario, control de acceso, versionado, auditoría |

Dominio de IA predominante: **Visión Computacional**.

## 4. Estructura del repositorio

Paquete Python instalable `sopvid` (src layout). Estado: **fase F0**, con la API y una base vacía funcionando. Los frentes de percepción, lenguaje y features están reservados.

```
├── README.md
├── CONTRIBUTING.md             # ramas, PRs, commits y reglas de datos/NDA
├── .env.example                # variables con valores de EJEMPLO (sin secretos)
├── pyproject.toml              # paquete sopvid, dependencias fijadas, ruff y pytest
├── Dockerfile                  # imagen de la API (Python 3.11)
├── docker-compose.yml          # API + PostgreSQL 16 con pgvector
├── Makefile                    # up, down, logs, migrate, test, lint, format
├── alembic.ini
├── .github/workflows/ci.yml    # ruff + pytest con Postgres en cada push y PR
├── src/sopvid/
│   ├── plataforma/
│   │   ├── config.py           # settings (pydantic-settings, lee .env)
│   │   ├── db.py               # engine, sesión y Base de SQLAlchemy
│   │   └── api/                # FastAPI: main.py, health.py (GET /health)
│   ├── percepcion/             # ingesta, transcripción y segmentación en pasos (reservado)
│   ├── lenguaje/               # búsqueda híbrida, chat RAG y SOP (reservado)
│   └── features/               # limpieza e ingeniería de características (reservado)
├── migrations/                 # Alembic; 0001 habilita la extensión vector
├── tests/                      # /health y conexión a la base
├── frontend/                   # Angular (entra en la semana 3 del roadmap)
├── notebooks/                  # exploración libre
├── data/                       # data card y reglas de datos (README.md); datos ignorados por Git
└── docs/
    ├── adr/                    # Architecture Decision Records (índice + plantilla)
    └── entregables/            # Semana N/AvanceN.51.ipynb (importan sopvid)
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
curl http://localhost:8000/health        # {"status":"ok","db":"ok"}
```

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

Para los notebooks de `docs/entregables/`, selecciona el kernel del `.venv`. `sopvid` encuentra el `.env` de la raíz aunque el notebook corra en una subcarpeta.

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
| 1 | Planteamiento del proyecto + ADR-001 | `docs/entregables/`, `docs/adr/` |
| 2 | Avance 0. Propuesta y firma de convenios | `docs/entregables/` |
| 8 | Avance 6. Producto de difusión | `docs/entregables/` |
| 9 | Avance 7. Resumen ejecutivo | `docs/entregables/` |

## 8. Gobernanza

- Rama principal protegida; una rama por tarea; nunca push directo a ramas protegidas.
- Todo cambio entra por Pull Request revisado por un integrante distinto al autor, con CI en verde.
- Commits convencionales: `tipo(alcance): descripción corta`.
- **Sin secretos en el repo**: solo los nombres de las variables de entorno en `.env.example`, sin valores. Nada de contraseñas, tokens ni llaves.
- Nada de binarios pesados, modelos grandes ni video en el repo.

## 9. Propiedad intelectual

Todo el contenido de este repositorio está sujeto al Acuerdo de Confidencialidad y Cesión de Propiedad Intelectual firmado con Alignity IQ Edge / Dr. Jose Jacobo Eluani Vázquez.
