# Estado del proyecto · 13 nov 2026

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

## Semana 5 (9–15 nov) · cierre del 13 nov

**Qué entró** (ramas `feat/s5`, unida a `main` en `0b2b20f`, y `feat/s5-pantallas`):

| RF | Qué | Commits |
|---|---|---|
| RF-01, 02 | SOP en PDF y Word, también adjunto a `POST /videos`; si no sigue la plantilla, Gemma lo convierte con una cita verificada por paso (asíncrono: 202 y `GET /sops/{id}/estado`) | `be4dac3`, `c10081d`, `e23d937` (ADR-015) |
| RF-04 | Revisar y corregir el SOP convertido con el mismo editor del SOP generado | `cd84a4b` (ADR-025) |
| RF-05 | Biblioteca: `GET /sops`, `DELETE /sops/{id}` (409 explicado si un video lo usa) y pantalla `/sops` | `6dc072a` |
| RF-06 | Subida por partes de 16 MB con reintentos y reanudación; AVI se acepta y se analiza (el navegador no lo reproduce: el reporte lo dice y ofrece descargarlo) | `55c2a9b` |
| RF-07 | Elegir el SOP de la biblioteca en `/nuevo`, con la casilla de imágenes y la estimación antes de subir | `6dc072a` |
| RF-08 | Pantalla Procesando: etapas según el modo, TXT en vivo, imágenes hechas, paso al resultado | `6c2c35d` |
| RF-11 | Miniatura por paso siempre (ffmpeg, sin modelo); descripción de imágenes con Gemma opcional y apagada | `0663985` (ADR-024) |
| RF-12 | Ficha de contexto con cita verificada por dato y por persona | `2111076`, `b3d6aeb` |
| RF-15, 17 | Personas y roles; afinidad de contexto, que detiene la validación si es < 60 (`?continuar=true` sigue) | `3c83a7d`, `5da40b8`, `5e97dc8`, `10172ba`, `430df47` (ADR-020) |
| RF-16 | Tiempo por paso (narrado o medido), total y horario | `070bcff`, `c369436`, `ddc18ff` (ADR-021) |
| RF-22 a 25, 27 | SOP generado desde el video, en español, con cuadro resumen, puntos y palabras clave con menciones, evidencia por dato, biblioteca y uso como referencia | `f3486de`, `2e5d5bb`, `fcca51e`, `95d7d40`, `57ddf5a`, `dab4132` (ADR-023) |
| RF-26 | Editor del SOP generado: unir con el siguiente paso, reordenar y quitar con deshacer | `cd84a4b` (ADR-025) |

Además: el rescate de un *Falta* entre *Sobra* contiguos y la segmentación guardada para que
repetir la validación dé el mismo porcentaje (`a9ff756`, `4ea732f`; ADR-022, RNF-07). Issues
cerrados: #7 (RF-05), #8 (RF-07), #9 (RF-08) y #10 (RF-06).

**Recorrido completo desde la pantalla (12–13 nov, sin Swagger ni scripts;
[capturas](../adr/datos/s5/pantallas/)).** Biblioteca → SOP del filtro en Word → editor → A, C, D y
E por partes → editor de E → biblioteca → validar E; C sin GPU; corte de red; AVI. Todo el camino
se pudo hacer desde la pantalla. Lo que salió mal:

| Dónde | Qué pasó | Qué se hizo |
|---|---|---|
| Imágenes prendidas | Las descripciones **inventan objetos** que llegan a la ficha y al SOP generado sin cita (RNF-06): "equipo de flujo" en 8 de 8 descripciones de E·1 y en el SOP 9298, "brazo mecánico" en 2 de 6 de C (es el brazo del operador) | ADR-024 (resultado medido), #16 |
| E·1 con imágenes | Falló la §14 por `sin_traducir` ("housing grant", "bol") y trajo "supervisor SNP" como equipo. **No es de las imágenes:** sale de la narración mal transcrita por Whisper; E·2, con imágenes, salió limpio y sin imágenes E pasa 6/6. En el primer cierre lo atribuí a las imágenes por error | #11 |
| C sin GPU | Nuevo estimó "+64 s" de imágenes y la etapa tardó 108.5 s (18.1 s por imagen contra 10.7). Con GPU, 14.6 s contra 7 estimados. Procesando se queda en "0 de 6 imágenes" toda la etapa (un solo lote) | #17 |
| Nuevo sin GPU | Solo avisa del tiempo de las imágenes; C tardó 7.0 min de punta a punta y nada lo anticipa | #19 |
| Corte de red al registrar | La pantalla dijo "¿está corriendo en el puerto 8000?" y no reintenta el registro sola; "Reintentar la subida" sí registra sin volver a subir | Mensaje corregido; resto en #19 |
| Reintentos de la subida | Cubren ~12 s de corte; un corte de 30 s acaba en el botón manual (que reanuda bien desde 16 MB) | #19 |
| Editor del SOP convertido | Sin datos marcados no hay cómo darlo por revisado: "Guardar cambios" deshabilitado y el aviso "lo convirtió el modelo" no se quita. Gemma recortó artículos en 3 nombres de paso sin advertencia | #18 |
| Biblioteca y `/nuevo` | ~20 SOP con el mismo título; el selector solo muestra código y título | #18 |
| E contra su SOP generado y editado | 83.33 % amarillo (2 *Parcial*): al unir pasos, la cita del video cubre una de 3–4 acciones. Además hay que subir el video otra vez | Comentado en #11 y #12 |
| Procesando de E | Una vez se quedó 48 s en "Redacción de los pasos" sin mostrar resumen ni claves; no se reprodujo en dos repeticiones (la API publicó cada etapa a tiempo) | Anotado en #17 |
| Reporte | "Cuánto tardó" no suma `afinidad` (donde se carga MiniLM), `personas` ni `tiempos`: el primer video tras arrancar dijo 38.2 s y fueron 57. La medición de RNF-01 tampoco tenía esa carga (se corrigió en el informe) | #20 |

**Resultado A–E (13 nov, `scripts/medir_s5.py`, imágenes apagadas;
[informe](../adr/datos/s5/medicion-s5-20261113-0021.md)).** Tres tandas intercaladas (A → B → C → D
→ E) con la GPU enfriada a ≤ 50 °C entre tandas, para no castigar a los últimos videos por el
calor (la caída de ~25 % tras ~15 min que se vio en PS1).

| Video | Criterio (§14) | GPU |
|---|---|---|
| A | ≥ 90 % en verde, sin *Falta*, afinidad ≥ 60, sin *distinto* ni *excede* | **PASA 3/3** (100 % las tres) |
| B | *Falta* 2 y 6, la limpieza como *Sobra*, 66.67 % | **PASA 3/3** |
| C | *Fuera de orden* 2 y 5, *distinto* 4, *excede* 1, afinidad ≥ 60 | **PASA 3/3** (75 %) |
| D | Afinidad < 60, se detiene antes de segmentar; al continuar, 6 *Falta* | **PASA 3/3** |
| E | Inglés → SOP en español completo, sin valores sin traducir, RNF-05 ≥ 80 % | **PASA 2/2** (RNF-05 15/15) |

RNF-07: A·1 regenerado con su segmentación sale en 100 % las dos veces, con la misma huella. MVP
sin regresión ([`mvp-20261113-0019`](../adr/datos/mvp/mvp-20261113-0019.md)): A 3/3 al 100 % y B
3/3 con *Falta* 2 y 6.

**Tiempos (RNF-01: 10 min de video en menos de 5 min).**

| | Validar (A–D) | Generar (E) | 10 min estimados (peor caso) | RNF-01 |
|---|---|---|---|---|
| Con GPU (RTX 2070 SUPER), 13 nov | 25–44 s por video de 2–3.5 min (factor 0.17–0.24) | 68.5–71.6 s (factor 0.31) | 3.2 min | **se cumple** |
| Sin GPU (`LLM_DISPOSITIVO=cpu`, Whisper int8) | C con imágenes desde la pantalla, 12 nov: 422 s (factor 2.1); A el 10 nov: 206 s (factor 1.53) | E el 10 nov: 483 s (factor 2.12) | ~21 min | **no se cumple** |

Con la GPU fría, E tarda 68.5–71.6 s, contra 81–83 s cuando se medía al final de una tanda larga.
**Esos números tienen MiniLM ya cargado.** El primer video después de arrancar la API (siempre, en
una máquina limpia) paga ~17 s más: con esa carga, el peor caso con GPU es **3.4–3.9 min** para
10 min y RNF-01 se sigue cumpliendo (corrección en el informe; el conteo de la pantalla, #20). La
corrida sin GPU de C (422 s) ya la incluye.

**Riesgos**

1. **RNF-01 sin GPU no se cumple** (~21 min estimados para 10 min) y la pantalla no lo anticipa
   (#19). Sigue pendiente acordar con el asesor y el patrocinador que RNF-01 se mide con GPU.
2. **Las imágenes prendidas no aportan y además inventan** objetos que llegan al SOP generado (RNF-06,
   ADR-024, #16); su estimación se queda corta (#17). Siguen apagadas por defecto y **la demo del modo
   generar va sin imágenes** (decisión del 13 nov).
3. **El resultado depende de la corrida.** Gemma no es determinista: el mismo A dio 100 % por MP4 y
   91.67 % por AVI en el recorrido (segmentación nueva). Para la demo, procesar antes y mostrar lo
   guardado.
4. **La ida y vuelta generar → editar → validar no da verde** (E: 83.33 %) y obliga a subir el video
   otra vez (#11, #12).

**Decisiones de la semana**

- [ADR-020](../adr/ADR-020-afinidad-personas-minilm.md): afinidad y personas solo con MiniLM y
  código; la afinidad baja detiene antes de segmentar.
- [ADR-021](../adr/ADR-021-tiempos.md): la duración narrada gana siempre; si no, la medida hasta el
  inicio del siguiente paso del video; ±`TOLERANCIA_TIEMPO`.
- [ADR-022](../adr/ADR-022-rescate-de-falta.md): rescate de *Falta* (siempre con el juez) y
  segmentación guardada para RNF-07.
- [ADR-023](../adr/ADR-023-sop-generado.md): Gemma agrupa los pasos del video eligiendo números y
  solo redacta; el código pone tiempos, fuentes, confianza y evidencia.
- [ADR-024](../adr/ADR-024-imagenes-opcionales-miniatura.md): miniatura siempre con ffmpeg;
  descripción de imágenes opcional, apagada y sin bloquear por falta de GPU. Resultado medido en el
  recorrido: las descripciones no aportan y además inventan (RNF-06).
- **13 nov: la demo del modo generar va sin imágenes** ([registro de decisiones](plan.md#registro-de-decisiones)).
- [ADR-025](../adr/ADR-025-sop-revisado-por-persona.md): `revisado` por dato y por paso; al editar
  se conserva la duración narrada.
- Reparto del 10 nov: Emmanuel toma RF-04, 05, 06 (partes), 07, 08, 11 y 26; Sara conserva la
  búsqueda (RF-32 a 37) y las descargas (RF-31) en S6
  ([registro de decisiones](plan.md#registro-de-decisiones)).

**Pasa a S6**

- Pantalla `/videos`: la lista de videos, para volver a un reporte sin saber su URL (pantalla 6).
- Issue #11: la cita en otro idioma y los errores de Whisper hunden el coseno (prioridad alta).
- PDF del reporte y del SOP con QR (RF-29, 30).
- Descargas TXT, SRT y JSON (RF-31, Sara).
- Búsqueda exacta (RF-32 a 37, Sara).
- Docker en máquina limpia.
- Guardar los juicios del juez para que el reporte regenerado salga idéntico (hoy coincide el
  porcentaje, no siempre la redacción).
- Del recorrido: #20 ("Cuánto tardó" sin la carga de MiniLM), #16 (imágenes que inventan), #17 (contador y estimación de imágenes), #18
  (revisar el SOP convertido sin editar), #19 (aviso sin GPU y reanudar al volver la red), #12
  (validar contra el SOP generado sin volver a subir) y el remux de AVI a MP4.

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
- **Pendiente:** confirmar el CI tras el merge, grabar C–E
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
| S2 | ✓ `feat/llm-spike` fusionada a `main` (merge `936af6f`); tablas `videos`, `sops`, `reportes`; grabar videos A–E |
| Dom 25 oct | Avance 4 |
| Dom 1 nov | ✓ Avance 5 |
| Dom 8 nov | **MVP de validación**: video + SOP en Markdown → reporte con segundo; pasan los videos A y B ([plan §5.1](plan.md#51-mvp-de-validación-hito-del-8-nov)). La lógica cumple; falta la pantalla del reporte (RF-20) |
| Dom 15 nov | ✓ SOP generado, personas, tiempos y afinidad: pasan los videos C, D y E (medido el 13 nov con GPU y las pantallas de S5: A–E pasan 14/14) |
| Dom 22 nov | ✓ App completa en Docker en máquina limpia |

## Resumen en dos frases

> El patrocinador fijó el producto 1.0 (validar videos contra su SOP o generarlo, y buscar al segundo
> exacto) y pidió costo cero, así que todo corre local con Gemma 4 E4B, faster-whisper y MiniLM en una
> GPU de 8 GB. Los avances académicos siguen con `has_errors`, y los experimentos del producto alimentan
> un paper sobre modelos pequeños locales.
