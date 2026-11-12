# ADR-024 · Imágenes opcionales y miniatura por paso

- **Estado:** Propuesto
- **Fecha:** 2026-11-11 (decisiones del 10 nov)
- **Autores:** Emmanuel Merida
- **Decisores:** equipo; la objeción y el visto bueno, con el patrocinador

---

## Contexto

RF-11 pide describir fotogramas: equipos, personas visibles, texto legible y riesgos. ADR-002 lo
resolvió con el mismo Gemma 4 E4B (hasta 20 fotogramas) y la voz como fuente principal. Hasta el
10 nov `Analisis.fotogramas` iba siempre vacía: la ficha de contexto (`contexto.py`) y el SOP
generado (`sop_generado.py`) ya sabían usar fotogramas (`[f=N]`, fuente "visual"), pero nada los
producía, y el reporte tenía un hueco para la miniatura de cada paso.

La objeción del patrocinador que motivó estas decisiones está en su propio apartado, justo antes
de los números que la contrastan.

Restricciones que pesan:

- **Tiempo sin GPU (ADR-018).** En CPU la ruta completa ya tarda 15–21 min estimados para 10 min de
  video y RNF-01 no se cumple (medición de cierre de S5). Cada llamada de visión suma.
- **El proceso no se bloquea por hardware (ADR-018).** La GPU cambia dónde corre un modelo, nunca
  qué se hace.
- **Regla 4.** El modelo no escribe tiempos: el segundo de cada imagen lo pone el código.
- **Personas (LFPDPPP).** Los rostros de los trabajadores son dato personal y el reconocimiento
  facial está fuera de alcance: del modelo solo sale un conteo.
- **Orden de las etapas.** La ficha de contexto va antes que los pasos del video (ADR-020); una
  imagen por paso obligaría a segmentar antes.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Describir siempre, una imagen por paso del video | La imagen cae en el paso exacto | Hay que segmentar antes de la ficha; en CPU suma minutos a todos los videos |
| B · Describir siempre, N imágenes parejas antes de la ficha | La ficha recibe la evidencia visual; una sola carga de Gemma | Sigue sumando tiempo a todos, aunque el usuario no lo necesite |
| C · **Miniatura siempre (ffmpeg); descripción opcional y apagada, N imágenes parejas antes de la ficha** | Lo visual que pide la pantalla cuesta milisegundos; quien necesita la descripción la enciende y ve antes cuánto tarda | Apagada por defecto, la ficha sigue solo con la voz |

## Decisión

**C**, con las cuatro decisiones del 10 nov (plan §2, registro de decisiones):

1. **La miniatura por paso se saca siempre, con ffmpeg y sin LLM.** Una por fila del reporte con
   segundo y una por paso del SOP generado, en `media/videos/<id>/miniaturas/`. La pantalla la
   pide por segundo (`GET /videos/{id}/thumb?t=`): la guardada a ≤ 1 s (RNF-03) o una nueva, en
   caché. Las del reporte salen en una sola llamada a ffmpeg por tanda de 20 (una entrada con su
   `-ss` y una salida por cuadro): con la opción apagada, lo único que se agrega es eso (las 15
   miniaturas de E: 1.1 s, contra 2.3 s con una llamada por miniatura). No cambia el contrato de `FilaReporte` ni de `PasoSOP`. Un video sin imagen visible (sin
   pista de video o negro) no tiene miniaturas y lleva el aviso **informativo** `sin_imagen`, que
   no vuelve provisional el reporte (`AVISOS_INFORMATIVOS` del contrato).
2. **La descripción con Gemma es opcional y viene apagada** (`FOTOGRAMAS_DESCRIBIR=false`). El
   parámetro `analizar_imagenes` de `POST /videos` gana sobre la instalación en los dos sentidos, y
   el reporte guarda lo que se usó de verdad (`metadatos.imagenes: {descritas, cantidad, tokens}`;
   también en `sops.generacion`).
3. **Encendida, se describen N imágenes repartidas de forma pareja, antes de la ficha**, en la misma
   carga de Gemma. N = los pasos del SOP (modo validar) o la duración × `PASOS_POR_MIN` (modo
   generar), entre `FOTOGRAMAS_MIN` (4) y `FOTOGRAMAS_MAX` (20, ADR-002); el centro de N tramos
   iguales. Lotes de `FOTOGRAMAS_LOTE` (8) con el prompt `fotogramas_v1`; el código pone `t` y
   `archivo`, ordena por `t` y descarta índices que no son del lote. Un lote que falla o un Ollama
   caído dejan el aviso `imagenes_incompletas` (sí vuelve provisional el reporte, ADR-019) y el
   análisis sigue. Al repetir la validación o la generación se reusan las imágenes guardadas.
   **Sin memoria:** si Ollama responde que el lote no cabe (VRAM o RAM: `out of memory`,
   `cudaMalloc`…), el lote baja a la mitad y se reintenta una vez, y los siguientes van con ese
   tamaño; si tampoco cabe, las imágenes que faltan no se describen (`imagenes_incompletas`,
   motivo `memoria_insuficiente`) y el análisis sigue. Antes de este cambio, un error de memoria se
   trataba como un Ollama caído: no tiraba el análisis, pero perdía todas las imágenes desde ese
   lote. `FOTOGRAMAS_LOTE` es la palanca para equipos con menos VRAM (4 o 2 evitan perder la
   primera llamada).
4. **Sin GPU se avisa y no se bloquea.** `GET /videos/estimacion` dice antes de subir cuántas
   imágenes se describirían y cuánto sumarían con y sin GPU (`SEG_IMAGEN_GPU`, `SEG_IMAGEN_CPU`),
   dónde correría Gemma y un aviso listo para la pantalla. Nunca responde "no permitido".

## Contexto: la objeción del patrocinador

En la demo del 9 de noviembre de 2026, el patrocinador (Jorge Pasalagua) cuestionó para
qué sirven los fotogramas. Al explicársele que dan contexto al análisis más allá de la
voz, respondió que no lo considera necesario: con la cantidad de videos que va a haber,
sumar muchos fotogramas por video "va a hacer un relajo". La objeción es de volumen y de
costo de procesamiento, no de utilidad puntual. No se discutió en la demo y queda
pendiente de confirmación por escrito.

De ahí salen las cuatro decisiones del 10 de noviembre que este ADR registra. La medición
de la sección siguiente las respalda: con los videos A a E, las descripciones no aportan
ningún dato nuevo a la ficha de contexto ni mueven la afinidad por sí mismas, y su único
efecto atribuible es diluir el componente de equipo.

## Números

**Resultado principal:** con A–E, las descripciones no aportan ningún dato nuevo a la ficha (en
ninguna corrida un dato quedó con fuente "visual": la voz ya respalda actividad, tema, lugar y
propósito) y no mueven la afinidad por sí mismas. Lo único que agregan a la ficha son equipos
genéricos (contenedor, cubo, herramienta), que diluyen el componente de equipos (86 → 71 en A y en
una corrida de C). Los cambios de afinidad que sí se vieron vienen de la variación de Gemma en
datos de audio, no de las imágenes: en A el propósito salió con otra redacción (objetivo 0 → 100,
afinidad 72 → 95). Ninguna afinidad cruzó `AFINIDAD_MIN`.

### Sonda del lote (10 nov, RTX 2070 SUPER de 8 GB, Ollama 0.40.2, `gemma4:e4b-it-q4_K_M`)

Ocho JPEG sintéticos de 512 px (patrones de prueba de ffmpeg con un texto conocido) en una sola
llamada, `num_ctx` 8192:

| | 1 imagen (en frío) | 8 imágenes (modelo cargado) |
|---|---|---|
| Tiempo total | 29.8 s (carga 10.8 s, lectura 17.6 s) | 7.4 s |
| Tokens de entrada / salida | 132 / 56 | 734 / 478 (~85 de entrada por imagen) |
| VRAM base → pico | 1.9 → 6.9 GB | 6.7 → 7.2 GB de 8 |
| Capas en la GPU | todas (`gpu_layers=-1`; el proyector de visión, en CUDA0) | todas |

Leyó el texto de las 8 imágenes tal cual. **El lote de 8 cabe en la GPU de referencia** con ~0.8 GB
de margen (el escritorio de Windows ocupa ~1.9 GB). La primera lectura de imágenes tras cargar el
modelo es lenta (17.6 s); las siguientes, ~0.2 s por imagen de lectura.

### Medición con C, D y E (11 nov)

Datos: `docs/adr/datos/imagenes/medicion-imagenes-20261111-0012.{md,json}`
(`scripts/medir_imagenes.py`). Misma PC de referencia; Gemma en frío en cada corrida, como en el
procesador; una corrida por combinación. N = 6 en C y D (pasos del SOP del filtro) y 8 en E
(3.8 min × 2.2). "Extra" = imágenes + ficha con imágenes − ficha sola: lo que suma encender la
opción (la carga del modelo, que la ficha sola también paga, no cuenta).

| Video | Dispositivo | Imágenes s | Ficha con / sin s | Extra s | Extra por imagen s | Tokens entrada / salida |
|---|---|---|---|---|---|---|
| C | GPU | 13.2 | 4.3 / 15.2 | 2.3 | 0.4 | 936 / 602 |
| D | GPU | 11.2 | 5.1 / 8.5 | 7.8 | 1.3 | 936 / 552 |
| E | GPU | 13.8 | 5.2 / 9.5 | 9.5 | 1.2 | 1 108 / 676 |
| C | CPU | 67.7 | 54.2 / 58.0 | 63.9 | 10.7 | 936 / 596 |
| D | CPU | 74.9 | 51.4 / 49.0 | 77.2 | 12.9 | 936 / 776 |
| E | CPU | 87.9 | 62.1 / 66.7 | 83.3 | 10.4 | 1 108 / 789 |

1. **Tiempo.** Con GPU, encender la opción suma ~2–10 s por video; sin GPU, ~1–1.5 min. Para un
   video de 10 min (N = 20, el tope) son ~24 s con GPU y ~3.6 min sin ella, sobre los 15–21 min
   que ya tarda la ruta en CPU. `SEG_IMAGEN_GPU=1.2` y `SEG_IMAGEN_CPU=10.7` (mediana del extra
   por imagen) quedan en Settings. Con los valores provisionales (1.5 y 15) la estimación
   sobrestimaba: +1 a +7 s en GPU y +13 a +37 s en CPU; con los medidos, el error en estos tres
   videos es de −1 a +5 s en GPU y de −13 a +2 s en CPU.
2. **Calidad de las descripciones (revisadas a mano contra las imágenes y los guiones).** Los
   equipos salen con nombres genéricos y correctos (manómetro, contenedor, cubeta, panel de
   control, rollo de material), sin marcas inventadas. El texto legible sale tal cual: el letrero
   `ENJUAGUE` y la etiqueta `NITRILO` en C, `ENVASADO`, `PAUSA`, `INICIO` y `CALIBRADO` en el
   panel de D, `RINSE LINE` y la escala del manómetro (`0 bar`) en E. El conteo de personas es
   0 o 1, como en las escenas. Fallas: una descripción de E en CPU ve "un brazo mecánico" donde
   hay una herramienta roja; el gafete parcial del operador (`MANTENIM…`) no se lee; y en E con
   GPU un riesgo copia literal la frase de ejemplo del prompt ("falta de guantes o lentes cuando
   la tarea los pide a la vista"): una observación de seguridad inventada (RNF-06). **Corregido el
   11 nov en la v1** (sin esperar a una v2): la frase salió del prompt y el código descarta un
   riesgo que la repita (`fotogramas.RIESGOS_DE_EJEMPLO`, con prueba).
3. **Ficha y afinidad.** En ninguna corrida un dato de la ficha quedó con fuente "visual": la
   transcripción ya respalda actividad, tema y lugar, así que las imágenes no cambian la
   evidencia de los datos. Lo que sí cambia es la lista de equipos, que suma los genéricos de
   las imágenes (contenedor, cubo, herramienta, unidad). La afinidad casi no se mueve: C 97 → 94
   (GPU) y 97 → 97 (CPU); D 18 → 17 (GPU) y 17 → 21 (CPU). Ninguna cruza `AFINIDAD_MIN` (60). Los
   valores de tema, propósito y resumen que cambian entre las corridas con y sin imágenes caben en
   la variación de Gemma entre corridas ya medida (ADR-018, ADR-022).

### Confirmación con A–E tras corregir el prompt (11 nov, GPU)

Datos: `docs/adr/datos/imagenes/medicion-imagenes-20261111-0046.{md,json}`. Con la frase de ejemplo
fuera del prompt, ningún riesgo la repite en A–E; en C apareció un relleno ("Ninguno visible"), que
el código ahora también descarta. Extra por imagen en GPU: 0.9–1.9 s (mediana 1.2, igual a
`SEG_IMAGEN_GPU`); la estimación quedó entre −4 y +1.7 s del tiempo real. Afinidad sin → con
imágenes: A 72 → 95 (por el propósito, ver arriba), B 95 → 95, C 97 → 97, D 18 → 19; ningún dato
con fuente visual.

### §14 con la opción apagada y el código final (11 nov, GPU)

Datos: `docs/adr/datos/s5/medicion-s5-20261111-0059.{md,json}`. A–E pasan en 14/14 corridas (A
100 % ×3, B 66.67 % ×3, C 75 % ×3, D detenida en 0 % ×3, E RNF-05 14/14) y la regeneración de A
reproduce el porcentaje. E tarda 69.5–70.9 s, como el 10 nov (68–69 s). En una corrida intermedia
E había tardado 81–83 s con la opción apagada: no era el código (esa medición no extrae miniaturas;
los tokens de salida eran los mismos) sino la GPU, que tras ~15 min seguidos de medición bajó de
~114 a ~87 tokens/s en todas las etapas.

## Consecuencias

- **Positivas:** la pantalla muestra qué pasaba en cada paso sin costo de modelo; quien quiere la
  descripción la enciende sabiendo cuánto tarda; con la opción apagada la §14 y A y B no cambian.
- **Negativas / riesgos:**
  - Apagada (por defecto), la ficha no recibe evidencia visual: un paso que no se narra y se ve
    poco puede seguir como *Falta* (riesgo ya anotado en ADR-002).
  - A y B **sí tienen imagen** (pista de video con contenido, no negra): generan miniaturas y no
    llevan `sin_imagen`. El aviso aplica a grabaciones de solo audio o con pantalla negra.
  - `SEG_IMAGEN_*` y `PASOS_POR_MIN` salen de pocos videos del equipo: la estimación es orientativa.
  - Una imagen de una escena estática (una diapositiva fija) se describe igual; no se detecta.
- **Seguimiento:**
  - Recalibrar `SEG_IMAGEN_*` y `PASOS_POR_MIN` con más videos; ablación con y sin imágenes en los
    experimentos del paper (ADR-002, plan §8); confirmar por escrito con el patrocinador la
    objeción y si la opción debe venir encendida en equipos con GPU.
  - **Afinidad inestable entre corridas (RNF-07, issue aparte para S6).** La afinidad de A varió
    23 puntos entre corridas (72 → 95) solo por la redacción del propósito que escribió Gemma. Con
    `AFINIDAD_MIN` = 60 sin calibrar y el minisplit dando 39–55, un video cerca del umbral puede
    detenerse en una corrida y continuar en la siguiente con la misma entrada. Toca RNF-07 y el
    criterio de aceptación de D.
  - **¿Llenar por llenar en `equipos` y `texto_visible`?** Revisar si tienen el mismo vicio que
    tenían los riesgos (copiar ejemplos o escribir algo para no dejar la lista vacía). Para
    `fotogramas_v2`, no ahora.
  - **Orden de las mediciones.** Medir A–E de corrido castiga a los últimos por el calentamiento
    de la GPU y no por el código (E: 69–71 s en frío, 81–83 s al final de una tanda larga). En las
    mediciones siguientes (PS6), intercalar las corridas o dejar enfriar entre tandas (plan §7).

## Referencias

- ADR-002 (voz como fuente principal, tope de 20), ADR-014 y ADR-018 (un modelo a la vez, CPU de
  base), ADR-019 (avisos y reporte provisional), ADR-020 (la ficha va antes de los pasos).
- Documento SOP V1.0: RF-11, RNF-01, RNF-03, §14.
- Plan §2, registro de decisiones del 10 nov.
