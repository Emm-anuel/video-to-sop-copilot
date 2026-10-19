# Fixtures de prueba

Todo lo que hay aquí lo **inventó el equipo**. Nada es material del cliente (NDA): ni videos,
audio, SOPs, transcripciones ni fragmentos. Los nombres de personas son ficticios.

## `transcripciones/`

Transcripciones inventadas para evaluar la segmentación en pasos (ADR-010). Cada archivo lleva su
propia `descripcion` con la palabra INVENTADA y los inicios de paso anotados a mano en
`inicios_paso`.

## `analisis_ejemplo.json`

Ejemplo del contrato `sopvid.contrato.Analisis` (esquema en `docs/contrato/analisis.schema.json`).
El contrato prohíbe campos extra, así que el JSON no puede llevar `_comentario` ni descripción:
la documentación vive aquí.

- **Origen:** transcripción INVENTADA por el equipo, en español, de un video que no existe. Los
  tiempos por palabra se generaron con un script desechable (duración según la longitud de la
  palabra y pausas entre segmentos), así que son coherentes pero no vienen de un ASR real.
- **SOP de referencia (también inventado):** "Cambio del cartucho del filtro de agua", 6 pasos.
- **Video:** `video_id` 1, 157.8 s, 25 segmentos, 330 palabras, idioma `es` (0.98), 4 fotogramas
  con descripción inventada (no hay imágenes: `archivo` es solo un nombre).
- **Narradora:** "Laura", técnica de mantenimiento (ficticia). Menciona al supervisor de turno
  en una aclaración, pero él no hace ningún paso.

### Inicios de paso reales, anotados a mano según la narración

| Paso del SOP | Segmento de inicio | `t_inicio` (s) | Segmentos del paso | Marcador de transición |
|---|---|---|---|---|
| 1. Ponerse guantes y lentes | 4 | 20.45 | 4–5 | "Primero" |
| 2. Cerrar la llave de paso | 6 | 33.44 | 6–8 | "Ahora" |
| 3. Liberar la presión | 9 | 55.51 | 9–11 | "Después" |
| 4. Retirar la carcasa y el cartucho usado | 12 | 74.76 | 12–16 | ninguno |
| 5. Colocar el cartucho nuevo | 17 | 104.90 | 17–20 | "Luego" |
| 6. Abrir la llave y revisar fugas | 21 | 127.32 | 21–24 | "Finalmente" |

Inicios de paso: `[4, 6, 9, 12, 17, 21]`.

Lo que **no** inicia paso, y sirve para detectar sobre-segmentación (ADR-013):

- **Introducción** (1–3): presentación, qué se va a hacer y cada cuándo se cambia el cartucho.
- **Aclaraciones dentro de un paso:** 5 (por qué los lentes), 7 (cómo saber que la llave está
  cerrada), 8 (qué hacer si la llave está dura), 15 (revisar el anillo de hule), 20 (no apretar de
  más).
- **Anécdota:** 16 (el anillo partido que goteó toda la noche).
- **Acciones de apoyo dentro de un paso:** 11 (poner la cubeta, parte del paso 3), 22–24 (purgar,
  revisar uniones y presión, parte del paso 6).
- **Cierre** (25).

El paso 4 empieza sin palabra de transición ("Con la llave de carcasa giro el vaso…"): solo se
distingue por el contenido.

### Fotogramas

| Archivo | `t` (s) | Paso al que pertenece |
|---|---|---|
| `f01.jpg` | 23.0 | 1 (guantes y lentes) |
| `f02.jpg` | 58.0 | 3 (botón de purga, cubeta) |
| `f03.jpg` | 84.0 | 4 (vaso retirado con el cartucho usado) |
| `f04.jpg` | 149.0 | 6 (manómetro cerca de 4 bar) |

## `sop_filtro_agua.md`, `sop_filtro_agua_simple.txt` y `sop_ejemplo.json`

El SOP de referencia del ejemplo anterior, "Cambio del cartucho del filtro de agua". Lo escribió
el equipo y es **INVENTADO**, igual que el video: no hay ningún SOP del cliente detrás. Sirve
para probar la conversión de RF-03 (`sopvid.lenguaje.sop_markdown`, ADR-015).

- **`sop_filtro_agua.md`:** la plantilla completa de `docs/contrato/plantilla_sop.md`: resumen,
  2 roles, 7 elementos de equipo, 2 riesgos (pasos 3 y 4), 2 fallas y, en cada paso, responsable,
  equipo, validación y 0.5 min (suman la duración total de 3 min). Convierte sin advertencias.
- **`sop_filtro_agua_simple.txt`:** lo mínimo en TXT: título en la primera línea, un
  "Responsable:" suelto y una lista numerada. Los pasos heredan el responsable con confianza media.
- **`sop_ejemplo.json`:** el SOP del contrato (`sopvid.contrato.SOP`, esquema en
  `docs/contrato/sop.schema.json`) que da `sop_filtro_agua.md`. No se edita a mano; si cambia el
  `.md` o el parser, se regenera con:

  ```powershell
  python scripts/convertir_sop.py tests/fixtures/sop_filtro_agua.md --salida tests/fixtures/sop_ejemplo.json
  ```

  `tests/test_sop_markdown.py` falla si el script deja de dar exactamente este archivo.

**Alineación con `analisis_ejemplo.json`, paso por paso.** El paso N del SOP es la fila N de la
tabla "Inicios de paso reales": mismo nombre, y empieza en el segmento anotado ahí (4, 6, 9, 12, 17
y 21). Los dos riesgos citan los pasos 3 y 4, los mismos en los que caen `f02.jpg` y `f03.jpg`.
`tests/test_sop_markdown.py` lee esa tabla y comprueba que los nombres y el número de pasos
coincidan.

Se guardan en el repo con LF; las pruebas leen con `encoding="utf-8"` y construyen en memoria las
variantes con CRLF y BOM.
