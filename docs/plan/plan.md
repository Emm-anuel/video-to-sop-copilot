# Plan de desarrollo · SOPVID 1.0

- **Versión:** 17 oct 2026 (reemplaza la del 10 oct)
- **Estado:** vigente; se revisa cada semana
- **Fuentes:** "Requerimientos técnicos y funcionales de proyecto SOP V1.0" (Dr. Jacobo Eluani,
  16 oct 2026), junta con el patrocinador del 16 oct, brief v1.0, NDA Alignity–Tec, ADR-006 y ADR-010,
  descripciones de los avances 3–5.
- Este documento no contiene datos del cliente. Lo no confirmado se marca *Por confirmar*.
- Versión visual del plan: `sopvid-arquitectura-plan.html` (proyecto en claude.ai).

---

## 1. Resumen

El 16 oct el patrocinador entregó el documento de requerimientos SOP V1.0 y fijó **costo cero**. El
producto deja de ser "búsqueda y chat sobre pasos" y pasa a ser una app web que:

1. **Valida un video contra un SOP**: qué pasos faltan, sobran o cambian de orden, y si coinciden
   personas, tiempos y contexto. Reporte con porcentaje, semáforo y PDF.
2. **Genera el SOP desde el video** cuando no existe: cuadro resumen, tabla de pasos, palabras clave y
   PDF, editable y guardable en la biblioteca.
3. **Busca por coincidencia exacta** en los videos publicados y salta al segundo exacto.

Todo corre local con Docker. La transcripción, la visión y el LLM son modelos abiertos servidos en la
misma máquina (opción B de la sección 8.1 del documento). Ningún video sale y no se paga ninguna API.

**Qué se conserva de lo hecho:** F0 (API, Postgres, Docker, CI), el cliente del LLM y Ollama en Docker
(ADR-006), la segmentación por segmentos numerados (ADR-010), la regla de que el LLM nunca escribe un
tiempo, `sopvid.features` para los avances y el MiniLM multilingüe investigado.

**Qué deja de aplicar:** el chat RAG con router, reordenador y redactor, la búsqueda híbrida con
vectores, la Pantalla 2 de chat conversacional, las etiquetas máquina/área/proceso como eje del producto,
la diarización y Colab como worker. Pasan a versión 2.

---

## 2. Decisiones

| ADR | Decisión | Estado |
|---|---|---|
| ADR-002 | Voz como fuente principal; los fotogramas solo se describen (RF-11). V-JEPA 2 diferido | Resuelto por el documento SOP V1.0 (16 oct) |
| ADR-003 | Grafo multi-video diferido; un SOP es una lista ordenada de pasos | Resuelto por el documento SOP V1.0 |
| ADR-004 | Alcance 1.0: 29 *Debe* + 4 *Debería* + 2 *Podría* (sección 5) | Equipo; se informa el 19 oct |
| ADR-005 | Se conserva PostgreSQL 16 de F0 en lugar de SQLite; pgvector queda para la versión 2 | Equipo |
| [ADR-006](../adr/ADR-006-llm-local.md) | `gemma4:e4b-it-q4_K_M` en Ollama, ahora también para describir fotogramas | Propuesto; ampliado el 17 oct |
| ADR-008 | Revisión humana dentro de 1.0 (RF-04, RF-21, RF-26); roles, firmas y versiones fuera | Resuelto por el documento SOP V1.0 |
| [ADR-010](../adr/ADR-010-segmentacion-pasos-llm.md) | Pasos del video: el LLM elige segmentos numerados; heurística de respaldo | Propuesto; se reutiliza para RF-13 |
| ADR-011 | Opción B: todo local, costo cero; ninguna API externa | Equipo (lo pidió el patrocinador el 16 oct) |
| ADR-012 | Emparejar pasos por cascada: MiniLM + algoritmo húngaro; solo la zona gris va a Gemma 4 como juez; orden con subsecuencia creciente más larga | Equipo |
| ADR-013 | Antes de emparejar, fusionar pasos del video consecutivos que caen en el mismo paso del SOP (mitiga la sobre-segmentación de `e4b`) | Equipo |
| ADR-014 | Hardware de referencia: PC de Emmanuel (RTX 2070 SUPER 8 GB). faster-whisper y Gemma 4 en secuencia, un modelo en GPU a la vez | Equipo |

Los ADR-002, 003 y 008 estaban pendientes de aprobación escrita del patrocinador porque el NDA (cl. 1)
nombra V-JEPA 2, el grafo y el HITL de tres bucles. El documento SOP V1.0, escrito por el patrocinador,
deja esos temas fuera de la versión 1.0; se cita como esa aprobación.

**Modelo de lenguaje.** El NDA (cl. 1) nombra a Gemma 4. `qwen3.5:9b` segmentó mejor en ADR-010, pero
usarlo en el producto requiere aprobación escrita; se mide solo como comparación en los experimentos.

---

## 3. Arquitectura

```
Subida (partes de 16 MB, reintentos) ── SOP nuevo: pdfplumber / python-docx → Gemma 4 → esquema SOP
  → ffmpeg: duración, audio mp3 mono 16 kHz, fotogramas, miniaturas
  → faster-whisper: idioma con confianza, texto con tiempo por palabra, TXT en vivo
  → Gemma 4 (visión): hasta 20 fotogramas, en lotes
  → Gemma 4: ficha de contexto
  → Gemma 4: pasos del video eligiendo segmentos numerados, SIN ver el SOP (ADR-010)
  ├─ Con SOP: afinidad → fusión (ADR-013) → cascada MiniLM → juez → orden, personas, tiempos → reporte
  └─ Sin SOP: Gemma 4 redacta el SOP en español (mismo esquema) → el supervisor corrige y guarda
  → PDF (ReportLab + qrcode), TXT, SRT, JSON
  → Publicar: índice de palabras normalizadas con su segundo → búsqueda exacta
```

| Componente | Tecnología | Notas |
|---|---|---|
| Web | Angular, servido por FastAPI | Vistas `/carga` (6 pantallas) y `/buscar` (1), clave de acceso por vista en variables de entorno |
| API y tareas | FastAPI (Python 3.11) + `ThreadPoolExecutor` | Avance por etapa 0–100 %; estado `error` con reprocesar |
| Base | PostgreSQL 16 (imagen pgvector de F0) | Tablas `sops`, `videos`, `reportes`, `palabras`, `busquedas` del documento |
| Archivos | Volumen de medios | Videos, SOP originales, fotogramas, miniaturas, PDF |
| Transcripción | faster-whisper `large-v3-turbo` (GPU, float16); `small` (CPU, int8) | Tiempo por palabra, VAD |
| LLM y visión | Ollama 0.40.2 · `gemma4:e4b-it-q4_K_M` · JSON Schema · temperatura 0 · semilla 42 | Mismo modelo para texto e imágenes |
| Emparejamiento | `paraphrase-multilingual-MiniLM-L12-v2` + `scipy.optimize.linear_sum_assignment` | Umbrales en `config`: 0.55 / 0.75 |
| Salidas | ReportLab, qrcode | Carta, español, encabezado y "Página X de Y" |

**Interfaces** (proveedor elegido por configuración, RNF-14): `Transcriptor.transcribir`,
`Vision.describir_fotogramas`, `Analista.convertir_sop / ficha_contexto / extraer_pasos / juzgar /
redactar_sop`, `Emparejador.emparejar / afinidad`. Toda salida del LLM se valida con Pydantic; si no
valida, dos reintentos con el error en el prompt.

**Memoria de video (8 GB).** Gemma 4 E4B ocupa ~4.7 GB con FA y faster-whisper turbo ~2 GB; el
escritorio de Windows usa ~1.6 GB. No caben juntos: la transcripción termina y libera la GPU antes de
que Ollama cargue el modelo (`OLLAMA_MAX_LOADED_MODELS=1`, descarga explícita entre etapas).

---

## 4. Contrato entre módulos

Sara entrega el análisis del video; Emmanuel lo consume. Mientras el pipeline no exista, Emmanuel
trabaja con un archivo de ejemplo en `tests/fixtures/` con este formato (datos inventados).

```json
{
  "video_id": 7,
  "duracion_s": 412.6,
  "idioma": {"codigo": "es", "confianza": 0.97, "fijado_a_mano": false},
  "segmentos": [
    {"i": 12, "t_inicio": 118.40, "t_fin": 124.95, "texto": "Ahora retiramos la tapa del filtro.",
     "palabras": [{"w": "Ahora", "t": 118.40, "t_fin": 118.71}]}
  ],
  "fotogramas": [
    {"t": 120.0, "archivo": "f_0120.jpg", "descripcion": "Operador con guantes sostiene una carcasa",
     "equipos": ["llave de carcasa"], "personas": 1, "texto_visible": [], "riesgos": []}
  ]
}
```

El SOP y el reporte usan los esquemas de la sección 10 del documento SOP V1.0 sin cambios.

---

## 5. Alcance 1.0 (ADR-004)

- **Entran los 29 *Debe*.**
- ***Debería*:** entran RF-04 (corregir SOP convertido), RF-25 (confianza y fuente), RF-31 (TXT, SRT,
  JSON) y RF-37 (filtros). RF-18 (EPP) y RF-21 (falso positivo) solo si la validación está estable el 8 nov.
- ***Podría*:** entran RF-16 (tiempos, lo evalúa el video C) y RF-35 (unir resultados a < 3 s).
  RF-28 (diagrama, glosario) queda fuera.
- **Fuera:** todo lo de la columna derecha de la sección 2 del documento, más diarización (PR-04) y
  búsqueda semántica (PR-08).

| Módulo | RF | Responsable | Semana |
|---|---|---|---|
| Subida, idioma, transcripción, avance en vivo | RF-06, 08, 09, 10 | Sara | S2–S3 |
| Fotogramas | RF-11 | Sara | S3 |
| SOP de referencia | RF-01, 02, 03 · RF-04, 05 | Emmanuel · Sara (pantallas) | S3 · S4–S5 |
| Contexto y pasos del video | RF-12, 13 | Emmanuel | S3 |
| Validación | RF-14, 15, 16, 17, 19 | Emmanuel | S4 |
| Evidencia y revisión | RF-20 · RF-21 | Sara | S4 · S6 |
| SOP generado | RF-22, 23, 24, 25, 27 · RF-26 | Emmanuel · Sara | S5 |
| PDF y descargas | RF-29, 30 · RF-31 | Emmanuel · Sara | S5 |
| Búsqueda | RF-32 a 37 | Sara | S5–S6 |

---

## 6. Roadmap

| Semana | Emmanuel | Sara | Compartido / checkpoint | Académico |
|---|---|---|---|---|
| S1 · 12–18 oct | Avance 3 | Guion de los videos de prueba | Revisión del documento SOP V1.0 | **Avance 3 (18 oct)** |
| S2 · 19–25 oct | Gemma 4 con imágenes; esquemas Pydantic; fixture del contrato | Grabar videos A–E; subida por partes; faster-whisper | Junta lun 19 oct; tablas en Postgres; SOP de referencia; repo privado | Avance 4 (25 oct) |
| S3 · 26 oct–1 nov | Lector de SOP; ficha de contexto; pasos del video | Fotogramas; avance en vivo | Anotación a mano; script de métricas | Avance 5 (1 nov) |
| S4 · 2–8 nov | Fusión, cascada, orden, personas, tiempos, afinidad, % | Biblioteca, nuevo análisis, reporte con salto al segundo | ✓ **Validación estable** (videos A–D) | — |
| S5 · 9–15 nov | SOP generado; PDF de reporte y SOP | SOP editable; publicar; búsqueda exacta | ✓ **App completa** (video E); primera medición de RNF | — |
| S6 · 16–22 nov | Si da tiempo: RF-18 | Si da tiempo: RF-21 | Docker en máquina limpia; RNF-01 a 07; video de demo | — |
| S7 · 23–29 nov | Experimentos del paper | Ajustes | Demo con el patrocinador (*Por confirmar*) | Resumen ejecutivo (*Por confirmar*) |
| S8 · 30 nov–6 dic | Borrador del paper | Informe de pruebas y README | Documento de requerimientos actualizado | Presentación final (*Por confirmar*) |
| S9 · 7–13 dic | — | — | Imagen 1.0 y release (NDA cl. 8) | Cierre |

---

## 7. Pruebas y métricas

Cinco videos grabados por el equipo sobre un mismo SOP propio (sección 14 del documento), cada paso
anotado a mano antes de programar la comparación. Resuelve la falta de datos narrados (ADR-009).

| Video | Qué se graba | Resultado esperado |
|---|---|---|
| A | Todos los pasos, en orden y en tiempo | ≥ 90 %, verde, sin pasos faltantes |
| B | Omite 2 pasos, agrega 1 | 2 *Falta*, 1 *Sobra*, cada uno con su segundo |
| C | Invierte 2 pasos, otra persona hace 1, un paso tarda el doble | 2 *Fuera de orden*, 1 *Distinto*, 1 *Excede* |
| D | Otro procedimiento | Afinidad < 60 y advertencia |
| E | Sin SOP, narrado en inglés | SOP en español completo |

| RNF | Meta | Cómo |
|---|---|---|
| 01 | 10 min de video en < 5 min | Medido en la PC de referencia (ADR-014); estimado ~4 min |
| 02 | Búsqueda < 1 s con 50 videos | Índice por palabra normalizada en Postgres |
| 03 | Salto con error < ±1 s | Tiempo por palabra de faster-whisper |
| 04 | ≥ 85 % de estados como los asigna una persona | Cascada calibrada con A–D |
| 05 | ≥ 80 % de pasos generados correctos | Video E contra SOP escrito a mano |
| 06 | Nada inventado con confianza alta | La cita se verifica por código en la transcripción |
| 07 | Mismo % en dos corridas | Temperatura 0, semilla 42, versiones fijadas |
| 10 · 15 | Sin claves de API; < USD 0.25 por video | No hay APIs: USD 0 |

---

## 8. Línea académica y paper

- **Avances 3–5:** siguen con `has_errors` sobre CaptainCook4D (ADR-009). El patrocinador pidió
  cumplir con la escuela primero. En el avance 4 se agrega una variante con embeddings MiniLM del texto
  de cada paso, el mismo modelo del producto.
- **Paper (interés del patrocinador):** cascada consciente de la dificultad con modelos pequeños
  locales para validar videos de procedimientos contra su SOP. Compara solo MiniLM + húngaro, solo
  Gemma 4 como juez y la cascada; ablación con y sin fotogramas. Métricas: exactitud por estado,
  % de pares escalados al LLM, segundos por video y VRAM. Base: MiniLM, DAAO, KG-MASD, CRISP-ML(Q).

---

## 9. Riesgos

| Riesgo | Impacto | Prob. | Mitigación |
|---|---|---|---|
| `gemma4:e4b` sobre-segmenta (ADR-010) y genera *Sobra* falsos | Alto | Alta | Fusión previa (ADR-013); cada *Sobra* exige cita; medir con video B |
| Carga de avances y modelos en Emmanuel hasta el 1 nov | Alto | Alta | PDF y SOP generado después del 1 nov; Sara toma pantallas y búsqueda |
| 8 GB de VRAM no alcanzan para dos modelos | Medio | Media | Etapas en secuencia; un modelo cargado a la vez |
| Gemma 4 E4B describe mal los fotogramas | Medio | Media | La voz manda; la imagen solo confirma equipos, EPP y riesgos |
| Angular consume la ruta crítica | Alto | Media | Pantallas sencillas; la API se prueba sola desde `/docs` |
| Ruido o varias voces en el audio | Medio | Media | Guion de grabación, micrófono cerca, VAD; video C con dos personas |
| Solo una PC del equipo tiene GPU | Medio | Media | Sara usa el perfil CPU; Ollama compartido por red privada para pruebas |
| Repositorio público con material bajo NDA | Alto | Por confirmar | Pasarlo a privado en S2 |

---

## 10. Para la junta del lunes 19 oct

**Informar:** opción B local y costo cero; Gemma 4 E4B como LLM y visión (NDA cl. 1); PC propia con GPU
de 8 GB como hardware de referencia; los 5 videos de prueba; el alcance de la sección 5; lo que queda en
versión 2 (diarización, búsqueda semántica, chat que pregunta antes de responder).

**Preguntar (una sola):** fecha de la demo y si basta con red local o necesitan una URL pública para los
QR del PDF. Sin respuesta, la demo corre en red local y los QR apuntan a la IP de la máquina.

**Control de cambios (sección 17 del documento):** registrar ADR-004, 011, 012 y 014 con fecha 19 oct.
