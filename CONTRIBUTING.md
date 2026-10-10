# Cómo contribuir

Guía de trabajo del Equipo 51. Si algo aquí choca con el [README](README.md) o con [data/README.md](data/README.md), manda la regla más estricta.

## 1. Ramas

- `main` está protegida: **nunca** se hace push directo.
- Una rama por tarea, creada desde `main` actualizada:

  ```bash
  git switch main && git pull
  git switch -c feat/transcripcion-whisper
  ```

- Nombre de rama: `tipo/descripcion-corta` en minúsculas con guiones, donde `tipo` es uno de los de la sección 3 (`feat/`, `fix/`, `docs/`, `chore/`, ...).
- Ramas cortas: si una tarea dura más de unos días, pártela.

## 2. Pull Requests

1. Antes de abrir el PR, corre localmente `make lint` y `make test` (o sus equivalentes de PowerShell, ver la sección 5 del README).
2. Abre el PR contra `main` con una descripción de **qué** cambia, **por qué** y **cómo se probó**.
3. Lo revisa **un integrante distinto al autor**. El CI (ruff + pytest) debe estar en verde.
4. Si el cambio toca arquitectura (tecnología nueva, reescribir un módulo, tolerar deuda), primero va un ADR en `docs/adr/` (ver [plantilla](docs/adr/0000-plantilla.md)).
5. Se integra con *squash merge*: el título del PR se convierte en el commit y por eso también sigue Conventional Commits.

## 3. Commits: Conventional Commits

Formato: `tipo(alcance): descripción en imperativo y en minúsculas`

| Tipo | Uso |
|---|---|
| `feat` | Funcionalidad nueva |
| `fix` | Corrección de un error |
| `docs` | Solo documentación |
| `test` | Agregar o corregir tests |
| `refactor` | Cambio interno sin cambiar comportamiento |
| `build` | Dependencias, Docker, empaquetado |
| `ci` | GitHub Actions |
| `chore` | Mantenimiento que no entra en los anteriores |

Alcances sugeridos: `plataforma`, `percepcion`, `lenguaje`, `features`, `api`, `db`, `notebooks`, `adr`.

Ejemplos:

```
feat(api): agregar endpoint GET /health
fix(db): reconectar cuando Postgres reinicia
docs(adr): proponer ADR-002 de motor de transcripción
```

Un cambio que rompe compatibilidad lleva `!` (`feat(api)!: ...`) y una línea `BREAKING CHANGE:` en el cuerpo.

## 4. Datos y NDA

Resumen operativo de [data/README.md](data/README.md). En caso de duda, **no subas el archivo** y pregunta.

- **Regla de oro:** ningún video, SOP o dato identificable del cliente entra al repositorio, ni siquiera fragmentos, capturas, transcripciones, audio ni salidas de notebook que los contengan.
- El material del cliente se **referencia por identificador**. Su contenido vive solo en el almacenamiento aprobado por el patrocinador (`CLIENT_STORAGE_*` en `.env`) y entra únicamente cuando el patrocinador lo libere formalmente (Fase 2).
- Se desarrolla con **datasets públicos** (Assembly101, EgoProceL, CaptainCook4D, OpenPack) y con datos sintéticos o grabados por el equipo. Se descargan localmente a rutas ignoradas (`data/raw/`, `data/interim/`, `media/`, ...); en el repo solo se documenta su origen y forma de descarga.
- **Conjunto de validación sellado:** nadie lo mira ni lo usa para ajustar nada hasta la evaluación final.
- **Privacidad:** los rostros de trabajadores son datos personales (LFPDPPP). Se anonimizan cuando el caso lo permita.
- **Secretos:** solo `.env.example` se versiona, con valores de ejemplo. `.env`, llaves, tokens y credenciales nunca se suben. Si un secreto llega a un commit, avisa al equipo de inmediato y rótalo: borrarlo del historial no basta.
- **No relajes el `.gitignore`.** Si necesitas versionar algo que hoy está ignorado, se discute en el PR.
- Antes de cada commit, revisa `git status` y `git diff --staged`, sobre todo en notebooks (las salidas pueden incluir datos).

## 5. Notebooks y entregables académicos

- **Ubicación:** el entregable oficial va en `docs/entregables/Semana N/AvanceN.51.ipynb`; la exploración libre, en `notebooks/`.
- **Un entregable ya entregado no se modifica** (p. ej. `Semana 3/Avance1.51.ipynb`). Si hay que corregir algo, se corrige en el paquete y se documenta en el siguiente avance.
- **El código vive en `src/sopvid/features/`**, con tests en `tests/test_features_*.py`. Los notebooks lo importan; no copian funciones de otro notebook.
- **Regla anti-fuga:** todo lo que aprende de los datos (medianas, codificadores, escaladores, selección, PCA) se ajusta solo con entrenamiento, dentro de un `Pipeline` de scikit-learn. La validación cruzada se agrupa por grabación (`GroupKFold`). Las etiquetas de validación y prueba no se miran.
- **Antes de entregar,** el notebook debe correr de principio a fin:

  ```powershell
  jupyter nbconvert --to notebook --execute --inplace "docs/entregables/Semana N/AvanceN.51.ipynb"
  ```

  Revisa además que las salidas no muestren rutas locales (p. ej. `C:\Users\...`) ni datos del cliente.
- **Dependencias nuevas:** van con versión exacta en `pyproject.toml`, en el extra que corresponda (`ml`, `notebooks` o `dev`), no en el núcleo, para que la imagen de la API no crezca.
