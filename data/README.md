# Datos del proyecto (data card)

> **Regla de oro.** Ningún video, SOP o dato identificable del cliente entra a este repositorio, ni siquiera fragmentos, capturas o transcripciones. El material del cliente se referencia por identificador y su contenido vive exclusivamente en el almacenamiento aprobado por el patrocinador.

El desarrollo y la medición de la columna vertebral se hacen con **datasets públicos** y **datos sintéticos o grabados por el propio equipo**. El material real del cliente se incorpora solo cuando el patrocinador lo libere formalmente (Fase 2), bajo NDA y en el entorno autorizado.

---

## 1. Datasets públicos

| Dataset | Para qué sirve aquí | Enlace / acceso |
|---|---|---|
| Assembly101 | Ensamblaje/desensamblaje, vistas estáticas y egocéntricas, acciones finas. Base del pipeline de pasos. | _[agregar enlace oficial]_ |
| EgoProceL | Videos egocéntricos de las mismas tareas por muchas personas. Banco de pruebas para consolidación multi-video. | arxiv.org/abs/2207.10883 _(verificar)_ |
| CaptainCook4D | Ejecuciones con errores procedurales anotados. **Dataset de los avances académicos 1–5** (`has_errors`, ADR-009). | Paper: arxiv.org/abs/2312.14556 · Anotaciones: github.com/CaptainCook4D/annotations (MIT) |
| OpenPack | Procesos de empaquetado en logística, multimodal. Cercano al dominio industrial. | _[agregar enlace oficial]_ |

> Los datasets **no se versionan** en el repo (son pesados). Aquí solo se documenta su origen, estructura y forma de descarga; cada quien los baja localmente a una ruta ignorada por Git.

### 1.1 CaptainCook4D en los avances (cómo se obtiene)

Solo se usan las **anotaciones** (no los videos). `sopvid.features.data` las descarga la primera vez que se ejecuta un avance, desde un *commit* fijo para que los resultados sean reproducibles:

- **Repositorio y commit:** `CaptainCook4D/annotations` @ `a8a920a3293c4db27099a20ddbe3a3a9be1283e3`.
- **Destino local:** `DATA_DIR` del `.env` (por defecto `data/raw/captaincook4d/`, ignorada por Git).
- **Archivos (~5 MB):**
  - `complete_step_annotations.json`: pasos por grabación con inicio, fin y bandera de error.
  - `error_annotations.json`: categorías de error por paso.
  - `video_information.csv`: duración, persona y entorno por video.
  - `recordings_data_split_combined.json`: partición oficial train/val/test por grabación (213 / 62 / 109 grabaciones).
  - `task_graphs/*.json`: grafo de dependencias de cada una de las 24 recetas; se agregó en el avance 2.

Hallazgos de calidad documentados en el avance 1:
- 171 pasos de entrenamiento tienen tiempos −1, que indican un paso omitido.
- 7 grabaciones tienen un `person_id` distinto entre las anotaciones y los metadatos.
- Dos `step_id` aparecen con dos descripciones distintas.

Los notebooks pueden escribir derivados en `data/processed/` o `data/interim/`; ambas carpetas también se ignoran.

## 2. Datos sintéticos / grabados por el equipo

- Descripción de qué se grabó o generó: _[...]_
- Estructura de carpetas y nomenclatura: _[...]_
- Cómo reproducir su generación (script/semilla): _[...]_

## 3. Conjunto de validación (sellado)

Videos con su SOP escrito correspondiente que **nadie mira ni usa para ajustar nada** hasta la evaluación final. Contaminarlo invalida las métricas del proyecto entero.

- Identificadores del conjunto apartado: _[...]_
- Fecha de sellado: _[...]_

## 4. Material del cliente (Fase 2)

- **No entra al repositorio bajo ninguna circunstancia.**
- Se referencia por identificador; el contenido vive en el almacenamiento aprobado por el patrocinador.
- Se incorpora solo cuando el patrocinador lo libere formalmente, bajo NDA firmado por cada integrante y en el entorno definido.

## 5. Privacidad y retención

- En video de planta pueden aparecer rostros de trabajadores: es dato personal conforme a la **Ley Federal de Protección de Datos Personales en Posesión de los Particulares (LFPDPPP)**, con anonimización cuando el caso lo permita.
- Retención y borrado: se documenta cuánto tiempo se conserva cada video y cómo se elimina a solicitud.
- Cifrado en tránsito y en reposo del material sensible, en particular el video.
