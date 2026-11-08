# ADR-018 · Usar la CPU como base y la GPU solo para acelerar, sin cambiar de modelo

- **Estado:** Propuesto. La parte de Whisper está decidida (8 nov 2026: `large-v3-turbo` en CPU y
  en GPU). Pasa a Aprobado, y ADR-014 a Reemplazado, cuando se fije el plazo de Gemma en CPU para
  la segmentación y se acuerde RNF-01 sin GPU.
- **Fecha:** 2026-10-27 (decisión de Whisper: 2026-11-08)
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
  antes del primer segmento, repite en CPU. **Decidido el 8 nov 2026: `large-v3-turbo` en los dos
  dispositivos** (int8 en CPU, float16 en cuda), por defecto en `WHISPER_MODELO` y
  `WHISPER_MODELO_CPU` (Settings, `.env.example` y `docker-compose.yml`). Quien configure otro
  modelo en CPU (p. ej. `small`, la mitad de tiempo) puede: el reporte y la ficha llevan el aviso
  `transcripcion_no_referencia` y el reporte queda provisional. Medición que lo respalda (A y B,
  i7-10700K, contra la transcripción de GPU; detalle en el seguimiento del 8 nov):

  | Whisper en CPU | Whisper (s) | RAM pico | WER | Errores que llegan a ficha / pasos | Ruta completa en CPU |
  |---|---|---|---|---|---|
  | `small`, int8 (antes) | 19.5-24.2 | 0.77 GB | 4.8-6.2 % | A 2 / 4 · B 2 / 8 | A 159.6 s · B 164.4 s |
  | `large-v3-turbo`, int8 (decidido) | 38.8-60.5 | 1.95 GB | 0.4-1.3 % | A 0 / 0 · B 1 / 2 | A 244.1 s (1.53×) · B 163.9 s (1.00×) |

  Criterio acordado: si `large-v3-turbo` en CPU no más que duplica el tiempo total por video, se usa
  el mismo modelo en los dos dispositivos. El peor caso medido fue 1.53× (con int8_float32, 1.16×).
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
4. **Whisper único: todavía no** (27 oct). En CPU, `small` tarda la mitad que `large-v3-turbo`. En
   B, `large-v3-turbo` dio 1 Sobra en CPU y GPU; `small`, 2 y 4. Con dos videos y la variación de
   Gemma no alcanza para elegir. *Decidido el 8 nov con la medición de WER y de errores que llegan a
   la ficha y a los pasos: `large-v3-turbo` en los dos (ver Decisión y el seguimiento del 8 nov).*

Siguientes pasos:

- **RNF-01 sin GPU:** llevar estos números al asesor y al patrocinador. Opciones: `gemma4:e2b`,
  menos llamadas al LLM, o que RNF-01 aplique con GPU y en CPU el video se procese en segundo plano.
- **Variación de Gemma (RNF-07):** issue aparte. Revisar si viene de Ollama (caché del prompt entre
  peticiones, hilos) y qué hacer con una cita de 3 palabras en vez de dejar el paso sin redactar.
- **Medir con repeticiones:** el script acepta la misma clave varias veces
  (`video_a=… video_a=…`); repetir cada configuración al menos 3 veces antes de atribuir una
  diferencia al dispositivo.

## Seguimiento: conversión del SOP con Gemma 4 en CPU y en GPU (7 nov 2026)

Mismo equipo de referencia (RTX 2070 SUPER, i7-10700K), `gemma4:e4b-it-q4_K_M`, Ollama 0.40.2.
En CPU, `LLM_DISPOSITIVO=cpu` y el resto de los valores por defecto (Ollama confirmó "cpu" en
`/api/ps`). Dos documentos inventados: el Word en prosa del fixture (1 420 caracteres) y un texto
de 9 047 caracteres con la misma prosa y notas que no son pasos (`num_ctx` 16384). Una corrida por
celda; datos en `docs/adr/datos/sop/antes-v2-20261107-1949.json` (prompt v2) y
`despues-v3-20261107-2014.json` (prompt v3, esquema recortado, ADR-015).

| Documento · prompt | GPU: tiempo · tokens/s · pasos | CPU: tiempo · tokens/s · pasos | Tokens de salida (GPU / CPU) |
|---|---|---|---|
| Prosa · v2 | 26.5 s · 110.0 · 8 | 138.0 s · 17.0 · 8 | 1 829 / 1 829 |
| Largo · v2 | 25.7 s · 103.5 · **8** | 201.2 s · 15.3 · **9** | 1 842 / 1 999 |
| Prosa · v3 | 17.5 s · 110.2 · 8 | 95.9 s · 17.2 · 8 | 1 156 / 1 130 |
| Largo · v3 | 19.1 s · 103.8 · 8 | 146.8 s · 14.9 · 8 | 1 163 / 1 181 |

- **CPU, unas 6.5 veces más lento:** genera ≈ 15-17 tokens/s contra ≈ 104-110 en GPU, y lee el
  prompt a ≈ 55 tokens/s. Con el plazo fijo de 180 s el texto largo con v2 (201 s) fallaba; con la
  respuesta en flujo (corte por inactividad, tope de 900 s) y `POST /sops` asíncrono, los dos
  documentos convierten sin error en CPU con los valores por defecto. El esquema recortado bajó el
  peor caso en CPU de 201 a 147 s.
- **El texto largo con v2: 8 pasos en GPU, 9 en CPU.** Los dos parten igual hasta el paso 2
  ("Girar la llave de paso a la derecha"). La CPU agrega un paso 3, "Verificar posición de la
  manija", con la frase "La manija debe quedar atravesada a la tubería."; la GPU pone esa misma
  frase como punto de validación del paso 2. **Se apega más al documento la de 8 (GPU):** la
  frase no es una acción nueva, es cómo se comprueba que la llave quedó cerrada; en la plantilla
  original del fixture es la "Validación" del paso 2. Del paso 4 en adelante coinciden (con
  palabras distintas). Con v3, los dos dispositivos dan 8 pasos en los dos documentos, con la
  misma división y nombres que cambian de palabras ("Presionar botón rojo" en GPU, "Presionar botón
  y purgar aire" en CPU).
- **RNF-07 significa el mismo modelo, no la misma salida idéntica.** En CPU y en GPU corren los
  mismos pesos (`gemma4:e4b-it-q4_K_M`), el mismo prompt, temperatura 0 y la misma semilla; lo que
  cambia es la aritmética de punto flotante de cada dispositivo, que en los tokens casi empatados
  elige otro y desde ahí el texto diverge. No se puede exigir la salida idéntica byte a byte (ya se
  veía en GPU sola, ver arriba: A dio 100 / 83.3 / 100 %). Lo que sí se exige es no cambiar de
  modelo según el equipo (opción B, descartada).
- **RF-04 cubre la diferencia.** Un SOP convertido con el LLM sale con `metodo: "llm"` y sus
  advertencias, y debe pasar por la corrección humana antes de usarse para validar (RF-04,
  ADR-008; la pantalla es de S5 y todavía no existe): un paso de más como el "Verificar posición
  de la manija" es justo lo que esa revisión corrige. El
  código ya garantiza lo que no puede variar: cada paso trae una cita verificada contra el
  documento, y lo que no la tiene sale con confianza baja y la advertencia `paso_sin_evidencia`.

## Seguimiento: ficha de contexto con Gemma 4 en CPU y en GPU (7 nov 2026)

Ficha de contexto (RF-12, `percepcion/contexto.py`, prompt `contexto_v1`) sobre A y B, con el
mismo equipo de referencia, `gemma4:e4b-it-q4_K_M` y Ollama 0.40.2. La etapa no cambia de lógica
con el dispositivo: mismo prompt, esquema, cortes, temperatura 0 y semilla. **Fotogramas en la
entrada: 0** (RF-11 aún no existe). Gemma se descarga antes de cada corrida, como en la API, así
que la espera al primer token incluye la carga en frío. Datos y fichas completas en
`docs/adr/datos/contexto/contexto-20261107-2344.*` (parte a) y `contexto-20261107-2349.*`
(parte b), con `scripts/medir_contexto.py`.

**a) Solo Gemma, con la misma transcripción guardada** (`media/video_*_v3/analisis.json`,
Whisper `large-v3-turbo`), dos corridas por celda:

| Video · Gemma | Tokens entrada → salida | Primer token | Tokens/s | Ficha |
|---|---|---|---|---|
| A · GPU | 1 114 → 290-292 | 6.7-6.9 s | 87-88 | 10.0-10.2 s |
| A · CPU | 1 114 → 291 | 28.1-30.9 s | 15.1-15.2 | 47.4-50.1 s |
| B · GPU | 984 → 284-310 | 5.9-6.2 s | 75-102 | 8.9-10.0 s |
| B · CPU | 984 → 307 | 25.9-27.8 s | 13.3-14.9 | 48.4-49.1 s |

- **Mismas personas en las 8 corridas:** un narrador, "No identificado", rol "técnico de
  mantenimiento", "participa" (A y B no dicen el nombre). Sin riesgo para P3 por el dispositivo.
- Datos con valor o vacíos: iguales entre CPU y GPU en A. En B, `proposito` sale lleno en 3 de 4
  corridas y vacío en la segunda de GPU: es la variación de Gemma en un mismo dispositivo, no de
  la CPU. Equipos: en A, CPU escribe "cartucho" donde GPU escribe "cartucho de filtro de agua";
  en B, iguales.
- La ficha mide ~290-310 tokens de salida (el tope que se fijó para recortar el esquema era
  ~600). En CPU la espera al primer token queda en 26-31 s, lejos de los 120 s que pondrían en
  riesgo el corte de 180 s cuando lleguen los fotogramas.

**b) Ruta completa** (Whisper + `validar` contra el SOP del fixture), una corrida por celda:
GPU = Whisper `large-v3-turbo` en cuda + Gemma en GPU; CPU = Whisper `small` int8 en CPU (su
valor por defecto) + Gemma en CPU.

| Video · ruta | Transcripción | Ficha | Pasos | Emparejamiento | Total | Ficha / total |
|---|---|---|---|---|---|---|
| A · GPU | 12.1 s | 10.4 s | 11.5 s | 31.1 s | 66.5 s | 16 % |
| B · GPU | 5.9 s | 8.4 s | 8.2 s | 1.5 s | 24.4 s | 35 % |
| A · CPU | 22.7 s | 49.1 s | 67.7 s | 16.3 s | 156.3 s | 31 % |
| B · CPU | 22.5 s | 50.6 s | 76.4 s | 34.5 s | 185.4 s | 27 % |

- **La ficha suma ~8-10 s por video en GPU y ~50 s en CPU.** El emparejamiento varía con los
  pares que llegan al juez y, en A con GPU (la primera corrida del proceso), incluye la carga de
  MiniLM; no se midió aparte.
- **El cambio de modelo de Whisper sí altera la ficha.** Mismas personas en las dos rutas, pero
  en A Whisper `small` transcribió "línea de enjuague" como "clínica del jugo": la ficha en CPU
  dice `lugar = "Clínica del jugo"` con fuente "audio" y confianza "alta", porque la cita sí
  aparece en esa transcripción. En equipos pasan los errores de Whisper ("guantes del tilo",
  "anillo de higule"). **La cita verificada prueba que el dato está en la transcripción, no que
  la transcripción esté bien:** con Whisper `small` en CPU, un dato de alta confianza puede ser
  un error de reconocimiento. Esto pesa para P3 (afinidad con el lugar del SOP) y para el SOP
  generado (P5). RNF-07 pide el mismo modelo; hoy la ruta de CPU por defecto usa otro Whisper
  (`small`) por tiempo. Opciones a decidir: `large-v3-turbo` también en CPU (más lento) o una
  advertencia en la ficha cuando Whisper no es el de referencia.
- Hallazgo del prompt v1, igual en los dos dispositivos: Gemma copia a veces citas literales de 3
  palabras ("línea de enjuague", "técnico de mantenimiento"), por debajo del mínimo de 4. El
  código las deja como "inferido" con confianza baja (el valor se conserva). En B, Gemma no llenó
  `lugar` aunque se dice. Para un `contexto_v2`: pedir la frase completa alrededor del dato.

## Seguimiento: Whisper large-v3-turbo en CPU contra small (8 nov 2026)

La medición de la ficha de contexto mostró que Whisper `small` en CPU transcribió "línea de
enjuague" como "clínica del jugue", y que la ficha lo dio como lugar con cita verificada. Se midió
`large-v3-turbo` en CPU (i7-10700K, 32 GB) con A y B, contra la transcripción de GPU como
referencia, con `scripts/medir_whisper.py`. Datos: `docs/adr/datos/whisper/whisper-20261108-0018.*`
(WER por palabras normalizadas, sin acentos ni puntuación; cada transcripción en su propio proceso
para medir la RAM pico; una corrida por celda).

| Video · Whisper | Segundos | × tiempo real | RAM pico | WER | Tramos que llegan a ficha / pasos |
|---|---|---|---|---|---|
| A · large-v3-turbo, cuda float16 (referencia) | 7.4 | 0.06 | 1.8 GB | — | — |
| A · large-v3-turbo, CPU int8 | 60.5 | 0.45 | 1.95 GB | 0.4 % | 0 / 0 |
| A · large-v3-turbo, CPU int8_float32 | 55.4 | 0.41 | 1.95 GB | 0.4 % | 0 / 0 |
| A · small, CPU int8 | 24.2 | 0.18 | 0.77 GB | 4.8 % | 2 / 4 |
| B · large-v3-turbo, cuda float16 (referencia) | 8.7 | 0.08 | 1.8 GB | — | — |
| B · large-v3-turbo, CPU int8 | 38.8 | 0.34 | 1.95 GB | 1.3 % | 1 / 2 |
| B · large-v3-turbo, CPU int8_float32 | 39.4 | 0.34 | 1.95 GB | 1.3 % | 1 / 2 |
| B · small, CPU int8 | 19.5 | 0.17 | 0.77 GB | 6.2 % | 2 / 8 |

- **"Clínica del jugue" desaparece con large-v3-turbo en CPU.** Solo `small` la produce (A), y
  llega al lugar y al resumen de la ficha. Con `small` también llegan a los pasos "plastanon",
  "ranobra", "marcasero" o "del tilo" (por "de nitrilo"). Con `large-v3-turbo` en CPU queda un
  error que llega a la ficha y a un paso ("del trilo" por "de nitrilo", en B) y un "flojo" por
  "aflojo" (B); en A, ninguno. RNF-07 sigue siendo el mismo modelo, no la misma salida: la CPU no
  reproduce byte a byte la transcripción de GPU, pero se le acerca diez veces más que `small`.
- **int8 e int8_float32 tardan lo mismo** (en CPU, ctranslate2 hace las dos con pesos int8 y
  cálculo en float32) y dieron transcripciones idénticas en A y en B. Se queda int8, el que ya usa `COMPUTE_TYPE_CPU`.
- **RAM:** ~1.95 GB contra 0.77 GB. Whisper y Gemma no corren a la vez (ADR-014), así que cabe de
  sobra en el equipo de referencia; en un equipo de 8 GB habría que revisarlo con Gemma en CPU.

**Ruta completa en CPU** (Whisper + ficha + pasos + emparejamiento con Gemma en CPU):

| Video | small | large-v3-turbo int8 | large-v3-turbo int8_float32 | GPU (referencia) |
|---|---|---|---|---|
| A | 159.6 s | 244.1 s (1.53×) | 184.9 s (1.16×) | 47.0 s |
| B | 164.4 s | 163.9 s (1.00×) | 164.6 s (1.00×) | 29.0 s |

Whisper en sí suma +36 s (A) y +19 s (B) sobre `small`; el resto de la diferencia de A con int8
(244 s) viene de las etapas de Gemma de esa corrida (ficha 61 s y pasos 103 s contra 47 y 68 s de
la corrida de int8_float32, con el mismo modelo y una transcripción idéntica), no de Whisper:
es la variación de Gemma en CPU entre corridas. En los dos videos, el cumplimiento fue igual en las cuatro rutas (A 100 %, B 66.67 %).

**Decisión (8 nov 2026): `WHISPER_MODELO_CPU=large-v3-turbo` (int8), el mismo modelo en los dos
dispositivos.** Con el criterio acordado (si `large-v3-turbo` en CPU no más que duplica el tiempo
total por video, se usa el mismo modelo), el peor caso medido es 1.53× y el típico 1.0–1.2×. Queda
por defecto en Settings, `.env.example` y `docker-compose.yml` (la API en Docker, que corre en CPU,
usa `WHISPER_MODELO_CPU`; `WHISPER_MODELO_API` ya no existe). El aviso
`transcripcion_no_referencia` se queda para quien configure otro modelo. Pendiente: confirmar los
tiempos en un equipo sin GPU de verdad y con los videos C–E.

## Referencias

- ADR-006 (Gemma 4 y Ollama), ADR-012 (MiniLM en CPU), ADR-014 (hardware de referencia),
  ADR-019 (validar sin LLM).
- Documento SOP V1.0, sección 8.1 (opción B, mini LLMs locales) y RNF-01, RNF-07.
- `docs/dev/llm.md`, sección "CPU o GPU".
