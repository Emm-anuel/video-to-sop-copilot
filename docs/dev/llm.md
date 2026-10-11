# LLM local con Ollama (desarrollo)

El LLM corre en local con [Ollama](https://ollama.com) dentro de Docker, bajo el profile `llm`
de `docker-compose.yml`. Es opcional: la API y la base levantan igual sin él, y `GET /health`
informa `"llm": "no_disponible"`. Decisión y benchmark: ADR-006. Cliente: `sopvid.lenguaje.llm`.

| Pieza | Valor |
|---|---|
| Imagen | `ollama/ollama:0.40.2` (fijada; Gemma 4 requiere ≥ 0.20.0) |
| Modelo por defecto | `LLM_MODEL=gemma4:e2b-it-q4_K_M` (cabe completo en 8 GB de VRAM) |
| Modelos descargados | volumen `sopvid_ollama` (`/root/.ollama`); `docker compose down` lo conserva |
| Puerto | `127.0.0.1:11434`, solo en el host local (Ollama no tiene autenticación) |
| Flash attention / caché KV | apagado / f16, fijados en el compose hasta medirlos (ADR-006) |
| Permanencia en GPU | `OLLAMA_KEEP_ALIVE=30m`: el modelo se descarga de la GPU 30 min después de la última petición |
| Timeout por petición | `LLM_TIMEOUT_S=180` (cubre la carga en frío; ver abajo) |

## Requisitos

- GPU NVIDIA con driver reciente en Windows y Docker Desktop con backend WSL2. No se instala
  CUDA ni el NVIDIA Container Toolkit a mano: Docker Desktop ya trae el runtime `nvidia`.
- Comprobación (debe listar la GPU):

  ```powershell
  docker run --rm --gpus all nvidia/cuda:13.4.2-base-ubuntu24.04 nvidia-smi
  ```

  Sin GPU NVIDIA el servicio `ollama` no arranca (reserva un dispositivo `nvidia`); en ese caso
  usa Ollama nativo (ver *Respaldo* abajo).

## Levantar

```powershell
docker compose --profile llm up -d --build
```

Arranca `db`, `api`, `ollama` y `ollama-pull`. Este último espera a que `ollama` esté sano,
descarga `LLM_MODEL` (≈ 4.6 GB la primera vez) y termina. Es idempotente: si el modelo ya está en
el volumen, termina en ~1 s sin contactar al registro.

```powershell
docker compose logs -f ollama-pull       # progreso de la descarga
curl.exe http://127.0.0.1:8000/health    # {"status":"ok","db":"ok","llm":"ok"}
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
- En Gemma 4 `e2b`/`e4b` es normal ver un `CPU_Mapped model buffer` grande (≈ 2.1 GB en `e2b`):
  son las tablas de embeddings por capa, que solo se consultan por índice. No es un reparto.
- **Ojo con `/api/ps`:** en 0.40.2 con el runner `llamacpp`, `size_vram` reporta solo una parte
  (≈ 264 MB con `e2b`, que en realidad ocupa ≈ 3.2 GB de VRAM). Úsalo para ver si el modelo está
  cargado, no para medir memoria; para eso, los logs y `nvidia-smi`.

La GPU también la usa el escritorio de Windows (≈ 1.5–1.7 GB en una RTX 2070 SUPER de 8 GB);
mide la VRAM libre antes de comparar corridas.

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

## Carga en frío, `OLLAMA_KEEP_ALIVE` y `LLM_TIMEOUT_S`

La primera petición después de arrancar `ollama` (o tras 30 min sin uso) carga el modelo en la
GPU antes de responder. Con `stream: false` Ollama no envía nada hasta terminar, así que
`LLM_TIMEOUT_S` debe cubrir **carga + generación**:

| Medición (`gemma4:e2b-it-q4_K_M`, RTX 2070 SUPER) | Tiempo |
|---|---|
| Primera llamada tras descargar el modelo (disco frío) | 107 s, de ellos 78 s de carga |
| Primera llamada tras reiniciar el contenedor | 56 s, de ellos 36 s de carga |
| Llamada con el modelo ya en GPU | 0.5–0.8 s |

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
python scripts/benchmark_llm.py --variante fa_off --modelos gemma4:e4b-it-q4_K_M qwen3:8b-q4_K_M
python scripts/benchmark_llm.py --tabla
```

Para medir una variante del servidor, reinicia `ollama` con la variable correspondiente (el
compose la toma del entorno) y vuelve a dejarlo como estaba al terminar:

```powershell
$env:OLLAMA_FLASH_ATTENTION = "1"; docker compose --profile llm up -d ollama
python scripts/benchmark_llm.py --variante fa_on --modelos gemma4:e4b-it-q4_K_M
Remove-Item Env:OLLAMA_FLASH_ATTENTION; docker compose --profile llm up -d ollama
```

## Observaciones de la prueba técnica (10 oct 2026, RTX 2070 SUPER 8 GB)

- Ollama 0.40.2 sirve los modelos con `llama-server` (llama.cpp) y activa por su cuenta la
  decodificación especulativa con la cabeza MTP que traen las etiquetas de Gemma 4
  (`--spec-type draft-mtp`). Con `temperature=0` la salida debería ser la misma; cambia la
  velocidad.
- Con `gemma4:e2b-it-q4_K_M`: todas las capas en GPU y +3.2 GB de VRAM en uso (modelo,
  proyector de visión, cabeza MTP y contexto CUDA); con el modelo en memoria genera
  ~150–170 tokens/s.
- Sin el profile, `GET /health` responde en ~2 s con `"llm": "no_disponible"`: en Docker Desktop
  resolver el nombre `ollama` tarda ~4 s en fallar, y el cliente corta la consulta al vencer
  `LLM_HEALTH_TIMEOUT_S`.
