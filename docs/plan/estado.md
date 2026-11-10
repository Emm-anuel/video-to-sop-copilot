# Estado del proyecto · 10 nov 2026

Resumen para el equipo y el asesor. El plan completo está en [plan.md](plan.md).

## Qué cambió esta semana

- **13 oct:** el patrocinador pidió seguir con la arquitectura propia y llevarla hacia modelos pequeños.
- **16 oct, junta con el patrocinador:** entregó el documento **"Requerimientos técnicos y funcionales
  de proyecto SOP V1.0"** (37 requerimientos) y fijó **costo cero**: nada de servicios de pago, ni con
  dinero del equipo ni de la empresa. Todo el producto será local en el servidor del cliente. Le
  interesa publicar un paper con los resultados de los modelos pequeños. Pidió priorizar la
  calificación y seguir los entregables de Canvas.
- **17 oct:** se reescribió el plan para la versión 1.0 del documento (validar video contra SOP,
  generar SOP y búsqueda exacta). Decisiones en [plan.md §2](plan.md#2-decisiones).

## Semana 5 (9–15 nov)

**Qué entró** (rama `feat/s5`):

| RF | Qué | Dónde |
|---|---|---|
| RF-01, 02 | SOP en PDF y Word, también adjunto a `POST /videos`; si no sigue la plantilla, Gemma lo convierte con una cita verificada por paso (asíncrono: 202 y `GET /sops/{id}/estado`) | `lenguaje/lectura_sop.py`, ADR-015 |
| RF-12 | Ficha de contexto con cita verificada por dato y por persona | `percepcion/contexto.py` |
| RF-15, 17 | Personas y roles; afinidad de contexto, que detiene la validación si es < 60 (`?continuar=true` sigue) | `lenguaje/personas.py`, `lenguaje/afinidad.py`, ADR-020 |
| RF-16 | Tiempo por paso (narrado o medido), total y horario | `lenguaje/tiempos.py`, ADR-021 |
| RF-22 a 25, 27 | SOP generado desde el video, en español, con cuadro resumen, puntos y palabras clave con menciones, evidencia por dato, biblioteca y uso como referencia | `lenguaje/sop_generado.py`, ADR-023 |
| RF-26 (parcial) | Solo el endpoint de edición; falta el editor con "Unir con el siguiente paso" | API |

Además: el rescate de un *Falta* entre *Sobra* contiguos y la segmentación guardada para que
repetir la validación dé el mismo porcentaje (ADR-022, RNF-07); la pantalla "No tengo SOP" y la
vista del SOP generado (`0c2f470`).

**Resultado A–E (10 nov, `scripts/medir_s5.py`;
[informe](../adr/datos/s5/medicion-s5-20261110-1311.md)).** Cada corrida es de punta a punta y con
segmentación nueva, en el commit `dab4132`.

| Video | Criterio (§14) | GPU | Sin GPU |
|---|---|---|---|
| A | ≥ 90 % en verde, sin *Falta*, afinidad ≥ 60, sin *distinto* ni *excede* | **PASA 3/3** (100 / 100 / 91.67 %) | PASA 1/1 (100 %) |
| B | *Falta* 2 y 6, la limpieza como *Sobra* (74.1 s), 66.67 % | **PASA 3/3** | — |
| C | *Fuera de orden* 2 y 5, *distinto* 4, *excede* 1, afinidad ≥ 60 | **PASA 3/3** (75 %, afinidad 97, sin el *Sobra* de "compañera") | — |
| D | Afinidad < 60, se detiene antes de segmentar; al continuar, 6 *Falta* | **PASA 3/3** (afinidad 18–20) | — |
| E | Inglés → SOP en español completo, sin valores sin traducir, RNF-05 ≥ 80 % | **PASA 2/2** (RNF-05 100 %, 15 pasos) | FALLA 0/1 (un valor sin traducir; RNF-05 85.7 %, 7 pasos) |

RNF-07: al regenerar A con su segmentación guardada, el porcentaje sale igual (100 % las tres
veces). El rescate de ADR-022 no se activó en ninguna corrida.

**Tiempos (RNF-01: 10 min de video en menos de 5 min).**

| | Validar (A–D) | Generar (E) | 10 min estimados (peor caso) | RNF-01 |
|---|---|---|---|---|
| Con GPU (RTX 2070 SUPER) | 27–42 s por video de 2–3.5 min (factor 0.17–0.25) | 68–69 s (factor 0.30) | 3.0 min | **se cumple** |
| Sin GPU (`LLM_DISPOSITIVO=cpu`, Whisper int8) | A: 206 s (factor 1.53) | E: 483 s (factor 2.12) | 21.2 min | **no se cumple** |

Sin GPU, Gemma va a unos 15 tok/s, contra 100–118 en GPU. Con GPU, la VRAM llega a 6.9 de 8 GB.

**Riesgos**

1. **RNF-01 sin GPU no se cumple** (15–21 min estimados). Hay que acordar con el asesor y el
   patrocinador que RNF-01 se mide con GPU y que, en CPU, el video se procese en segundo plano, o
   bien reducir las llamadas a Gemma.
2. **El resultado depende del dispositivo y de la corrida.** Gemma no es determinista y, en CPU,
   la transcripción cambia la segmentación y el SOP generado (E: 7 pasos contra 15 y un valor sin
   traducir). Para la demo conviene procesar antes y mostrar lo guardado.
3. **El SOP generado sale con ~15 pasos para 6 reales y 16 elementos de equipo para 7.** Se
   necesita el editor de RF-26 antes de guardarlo en la biblioteca. Además, A sigue con 5 a 8
   *Sobra* falsos por corrida (ADR-013) y la VRAM queda al 86 %.

**Decisiones de la semana**

- [ADR-020](../adr/ADR-020-afinidad-personas-minilm.md): afinidad y personas solo con MiniLM y
  código; la afinidad baja detiene antes de segmentar.
- [ADR-021](../adr/ADR-021-tiempos.md): la duración narrada gana siempre; si no, la medida hasta el
  inicio del siguiente paso del video; ±`TOLERANCIA_TIEMPO`.
- [ADR-022](../adr/ADR-022-rescate-de-falta.md): rescate de *Falta* (siempre con el juez) y
  segmentación guardada para RNF-07.
- [ADR-023](../adr/ADR-023-sop-generado.md): Gemma agrupa los pasos del video eligiendo números
  (v2, sin candado) y solo redacta; el código pone tiempos, fuentes, confianza y evidencia. RNF-05
  se mide por tramos, como lo dice el documento.

**Pendiente para S6**

- PDF del reporte y del SOP con QR (RF-29, 30) y descargas TXT, SRT y JSON (RF-31).
- Búsqueda exacta (RF-32 a 37).
- Docker en máquina limpia.
- Fotogramas en la ficha de contexto (P2.1), cuando Sara entregue RF-11.
- Editor RF-26 con "Unir con el siguiente paso" (el SOP generado sale con ~15 pasos para 6 reales).
- Guardar los juicios del juez para que el reporte regenerado salga idéntico (hoy coincide el
  porcentaje, no siempre la redacción).
- El rendimiento en CPU (RNF-01 sin GPU).
- Regrabar E más despacio si los errores de transcripción en inglés siguen afectando el SOP.

## 7 de noviembre (MVP el domingo 8)

- **La lógica del MVP cumple; falta lo que se ve.** Por la API, A da 100 % en verde sin *Falta* y B
  da 2 *Falta* (pasos 2 y 6) y 1 *Sobra* (limpiar la carcasa). También pasa sin GPU.
- **Pantallas del MVP** (detalle en [`frontend/README.md`](../../frontend/README.md)):
  - `/videos/:id/reporte` · **reporte con el video que salta al segundo (RF-20) · Sara.** Es la
    única obligatoria. Al 7 nov no se ha empezado.
  - `/nuevo` · **subir SOP y video · Emmanuel**, opcional. Emmanuel crea también la base del
    proyecto Angular y un reporte provisional que Sara reemplaza. Sara: `git pull` antes de empezar y
    no generes otro proyecto.
- **`GET /videos/{id}/video`** (7 nov, `a40b124`): entrega el video con `Range` (206) para el
  reproductor.
- **CPU de base (ADR-018, 1 nov):** el compose ya no exige GPU. Medido el 27 oct: con GPU, 24–56 s
  por video de ~2 min (cumple RNF-01); sin GPU, 159–223 s (12–16.5 min estimados para 10 min, no
  cumple). Se lleva al asesor y al patrocinador.
- **Gemma no es determinista:** con temperatura 0 y semilla fija, 1 de 3 corridas mueve una
  frontera (A repetido: 100 / 83.3 / 100 %). Para la demo, procesar A y B antes y mostrar los
  reportes guardados.
- **Ramas unidas (1 nov, `58a31ac`):** la validación se implementó dos veces en paralelo; quedó la de
  `143a06f`. "Validar sin LLM" pasó de ADR-017 a ADR-019. Lección: tomar el issue antes de empezar.
- **Medición del MVP con repeticiones (`scripts/medir_mvp.py`, 7 nov):** Whisper una vez por
  video y la validación 3 veces, con el commit registrado
  ([`docs/adr/datos/mvp/mvp-20261107-1113.md`](../adr/datos/mvp/mvp-20261107-1113.md)). **B pasa
  3/3** (2 *Falta*, la limpieza como *Sobra*, 66.7 % rojo). **A pasa 2/3**: 91.7 % y 100 % en verde;
  en la otra corrida Gemma dejó un paso sin redactar, el paso 6 salió *Falta* y el reporte quedó
  provisional (83.3 %, amarillo). A trae 4–6 *Sobra* falsos en cada corrida (absorción de
  ADR-013). Para la demo, mostrar reportes ya procesados.
- **Pendiente:** repositorio privado (NDA) antes del push, confirmar el CI tras el merge, grabar C–E
  (checkpoint del 15 nov) y correr `scripts/calibrar_umbrales.py` con ellos.

## 31 de octubre

- **Validación y reporte, de punta a punta.** `POST /sops` guarda el SOP y `POST /videos` con su
  `sop_id` sigue, en el mismo trabajo del análisis, hasta `reportes`; `GET /videos/{id}/reporte`
  entrega porcentaje, semáforo y una fila por paso con su cita y su segundo (ADR-017). Si Ollama
  estaba caído, `POST /videos/{id}/validar` repite solo la validación, sin Whisper (ADR-019). Es
  el camino del MVP del 8 de noviembre.
- **`scripts/calibrar_umbrales.py`**, que el plan §5.3 daba por hecho y no existía: prueba la rejilla
  de umbrales con la anotación a mano y deja el informe en `docs/adr/datos/emparejamiento/`.
- **Avance 5 generado y ejecutado** (`docs/entregables/Semana 7/Avance5.51.ipynb`): diez ensambles de
  las tres familias. **Ninguno supera al individual del avance 4 por más que la variación entre
  pliegues**; el *voting* de los tres individuales gana +0.013 (4 de 5 pliegues) y la regla fijada
  antes de mirar la tabla no lo considera suficiente, así que el modelo final sigue siendo la SVM.
  El hallazgo útil es otro: la SVM, al pasar de su umbral de F2 a su umbral de costo, baja el recall
  en validación de 0.799 a 0.707, porque su calibración (Brier 0.213) es peor que la del *voting*
  (0.177): el umbral del *voting* transfiere mejor. La recomendación para el producto queda en 10.2.

## Lo que ya está hecho

**Académico**
- Avances 1 y 2 entregados (`has_errors` sobre CaptainCook4D; `build_features` listo para el avance 3).

**Repositorio**
- **`main`:** F0 (API con `/health`, Postgres 16 con pgvector vía Alembic, Docker, tests, CI) y
  `sopvid.features`.
- **`feat/llm-spike` (fusionada en `main`, merge `936af6f`):** cliente del LLM, Ollama 0.40.2 en Docker, benchmark de modelos
  (ADR-006) y prototipo de segmentación por segmentos numerados (ADR-010). Ambos se reutilizan en 1.0:
  el cliente para todas las tareas de Gemma 4 y la segmentación para extraer los pasos del video (RF-13).

**Hardware de referencia (ADR-014):** PC de Emmanuel con RTX 2070 SUPER de 8 GB, i7-10700K, 32 GB de
RAM, SSD con ~199 GB libres, Windows 11, WSL2 y Docker 29.8.

## Lo que falta

| Cuándo | Qué |
|---|---|
| **Dom 18 oct, 23:59** | **Avance 3** (baseline) desde `build_features` |
| Lun 19 oct | Junta con Jorge: informar decisiones y preguntar la fecha de la demo ([plan §10](plan.md#10-para-la-junta-del-lunes-19-oct)) |
| S2 | ✓ `feat/llm-spike` fusionada a `main` (merge `936af6f`); repo privado; tablas `videos`, `sops`, `reportes`; grabar videos A–E |
| Dom 25 oct | Avance 4 |
| Dom 1 nov | ✓ Avance 5 |
| Dom 8 nov | **MVP de validación**: video + SOP en Markdown → reporte con segundo; pasan los videos A y B ([plan §5.1](plan.md#51-mvp-de-validación-hito-del-8-nov)). La lógica cumple; falta la pantalla del reporte (RF-20) |
| Dom 15 nov | ✓ SOP generado, personas, tiempos y afinidad: pasan los videos C, D y E (medido el 10 nov con GPU: A–E pasan 14/14) |
| Dom 22 nov | ✓ App completa en Docker en máquina limpia |

## Resumen en dos frases

> El patrocinador fijó el producto 1.0 (validar videos contra su SOP o generarlo, y buscar al segundo
> exacto) y pidió costo cero, así que todo corre local con Gemma 4 E4B, faster-whisper y MiniLM en una
> GPU de 8 GB. Los avances académicos siguen con `has_errors`, y los experimentos del producto alimentan
> un paper sobre modelos pequeños locales.
