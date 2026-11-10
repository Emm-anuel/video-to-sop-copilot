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

## Referencias

- Documento SOP V1.0, §6, §10 y §14; RF-22 a RF-27, RNF-05 y RNF-06.
- ADR-010, ADR-012, ADR-013, ADR-015, ADR-018, ADR-019, ADR-020, ADR-021, ADR-022.
