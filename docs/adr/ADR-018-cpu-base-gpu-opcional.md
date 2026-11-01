# ADR-018 · Usar la CPU como base y la GPU solo para acelerar, sin cambiar de modelo

- **Estado:** Propuesto. Reemplazará a ADR-014 cuando se tengan los números de la medición en CPU
- **Fecha:** 2026-10-27
- **Autores:** Emmanuel Merida
- **Decisores:** equipo y asesor (Dr. Raúl); RNF-01 sin GPU, con el patrocinador

---

## Contexto

El 27 oct el asesor pidió que el sistema no obligue a comprar una tarjeta de video. Hasta ese día
todo se había medido en la PC de referencia de ADR-014 (RTX 2070 SUPER de 8 GB), y había tres
cosas que lo impedían o lo hacían poco claro:

1. El servicio `ollama` de `docker-compose.yml` reservaba una GPU NVIDIA y no arrancaba sin ella.
2. Ollama elegía la GPU por su cuenta: no había forma de forzar la CPU para medir, ni de saber
   después dónde había corrido Gemma.
3. El "perfil GPU" usaba otro Whisper (`large-v3-turbo`) que el de CPU (`small`), así que el mismo
   video podía dar otro resultado según la máquina (RNF-07).

El documento SOP V1.0 (sección 8.1) ya advierte que la opción B sin GPU puede tardar "varios
minutos" por video. La estimación de partida es ~16 min para 10 min de video en CPU, contra la meta
de RNF-01 de menos de 5.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · GPU obligatoria (ADR-014 tal cual) | Cumple RNF-01 en la PC de referencia | El asesor lo descartó; un cliente sin GPU no puede usar el sistema |
| B · CPU de base y otro modelo más chico en CPU | Más rápido sin GPU | El resultado depende del equipo (rompe RNF-07) |
| C · CPU de base, GPU opcional, **mismo modelo en los dos** | Mismo resultado en cualquier equipo; con GPU solo tarda menos | Sin GPU puede no cumplir RNF-01 |

## Decisión

Opción C. La GPU cambia **dónde** corre cada modelo, nunca **cuál**.

- **Whisper:** `WHISPER_DISPOSITIVO=auto` (ya existía): cuda si ctranslate2 ve la GPU; si falla
  antes del primer segmento, repite en CPU. Un solo `WHISPER_MODELO` para todos los equipos, que se
  elige con la medición (`small` contra `large-v3-turbo` int8 en CPU).
- **Gemma 4:** nueva `LLM_DISPOSITIVO=auto|cpu`. Con `auto`, Ollama usa la GPU si la ve; con `cpu`,
  el cliente manda `num_gpu=0` y corre solo en CPU.
- **MiniLM:** siempre en CPU (ADR-012), sin cambios.
- **Docker:** la reserva de GPU sale de `docker-compose.yml` a un `docker-compose.gpu.yml` opcional.
- **Visibilidad:** `plataforma/hardware.py` detecta la GPU con `nvidia-smi` y arma el plan por etapa.
  La API lo registra al arrancar, con un aviso si la configuración no cuadra con el equipo (hay GPU
  y ctranslate2 no la ve, `WHISPER_DISPOSITIVO=cuda` sin GPU, `LLM_DISPOSITIVO=cpu` con GPU), y lo
  informa en `GET /health` (`dispositivos`). Cada reporte guarda dónde corrió de verdad cada modelo
  en `metadatos.dispositivos` (campo opcional del contrato; los reportes anteriores quedan válidos).

## Consecuencias

- **Positivas:** el sistema arranca y valida en un equipo sin tarjeta. Cada reporte dice si corrió
  con GPU, así que un tiempo de RNF-01 se puede interpretar. La medición CPU contra GPU es
  reproducible con `scripts/medir_dispositivos.py`.
- **Negativas / riesgos:**
  - Sin GPU, RNF-01 probablemente no se cumple. Si la medición lo confirma, las opciones son un
    Whisper más chico, `gemma4:e2b` (sigue siendo Gemma 4, NDA cl. 1), menos llamadas al LLM, o
    acordar con el asesor y el patrocinador que RNF-01 aplica con GPU y que en CPU el video se
    procesa en segundo plano. Esta última la deciden ellos.
  - Gemma en CPU puede pasar de `LLM_TIMEOUT_S=180` por petición. Si pasa, la segmentación cae a la
    heurística y el reporte sale provisional (ADR-019). La medición usa 900 s; con sus números se
    fija el valor de CPU.
  - `compute_type` sí cambia con el dispositivo (float16 en cuda, int8 en CPU). Puede mover una
    palabra en la transcripción. La medición compara el resultado final entre configuraciones.
  - Ollama 0.40.2 no informa bien cuánta VRAM usa (`size_vram`, ver `docs/dev/llm.md`): el reporte
    solo distingue `cpu` de `gpu`, no si Gemma quedó repartido.
  - La API dentro de Docker no ve la GPU aunque `ollama` sí: su `dispositivos.gpu` sale en `null`.
- **Seguimiento:** correr `scripts/medir_dispositivos.py` con A y B (`--config cpu --config auto`,
  `--whisper small --whisper large-v3-turbo`), guardar el resumen en `docs/adr/datos/` y completar
  la sección de resultados. Con eso: elegir el `WHISPER_MODELO` único, fijar `LLM_TIMEOUT_S` para
  CPU, pasar este ADR a Aprobado y ADR-014 a Reemplazado.

## Resultados de la medición (27 oct, PC de referencia)

Datos crudos: `docs/adr/datos/medicion-dispositivos-20261027-1901.md` y `.json`. Una corrida por
combinación (config × Whisper × video), Gemma descargado antes de cada una. A dura 135 s y B 115 s.

| | Solo CPU (`cpu`) | Con GPU (`auto`) |
|---|---|---|
| Total por video | 159–223 s | 24–56 s |
| Segundos de proceso por segundo de video | 1.23–1.65 | 0.20–0.41 |
| Estimado para 10 min (lineal, sobrestima) | 12.3–16.5 min · **no cumple RNF-01** | 2.0–4.1 min · cumple |
| Transcribir: `small` / `large-v3-turbo` | 26–33 s / 45–59 s (int8) | 6–11 s / 6–8 s (float16) |
| Segmentar con Gemma | 90–106 s | 14–44 s |
| Emparejar con juez | 16–83 s | 0.4–5 s |
| Criterio del MVP | 4 de 4 pasan | 4 de 4 pasan (1 provisional) |
| RAM máxima del proceso | 1.5–2.8 GB | 1.8–2.4 GB |
| VRAM máxima (con 2.3–2.6 GB del escritorio) | — | 7.2–7.6 de 8 GB |

Lo que dicen los números:

1. **Sin GPU funciona y da el resultado correcto, pero no cumple RNF-01.** Gemma es la mayor parte
   del tiempo en CPU (segmentar y juez). Con videos de 2 min ninguna petición pasó de 180 s, así
   que `LLM_TIMEOUT_S` no estorbó; con 10 min de transcripción, por medir.
2. **Con GPU cumple RNF-01 con margen**, pero la VRAM llegó a 7.6 de 8 GB (el 27 oct, por la API,
   fue 6.3). El escritorio de Windows ocupa ~2.4 GB.
3. **La diferencia de resultados no la causa el dispositivo, sino Gemma.** La tabla marcó resultados
   distintos entre CPU y GPU en dos combinaciones. Para aislarlo:
   - Whisper `large-v3-turbo` en GPU, 3 veces sobre A: transcripción idéntica las 3.
   - Gemma con la misma transcripción de A, 3 veces: en GPU, 2 iguales y 1 con un paso más; en
     CPU, también 2 iguales y 1 distinta. La diferencia es una frontera cerca de 115–119 s.
   - A completo con GPU y `large-v3-turbo`, 3 veces más: 100 %, 83.3 % (no pasa) y 100 %. En el
     de 83.3 %, y en el provisional de la primera ronda, la redacción dejó un paso sin redactar
     porque la cita salió de 3 palabras y la validación pide 4 a 15.

   Con temperatura 0 y semilla fija, Gemma en Ollama 0.40.2 no da la misma segmentación en todas
   las corridas, ni en CPU ni en GPU. Es un riesgo para RNF-07 independiente de esta decisión.
4. **Whisper único: todavía no.** En CPU, `small` tarda la mitad que `large-v3-turbo`. En B,
   `large-v3-turbo` dio 1 Sobra en CPU y GPU; `small`, 2 y 4. Con dos videos y la variación de
   Gemma no alcanza para elegir: se decide con C–E y varias corridas por configuración.

Siguientes pasos:

- **RNF-01 sin GPU:** llevar estos números al asesor y al patrocinador. Opciones: `gemma4:e2b`,
  menos llamadas al LLM, o que RNF-01 aplique con GPU y en CPU el video se procese en segundo plano.
- **Variación de Gemma (RNF-07):** issue aparte. Revisar si viene de Ollama (caché del prompt entre
  peticiones, hilos) y qué hacer con una cita de 3 palabras en vez de dejar el paso sin redactar.
- **Medir con repeticiones:** el script acepta la misma clave varias veces
  (`video_a=… video_a=…`); repetir cada configuración al menos 3 veces antes de atribuir una
  diferencia al dispositivo.

## Referencias

- ADR-006 (Gemma 4 y Ollama), ADR-012 (MiniLM en CPU), ADR-014 (hardware de referencia),
  ADR-019 (validar sin LLM).
- Documento SOP V1.0, sección 8.1 (opción B, mini LLMs locales) y RNF-01, RNF-07.
- `docs/dev/llm.md`, sección "CPU o GPU".
