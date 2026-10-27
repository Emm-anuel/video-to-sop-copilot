# Transcripción con faster-whisper (desarrollo)

Idioma con confianza (RF-09) y transcripción con tiempo por frase y por palabra (RF-10), con
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) corriendo en local (costo cero,
ADR-011). Código: `sopvid.percepcion.transcripcion`. Hardware de referencia: ADR-014.

| Pieza | Valor |
|---|---|
| Paquetes | `faster-whisper==1.2.1`, `ctranslate2==4.8.3`, `onnxruntime==1.31.0` (VAD) y `av==18.1.0` (decodificación), fijados por RNF-07; sin torch |
| Perfil CPU (por defecto) | `small` en int8 |
| Perfil gpu | `large-v3-turbo` en float16, en el venv de Windows con el extra `gpu` |
| Decodificación (RNF-07) | `temperature=0` sin respaldo, `beam_size=5`, `condition_on_previous_text=False`, VAD Silero, tiempo por palabra |
| Pesos | `WHISPER_CACHE_DIR` (`models/whisper`, ignorada por Git; en Docker, volumen `modelos`) |
| Memoria | el modelo se carga en cada `transcribir` y se libera al terminar (no cabe junto a Gemma 4) |

## Perfiles

Se eligen con tres variables en `.env` (ver `.env.example`):

| Variable | CPU | gpu |
|---|---|---|
| `WHISPER_MODELO` | `small` | `large-v3-turbo` |
| `WHISPER_DISPOSITIVO` | `auto` o `cpu` | `cuda` |
| `WHISPER_COMPUTE_TYPE` | `auto` (int8) | `float16` (o `auto`) |

Con `WHISPER_DISPOSITIVO=auto`, se usa cuda si ctranslate2 ve una GPU NVIDIA. Si cuda falla
antes del primer segmento (p. ej. faltan las DLL de cuBLAS), se repite en CPU con int8 y queda un
aviso. Con `cuda` explícito no hay respaldo: el error sale tal cual.

## Uso

```python
from pathlib import Path

from sopvid.percepcion.medios import extraer_audio
from sopvid.percepcion.transcripcion import TranscriptorWhisper, escritor_txt

audio = extraer_audio(Path("media/demo/video.mp4"), Path("media/demo/audio.mp3"))
with escritor_txt(Path("media/demo/transcripcion.txt")) as al_segmento:
    t = TranscriptorWhisper().transcribir(audio, idioma=None, al_segmento=al_segmento)
print(t.idioma, len(t.segmentos), t.dispositivo, t.respaldo_cpu, t.segundos)
```

- `idioma=None` detecta el idioma (`t.idioma.confianza` = probabilidad de Whisper). Con
  `idioma="es"` se fuerza y queda `fijado_a_mano=True`, con confianza 1.
- El TXT se escribe mientras avanza: una línea `[mm:ss] texto` por segmento, con flush.
- `t.segmentos` ya cumple las reglas del contrato (`Segmento` de `sopvid/contrato.py`): ids
  desde 0, sin solaparse, palabras en orden y dentro de su segmento, tiempos ≥ 0.

## CPU (cualquier máquina)

```powershell
python -m venv .venv ; .venv\Scripts\activate ; pip install -e .[dev]
```

No hace falta nada más. La primera corrida descarga `small` (~0.5 GB) a `models/whisper`.

## GPU en Windows (RTX 2070 SUPER, venv)

El wheel de ctranslate2 4.8.3 para Windows necesita **cuBLAS de CUDA 12** (`cublas64_12.dll`) y
solo trae el cargador de **cuDNN 9.10.2** (`cudnn64_9.dll`); las partes de cuDNN que ese cargador
abre (`cudnn_ops64_9.dll`, `cudnn_cnn64_9.dll`, …) no vienen. Las dos cosas se instalan como
wheels de NVIDIA con el extra `gpu` de `pyproject.toml`; no hace falta instalar el CUDA Toolkit,
solo un driver con soporte para CUDA 12 (el 617.42 de la PC de referencia sirve).

```powershell
pip install -e ".[dev,gpu]"     # nvidia-cublas-cu12==12.9.1.4, nvidia-cudnn-cu12==9.10.2.21 (~1.25 GB)
```

- `nvidia-cudnn-cu12` se fija en 9.10.2.21 para que coincida con el cargador que trae
  ctranslate2; si se sube ctranslate2, revisa su versión de cuDNN
  (`(Get-Item .venv\Lib\site-packages\ctranslate2\cudnn64_9.dll).VersionInfo.FileVersion`).
- Las DLL quedan en `.venv\Lib\site-packages\nvidia\{cublas,cudnn}\bin`. ctranslate2 no las
  busca ahí; `sopvid` agrega esas carpetas al buscador de DLL y al `PATH` del proceso antes de
  cargar el modelo en cuda (`_registrar_dll_nvidia`). No hay que tocar el `PATH` del sistema.
- El extra `gpu` no está dentro de `dev`: el CI y la imagen Docker no lo instalan.

### Confirmar que corrió en cuda y no cayó a CPU

1. Usa `WHISPER_DISPOSITIVO=cuda`: sin respaldo, si cuda falla verás el error en lugar de una
   corrida lenta en CPU.
2. En el resultado: `t.dispositivo == "cuda"` y `t.respaldo_cpu is False`. `dispositivo` es el
   real, no el configurado.
3. En el log: `Whisper large-v3-turbo cargado en cuda/float16 …` y ningún aviso. Si cayó a CPU,
   el aviso dice el modelo, la causa y que el tiempo no sirve para RNF-01:

   ```
   WARNING Whisper large-v3-turbo: cuda falló antes del primer segmento (RuntimeError: Library
   cublas64_12.dll is not found or cannot be loaded); se repite en CPU (int8). El tiempo de esta
   corrida no sirve para RNF-01.
   ```

4. Mientras corre, `nvidia-smi` muestra el proceso de Python con ~2.4 GB de VRAM; al terminar,
   la memoria vuelve a su nivel previo.
5. La prueba lenta lo exige con `SOPVID_DISPOSITIVO_ESPERADO=cuda` (ver abajo).

## Prueba con el modelo real

`tests/test_transcripcion.py::test_whisper_real` está marcada `lento` y usa el audio de
`SOPVID_AUDIO_PRUEBA`, que vive **fuera del repo**; si la variable no apunta a un archivo, se
salta. Comprueba que la salida valide como `Analisis`, que haya una línea del TXT por segmento y
que los tiempos no pasen de la duración.

```powershell
$env:SOPVID_AUDIO_PRUEBA = "$env:TEMP\sopvid_prueba\narracion.mp3"
# CPU
$env:WHISPER_DISPOSITIVO = "cpu"; $env:WHISPER_MODELO = "small"; $env:SOPVID_DISPOSITIVO_ESPERADO = "cpu"
pytest tests/test_transcripcion.py -m lento
# GPU
$env:WHISPER_DISPOSITIVO = "cuda"; $env:WHISPER_MODELO = "large-v3-turbo"; $env:SOPVID_DISPOSITIVO_ESPERADO = "cuda"
pytest tests/test_transcripcion.py -m lento
```

Para tener un audio sin material del cliente se puede sintetizar una narración inventada con la
voz en español de Windows (`System.Speech`, voz "Microsoft Sabina Desktop", es-MX) y pasarla por
`extraer_audio`. **Guarda el `.ps1` en UTF-8 con BOM:** Windows PowerShell 5.1 lee un archivo
sin BOM como ANSI y la voz pronuncia "é" como "A copyright" y "ó" como "super índice 3".

## Re-corte por frases y pausas

Whisper agrupa por ventanas de audio, no por frases. Con habla real (videos A y B, 26 oct) dejó un
segmento de 35 s con la intro y los pasos 1 y 2, y marcó pausas de 4 a 7 s solo con una coma; también
corta a media frase ("Ahora | retiro la carcasa"). Como el LLM elige las fronteras de paso *entre*
segmentos (ADR-010), un segmento que mezcla dos pasos ya no se puede separar.

`resegmentar` (en `percepcion/transcripcion.py`, llamado por `analizar_video`) junta las palabras de
todos los segmentos y corta después de `. ? ! …` o en un silencio ≥ `PAUSA_CORTE_S` (1.5 s); una coma
sola no corta. Un fragmento de una palabra ("Siguiente.", un "Ahora" dicho antes de la pausa) se une
al segmento siguiente. Los tiempos son los de las palabras (regla 4). Si un segmento no trae palabras
que reproduzcan su texto, o si los segmentos se enciman, la transcripción se deja igual. El TXT en vivo
conserva los segmentos de Whisper; el `Analisis` lleva los re-cortados.

Efecto en A y B (anotación a mano, F1 de inicios de paso a ±2 s, después de la fusión de ADR-013):

| Video | Segmentos Whisper → re-corte | F1 antes | F1 después | Inicios no detectados |
|---|---|---|---|---|
| A | 12 → 24 | 0.46 | 0.67 | 3 → 0 |
| B | 14 → 14 | 0.40 | 0.91 | 3 → 0 |

En A el recall ya es 1.0; lo que queda es sobre-segmentación de Gemma 4 (12 pasos para 6), que la
fusión no junta porque los fragmentos se parecen a pasos distintos del SOP.

## Mediciones (25 oct 2026, RTX 2070 SUPER, i7-10700K)

Narración sintética de 58.3 s (9 frases, 14.4 s de silencio que quita el VAD), modelo ya en caché.
El tiempo total incluye cargar el modelo.

| Perfil | Carga | Total | Segmentos / palabras | Idioma |
|---|---|---|---|---|
| `large-v3-turbo`, cuda, float16 | 2.7–3.8 s | 6.6 s | 9 / 129 | es, 1.00 |
| `small`, cpu, int8 | 2.2 s | 14.9 s | 9 / 129 | es, 0.99 |
| `large-v3-turbo`, cpu, int8 (respaldo) | 3.6–4.0 s | 39.0 s | 9 / 129 | es, 1.00 |

En GPU, la VRAM usada pasó de 1.7 GB (escritorio) a 4.1 GB y volvió a 1.7 GB al terminar.
`large-v3-turbo` transcribió las 9 frases sin errores; `small` escribió "linea" sin acento,
"vitácora" y "0" por "cero". Es una referencia, no la medición de RNF-01 (que se hace en S5 con
video real).

## Descarga de pesos y red

La primera carga descarga el modelo del Hub de Hugging Face (`small` ≈ 0.5 GB,
`large-v3-turbo` ≈ 1.6 GB). Después, cada carga todavía consulta la revisión en el Hub (solo el
nombre del modelo; el audio nunca sale de la máquina). Con `HF_HUB_OFFLINE=1` carga directo de la
caché, sin red.

## Docker

**La imagen actual corre Whisper solo en CPU** (perfil por defecto, `small`):

- El servicio `api` de `docker-compose.yml` no reserva la GPU (no tiene `deploy.resources`
  como `ollama`).
- La imagen no trae cuBLAS ni cuDNN: el chequeo del Dockerfile impide paquetes `nvidia-*`, y en
  Linux las bibliotecas de esos wheels además tendrían que estar en `LD_LIBRARY_PATH` antes de
  arrancar el proceso.

Habilitarlo (imagen base CUDA o wheels de NVIDIA, +1–2 GB, y reservar la GPU en `api`) está
pendiente; ver el seguimiento de ADR-014. En el MVP, la transcripción con GPU corre en el host,
desde el venv.
