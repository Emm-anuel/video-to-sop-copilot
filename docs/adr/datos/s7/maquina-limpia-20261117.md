# Ensayo de máquina limpia · 17 nov 2026

Issue: [#38](https://github.com/Emm-anuel/video-to-sop-copilot/issues/38).

Qué es: la instalación desde cero siguiendo el README, en **un clon aparte de la máquina de
desarrollo** (`..\sopvid-limpia`, rama `chore/maquina-limpia` desde `2f68f5c`, proyecto de compose
`sopvid-limpia`). **No es una máquina limpia de verdad** y no cierra la meta de S6: faltan Docker
Desktop, WSL2 y el driver (ya estaban), las imágenes base ya estaban en la caché de Docker y el
firewall ya tenía reglas. Eso se cubre con [`docs/demo/maquina-limpia.md`](../../../demo/maquina-limpia.md)
en otro equipo; hasta entonces `docs/plan/plan.md` no marca ✓ la "App completa".

Sin material del cliente: solo pasos, segundos, porcentajes y estados.

## Equipo y condiciones

| | |
|---|---|
| CPU / RAM | i7-10700K (16 hilos) · 32 GB; Docker (WSL2) ve 16.7 GB |
| GPU | RTX 2070 SUPER 8 GB, driver 617.42 |
| Software | Windows 11 (10.0.26300), Docker 29.8.0, Compose v2, Python 3.11.9 y ffmpeg 9.0.2 en el host |
| Red | descargas de ~24–28 MB/s (Gemma); Wi-Fi 192.168.50.x, perfil de red *Privada* |
| Aislamiento | `COMPOSE_PROJECT_NAME=sopvid-limpia`: volúmenes `sopvid-limpia_*` (comprobado con `docker compose --profile llm config` antes del primer `up`); `sopvid` solo se paró (`stop`), nunca `down -v` |
| Caché de Docker | python, node, pgvector y ollama **ya estaban**: su descarga no se midió |

## Tiempos, paso a paso (Docker, API con Whisper en CPU)

| # | Paso | Tiempo | Resultado |
|---|---|---|---|
| 1 | `git clone` | 2.7 s | `.git` de 12 MB |
| 2 | `docker compose build --no-cache` | **3 min 07 s** | imagen `sopvid-api:0.1.0` de **3.27 GB** (apt+ffmpeg 35 s, torch CPU 32 s, `pip install .` 67 s) |
| 3 | `docker compose up -d --build` | 10 s | db sana, api sana, web arriba |
| 4 | `alembic upgrade head` | 3 s | 0001 a 0008 |
| 5 | `web`: `npm ci` y bundle | 17 s + 7 s | 305 paquetes; 4200 responde 200 y `/api` reenvía bien |
| 6 | `docker compose --profile llm up -d` | 7 s | Ollama sano; `ollama-pull` en marcha. **Sin GPU**: el README decía "con GPU" |
| 7 | descarga de Gemma (`gemma4:e4b-it-q4_K_M`) | **4 min 30 s** | 6.6 GB en el volumen (≈24 MB/s); `/health` pasa a `llm: ok` |
| 8 | recrear Ollama con `docker-compose.gpu.yml` | ~10 s | 43/43 capas en GPU, ~115 tokens/s. Sin volver a descargar |
| 9 | SOP en Word → `listo` | **2 min 44 s** (primera vez) | `metodo: llm`, 6 pasos, 0 advertencias; 101 s son la carga en frío de Gemma |
| 10 | Video A validado, **primera vez** | **3 min 08 s** | 91.67 % verde, 0 *Falta*; Whisper cargó en 74.6 s (descarga de 1.6 GB incluida), MiniLM en 35.1 s (458 MB). Sin timeout |
| 11 | Video A, modelos en caché | **78 s** (video de 135 s: 0.58×) | 100 % verde; Whisper CPU 47 s |
| 12 | PDF, QR, token, publicar, buscar, SRT | segundos | ver abajo |
| 13 | Video E en modo generar, sin imágenes | **144 s** (video de 227 s: 0.63×) | SOP de 13 pasos; Whisper CPU 86 s; advertencia `sin_traducir` |

**De `git clone` al primer reporte validado en Docker: 15 min 51 s** (23:45:55 a 00:01:46), con todas
las descargas y sin demora humana: 8 min 49 s hasta `llm: ok` (incluye poner las claves a mano) más el
paso 9 (2 min 44 s) y el 10 (3 min 08 s), y el paso 8, que el README no decía. **Sin descargas no se
midió de punta a punta**; solo sus piezas: A en 78 s (11), la conversión de SOP con Gemma ya cargada
(~25 s en otras mediciones, `docs/dev/llm.md`) y `up` + migrar (13 s) más 3 min de la imagen si hay
que construirla.

## Modo demo: API en el host con GPU

| # | Paso | Tiempo | Resultado |
|---|---|---|---|
| 14 | `py -3.11 -m venv .venv` | 13 s | |
| 15 | `pip install torch==2.13.0` (índice CPU) | 1 min 25 s | `2.13.0+cpu` |
| 16 | `pip install -e ".[dev,gpu]"` | 3 min 31 s | ctranslate2 4.8.3, faster-whisper 1.2.1 (con los wheels de NVIDIA, ~1.25 GB) |
| 17 | `up -d db ollama web` con `docker-compose.gpu.yml` y `API_URL_WEB` | seg. | web reenvía a `host.docker.internal:8000` |
| 18 | `uvicorn` (un proceso) | 15 s | `/health`: `db: ok`, `llm: ok`, GPU RTX 2070 SUPER, Whisper `cuda/float16` |
| 19 | Video A, **primera vez** (descarga de Whisper y MiniLM al host) | **4 min 54 s** | 100 % verde; Whisper cargó en 151.5 s, MiniLM en 107.5 s |
| 20 | Video A, modelos en caché | **35 s** (0.26×) | 100 % verde, `transcripcion: gpu`, `llm: gpu`; dentro de los 25–44 s medidos antes |

Criterio del encargo (`/health` con `db` y `llm` en `ok`, A con Gemma al 100 % en GPU): **cumplido**.
Prepararlo suma ~5 min de pip y ~5 min de la primera corrida.

## Comparación con lo medido (S5/S6)

| | Medido antes | Ensayo | |
|---|---|---|---|
| A validado | ≥ 90 % sin *Falta* | 91.67 %, 100 %, 100 %, 100 % (4 corridas), 0 *Falta* | cumple; varía entre corridas (Gemma no determinista) |
| Búsqueda (solo A publicado) | «manometro» 3, «cartuchos» 4, «llave de paso» 2 | 3, 4 y 2, en 6–12 ms del servidor | **igual** |
| A con GPU en el host | 25–44 s | 35 s | igual |
| A con Whisper en CPU dentro de Docker | no medido | 78 s (0.58×); E 144 s (0.63×) | extrapolado a 10 min, ~6 min: **no cumple RNF-01** (5 min) con Whisper en CPU |
| QR | ±1 s (RNF-03) | segundo 49.2 en el PDF; el celular abrió `/v/<id>` con el video en el segundo 49 | cumple |

## QR, PDF y acceso

- **PDF del reporte de A:** 4 páginas, 5 enlaces `<APP_URL_PUBLICA>/v/<id>?t=<s>&k=<token>`; el texto
  visible y la anotación del enlace son el mismo (token de 22 caracteres).
- **Token:** con él, sin clave, `/video` responde 206 y `/thumb` 200, también por el proxy del 4200. Con
  el token de otro video, uno alterado o sin token: 401. La clave de carga no abre `/buscar` (401).
- **SOP generado de E:** PDF de 4 páginas con un QR a `/v/<id>?t=0.0&k=…`.
- **Celular** (con `APP_URL_PUBLICA=http://192.168.50.15:4200`, PDF regenerado): **abrió el sistema con
  el video en el segundo 49**. Había una regla de firewall "Puerto 4200" (perfil Private) creada a mano,
  y Docker Desktop Backend ya trae reglas de entrada Private y Public: **no se probó sin la regla
  propia**.
- Un falso positivo mío: el primer intento de validar el token falló (401) porque mi regex pegaba la
  línea siguiente del PDF al token; no es un fallo de la app.

## Hallazgos y correcciones

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | El README llamaba "opcional" al LLM; sin Ollama, validar y generar terminan en error | README §5, `docker-compose.yml` (encabezado) y `docs/dev/llm.md` lo dicen; el script levanta el profile `llm` siempre salvo `-SinLLM` |
| 2 | `--profile llm` solo (README, llm.md) **no usa la GPU**; hacía falta sumar `docker-compose.gpu.yml` | README (comando con GPU a mano) y `levantar.ps1`, que lo suma solo |
| 3 | `levantar.ps1` no copiaba el `.env`, no migraba ni esperaba a `/health` y el README tenía 5 pasos sueltos | `levantar.ps1` reescrito: crea `.env` con claves nuevas, levanta, espera a la API, migra, espera a Gemma y la carga una vez (flags `-SoloEnv`, `-NoEsperar`, `-SinCalentar`) |
| 4 | `SECRETO_ENLACES` se generaba con `python -c …` y la opción A no exige Python | el script lo genera con el generador criptográfico del sistema; a mano, `openssl rand -base64 32` |
| 5 | `docker compose up -d` vuelve antes de que termine la descarga de Gemma: `/health` dice `llm: no_disponible` unos 5 min sin explicación | el script espera y muestra el avance; README lo explica |
| 6 | `make up-gpu` y su equivalente (README, `docs/dev/api.md`, CLAUDE.md §6) **no incluían `ollama-pull`**: en una máquina nueva Gemma nunca se descarga (comprobado con `up --dry-run`) | `ollama-pull` agregado a esos cuatro comandos |
| 7 | El README no decía de dónde salen los videos y el SOP en Word | sección "Material de la demo" (nada del cliente en Git) |
| 8 | Requisitos incompletos: disco, puertos (el 11434 está fijo), GPU, memoria | README §5, "Requisitos para la demo" y `docs/demo/maquina-limpia.md` |
| 9 | La API en Docker con Whisper en CPU no cumple RNF-01 y el README no lo decía | README §5 con los tiempos medidos y la opción D (API en el host con GPU, con los comandos probados) |
| 10 | Primera conversión de SOP: 2 min 44 s por la carga en frío de Gemma (101 s) con un tope de espera de 180 s | `levantar.ps1` carga el modelo al final (en el ensayo solo se probó la ruta con el modelo ya en caché, 28 s) |
| 11 | Los QR para el celular nunca se habían probado | README, "QR del PDF con el celular" (IP, `APP_URL_PUBLICA`, regenerar el PDF, firewall) |
| 12 | `image: sopvid-api:0.1.0` fija el nombre: construir en el clon retagueó la imagen de `sopvid` (mismo commit) | sin cambio; se anota |

## Lo que sigue sin probarse

- **`levantar.ps1` completo desde cero** (clon sin `.env`, sin volúmenes, sin imagen): corrí por
  separado `-Plan`, `-SoloEnv` (en un directorio de prueba: llena las tres claves, no toca el resto,
  no escribe BOM, y a la segunda vez no toca) y la ruta **idempotente** sobre el clon ya levantado
  (42 s: migra, ve el modelo, lo carga en 28 s). La ruta con descarga real de Gemma y el texto de avance
  no se corrieron (para eso haría falta borrar volúmenes).
- Que cargar Gemma al final quite el costo del primer arranque en frío: el modelo ya estaba en la caché
  del sistema. Es la razón de ser del paso, no un resultado medido.
- Docker Desktop, WSL2 y el driver desde cero; red distinta; imágenes base sin caché; otro equipo y
  otra persona. Todo en `docs/demo/maquina-limpia.md`.
- Las pantallas (lista en `docs/demo/guion.md`, §7): solo se comprobó por la API y por el QR en el
  celular.
- No se alteró la regla de firewall del usuario, así que no se sabe si hacía falta.

## Para el siguiente

- **Exposición a la red:** Docker publica el 8000 y el 5432 (contraseña de desarrollo) en `0.0.0.0`;
  Ollama ya va a `127.0.0.1`. Habría que hacer lo mismo con el 5432 (`127.0.0.1:${POSTGRES_PORT}`) y
  decidir si la API necesita estar en todas las interfaces. No se cambió. Se comprueba desde el celular
  (`http://<IP>:8000/health`) en la lista de máquina limpia.
- **El repo es público** hoy (`gh repo view`), con el README y los prompts dentro: conviene confirmar
  con el patrocinador que eso es lo acordado (NDA cl. 3.1 y 3.2).
- **Pesos de Whisper y MiniLM:** podrían bajarse al levantar, no al primer video (~2-3 min). Pide una
  función en el código, no un script: queda como issue.
- **E genera una palabra clave sin traducir** en 1 de 3 corridas (#32): salió en este ensayo.
