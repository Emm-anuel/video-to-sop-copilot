# Estado del proyecto · 7 nov 2026

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
| Dom 15 nov | ✓ SOP generado, personas, tiempos y afinidad: pasan los videos C, D y E |
| Dom 22 nov | ✓ App completa en Docker en máquina limpia |

## Resumen en dos frases

> El patrocinador fijó el producto 1.0 (validar videos contra su SOP o generarlo, y buscar al segundo
> exacto) y pidió costo cero, así que todo corre local con Gemma 4 E4B, faster-whisper y MiniLM en una
> GPU de 8 GB. Los avances académicos siguen con `has_errors`, y los experimentos del producto alimentan
> un paper sobre modelos pequeños locales.
