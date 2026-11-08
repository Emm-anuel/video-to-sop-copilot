# ADR-015 · Convertir el SOP de referencia con una plantilla y un parser; Gemma 4 solo sin plantilla

- **Estado:** Propuesto
- **Fecha:** 2026-10-19
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

El documento SOP V1.0 (§5.1) pide un LLM para convertir el SOP de referencia al esquema de su
sección 10. ADR-006 lo dejó como uno de los usos de Gemma 4. Pero el MVP de validación (8 nov,
plan §5.1) solo necesita SOP en TXT o Markdown escritos por el equipo (RF-03). Los SOP del
cliente, en PDF o Word (RF-01 y RF-02), llegan en S5.

Un SOP convertido a medias contamina todo lo que viene después: un paso de más o de menos sale
en el reporte como *Falta* o *Sobra*. Las pruebas de regresión (regla 7) necesitan una conversión
que dé siempre lo mismo y que corra en CI sin Ollama ni GPU (ADR-014). También hay que respetar el
costo cero (ADR-011) y el NDA: los errores y el log no pueden citar texto del SOP.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Gemma 4 para todo | Acepta cualquier formato desde el primer día | No es determinista; ocupa la GPU, que se comparte con faster-whisper; las pruebas necesitan Ollama; puede inventar o fusionar pasos |
| B · Plantilla + parser con código; Gemma 4 solo para texto libre, PDF y Word en S5 | Determinista y probado sin Ollama; cubre el MVP; deja RF-01 y RF-02 para cuando hagan falta | Hay que escribir los SOP del MVP en la plantilla; dos caminos de entrada que mantener |
| C · Solo plantilla | Lo más simple | No cumple RF-01 ni RF-02: los SOP del cliente en PDF o Word no entran |

## Decisión

**B.** Un SOP en Markdown o TXT que sigue `docs/contrato/plantilla_sop.md` se convierte con
código, sin LLM (`sopvid.lenguaje.sop_markdown.convertir_sop`), al contrato `sopvid.contrato.SOP`.
La plantilla solo exige "# Título" y "## Pasos". Lo que no aparece queda vacío, nunca inventado.
Las desviaciones menores (numeración, claves desconocidas, tiempos, nombres que no empiezan en
infinitivo) se corrigen o se ignoran y quedan como advertencias con tipo y línea. Sin título, sin
pasos o con un paso sin nombre, la conversión falla con un mensaje que dice el formato esperado.
`sop_a_markdown` escribe un SOP con la misma plantilla, y `scripts/convertir_sop.py` convierte un
archivo a JSON.

Gemma 4 convierte solo los SOP sin plantilla (texto libre, PDF y Word) en S5. Su salida se
valida contra el mismo contrato `SOP`; el diseño de ese camino se decide al implementarlo.

**Diseño del camino con Gemma 4 (S5, 7 nov 2026, `sopvid.lenguaje.lectura_sop`).**
`extraer_texto` saca el texto sin LLM: PDF con pdfplumber (líneas partidas por el ancho de la
página vueltas a unir, tablas como líneas "Encabezado: valor | …" en su lugar) y Word con
python-docx (cuerpo en orden de documento, encabezados como "#", listas con su viñeta o número).
Un PDF sin texto se rechaza con un mensaje que pide Word, TXT o Markdown (el OCR es PR-10). Luego
`convertir_documento` intenta `convertir_sop`; si falla o ignoró texto (advertencias
`clave_desconocida` o `seccion_desconocida`), convierte con Gemma 4: prompt
`prompts/sop_texto_libre_v1.md`, JSON restringido a un esquema sin números de paso, fuente ni
tiempos (los pone el código), temperatura 0, `SEMILLA` y hasta 3 intentos como el juez. El código
pone `fuente="documento"` y hereda el responsable del resumen igual que la plantilla. Cada paso
trae `cita_origen` (4 a 25 palabras copiadas del documento); si no aparece tal cual en el texto
(normalizado), el paso lleva la advertencia `paso_sin_evidencia`. El nombre queda libre. La
respuesta de `POST /sops` dice `metodo: "plantilla" | "llm"`. Si Ollama no responde, 503 y no se
guarda nada (criterio de ADR-019). Markdown y TXT pasan por el mismo camino: si no siguen la
plantilla, ya no dan error, los convierte Gemma 4.

**Asíncrono (7 nov, después de medir en CPU).** Con Gemma solo en CPU una conversión tarda
2-3.5 min, demasiado para una petición. `POST /sops` responde 202 y la conversión corre en el
trabajador de la cola, que tiene prioridad (un SOP va antes que el siguiente video, sin
interrumpir el que corre); el estado se consulta en `GET /sops/{id}/estado` (`sops.estado`,
migración 0004). La plantilla también pasa por ahí. Si Ollama no responde, el SOP queda en
`error` con un mensaje que dice qué hacer, en lugar del 503. Un video espera a su SOP y, si la
conversión falla, queda en error con ese mensaje.

## Consecuencias

- **Positivas:** la conversión es determinista, se prueba sin Ollama ni base de datos y cuesta
  cero. Un SOP fuera de plantilla falla con un mensaje claro en lugar de convertirse a medias. Los
  errores, las advertencias y el log citan números de paso y de línea, no texto del SOP. Las
  advertencias tienen un tipo estable, para agruparlas en la pantalla de corrección (RF-04).
- **Negativas / riesgos:** los SOP del MVP se escriben a mano en la plantilla. La plantilla no
  tiene cómo escapar sus separadores (":", ",", ";", "Paso:" y "Control:" en un riesgo).
  `sop_a_markdown` no lleva los metadatos (confianza, fuente, tiempos) ni los puntos y palabras
  clave: para eso, la fuente de verdad es el JSON.
- **Seguimiento:** en S5, al implementar RF-01 y RF-02, se mide cuántos SOP reales (por
  identificador, sin copiarlos al repo) siguen la plantilla y cuántos necesitan a Gemma 4. Se
  decide entonces si la salida del LLM pasa por la misma revisión humana (RF-04).
  - **Primera prueba con Gemma 4 real (7 nov 2026,
    [`datos/sop/prosa-20261107-1845.json`](datos/sop/prosa-20261107-1845.json)).** Entrada: un
    Word en prosa generado por `docx_en_prosa` a partir de `tests/fixtures/sop_filtro_agua.md`
    (inventado; sin secciones, listas ni nombres de paso). `gemma4:e4b-it-q4_K_M` en la RTX 2070
    SUPER, 3 corridas: las 3 idénticas, en el primer intento, 22–27 s cada una.
    - Bien: 6 de 6 pasos, en el orden del documento, sin juntar ni partir; nombres en
      infinitivo; objetivo, lugar y responsable copiados del texto; alcance, horario, tiempos,
      riesgos y fallas en vacío, porque la prosa no los trae (no inventó). Puntos de validación y
      equipo por paso salen del texto.
    - Mal: (1) los nombres son telegráficos ("Girar llave de paso antes del filtro" por "girar
      la llave de paso que está antes del filtro"), así que la verificación literal los marca a
      los 6 como `nombre_sin_evidencia` y el aviso pierde valor (por eso se cambió a verificar
      una cita por paso, `paso_sin_evidencia`); (2) en 3 pasos la acción quedó
      solo en el nombre y la descripción empieza a media frase ("antes de tocar el filtro.");
      (3) inventó descripciones genéricas para el equipo ("material necesario") y puso como
      punto de validación una acción ("Revisar el anillo de hule…").
    - Siguiente: un `sop_texto_libre_v2` que pida copiar el nombre como fragmento contiguo del
      texto (o relajar la verificación a cobertura de palabras) y la descripción completa, y
      dejar vacía la descripción del equipo si el documento no la trae. Medir con SOP reales en
      cuanto lleguen. Mientras, la salida del LLM debe pasar por la corrección humana (RF-04).
  - **v1 contra v2 con `cita_origen` (7 nov 2026,
    [`prosa-v1-20261107-1858.json`](datos/sop/prosa-v1-20261107-1858.json),
    [`prosa-v2-20261107-1858.json`](datos/sop/prosa-v2-20261107-1858.json)).** Mismo Word en
    prosa, mismo modelo y GPU, 3 corridas por prompt, todas válidas en el primer intento (26–31
    s). El esquema ya pide `cita_origen` en los dos; v2 (`sop_texto_libre_v2.md`, el que queda
    por defecto) además la explica, pide descripción completa sin repetir el nombre y equipo sin
    descripciones genéricas. Medidas: pasos con evidencia = cita verificada; descripción cortada
    = empieza en minúscula (a media frase) o repite el nombre; equipo inventado = descripción
    del equipo que no aparece en el documento.

    | Medida (por corrida) | v1 | v2 |
    |---|---|---|
    | Pasos (la referencia tiene 6) | 8 · 8 · 8 | 8 · 8 · 8 |
    | Pasos con evidencia | 7 de 8 en las 3 | 8 de 8 en las 3 |
    | Descripciones cortadas | 6 · 2 · 2 | 0 · 0 · 0 |
    | Equipo con descripción inventada | 7 de 7 en las 3 ("Herramienta", "Equipo de protección") | 0 de 7 |
    | Roles con descripción inventada | 1 de 1 | 0 de 1 |
    | Corridas idénticas | no (la 1.ª difiere) | casi (una palabra en 1 de 3) |

    - v2 corrige los tres problemas que se midieron. La cita no se resume: aparece tal cual en
      los 8 pasos. Las descripciones de v2 parafrasean un poco ("hasta que cese la salida de
      aire"); la evidencia queda en la cita, no en la descripción.
    - Hallazgo nuevo: con `cita_origen` en el esquema, los dos prompts parten la prosa en 8 pasos
      en lugar de 6: "Colocar la cubeta debajo del filtro" y "Revisar y cambiar el anillo de
      hule" salen como pasos propios (en la plantilla son la segunda oración de los pasos 3 y 4).
      Son acciones reales, pero un SOP con más pasos que el original deja más *Falta* posibles en
      el reporte. Sin la cita (corrida de las 18:45), v1 daba 6. Pendiente para un v3: decir que
      en prosa cada párrafo es un paso salvo que el documento separe las acciones, y medir con SOP
      reales antes de decidir.
    - Resuelto (P1, punto 5): un documento largo podía no caber en `LLM_NUM_CTX` (8192) y fallar
      los 3 intentos. Ahora se estiman los tokens antes de llamar al LLM; si no caben, cada
      petición pide `LLM_NUM_CTX_SOP` (16384, +200 MiB de VRAM) y, si tampoco, 422 "el documento
      es demasiado largo". Los reintentos ya no reenvían la respuesta anterior. Cifras en
      docs/dev/llm.md.
    - Resuelto (P1, punto 4): `POST /sops` convertía dentro de la petición sin coordinarse con
      el trabajador, así que Gemma podía cargarse mientras Whisper transcribía otro video
      (ADR-014). Primero se agregó `CANDADO_MODELO_PESADO` (`plataforma/hardware.py`) con una
      espera `LLM_ESPERA_GPU_S` y 503; después, al pasar la conversión al trabajador (POST
      /sops asíncrono), todo lo que carga un modelo corre en el mismo hilo: la espera y el 503
      se quitaron y el candado se queda como protección.

## Referencias

- Documento SOP V1.0, §5.1 y §10; plan §5.1 (MVP de validación).
- RF-01 a RF-05; ADR-004, ADR-006 (usos de Gemma 4), ADR-011, ADR-014.
- `docs/contrato/plantilla_sop.md`, `src/sopvid/lenguaje/sop_markdown.py`,
  `scripts/convertir_sop.py`, `tests/test_sop_markdown.py`.
- `src/sopvid/lenguaje/lectura_sop.py`, `src/sopvid/lenguaje/prompts/sop_texto_libre_v1.md`,
  `tests/test_lectura_sop.py`; ADR-019 (503 sin LLM).
