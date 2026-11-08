# LLM local con Ollama (desarrollo)

El LLM corre en local con [Ollama](https://ollama.com) dentro de Docker, bajo el profile `llm`
de `docker-compose.yml`. Es opcional: la API y la base levantan igual sin él, y `GET /health`
informa `"llm": "no_disponible"`. Decisión y benchmark: ADR-006. Cliente: `sopvid.lenguaje.llm`.

| Pieza | Valor |
|---|---|
| Imagen | `ollama/ollama:0.40.2` (fijada; Gemma 4 requiere ≥ 0.20.0) |
| Modelo por defecto | `LLM_MODEL=gemma4:e4b-it-q4_K_M` (cabe completo en 8 GB de VRAM: 4.7 GiB con FA; ADR-006) |
| Modelos descargados | volumen `sopvid_ollama` (`/root/.ollama`); `docker compose down` lo conserva |
| Puerto | `127.0.0.1:11434`, solo en el host local (Ollama no tiene autenticación) |
| Flash attention / caché KV | encendido / f16, fijados en el compose (ADR-006) |
| Permanencia en GPU | `OLLAMA_KEEP_ALIVE=30m`: el modelo se descarga de la GPU 30 min después de la última petición |
| Timeout por petición | `LLM_TIMEOUT_S=180` (cubre la carga en frío; ver abajo) |

## Requisitos

- **Ninguna GPU obligatoria (ADR-018).** Sin tarjeta, Ollama corre Gemma en CPU: mismo modelo y
  mismo resultado (RNF-07), solo más lento.
- **Para acelerar con GPU NVIDIA:** driver reciente en Windows y Docker Desktop con backend WSL2.
  No se instala CUDA ni el NVIDIA Container Toolkit a mano: Docker Desktop ya trae el runtime
  `nvidia`. Comprobación (debe listar la GPU):

  ```powershell
  docker run --rm --gpus all nvidia/cuda:13.4.2-base-ubuntu24.04 nvidia-smi
  ```

## Levantar

Lo más simple es el script, que detecta la GPU (`nvidia-smi` y el runtime `nvidia` de Docker) y
suma `docker-compose.gpu.yml` solo si las dos cosas están:

```powershell
.\scripts\levantar.ps1 -Build     # -Plan: solo dice qué haría · -Cpu: fuerza CPU
```

A mano:

```powershell
# Cualquier equipo (Gemma en CPU)
docker compose --profile llm up -d --build
# Con GPU NVIDIA: se suma docker-compose.gpu.yml, que reserva la GPU para ollama
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d --build
```

Arranca `db`, `api`, `ollama` y `ollama-pull`. Este último espera a que `ollama` esté sano,
descarga `LLM_MODEL` (≈ 6.6 GB la primera vez) y termina. Es idempotente: si el modelo ya está en
el volumen, termina en ~1 s sin contactar al registro.

```powershell
docker compose logs -f ollama-pull       # progreso de la descarga
curl.exe http://127.0.0.1:8000/health    # {"status":"ok","db":"ok","llm":"ok","dispositivos":{...}}
```

`"llm": "ok"` significa que Ollama responde **y** tiene `LLM_MODEL` descargado.

Para detener solo el LLM: `docker compose --profile llm stop ollama`. `docker compose down`
(sin profile) no detiene los servicios del profile; usa `docker compose --profile llm down`.

## Usar otro modelo

1. Cambia `LLM_MODEL` en tu `.env` (etiqueta exacta de ollama.com/library, p. ej.
   `qwen3:8b-q4_K_M`).
2. Descárgalo y recrea la API para que lea el nuevo valor:

   ```powershell
   docker compose --profile llm run --rm ollama-pull
   docker compose up -d api
   ```

Para descargar un modelo sin cambiar el de la API (p. ej. para el benchmark):

```powershell
docker compose exec ollama ollama pull gemma4:e4b-it-q4_K_M
docker compose exec ollama ollama list
```

Para borrar un modelo: `docker compose exec ollama ollama rm <etiqueta>`.

## Verificar que el modelo quedó en la GPU

Haz una petición para que el modelo se cargue y luego revisa tres fuentes:

```powershell
docker compose exec ollama ollama ps        # columna PROCESSOR: "100% GPU"
docker compose logs ollama | Select-String "offloaded|model buffer size|KV buffer"
nvidia-smi                                  # VRAM en uso antes y después de cargar
```

- En los logs, `offloaded N/N layers to GPU` confirma que todas las capas están en la GPU. Si
  sale `offloaded k/N` con `k < N`, el modelo se repartió con la CPU y será mucho más lento.
- En Gemma 4 `e2b`/`e4b` es normal ver un buffer de modelo grande en la CPU (`CPU_Mapped` o
  `CUDA_Host`; ≈ 2.7 GB en `e4b`): son las tablas de embeddings por capa, que solo se consultan por
  índice. No es un reparto.
- **Ojo con `/api/ps`:** en 0.40.2 con el runner `llamacpp`, `size_vram` no es confiable (≈ 0.25 GB
  con `e4b`, que en realidad ocupa ≈ 4.7 GB de VRAM). Úsalo para ver si el modelo está cargado, no
  para medir memoria; para eso, los logs y `nvidia-smi`.

La GPU también la usa el escritorio de Windows (≈ 1.5–1.7 GB en una RTX 2070 SUPER de 8 GB);
mide la VRAM libre antes de comparar corridas.

## CPU o GPU: `LLM_DISPOSITIVO` y dónde quedó cada modelo (ADR-018)

La regla: la GPU cambia **dónde** corre cada modelo, nunca **cuál**.

| Etapa | Sin GPU | Con GPU | Cómo se fuerza la CPU |
|---|---|---|---|
| Whisper | CPU, int8 | cuda, float16 (`WHISPER_DISPOSITIVO=auto`) | `WHISPER_DISPOSITIVO=cpu` |
| Gemma 4 (Ollama) | CPU | GPU si Ollama la ve (`LLM_DISPOSITIVO=auto`) | `LLM_DISPOSITIVO=cpu` → `num_gpu=0` |
| MiniLM | CPU | CPU (no compite por la VRAM) | — |

- **Al arrancar**, la API registra el plan (`INFO sopvid.plataforma.hardware: Dispositivos: …`) y
  un `WARNING` por cada cosa que no cuadra: hay GPU pero ctranslate2 no la ve (falta el extra
  `gpu` del venv), `WHISPER_DISPOSITIVO=cuda` sin GPU, o `LLM_DISPOSITIVO=cpu` con GPU.
- **`GET /health`** trae lo mismo en `dispositivos`: la GPU que ve la API (`nvidia-smi`), Whisper
  como `dispositivo/compute_type`, la política de Gemma y los avisos.
- **Cada reporte** guarda dónde corrió de verdad cada modelo en `metadatos.dispositivos`
  (`gpu`, `transcripcion`, `transcripcion_respaldo_cpu`, `llm`, `embedder`). El de Gemma se
  pregunta a Ollama (`/api/ps`) antes de descargarlo: `size_vram > 0` → `gpu`, `0` → `cpu`.
  Como `size_vram` no mide bien en 0.40.2 (ver arriba), no se informa cuánta VRAM; para eso, los
  logs (`offloaded N/N layers`) y `nvidia-smi`.
- **La API en Docker** no ve la GPU aunque `ollama` sí la tenga: su `dispositivos.gpu` sale en
  `null` y Whisper en CPU (ADR-014). Lo que cuenta para Gemma es `metadatos.dispositivos.llm`.
- **Medir CPU contra GPU** con A y B: `scripts/medir_dispositivos.py`.

## Llamar al LLM desde Python

```python
from sopvid.lenguaje.llm import ClienteLLM

esquema = {
    "type": "object",
    "properties": {"pasos": {"type": "array", "items": {"type": "string"}}},
    "required": ["pasos"],
}
with ClienteLLM.desde_settings() as llm:
    r = llm.chat([{"role": "user", "content": "..."}], esquema=esquema)
    r.datos  # JSON ya interpretado
    r.metricas  # load_duration, prompt_eval_duration, eval_count, eval_duration (ns)
```

El cliente fija `temperature=0`, `seed=42` y `num_ctx=LLM_NUM_CTX`, envía `"think": false` salvo
que se pida lo contrario, reintenta una sola vez ante timeout o error de red y lanza
`LLMNoDisponible`, `LLMRespuestaInvalida` o `LLMError` en lugar de excepciones de httpx.
`chat(..., num_ctx=N)` cambia la ventana solo en esa petición (Ollama recarga el modelo si cambia).

`chat_en_flujo` pide la respuesta con `stream: true` (el `format` con JSON Schema sigue valiendo) y
cambia el plazo fijo por plazos por fragmento: espera el primero hasta `LLM_TIMEOUT_S` (carga y
lectura del prompt), después corta si pasan `LLM_INACTIVIDAD_S` (60 s) sin un fragmento, y en
total corta en el tope que se le pase. Lo usa la conversión del SOP, con tope `LLM_TIMEOUT_SOP_S`
(900 s) para toda la conversión: en CPU genera ≈ 16 tokens/s y un SOP tarda 150-200 s, más que
el `LLM_TIMEOUT_S` de 180 s con que fallaba. Los errores se distinguen: `LLMNoDisponible`
("Ollama no responde": sin conexión, sin ningún token o callado a media respuesta) y
`LLMTiempoExcedido` (seguía generando y pasó el tope). Ninguno se reintenta. Cada llamada, en
flujo o no, deja en el log los tokens generados y los tokens/s (`eval_count`, `eval_duration`).

## Ventana de contexto para convertir un SOP (`LLM_NUM_CTX_SOP`, ADR-015)

La conversión de un SOP sin plantilla (`lectura_sop.convertir_documento`) estima los tokens antes
de llamar al LLM: caracteres / 3.5 de los mensajes (prompt y documento), más una salida de 3 veces
los tokens del documento + 512, más una corrección (cada reintento manda solo la última, sin la
respuesta anterior). Si cabe en `LLM_NUM_CTX` (8192), se usa esa ventana; si no, cada petición
pide `LLM_NUM_CTX_SOP` (16384); si tampoco cabe, 422 "El documento es demasiado largo; divídelo o
usa la plantilla". Con el prompt v2, eso deja ≈ 5 800 caracteres de documento en 8192 y
≈ 12 900 en 16384.

La estimación es conservadora a propósito: en el Word en prosa del fixture (2 300 caracteres)
estimó 4 190 tokens y usó 3 049 (1 220 de entrada, 1 829 de salida); en un texto de 9 047
caracteres con notas que no son pasos estimó 11 899 y usó 5 105 (3 262 + 1 843), porque la salida
crece con los pasos, no con todo el texto. El texto medido da ≈ 3.35 caracteres por token.

**VRAM en la RTX 2070 SUPER (8 GB), 7 nov 2026, Ollama 0.40.2, `gemma4:e4b-it-q4_K_M`, FA y caché
KV f16** (`nvidia-smi` antes y después de cargar; el escritorio ya ocupaba 2 055 MiB):

| `num_ctx` | VRAM en uso | Del modelo | Capas en GPU |
|---|---|---|---|
| — (sin modelo) | 2 055 MiB | — | — |
| 8192 | 6 827 MiB | +4 772 MiB | todas (`gpu_layers=-1`) |
| 16384 | 7 030 MiB | +4 975 MiB | todas |

Doblar la ventana cuesta solo ≈ 200 MiB: Gemma 4 usa atención de ventana deslizante en la mayoría de
sus capas y la caché KV casi no crece. Con 16384 quedan ≈ 1.1 GB libres en esta GPU; la conversión
de 9 047 caracteres pidió 16384, tardó 25 s y dejó la VRAM total en 6 917 MiB. Whisper no está
cargado al mismo tiempo: lo impide el candado de modelo pesado (ADR-014).

## Carga en frío, `OLLAMA_KEEP_ALIVE` y `LLM_TIMEOUT_S`

La primera petición después de arrancar `ollama` (o tras 30 min sin uso) carga el modelo en la
GPU antes de responder. Con `stream: false` Ollama no envía nada hasta terminar, así que
`LLM_TIMEOUT_S` debe cubrir **carga + generación**:

| Medición (RTX 2070 SUPER) | Tiempo |
|---|---|
| `e2b`: primera llamada tras descargar el modelo (disco frío) | 107 s, de ellos 78 s de carga |
| `e2b`: primera llamada tras reiniciar el contenedor | 56 s, de ellos 36 s de carga |
| `e4b`: carga tras reiniciar el contenedor (benchmark) | 85.7 s; con 120 s de timeout la llamada falló |
| `e4b`: carga con los pesos en la caché del sistema | 8.6–11.2 s |
| Llamada corta con el modelo ya en GPU | < 1 s |

Por eso el valor por defecto es 180 s y no 120 s. Si un timeout ocurre igual, el cliente reintenta
una vez: la carga ya avanzó del lado del servidor y el segundo intento suele responder rápido.
Los modelos más grandes cargan más lento; ADR-006 registra la carga de cada candidato.

`OLLAMA_KEEP_ALIVE=30m` evita pagar esa carga a cada rato durante el desarrollo, a cambio de
que el modelo ocupe VRAM 30 min tras la última petición. Para liberarla antes:
`docker compose exec ollama ollama stop <modelo>`.

## `LLM_BASE_URL` según dónde corre el código

| Quién llama | Valor |
|---|---|
| Scripts, tests y notebooks en el host | `http://127.0.0.1:11434` (en Windows, `localhost` pierde ~2 s por conexión probando IPv6) |
| La API dentro de Docker, con el profile `llm` | `http://ollama:11434` (el compose lo pone solo vía `LLM_BASE_URL_API`) |
| La API dentro de Docker, con Ollama nativo | `LLM_BASE_URL_API=http://host.docker.internal:11434` en `.env` |

## Respaldo: Ollama nativo en Windows

Si Docker no ve la GPU, instala Ollama para Windows (misma versión que el compose), corre
`ollama pull <LLM_MODEL>` y define `LLM_BASE_URL_API=http://host.docker.internal:11434` en `.env`.
No levantes el profile `llm` a la vez: ambos usan el puerto 11434.

## Benchmark (ADR-006)

`scripts/benchmark_llm.py` mide, desde el host, cada modelo ya descargado con tres tareas sobre
una transcripción inventada (resumir, segmentar en pasos y responder con citas): VRAM libre antes de
cada corrida, capas en GPU según los logs, VRAM real con `nvidia-smi`, tiempo a primer token,
tokens/s y validez del JSON. Resultados crudos en `docs/adr/datos/benchmark_llm/<variante>.json`.

```powershell
python scripts/benchmark_llm.py --variante fa_on --modelos gemma4:e4b-it-q4_K_M qwen3:8b-q4_K_M
python scripts/benchmark_llm.py --tabla
```

Para medir una variante del servidor, reinicia `ollama` con la variable correspondiente (el
compose la toma del entorno) y vuelve a dejarlo como estaba al terminar:

```powershell
$env:OLLAMA_FLASH_ATTENTION = "0"; docker compose --profile llm up -d ollama
python scripts/benchmark_llm.py --variante fa_off --modelos gemma4:e4b-it-q4_K_M
Remove-Item Env:OLLAMA_FLASH_ATTENTION; docker compose --profile llm up -d ollama
```

## Observaciones de la prueba técnica (10 oct 2026, RTX 2070 SUPER 8 GB)

- Ollama 0.40.2 sirve los modelos con `llama-server` (llama.cpp) y activa por su cuenta la
  decodificación especulativa con la cabeza MTP que traen las etiquetas de Gemma 4
  (`--spec-type draft-mtp`). Con `temperature=0` la salida debería ser la misma; cambia la
  velocidad.
- Con `gemma4:e4b-it-q4_K_M` y FA: 43/43 capas en GPU y +4.7 GiB de VRAM en uso (modelo,
  proyector de visión, cabeza MTP y contexto CUDA); genera ~90–110 tokens/s y el tiempo a primer
  token al segmentar una transcripción de ~1,500 palabras es ~1.5 s. `e2b` es más rápido, pero
  segmenta mal (ADR-006).
- Sin el profile, `GET /health` responde en ~2 s con `"llm": "no_disponible"`: en Docker Desktop
  resolver el nombre `ollama` tarda ~4 s en fallar, y el cliente corta la consulta al vencer
  `LLM_HEALTH_TIMEOUT_S`.
