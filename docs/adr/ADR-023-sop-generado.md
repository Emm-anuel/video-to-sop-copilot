# ADR-023 · SOP generado: agrupar los pasos del video, Gemma solo redacta y el código pone la evidencia

- **Estado:** Propuesto (decisiones de diseño del equipo, 9 nov)
- **Fecha:** 2026-11-09
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

El documento SOP V1.0 (§6; RF-22 a RF-25 y RF-27) pide que, cuando quien carga marca "No tengo
SOP", la app redacte un SOP en español desde el mismo análisis del video (idioma, transcripción,
fotogramas, ficha de contexto y pasos), que se pueda corregir y guardar en la biblioteca y que
después sirva, sin conversión, como referencia para validar otros videos. El SOP generado y el de
referencia usan el mismo esquema (§10).

Lo que ya existe y se reusa: la ficha de contexto (RF-12, `percepcion/contexto.py`), los pasos del
video extraídos sin SOP (RF-13, ADR-010; regla 5) y su segmentación guardada (RNF-07, ADR-022),
los responsables por persona y rol (ADR-020, `lenguaje/personas.py`), la duración narrada o medida
(ADR-021, `lenguaje/tiempos.py`), la verificación de citas (`sopvid.texto`, `contexto.ubicar_cita`)
y la escritura en la plantilla Markdown (ADR-015, `sop_a_markdown`).

Restricciones:

- **Regla 4.** Gemma nunca escribe un tiempo, una fuente, una confianza, un conteo ni un número;
  todo segundo sale de la transcripción.
- **General.** La lógica sirve para cualquier video y cualquier idioma que detecte Whisper. El
  video E (§14: sin SOP, en inglés) y `tests/fixtures/sop_filtro_agua.md` son la prueba de
  aceptación: ninguna frase, paso ni término suyo va en el código ni en los prompts.
- **RNF-05.** Al menos el 80 % de los pasos **generados** debe coincidir con los que narra el
  operador (comparación contra un SOP escrito a mano).

Tres hechos medidos o leídos antes de decidir:

1. **Sin SOP no hay fusión.** ADR-013 une pasos consecutivos del video cuyo paso del SOP más
   parecido es el mismo; al generar no hay SOP ("los pasos del video se usan tal cual"), y la
   segmentación guardada es la de antes de fusionar. `gemma4:e4b` sobre-segmenta: en A deja de 14 a
   17 pasos del video para 6 reales (ADR-022), y la presentación del operador sale como un paso.
   Con un paso del SOP por paso del video, RNF-05 no se puede cumplir (6 de 14 ≈ 43 %).
2. **El contrato no tiene dónde guardar la evidencia de cada dato.** RF-25 pide confianza y fuente
   "en cada dato", y las citas son la evidencia; pero `PasoSOP.equipo` y `puntos_validacion` son
   listas de texto, y `Riesgo`, `Falla` y `PuntoClave` no llevan cita ni fuente.
3. **La ida y vuelta en Markdown no lleva metadatos.** `sop_a_markdown` no escribe confianza,
   fuente, `t`, tiempos del video, puntos ni palabras clave (ADR-015).

## Opciones consideradas

**Cómo pasar de pasos del video a pasos del SOP**

| Opción | A favor | En contra |
|---|---|---|
| A · Llamada aparte de agrupación: Gemma devuelve solo números de paso del video | Tarea corta y separada (~150 tokens de salida); cumple la regla 4 como la segmentación (elige números, no tiempos); deja fuera la intro, el cierre y las preguntas del entrevistador | Una llamada más |
| B · Agrupar dentro de la llamada que redacta | Una llamada menos | Mezcla dos tareas (ADR-010: pedirle más campos a Gemma la hizo partir peor); los lotes se complican porque un grupo no puede cruzar de un lote a otro |
| C · Un paso del SOP por paso del video | Sin código nuevo | RNF-05 falla; todo el arreglo queda para RF-26 |
| D · Fusionar con MiniLM los pasos consecutivos parecidos | Determinista | Dentro de un mismo procedimiento casi todos los pasos se parecen; un umbral sin SOP no tiene contra qué calibrarse |

**Dónde guardar la evidencia**

| Opción | A favor | En contra |
|---|---|---|
| A · Campos opcionales en el contrato `SOP` | Un solo esquema para cargado y generado; la pantalla lee la evidencia junto al dato; un SOP cargado valida igual | El esquema crece |
| B · Columna aparte (`sops.evidencia`) con claves por ruta | El contrato no cambia | Al editar o reordenar (PUT, RF-26) las rutas dejan de apuntar al dato |

## Decisión

### 1. Orden: una sola carga de Gemma, cuatro llamadas nuevas

Ficha de contexto → pasos del video (las dos se reusan si están guardadas, como en ADR-019 y
ADR-022) → **agrupar** → **pasos** (por lotes de hasta 8) → **resumen** → **claves**; después,
solo código. Cada llamada va en flujo (`ClienteLLM.chat_en_flujo`, corte por inactividad, un tope
`LLM_TIMEOUT_SOP_S` para toda la generación), con temperatura 0 y `SEMILLA`, y se reintenta hasta 3
veces **solo** si el JSON no es válido o no cumple el esquema; un corte por tiempo o un Ollama
caído no se reintenta. Se registran por llamada los intentos, los segundos, los tokens de salida y
los tokens/s. Prompts versionados: `sop_generado_agrupar_v1`, `sop_generado_pasos_v1`,
`sop_generado_resumen_v1` y `sop_generado_claves_v1`, con las reglas de §6 (distinguir al
entrevistador del operador, pasos en orden y en infinitivo, no inventar, redactar en español
aunque el video esté en otro idioma) y las citas literales en el idioma original, sin corregir lo
que transcribió Whisper.

### 2. Esquemas mínimos: Gemma escribe solo valores y citas

- **Agrupar:** `{"grupos":[{"pasos_video":[n,…]}],"fuera":[{"paso_video":n,"tipo":…}]}`, con
  `tipo` ∈ introducción, cierre, entrevistador o comentario. El código exige que cada paso del
  video aparezca una vez, que cada grupo sea consecutivo y que los grupos vayan en orden.
- **Pasos:** por paso, `nombre`, `descripcion` y listas `equipo` y `puntos_validacion` de
  `{"cita","valor"}` (con fotogramas, además `"f"`, el número del fotograma).
- **Resumen:** `titulo`, `objetivo` y `alcance` (`{"cita","valor"}`), `duracion_total`
  (`{"cita"}`), `riesgos` (`cita`, `descripcion`, `nivel`, `control`) y `en_caso_de_falla`
  (`cita`, `situacion`, `accion`). No se piden lugar, horario, responsable, roles, equipo ni
  versión.
- **Claves:** `puntos_clave` (`cita`, `texto`) y `palabras_clave` (`termino` en español,
  `literal` como se dijo en el video, `categoria`).

### 3. Lo que pone el código

- **Evidencia (RF-25):** una cita verificada con `contiene_cita` (primero en el tramo del paso,
  luego en toda la transcripción; la regla de largo de la ficha: 2–3 palabras, confianza media;
  4–25, alta) da fuente `audio` y el `t` de su segmento; si no, un fotograma que existe da `visual`,
  media y su `t`; sin evidencia, `inferido`, confianza baja y el campo en `campos_inferidos`.
- **Paso:** número, `t_inicio` y `t_fin` de los pasos del video del grupo; cita, fuente y
  confianza de la mejor cita verificada de esos pasos. Responsable: el **rol** de la persona de la
  ficha que lo hace (`personas.quien_hizo`, la misma regla de ADR-020), nunca su nombre
  (LFPDPPP); "responsable" va en `campos_inferidos` si el rol no aparece en la cita de la persona.
  Tiempo: la duración narrada en el tramo (ADR-021), con su cita; si no, la medida hasta el inicio
  del siguiente paso del video, con `tiempo_esperado_min` en `campos_inferidos` y confianza media.
- **Resumen:** lugar y horario, de la ficha; responsable, el rol que más pasos tiene; roles y
  personas, de las personas de la ficha; equipo de operación, la unión del equipo de los pasos y de
  la ficha sin repetir; duración total, la narrada (`duracion_en_texto` sobre la cita verificada) o
  la suma de los pasos; número de paso de cada riesgo, el paso en cuyo tramo cae su cita; versión
  "1.0".
- **Palabras clave (RF-24):** las menciones y sus segundos se cuentan con la forma literal sobre
  las palabras con tiempo de la transcripción, normalizadas con `sopvid.texto.forma_busqueda` (sin
  acentos ni mayúsculas, plural simple: el mismo criterio que usará la búsqueda exacta). Un término
  con 0 menciones se descarta.

### 4. Contrato: campos opcionales, mismo esquema

`Dato.cita`; en `PasoSOP`, `cita`, `fuente` y `evidencia` (campo, valor, cita, fuente, confianza,
t) para el equipo, los puntos de validación, el tiempo y el responsable; `cita`, `fuente`,
`confianza` y `t` en `Riesgo` y `Falla`; `cita`, `fuente` y `confianza` en `PuntoClave`;
`PalabraClave.literal`, y `Resumen.version` ("1.0"). Todos con valor por defecto: un SOP cargado
valida igual. La ida y vuelta en Markdown garantiza el contenido de la plantilla (título, resumen,
roles, equipo, riesgos, fallas y pasos); la evidencia, los tiempos del video y las claves viven
solo en el JSON, como ya decía ADR-015. Para que la plantilla los lea igual, el generador quita
",", ";" y ":" de los valores de lista.

### 5. Fallas (criterio de ADR-019)

Si una llamada falla, el SOP sale con lo que se pudo y la advertencia `sop_incompleto` dice qué
parte faltó: la agrupación (un paso del SOP por paso del video), pasos sin redactar (con el nombre
y la descripción del paso del video, marcados como inferidos y con confianza baja), el resumen o
las claves. Nunca un SOP sin pasos: si no hay pasos del video, o Ollama no responde al empezar, el
video y el SOP quedan en error con un mensaje claro y se puede repetir.

### 6. Persistencia, biblioteca y API

El SOP se guarda en `sops` con `origen="generado"`, los estados de P1 y `videos.sop_id` apuntando a
él (§10). La migración 0006 agrega `sops.en_biblioteca` (los cargados ya están; un generado entra
con `POST /sops/{id}/biblioteca`) y `sops.generacion` (prompts, modelo, llamadas, dispositivo y
grupos). Un generado que no está en la biblioteca no sirve como `sop_id` (422). `GET
/videos/{id}/sop`, `PUT /sops/{id}` (valida con el contrato) y `GET /sops/{id}.md`. Repetir la
generación (`POST /videos/{id}/generar`) reusa la transcripción, la ficha y la segmentación
guardadas, salvo `?segmentar=true`; si el SOP anterior ya está en la biblioteca, se crea uno nuevo
en vez de pisarlo.

## Consecuencias

- **Positivas:** se reusa todo lo medido (ficha, segmentación, personas, tiempos, citas); la regla
  4 se cumple por construcción; un SOP generado y guardado valida otros videos sin conversión; lo
  inferido queda marcado para revisarlo (RF-26).
- **Negativas / riesgos:**
  - La agrupación es otra salida de Gemma que puede variar entre corridas (la segmentación ya varía,
    ADR-022); se guarda en `sops.generacion`, pero repetir la generación vuelve a pedirla.
  - Los errores de Whisper llegan a las citas y a la forma literal de las palabras clave (en E,
    "shut-off" se transcribe "shove-off"): la cita es literal a la transcripción, no al audio.
  - El plural simple es un recorte de terminaciones, no un lematizador (mismas limitaciones que
    `personas.forma_base`).
  - El nivel de un riesgo lo juzga Gemma como texto; si el video no lo dice, es una estimación.
- **Seguimiento:** medir E (3 corridas en GPU y 1 en CPU), RNF-05 contra el SOP escrito a mano,
  el uso cruzado (A validado contra el SOP de E) y el SOP generado desde A; resultados en
  `docs/adr/datos/sop_generado/` y en este ADR.

## Medición con Gemma real (10 nov 2026): la prueba de aceptación E **no pasa**

`scripts/medir_sop_generado.py`, commit `95d7d40`, `gemma4:e4b-it-q4_K_M` en la RTX 2070 SUPER
(punto 0 confirmado: `ollama ps` dice "100% GPU" antes de medir y `dispositivo_cargado` dice
"gpu" en cada corrida), Whisper `large-v3-turbo` en GPU. Datos en
[`datos/sop_generado/`](datos/sop_generado/): informes `sop-generado-<fecha>.md` y cada SOP
generado (`<fecha>-video_e-<n>.json`, con sus advertencias y `generacion`).

**Lo que sí sale bien.** Idioma `en` con confianza 1.00. El SOP sale en español, con el cuadro
resumen completo en las 4 corridas de E: título, objetivo, alcance, lugar, horario o frecuencia,
responsable ("Técnico de mantenimiento", el rol, nunca el nombre), roles, 15 elementos de equipo,
2–3 riesgos, 1 falla, duración total narrada (3 min, de "The whole job takes about 3 minutes"),
5 de 5 nombres en infinitivo, 7 puntos clave y 10–12 palabras clave con sus menciones. Ninguna
corrida dejó advertencias.

**RNF-05 (≥ 80 % de los pasos generados correctos) no se cumple.** Comparado con
`tests/fixtures/sop_filtro_agua.md` (MiniLM, húngaro, umbrales y juez, sin fusión ni rescate;
correcto = *Cumple* o *Parcial*, en orden y con el punto medio en el tramo anotado de `video_e`):

| Corrida | Pasos del video | Pasos del SOP | Correctos | Referencia cubierta |
|---|---|---|---|---|
| E 1 (GPU) | 18 | 5 | 3 (60 %) | 4 de 6 (faltan 4 y 5) |
| E 2 (GPU) | 18 | 5 | 3 (60 %) | 4 de 6 (faltan 4 y 5) |
| E 3 (GPU) | 17 | 2 | 1 (50 %) | 2 de 6 |
| E (CPU) | 18 | 5 | 3 (60 %) | 4 de 6 (faltan 4 y 5) |

**Por qué.** La agrupación junta de más. En las corridas 1, 2 y CPU, Gemma unió los pasos del
video 5 a 13 (liberar la presión, retirar la carcasa y el cartucho, colocar el cartucho nuevo:
tres pasos de la referencia) en uno, "Liberar presión y reemplazar cartucho" (102–187 s); en la 3
unió del 4 al 17 en uno solo. Además, en E 2 dejó el cierre ("Done…") como un paso y en E 1
partió el paso 6 en dos (abrir la llave / verificar la junta). La redacción de cada paso, sus
citas y el cuadro resumen son correctos: el problema es la granularidad de la agrupación, no la
segmentación (los 17–18 pasos del video separan bien las acciones).

**Segunda falla: en A, la agrupación no salió en 3 intentos.** Gemma puso el último paso del
video a la vez en un grupo y fuera como cierre ("pasos del video repetidos: [14]") y, con
temperatura 0, repitió la misma respuesta en los 3 intentos; el SOP de A quedó con un paso por
paso del video (14) y la advertencia `sop_incompleto`. En E 3 pasó lo mismo una vez y el
reintento lo corrigió. El formato de dos listas (grupos y fuera) permite poner un paso en las dos.

**Uso cruzado (RF-27).** A validado contra el SOP generado de E 1: 80 % amarillo (3 *Cumple*, 2
*Parcial*, 6 *Sobra*, 0 *Falta*). No sale verde por la misma causa: el paso 3 del SOP de E junta
tres pasos de A, así que los fragmentos de A de retirar y colocar el cartucho quedan como
*Sobra*, y los dos *Parcial* son pasos del SOP de E más amplios que su par en A.

**Tiempos (E, 3 min 47 s de video).** GPU: 51.6, 55.3 y 57.3 s de Gemma (ficha 10–13 s,
segmentación 17–20 s, SOP 22–27 s; agrupar 2.3–4.0 s, pasos 7.9–10.0 s, resumen 5.7–6.3 s, claves
6.1–6.9 s), 80–130 tokens/s, 6 652–6 689 MiB de VRAM. CPU (`LLM_DISPOSITIVO=cpu`): 428.8 s de
Gemma (ficha 60 s, segmentación 155 s, SOP 213 s), 13–17 tokens/s. En CPU el modo generar es unas
8 veces más lento: para un video de 10 min serían ~15–20 min solo de Gemma, lejos de RNF-01; sirve
como respaldo (ADR-018), no para la demo.

**Regresión del MVP** (`scripts/medir_mvp.py`, A y B ×3, mismo commit;
[`datos/mvp/mvp-20261110-0039.md`](datos/mvp/mvp-20261110-0039.md)): A 3/3 verde (91.67–100 %),
B 3/3 (66.67 %, *Falta* 2 y 6). Sin regresión.

**Siguiente (pendiente de decisión del equipo, sin tocar código todavía):** cambiar la agrupación
a una decisión por paso del video (ver el informe de esta sesión) y volver a medir E ×3 y A.

## Agrupación v2 y candado por coseno (aprobados por el equipo el 10 nov; medidos el mismo día)

**Qué cambia (decisión 2, "Agrupar").** `sop_generado_agrupar_v2`: Gemma ya no devuelve grupos;
pone **una etiqueta por paso del video**, comparándolo solo con el anterior:
`{"pasos":[{"paso_video":n,"etiqueta":…}]}`, con `etiqueta` ∈ `nuevo`, `continua`,
`introduccion`, `cierre`, `entrevistador` o `comentario`. El código exige una etiqueta por paso
del video (del 1 al último, una vez) y al menos una acción, y arma los grupos
(`agrupar_por_etiquetas`): `nuevo` abre un paso del SOP, `continua` se une al abierto si el paso
del video anterior está en él (si no, abre uno: un `continua` tras una pregunta del entrevistador
parte la acción en dos y cada grupo sigue siendo de pasos consecutivos) y las otras cuatro lo
dejan fuera. Un paso del video ya no puede quedar en un grupo y fuera a la vez (la falla de A con
la v1). La v1 se conserva (`validar_agrupacion`, `ESQUEMA_AGRUPAR_V1`): basta con poner
`PROMPT_AGRUPAR = "sop_generado_agrupar_v1"`.

**Candado general por código (`SOP_CANDADO`, `aplicar_candado`).** Dentro de cada grupo, si el
coseno MiniLM entre un paso del video y el anterior del grupo es menor que `UMBRAL_FUSION`, el
código lo parte ahí en un paso nuevo, aunque Gemma haya dicho `continua`. El texto es el de la
fusión (`texto_para_embeber`: nombre, descripción y cita) en minúsculas. No toca la agrupación de
respaldo (uno a uno) y solo carga MiniLM si hay algún grupo de más de un paso. `GeneracionSOP`
guarda `etiquetas` (las de Gemma, tal cual), `candado` y `cortes_candado` (campos con valor por
defecto: lo ya guardado valida igual).

**Medición** (`scripts/medir_sop_generado.py --candado no|si`, GPU, Gemma "100% GPU" en el punto
0, mismos `analisis.json` de E y A que la medición anterior; informes
[`sop-generado-20261110-1047.md`](datos/sop_generado/sop-generado-20261110-1047.md) sin candado
y [`sop-generado-20261110-1056.md`](datos/sop_generado/sop-generado-20261110-1056.md) con él).
RNF-05 contra `tests/fixtures/sop_filtro_agua.md` (6 pasos); la anotación de A usa los mismos 6
pasos, así que A también se compara. Uso cruzado: A validado contra el SOP de E 1 después de pasar
por JSON, como lo guarda la biblioteca (`sops.contenido`) y lo lee la validación.

| Variante | Corrida | Pasos del video | Pasos del SOP | Correctos (RNF-05) | Referencia cubierta |
|---|---|---|---|---|---|
| v2 sola | E 1 | 18 | 15 | 6 (40.0 %) | 6 de 6 |
| v2 sola | E 2 | 18 | 15 | 6 (40.0 %) | 6 de 6 |
| v2 sola | E 3 | 17 | 14 | 6 (42.9 %) | 6 de 6 |
| v2 sola | A 1 / 2 / 3 | 17 / 15 / 15 | 12 / 11 / 10 | 50.0 / 54.5 / 60.0 % | 6 de 6 |
| v2 + candado | E 1 | 17 | 14 | 6 (42.9 %) | 6 de 6 |
| v2 + candado | E 2 | 18 | 15 | 6 (40.0 %) | 6 de 6 |
| v2 + candado | E 3 | 17 | 14 | 6 (42.9 %) | 6 de 6 |
| v2 + candado | A 1 / 2 / 3 | 14 / 15 / 15 | 12 / 12 / 13 | 50.0 / 50.0 / 46.2 % | 6 de 6 |

Uso cruzado (A contra el SOP de E 1): v2 sola, 70.0 % amarillo (10 *Cumple*, 1 *Parcial*, 4
*Falta*); v2 + candado, 57.14 % rojo (7 *Cumple*, 2 *Parcial*, 5 *Falta*, 3 *Sobra*). Ninguna
corrida dejó advertencias ni reintentó la agrupación. Tiempos de Gemma por corrida: 53–72 s
(dos corridas de A tardaron 127–129 s por una llamada lenta de la redacción, no de la
agrupación).

**Ninguna variante llega a la meta (E ≥ 80 % en las 3, A cerca de 6 pasos, uso cruzado en
verde).** La v2 falla al revés que la v1:

1. **Gemma casi no usa `continua`.** En E marcó `nuevo` en los 14–15 pasos de acción de las 6
   corridas (cero `continua`); en A, 1–3 por corrida. El prompt pide "nuevo" si cambia la
   herramienta, la pieza o el fin, y en un video segmentado fino casi cada pedazo nombra otra pieza.
2. **Las fronteras son todas correctas.** En las 12 corridas, cada paso generado cae dentro del
   tramo anotado de un solo paso de referencia y en orden (E: 1, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5,
   6, 6, 6[, 6]); los 6 pasos de referencia quedan cubiertos siempre. La v1 cruzaba fronteras
   (juntaba 3 pasos de referencia en uno); la v2 no cruza ninguna, solo no junta.
3. **La métrica es uno a uno.** RNF-05 empareja con el húngaro: con 6 pasos de referencia, cada
   paso generado de más es *Sobra*. Con 14–15 pasos el techo es 6/14 = 42.9 %; para 80 % hacen
   falta 7 pasos o menos.
4. **El candado no puede ayudar y en A estorbó.** Solo parte grupos, y en E no había ningún grupo
   que partir. En A partió 4 `continua` (pasos del video 9, 9, 9 y 13) que Gemma había puesto
   bien: los dos pedazos caen en el mismo paso de referencia. Por eso el uso cruzado baja de 70 %
   a 57 %. Dentro de un mismo paso del procedimiento, el coseno entre pedazos seguidos puede ser
   menor que 0.55 (cambian la pieza y el verbo), así que el candado corta justo lo que hay que
   juntar.

**Decisión del equipo (10 nov):** el candado queda apagado por defecto (`SOP_CANDADO=false`; el
código se conserva) y se hace un último intento con el prompt.

## Agrupación v3: criterio de resultado (10 nov) y limitación que queda

**Qué cambia.** `sop_generado_agrupar_v3`, mismo esquema de etiquetas que la v2 (la v1 y la v2 se
conservan). Criterio de resultado: preparar, hacer y revisar una misma cosa son un paso
(`continua`); un paso nuevo empieza cuando el operador pasa a otro resultado, no cuando nombra otra
pieza u otra herramienta. Trae un ejemplo resuelto de un procedimiento inventado sin relación con
los videos de prueba (cambiar la llanta de un auto: 13 pedazos, 4 pasos).

**Medición** (mismo método y mismos `analisis.json`; candado apagado;
[`sop-generado-20261110-1113.md`](datos/sop_generado/sop-generado-20261110-1113.md)). La v3 sí
junta (E 1 y E 2 bajan de 15 a 12 pasos y A, de 10–12 a 4–8), pero de forma desigual: con las
mismas entradas, E 3 salió con 5 pasos, y en 4 de las 6 corridas un paso generado mezcla pasos de
referencia (en E 3, de "liberar la presión" a "retirar el cartucho"; en A 2 y A 3, "retirar" con
"colocar" o "colocar" con "abrir la llave"). Uso cruzado: 79.2 % amarillo (8 *Cumple*, 3
*Parcial*, 1 *Falta*, 1 *Sobra*).

## RNF-05 como lo pide el documento y decisión final (10 nov)

**Métrica.** RNF-05 dice "al menos 80 % de los pasos generados coinciden con los que narra el
operador". Desde el 10 nov la métrica principal (`medir_sop_generado.correctos_por_tramos`) es
**por tramos**: un paso generado es correcto si cae dentro del tramo anotado de **un solo** paso
de referencia (del segundo anotado de ese paso al del siguiente, con 1 s de tolerancia en cada
borde, `TOLERANCIA_TRAMO_S`; la anotación está verificada a ±0.8 s) y respeta el orden (su paso de
referencia no es anterior al de un paso correcto previo). Un SOP más detallado que el escrito a
mano no se castiga; uno que mezcla dos pasos de referencia o que cae en la presentación o el
cierre, sí. Datos secundarios: el **uno a uno** de arriba (húngaro, más estricto: cada paso de
más es *Sobra*) y la **cobertura en orden** (pasos de referencia con un par *Cumple* o *Parcial*
que no está fuera de orden).

Tabla consolidada, recalculada con los datos guardados de cada medición (E ×3 y A ×3 en GPU; la
v1 se midió sin A):

| Variante | E: pasos del SOP | E: RNF-05 por tramos | E: uno a uno | E: cobertura | A: pasos del SOP | A: RNF-05 por tramos | A: uno a uno | A: cobertura | Uso cruzado |
|---|---|---|---|---|---|---|---|---|---|
| v1 (0024) | 5 / 5 / 2 | 80 / 60 / 50 % | 60 / 60 / 50 % | 4 / 4 / 2 de 6 | 14 (falló la agrupación) | — | — | — | 80.0 % amarillo |
| **v2 (1047)** | 15 / 15 / 14 | **100 / 100 / 100 %** | 40 / 40 / 42.9 % | 6 / 6 / 6 de 6 | 12 / 11 / 10 | **100 / 100 / 90 %** | 50 / 54.5 / 60 % | 6 / 6 / 6 de 6 | 70.0 % amarillo |
| v2 + candado (1056) | 14 / 15 / 14 | 100 / 100 / 100 % | 42.9 / 40 / 42.9 % | 6 / 6 / 6 de 6 | 12 / 12 / 13 | 100 / 100 / 100 % | 50 / 50 / 46.2 % | 6 / 6 / 6 de 6 | 57.1 % rojo |
| v3 (1113) | 12 / 12 / 5 | 100 / 100 / 60 % | 50 / 50 / 60 % | 6 / 6 / 4 de 6 | 8 / 4 / 5 | 87.5 / 25 / 60 % | 50 / 75 / 60 % | 5 / 4 / 4 de 6 | 79.2 % amarillo |

Sensibilidad a la tolerancia (pasos correctos por tramos con 0 / 1 / 2 s): con 0 s, la v2 baja a
12 de 15 en E porque los inicios de Whisper y de la anotación difieren en menos de un segundo; de
1 s en adelante no cambia, salvo un paso de A 3 de la v2 que se pasa del borde entre 1 y 2 s (9
de 10 con 1 s; 10 de 10 con 2 s).

**Decisión: v2 predeterminada** (`PROMPT_AGRUPAR = "sop_generado_agrupar_v2"`, `SOP_CANDADO=false`).
Es estable (mismas etiquetas en las 3 corridas de E), no mezcla pasos de referencia y cubre los 6
en orden en las 12 corridas; con la métrica del documento, RNF-05 se cumple en E (100 % en las 3) y
en A (90–100 %). La v1 y la v3 se conservan para reproducir lo medido; la v3 junta más, pero mezcla
pasos en 4 de 6 corridas y no es estable.

**Limitación conocida (RF-26).** La v2 encuentra las fronteras de los pasos y no inventa ni mezcla
pasos, pero el SOP sale más detallado que uno escrito a mano: unos 15 pasos contra 6 en E (10–12
en A). Quien revisa junta pasos con RF-26 antes de guardarlo en la biblioteca; el editor necesita
"Unir con el siguiente paso" (anotado para la pantalla en `frontend/README.md`). Por el mismo
detalle, el uso cruzado sin revisar queda en amarillo (70 %: los pasos finos del SOP de E que A
narra juntos salen como *Falta*). Cada SOP guarda en `sops.generacion` las etiquetas de Gemma y
los grupos.

**E en CPU con la v2** (`LLM_DISPOSITIVO=cpu`, "100% CPU" en el punto 0, 1 corrida;
[`sop-generado-20261110-1152-cpu.md`](datos/sop_generado/sop-generado-20261110-1152-cpu.md)):
**476.2 s de Gemma** (ficha 63.7 s, segmentación 153.3 s, SOP 259.3 s: agrupar 41.9 s, pasos
98.7 s en dos lotes, resumen 52.9 s, claves 65.8 s), 14–18 tokens/s, 18 pasos del video y 15 del
SOP, las mismas etiquetas que en GPU y RNF-05 de 100 % por tramos (40 % uno a uno). Contra unos
64 s en GPU, son unas 7.4 veces más; con la v1 en CPU fueron 428.8 s (la v2 tarda más en redactar
porque son 15 pasos, no 5). Sigue siendo respaldo (ADR-018), no para la demo.

## Prueba manual de E (10 nov): valores en español y equipo sin repetir

**Lo que se vio** (video 6971, SOP 6314, v2 con `pasos_v1` y `resumen_v1`). Las citas salen bien
en inglés, pero algunos valores también: el equipo de 5 pasos ("cartridge", "plastic wrap",
"wrench", "red button", "paper towel"), el control de un riesgo y la acción de las dos fallas,
copiados de la cita. Y el equipo de operación tenía 19 elementos para 7 reales: la unión del
equipo de los pasos y de la ficha solo juntaba nombres iguales.

**Cambios.**

1. **Prompts** `sop_generado_pasos_v2` y `sop_generado_resumen_v2` (las v1 se conservan): todo lo
   que no es cita va en español, traducido y redactado con palabras propias, con un ejemplo de
   otro procedimiento; el nombre del equipo, corto y sin lugar ni descripción.
2. **Revisión por código** (`revisar_idioma`, advertencia `sin_traducir`): si el video no está en
   español, un valor (título, objetivo, alcance, lugar, horario, equipo, roles, riesgos, fallas,
   nombre, descripción, equipo y validación de cada paso, puntos clave y términos de las palabras
   clave) parece sin traducir si más de la mitad de sus palabras de 3 letras o más aparecen en la
   transcripción (`forma_busqueda`). Hay una advertencia por lugar, con el lugar y cuántos
   valores, nunca el texto. Sobre el SOP 6314 marca exactamente lo visto (9 lugares), sin avisos
   falsos en las descripciones. Un término igual en los dos idiomas ("manual", "panel") puede
   dar un aviso falso: es solo una advertencia.
3. **Equipo de operación** (`unir_equipo`, `UMBRAL_EQUIPO=0.85`): primero junta los nombres
   iguales (`clave_elemento`); después, un nombre cuyo coseno MiniLM en minúsculas con uno ya
   guardado es ≥ el umbral se une a ese, que conserva su nombre. Compara contra los guardados, no
   en cadena.

**Medición** (E ×3 en GPU, mismo `analisis.json`;
[`sop-generado-20261110-1224.md`](datos/sop_generado/sop-generado-20261110-1224.md)):

| Corrida | Pasos del SOP | Valores sin traducir | Equipo de operación | RNF-05 por tramos | Uno a uno |
|---|---|---|---|---|---|
| E 1 | 14 | 0 | 18 | 100 % | 42.9 % |
| E 2 | 14 | 0 | 16 | 100 % | 42.9 % |
| E 3 | 15 | 0 | 16 | 100 % | 40.0 % |

Los valores salen en español en las 3 corridas y RNF-05 no empeora. **El equipo no queda cerca
del real (7):** los duplicados que quedan son sinónimos que MiniLM no relaciona, y bajar el umbral
junta antes cosas distintas.

- Del equipo de los pasos salen 12 nombres por corrida, todos con cita: los 7 reales, otros que
  sí se nombran (el botón de purga, la envoltura del cartucho, la válvula, el manómetro) y dos
  ruidos ("Supervisor de ajuste", de un error de Whisper; "llave" junto a "llave de carcasa", con
  coseno 0.77). La ficha de contexto agrega 4–6 que son los mismos con otras palabras:
  "manómetro" / "medidor de presión", "cartucho de filtro" / "cartucho nuevo", "contenedor" /
  "cubo", "llave inglesa" (cosenos < 0.52).
- Barrido del umbral en E: 0.85 y 0.80 dan 18 / 16 / 16; 0.75, 17 / 15 / 15; 0.65, 15 / 13 / 14.
  Mientras tanto se unen pares distintos ("llave de carcasa" / "contenedor" 0.66, "válvula de
  corte" / "cartucho de filtro" 0.67).
- En A (español) el umbral 0.85 ya deja 9–11 de 10–12, pero 0.75 une "llave de la carcasa" (la
  herramienta) con "llave de paso" (la válvula). Quitar el equipo de la ficha tampoco sirve: en A
  la ficha trae equipo real que los pasos no nombran (lentes, bolsa de residuos, cartucho).
- Con cualquier umbral, en español "llave" y "llave de paso" (0.90) se unen: el coseno no
  distingue la herramienta de la válvula.

**Pendiente (decisión del equipo).** Juntar sinónimos necesita algo más que el coseno. La opción
más directa es pedir a Gemma, en la llamada del resumen, la lista única del equipo en español
(juntando sinónimos, cada uno con una cita verificada) y dejar `unir_equipo` como red de
seguridad. Mientras tanto, quien revisa quita los repetidos con RF-26.

## Referencias

- Documento SOP V1.0, §6, §10 y §14; RF-22 a RF-27, RNF-05 y RNF-06.
- ADR-010, ADR-012, ADR-013, ADR-015, ADR-018, ADR-019, ADR-020, ADR-021, ADR-022.
