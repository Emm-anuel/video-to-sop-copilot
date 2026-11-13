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

**Primer hito: MVP de validación (8 nov).** Un video y un SOP en Markdown entran; sale el reporte de
pasos con su segundo. Solo voz, sin fotogramas, PDF ni búsqueda. Se hace primero porque es lo más
difícil y lo que miden los videos de prueba; el SOP generado y la búsqueda reutilizan lo mismo después
(sección 5.1).

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
| [ADR-015](../adr/ADR-015-sop-plantilla-markdown.md) | SOP de referencia en Markdown/TXT con plantilla y parser por código (RF-03); Gemma 4 solo para texto libre, PDF y Word en S5 | Propuesto (19 oct) |

Los ADR-002, 003 y 008 estaban pendientes de aprobación escrita del patrocinador porque el NDA (cl. 1)
nombra V-JEPA 2, el grafo y el HITL de tres bucles. El documento SOP V1.0, escrito por el patrocinador,
deja esos temas fuera de la versión 1.0; se cita como esa aprobación.

**Modelo de lenguaje.** El NDA (cl. 1) nombra a Gemma 4. `qwen3.5:9b` segmentó mejor en ADR-010, pero
usarlo en el producto requiere aprobación escrita; se mide solo como comparación en los experimentos.

### Registro de decisiones

Decisiones del equipo sin ADR propio, la más reciente arriba. Lo que se decide fuera del
repositorio (juntas, chats, documentos compartidos) se anota aquí el mismo día.

| Fecha | Decisión | Detalle |
|---|---|---|
| 13 nov | La demo del modo generar va sin imágenes | Las descripciones no aportan datos a la ficha y además inventan objetos que llegan al SOP generado sin cita (RNF-06; ADR-024, resultado del recorrido del 12 nov; #16). Decisión de Emmanuel |
| 13 nov | Las mediciones de A–E con GPU se corren en tandas intercaladas con la GPU enfriada a ≤ 50 °C entre tandas | La RTX 2070 SUPER pierde ~25 % de rendimiento tras ~15 min seguidos (PS1): medir video por video castigaba a los últimos (E: 81–83 s contra 68–72 s en frío). `medir_s5.py --informe` junta las tandas (`unir_tandas`) |
| 12 nov | Pendiente para S6: validar un video contra el SOP que se generó desde él sin volver a subirlo | Hoy `POST /videos/{id}/validar` responde 422 con un video de modo generar, así que hay que subirlo otra vez y repetir Whisper. Es fricción del producto, no solo de la prueba de RNF-05 con E. Responsable: Emmanuel |
| 12 nov | Al editar un SOP, la duración total narrada por el operador se conserva | Sin total narrado y con todos los pasos cronometrados, la suma; sin tiempos en los pasos, el que había (ADR-025, ADR-021) |
| 10 nov | El repositorio de desarrollo se mantiene público; el del patrocinador es otro y es privado. Decisión de Emmanuel | Se conserva la cl. 5: nada del cliente entra al repositorio. La propiedad del código sigue siendo del patrocinador (cl. 3.1) |
| 10 nov | Reparto: Emmanuel toma RF-04, 05, 06 (partes), 07, 08, 11 y 26, que estaban a nombre de Sara. Sara conserva la búsqueda (RF-32 a 37) y las descargas (RF-31) en S6 | §5.2 y §6 |
| 10 nov | Fotogramas (RF-11): la miniatura se extrae siempre, con ffmpeg y sin modelo | Se pide por segundo con `GET /videos/{id}/thumb?t=`. No vive en `Fotograma` (su `descripcion` es obligatoria) ni agrega campos a `PasoVideo` o `FilaReporte` |
| 10 nov | Fotogramas (RF-11): la descripción con Gemma 4 es opcional y viene apagada | Apagada, `Analisis.fotogramas` va vacía y la ficha de contexto sigue solo con la voz, como hoy |
| 10 nov | Fotogramas (RF-11): se describen N imágenes repartidas de forma pareja, antes de la ficha de contexto; no una por paso | N = pasos estimados: los del SOP en modo validar, por duración en modo generar; tope de 20 (ADR-002). Una por paso exigiría segmentar antes, y la ficha va primero |
| 10 nov | Fotogramas (RF-11): sin GPU se avisa y no se bloquea | Con la descripción encendida en un equipo sin GPU, Gemma describe igual, más lento, con un aviso; no se salta la descripción (ADR-018: la GPU solo acelera) |

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
| Base | PostgreSQL 16 (imagen pgvector de F0) | Tablas `sops`, `videos`, `reportes`, `palabras`, `busquedas` de la sección 10 del documento, en Postgres con JSONB para SOP, análisis y reporte (ADR-005). Ya creadas: `plataforma/modelos.py`, migración `0002` (21 oct) |
| Archivos | Volumen de medios | Videos, SOP originales, fotogramas, miniaturas, PDF |
| Transcripción | faster-whisper `large-v3-turbo` (GPU, float16); `small` (CPU, int8) | Tiempo por palabra, VAD |
| LLM y visión | Ollama 0.40.2 · `gemma4:e4b-it-q4_K_M` · JSON Schema · temperatura 0 · semilla 42 | Mismo modelo para texto e imágenes |
| Emparejamiento | `paraphrase-multilingual-MiniLM-L12-v2` (CPU) + `scipy.optimize.linear_sum_assignment` | Umbrales en `config`: 0.55 / 0.75; detalle en §5.3 |
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

Sara entrega el análisis del video; Emmanuel lo consume. El contrato es el modelo `Analisis` de
`src/sopvid/contrato.py`; su JSON Schema se exporta a `docs/contrato/analisis.schema.json` con
`python scripts/exportar_contrato.py` (no se edita a mano). Mientras el pipeline no exista, Emmanuel
trabaja con `tests/fixtures/analisis_ejemplo.json` (datos inventados, documentados en
`tests/fixtures/README.md`). Forma resumida:

```json
{
  "version_contrato": 1,
  "video_id": 1,
  "duracion_s": 157.8,
  "idioma": {"codigo": "es", "confianza": 0.98, "fijado_a_mano": false},
  "transcripcion": [
    {"id": 4, "t_inicio": 20.45, "t_fin": 25.54,
     "texto": "Primero me pongo los guantes de nitrilo y los lentes de seguridad.",
     "palabras": [{"w": "Primero", "t": 20.45, "t_fin": 20.96}]}
  ],
  "fotogramas": [
    {"t": 23.0, "archivo": "fotogramas/f01.jpg",
     "descripcion": "Persona con guantes azules y lentes de seguridad frente a un filtro de cartucho montado en la pared.",
     "equipos": ["filtro de cartucho", "manómetro"], "personas": 1, "texto_visible": [], "riesgos": []}
  ]
}
```

Reglas que el pipeline debe cumplir (las valida el modelo): campos extra prohibidos; ids de segmento
estrictamente crecientes y segmentos sin solaparse; tiempos finitos, ≥ 0 y fin ≥ inicio; palabras en
orden; listas vacías como `[]`, nunca `null`. Para comprobar una salida:
`Analisis.model_validate_json(Path(ruta).read_text(encoding="utf-8"))`.

El SOP y el reporte usan los esquemas de la sección 10 del documento SOP V1.0 sin cambios.

---

## 5. Alcance 1.0 (ADR-004)

- **Entran los 29 *Debe*.**
- ***Debería*:** entran RF-04 (corregir SOP convertido), RF-25 (confianza y fuente), RF-31 (TXT, SRT,
  JSON) y RF-37 (filtros). RF-18 (EPP) y RF-21 (falso positivo) solo si hay tiempo en S7.
- ***Podría*:** entran RF-16 (tiempos, lo evalúa el video C) y RF-35 (unir resultados a < 3 s).
  RF-28 (diagrama, glosario) queda fuera.
- **Fuera:** todo lo de la columna derecha de la sección 2 del documento, más diarización (PR-04) y
  búsqueda semántica (PR-08).

### 5.1 MVP de validación (hito del 8 nov)

Validar un video contra un SOP, de punta a punta, solo con la voz. Va primero por tres razones: es lo
más riesgoso (emparejar pasos con Gemma 4 E4B, que sobre-segmenta), es lo que miden los videos A–D y
RNF-04, y es el experimento del paper. Generar el SOP reutiliza los mismos pasos del video y solo
agrega la redacción; la búsqueda exacta no usa IA.

| Entra en el MVP | Después del MVP |
|---|---|
| Subir un video completo (sin partes) | Subida por partes de 16 MB con reintentos (RF-06) |
| SOP en TXT o Markdown escrito por el equipo, convertido al esquema con plantilla y código (RF-03, ADR-015) ✓ | Leer PDF y Word (RF-01), biblioteca (RF-05), corregir la conversión (RF-04) |
| Idioma y transcripción con tiempo por palabra (RF-09, RF-10) | Avance en vivo (RF-08), fotogramas (RF-11) |
| Pasos del video con Gemma 4 sin ver el SOP (RF-13) | Ficha de contexto (RF-12) y afinidad (RF-17) |
| Fusión, cascada y orden: Cumple / Parcial / Falta / Sobra / Fuera de orden (RF-14, ADR-012, ADR-013) | Personas (RF-15) y tiempos (RF-16) |
| Porcentaje y semáforo (RF-19) | PDF del reporte (RF-29) y descargas (RF-31) |
| Una pantalla: tabla del reporte con cita, y el video que salta al segundo (RF-20, Sara). Opcional: `/nuevo` para subir SOP y video (Emmanuel, 7 nov). Detalle en `frontend/README.md` | Las otras pantallas, SOP generado, búsqueda |

**Criterio de terminado:** el video A da ≥ 90 % en verde, sin *Falta*; el video B da 2 *Falta* y
1 *Sobra*, cada uno con su segundo. Medido con el script de métricas, con el commit registrado
(`scripts/medir_mvp.py`, varias repeticiones por video; informes en `docs/adr/datos/mvp/`).

**Orden después del MVP:** (1) SOP generado, sobre los mismos pasos (video E) · (2) personas y tiempos
(video C) · (3) contexto y afinidad (video D) · (4) fotogramas, lectura de PDF y Word, subida por partes
· (5) PDF del reporte y del SOP · (6) búsqueda exacta y el resto de las pantallas.

### 5.2 Responsables por módulo

| Módulo | RF | Responsable | Semana |
|---|---|---|---|
| Ingesta de audio (ffmpeg: duración y mp3) | RF-06 (simple), etapa de ffmpeg | Emmanuel (tomada el 25 oct; hecha) | S2 |
| Subida simple | RF-06 (simple), subida | Emmanuel (tomada el 25 oct; hecha) | S2 |
| Idioma y transcripción | RF-09, 10 | Emmanuel (tomados el 25 oct) | S2 |
| Subida por partes y avance en vivo | ✓ RF-06 (partes de 16 MB, reintentos y AVI; `55c2a9b`, 12 nov) · ✓ RF-08 (`6c2c35d`, 12 nov) | Emmanuel (tomados de Sara el 10 nov) | S5 |
| Fotogramas | ✓ RF-11 (miniatura siempre; descripción opcional, §2 registro de decisiones; `0663985`, 10–11 nov, ADR-024) | Emmanuel (tomado de Sara el 10 nov) | S5 |
| SOP de referencia | ✓ RF-03 (TXT/MD, ADR-015) · ✓ RF-01, 02 (PDF/Word, 7 nov) · ✓ RF-04 (`cd84a4b`), 05 y 07 (`6dc072a`), 11–12 nov (corregir la conversión, biblioteca y elegir un SOP de ella) | Emmanuel · Emmanuel · Emmanuel (tomados de Sara el 10 nov) | S2 · S5 · S5 |
| Pasos del video y contexto | ✓ RF-13 · ✓ RF-12 (7 nov) | Emmanuel | S2–S3 · S5 |
| Validación | ✓ RF-14, 19 · ✓ RF-15, 16, 17 (8–9 nov) | Emmanuel | S3–S4 · S5 |
| Evidencia y revisión | RF-20 · RF-21 | Sara | S3–S4 · S7 |
| Base de Angular y pantalla para subir SOP y video (MVP, opcional) | — | Emmanuel (7 nov) | S4 |
| SOP generado | ✓ RF-22 a 25, 27 (10 nov) · ✓ RF-26 (11 nov: editor con "Unir con el siguiente paso", reordenar y quitar con deshacer; el mismo editor revisa el SOP convertido, RF-04; ADR-025) | Emmanuel · Emmanuel (tomado de Sara el 10 nov) | S5 · S5–S6 |
| PDF y descargas | RF-29, 30 · RF-31 | Emmanuel · Sara | S6 |
| Búsqueda | RF-32 a 37 | Sara | S6 |

### 5.3 Implementación de MiniLM

MiniLM (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 118 M de parámetros, sección 8.1
del documento) convierte cada paso en un vector y mide su parecido con similitud coseno. **Corre en CPU
dentro del contenedor de la API**, no en la GPU: así no compite con faster-whisper ni con Gemma 4 por los
8 GB de VRAM, y con decenas de pasos tarda milisegundos.

**Dónde vive:** `src/sopvid/lenguaje/emparejamiento.py`, detrás de la interfaz `Emparejador`.

| Pieza | Qué hace | Entrada → salida |
|---|---|---|
| `Embedder` | Carga MiniLM una sola vez, en CPU, y vectoriza textos (filas de norma 1) | `list[str]` → matriz `n × 384` float32 |
| `texto_para_embeber(paso)` | Paso del SOP = `nombre + ". " + descripción`; paso del video = `nombre + ". " + descripción + ". " + cita` (ADR-012, 27 oct); las partes vacías se omiten, sin punto doble | paso → `str` |
| `similitud(a, b)` | Coseno entre cada fila de dos matrices de vectores (los de los pasos del SOP y los del video) | matrices `m × d` y `n × d` → matriz `m × n` en [-1, 1] |
| `fusionar(pasos_sop, pasos_video, embedder)` | ADR-013: une pasos consecutivos cuyo mejor paso del SOP es el mismo con parecido ≥ `UMBRAL_FUSION` (0.55) | pasos del video → pasos fusionados + registro `Fusion` |
| `asignar(S)` | Algoritmo húngaro (`scipy.optimize.linear_sum_assignment` con `maximize=True`); en empate, la asignación que respeta el orden | matriz SOP × video → pares (`Par`) y los índices sin pareja |
| `clasificar(asignacion, pasos_sop, pasos_video)` | < 0.55 el par se rompe (*Falta* + *Sobra*) · 0.55–0.75 `zona_gris` (va a Gemma 4) · ≥ 0.75 *Cumple* (la revisión de EPP del punto 4 de ADR-012 queda diferida con RF-18); tiempo y cita del paso del video | asignación → `Clasificacion` (estado por paso + conteo y % de pares al LLM) |
| `orden(clasificacion)` | Cumple, Parcial y zona gris ordenados por `t_inicio`; subsecuencia creciente más larga de `indice_sop` en O(n log n) (en empate, la que deja fuera lo más tardío del video); el resto lleva la marca `fuera_de_orden` (no es un estado) con su posición esperada y observada | `Clasificacion` → `Clasificacion` nueva con el orden revisado |
| `JuezGemma.juzgar(paso_sop, paso_video, similitud, narracion)` | Juez de la zona gris (ADR-012, punto 3; `lenguaje/juez.py`, prompt en `lenguaje/prompts/juez_zona_gris_v1.md`): *Cumple*, *Parcial* o no corresponde, con justificación y cita verificada contra la narración del paso (cortada por palabra); JSON restringido, `SEMILLA`, 3 intentos; sin respuesta válida u Ollama caído, respaldo en `zona_gris` ("sin revisar") | par + narración → `Juicio` |
| `aplicar_juez(clasificacion, pasos_sop, pasos_video, transcripcion, juez)` | Pasa cada `zona_gris` por el juez; "no corresponde" rompe el par en *Falta* + *Sobra*; con Ollama caído deja de llamarlo en esa corrida | `Clasificacion` → `Clasificacion` con `Juicio` y resumen del juez (veredictos y `segundos_juez`) |
| `marcar_marco(clasificacion)` | ADR-016: un *Sobra* que empieza antes del primer paso emparejado o después del último lleva `marco_operador` ("intro" / "cierre"); sigue en el resultado con su cita y su segundo, pero sale de `conteo["Sobra"]` | `Clasificacion` → `Clasificacion` con la marca y `resumen.marco_operador` |
| `emparejar(sop, pasos_video, juez=None, transcripcion=())` | Cascada completa: `fusionar` → similitud sobre los pasos fusionados → `asignar` → `clasificar` → juez (si lo hay) → `orden` → `marcar_marco`; `EmparejadorMiniLM` cumple `Emparejador` | SOP + pasos del video (+ transcripción) → `ResultadoEmparejamiento` (clasificación, fusiones, pasos fusionados) |
| `afinidad(sop, contexto, embedder)` | `lenguaje/afinidad.py` (ADR-020, 8 nov): global, título ~ actividad, objetivo ~ propósito y equipos, sin palabras genéricas y en minúsculas; cada componente a 0–100 con un mapeo lineal (`AFINIDAD_COS_CERO/CIEN`) y promedio ponderado por la evidencia; explicación armada por el código. Bajo `AFINIDAD_MIN` la validación se detiene tras la ficha (`afinidad_baja`) hasta `?continuar=true` | SOP, contexto → `Afinidad` (0–100) o None sin ficha |
| `emparejar_roles(roles, personas, embedder)` y `asignar_responsables(...)` | `lenguaje/personas.py` (ADR-020): roles por núcleo y complemento (`UMBRAL_ROL`, `UMBRAL_ROL_COMPLEMENTO`); responsable de cada par por el responsable del paso, el nombre en la narración o el narrador único; *distinto* solo con una persona distinguible | roles, personas → *Presente / Mencionado / Ausente*; pares → *Coincide / Distinto / No identificado* |

**Dependencias:** `sentence-transformers` con versión exacta en `pyproject.toml` (la conservadora al
agregarla) y `torch` en su build de CPU para no inflar la imagen. `scipy` ya está fijado (1.17.1).
Los pesos (~470 MB) se descargan la primera vez a `EMBEDDER_CACHE_DIR` (por defecto `models/embedder`,
ignorada por Git; en Docker, el volumen `modelos`), no a la imagen.

**Umbrales en configuración** (RNF-14): `UMBRAL_BAJO=0.55`, `UMBRAL_ALTO=0.75`, `UMBRAL_FUSION=0.55`
(ya en `Settings`, con `UMBRAL_BAJO ≤ UMBRAL_ALTO`) y `AFINIDAD_MIN=60`. Se calibran con `scripts/calibrar_umbrales.py` sobre los videos A–D anotados a mano:
elige los valores que maximizan la coincidencia con la anotación y guarda el resultado en
`docs/adr/datos/emparejamiento/`.

**Pruebas** (`tests/test_emparejamiento.py`, con pasos inventados, sin GPU ni Ollama):
pasos idénticos → *Cumple*; un paso omitido → *Falta*; uno agregado → *Sobra*; dos invertidos →
*Fuera de orden*; un paso partido en dos → se fusiona; mismo resultado en dos corridas.

**Uso académico:** en el avance 4 se agrega una variante del modelo `has_errors` con los embeddings
MiniLM del texto de cada paso de CaptainCook4D (plan §8).

---

## 6. Roadmap

| Semana | Emmanuel | Sara | Compartido / checkpoint | Académico |
|---|---|---|---|---|
| S1 · 12–18 oct | Avance 3 | Guion de los videos de prueba | Revisión del documento SOP V1.0 | **Avance 3 (18 oct)** |
| S2 · 19–25 oct | Pasos del video con el esquema extendido de ADR-010; ✓ conversión del SOP en Markdown (ADR-015, 19 oct); ✓ fixture del contrato (18 oct); ✓ **MiniLM:** dependencia, `Embedder` y `similitud` con pruebas (ca82b10, 19 oct); ✓ **ingesta de audio y transcripción**, tomadas de Sara (rama `feat/percepcion-transcripcion`, 25 oct): `medios.py` (duración, mp3 mono 16 kHz) y `transcripcion.py` (RF-09, RF-10: idioma, tiempo por palabra, TXT en vivo); GPU en el host, Docker solo CPU (ADR-014); ✓ **subida simple** (RF-06 del MVP), tomada de Sara (25 oct): `POST /videos`, cola de análisis de un trabajador y consulta de estado, TXT en vivo y `Analisis` | Grabar videos A–E | Junta lun 19 oct; ✓ tablas `videos`, `sops`, `reportes` (y también `palabras`, `busquedas`; migración `0002`, 21 oct); SOP de referencia en Markdown | Avance 4 (25 oct) |
| S3 · 26 oct–1 nov | **MiniLM:** `fusionar`, `asignar` (húngaro), `clasificar` y `orden` con sus pruebas | Pantalla del reporte con reproductor al segundo | Anotación a mano de A–E; script de métricas | Avance 5 (1 nov) |
| S4 · 2–8 nov | ✓ **juez Gemma 4 en la zona gris** (`lenguaje/juez.py`, adelantado al 27 oct; falta medirlo con A y B); porcentaje; **calibrar umbrales MiniLM** con A y B | Pantalla del reporte con la API (RF-20; base de Angular y `/nuevo` por Emmanuel el 7 nov; `GET /videos/{id}/video` listo) | **MVP de validación** (videos A y B; la lógica cumple desde el 27 oct) | — |
| S5 · 9–15 nov | ✓ SOP generado (RF-22 a 25, 27; ADR-023); ✓ **MiniLM:** `afinidad` y `emparejar_roles` (RF-15, 17; ADR-020); ✓ tiempos (RF-16, ADR-021); ✓ contexto (RF-12); ✓ PDF y Word (RF-01, 02); ✓ rescate de *Falta* y segmentación guardada (ADR-022); ✓ editor del SOP (RF-26) y revisión del SOP convertido (RF-04), ADR-025 (11–12 nov); **tomados de Sara (10 nov), todos hechos:** ✓ fotogramas (RF-11, `0663985`, ADR-024), ✓ subida por partes y AVI (RF-06, `55c2a9b`), ✓ avance en vivo (RF-08, `6c2c35d`), ✓ biblioteca y elegir el SOP (RF-05, 07, `6dc072a`), ✓ corregir el SOP convertido y editor del SOP generado (RF-04, 26, `cd84a4b`) | — (sus tareas de S5 pasan a Emmanuel el 10 nov; §2) | ✓ Videos C, D y E grabados; ✓ **medición de cierre (10 nov, [informe](../adr/datos/s5/medicion-s5-20261110-1311.md)):** con GPU A–E pasan la §14 en 14/14 corridas y RNF-01 se cumple (3.0 min estimados para 10 min); sin GPU, A pasa, E falla por un valor sin traducir y RNF-01 no se cumple (21.2 min); ✓ **recorrido completo desde la pantalla (12–13 nov, [capturas](../adr/datos/s5/pantallas/))**: todo el camino se hace sin salir de la pantalla; salieron #16 a #19; ✓ **medición del cierre con las pantallas (13 nov, [informe](../adr/datos/s5/medicion-s5-20261113-0021.md))**: tres tandas intercaladas con la GPU enfriada, A–E 14/14 con GPU, RNF-01 3.2 min estimados para 10 min (3.4–3.9 min con la carga de MiniLM del primer video tras arrancar); MVP sin regresión | — |
| S6 · 16–22 nov | PDF del reporte y del SOP con QR (RF-29, 30); pantalla `/videos` (lista de videos); #11 (cita en otro idioma y coseno, prioridad alta); guardar los juicios del juez; validar el mismo video contra el SOP generado desde él sin volver a subirlo (#12); del recorrido del 12 nov: #20 ("Cuánto tardó" sin la carga de MiniLM), #16 (las imágenes inventan), #17 (contador y estimación de imágenes), #18 (marcar revisado el SOP convertido), #19 (aviso sin GPU y reanudar la subida) y el remux de AVI a MP4 | Búsqueda exacta (tablas `palabras` y `busquedas` ya existen desde S2: solo falta la lógica de publicar y buscar) y su pantalla `/buscar`; descargas TXT, SRT y JSON (RF-31) | ✓ **App completa**; Docker en máquina limpia; RNF-01 a 07; video de demo | — |
| S7 · 23–29 nov | Experimentos del paper; si da tiempo RF-18 | Ajustes; si da tiempo RF-21 | Demo con el patrocinador (*Por confirmar*) | Resumen ejecutivo (*Por confirmar*) |
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

**Guion del video C:** las dos inversiones son **dos pares separados**, los pasos 2↔3 y 5↔6, no dos
pasos sueltos. `orden` marca un paso por cada par invertido (el que llega tarde, según la subsecuencia
creciente más larga de ADR-012), así que dos pares separados dan los 2 *Fuera de orden* que pide la
sección 14 del documento. Un solo par invertido daría 1. Lo cubren las pruebas del video C reducido
en `tests/test_emparejamiento.py`, incluida la de MiniLM real (`-m lento`).

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

**Orden de las mediciones (11 nov, ADR-024; aplicar en PS6).** Medir A–E de corrido castiga a los
últimos por el calentamiento de la GPU y no por el código: tras ~15 min seguidos, Gemma bajó de
~114 a ~87 tokens/s y E pasó de 69–71 s a 81–83 s con el mismo código. Intercalar las corridas
(A, B, C, D, E, A, B…) o dejar enfriar entre tandas, y anotar la temperatura de la GPU al empezar
y al terminar (`nvidia-smi --query-gpu=temperature.gpu,clocks.sm`).

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
| Carga de avances y modelos en Emmanuel hasta el 1 nov | Alto | Alta | PDF y SOP generado después del 1 nov. Desde el 10 nov la carga se invierte: Emmanuel toma RF-04 a 08, 11 y 26 y Sara se queda con la búsqueda y las descargas (§2, registro de decisiones) |
| 8 GB de VRAM no alcanzan para dos modelos | Medio | Media | Etapas en secuencia; un modelo cargado a la vez |
| Gemma 4 E4B describe mal los fotogramas | Medio | Media | La voz manda; la imagen solo confirma equipos, EPP y riesgos |
| Angular consume la ruta crítica | Alto | Media | Pantallas sencillas; la API se prueba sola desde `/docs` |
| Ruido o varias voces en el audio | Medio | Media | Guion de grabación, micrófono cerca, VAD; video C con dos personas |
| Whisper corta segmentos a media frase y las fronteras de paso de ADR-010 (que el LLM elige entre segmentos) quedan desplazadas o mezclan dos pasos | Alto | Ocurrió (26 oct) | Con habla real (videos A y B) Whisper juntó intro y pasos 1–2 en un segmento de 35 s y marcó pausas de 4–7 s solo con coma. Mitigado con `resegmentar` (frases y pausas ≥ 1.5 s con los tiempos por palabra, antes de segmentar): F1 de inicios a ±2 s de 0.46 → 0.67 en A y 0.40 → 0.91 en B, sin inicios perdidos (`docs/dev/transcripcion.md`). Queda la sobre-segmentación de Gemma 4 en A (fila de ADR-010) |
| Solo una PC del equipo tiene GPU | Medio | Media | Sara usa el perfil CPU; Ollama compartido por red privada para pruebas |
| Repositorio público con material bajo NDA | Alto | Por confirmar | El repositorio de desarrollo se queda público (10 nov, §2); el del patrocinador es privado. Nada del cliente entra (regla 1 de CLAUDE.md) y los issues, commits y PR citan la sección del documento del patrocinador en lugar de copiarla |

---

## 10. Para la junta del lunes 19 oct

**Informar:** el MVP de validación para el 8 nov (sección 5.1); opción B local y costo cero; Gemma 4 E4B como LLM y visión (NDA cl. 1); PC propia con GPU
de 8 GB como hardware de referencia; los 5 videos de prueba; el alcance de la sección 5; lo que queda en
versión 2 (diarización, búsqueda semántica, chat que pregunta antes de responder).

**Preguntar (una sola):** fecha de la demo y si basta con red local o necesitan una URL pública para los
QR del PDF. Sin respuesta, la demo corre en red local y los QR apuntan a la IP de la máquina.

**Control de cambios (sección 17 del documento):** registrar ADR-004, 011, 012 y 014 con fecha 19 oct.

> **Nota para la fila del 22 oct:** el video C (sección 14) se graba con dos inversiones separadas
> (pasos 2↔3 y 5↔6). El resultado esperado sigue igual (2 *Fuera de orden*) y no cambia `orden`: cada
> par invertido marca un solo paso, el que llega tarde (ADR-012). *Fuera de orden* es una marca sobre
> el paso y no un estado, así que un paso puede ser *Cumple* y estar fuera de orden a la vez.
