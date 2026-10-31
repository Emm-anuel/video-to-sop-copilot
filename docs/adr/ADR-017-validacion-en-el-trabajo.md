# ADR-017 · Validar en el mismo trabajo que el análisis

- **Estado:** Propuesto
- **Fecha:** 2026-10-31
- **Autores:** _[completar]_
- **Decisores:** equipo

---

## Contexto

El MVP de validación (plan §5.1, hito del 8 nov) necesita que un video y un SOP entren juntos y
salga el reporte: pasos del video (RF-13), emparejamiento (ADR-012, ADR-013), porcentaje y
semáforo (RF-19) y la tabla con cita y segundo (RF-20). Las piezas ya existen, pero la API solo
llegaba hasta `GET /videos/{id}/analisis`: `segmentar` y `emparejar` se llamaban únicamente desde
`scripts/`.

Tres fuerzas mandan aquí:

1. **Un modelo en GPU a la vez (ADR-014).** Whisper y Gemma 4 no caben juntos en 8 GB, así que
   cualquier trabajo que use un modelo tiene que pasar por la cola de un solo trabajador.
2. **La pantalla ya sabe consultar.** Sara integra el reporte contra el patrón existente —202,
   `Location`, `GET /videos/{id}` cada pocos segundos—, no contra uno nuevo.
3. **Sin tiempo para una migración.** Una columna de estado de validación obliga a una migración
   `0003` y a distinguir dos procesos en la misma fila (`análisis` y `validación`), justo en la
   semana del MVP.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A. Endpoint síncrono `POST /videos/{id}/reporte` que segmenta y empareja en la petición | Nada que migrar; el cliente recibe el reporte en la misma llamada | La petición dura minutos (Gemma 4 en frío, juez de la zona gris): un proxy o el navegador la cortan; dos peticiones simultáneas pelean por la GPU porque no pasa por la cola; no hay avance que mostrar |
| B. Segunda cola con estado propio (`videos.validacion` + migración `0003`) | Estados independientes; se puede revalidar sin volver a transcribir | Migración nueva en la semana del MVP; dos estados que mantener y documentar; dos turnos de GPU separados (Ollama carga y descarga dos veces) |
| C. La validación como segunda mitad del trabajo de análisis, cuando el video llegó con `modo="validar"` y su SOP | Cero migraciones (`modo` y `sop_id` ya existen en el modelo de datos de la sección 10, y `reportes` también); un solo turno de GPU; un solo patrón de consulta para la pantalla | Un fallo de validación deja el video en `error`; no hay detalle de avance por etapa; revalidar contra otro SOP exige volver a subir el video |

## Decisión

**Opción C.** `POST /videos` acepta el SOP (archivo `sop` en Markdown o TXT, o un `sop_id` ya
guardado) y crea la fila de `sops` con `guardar_sop`, convirtiendo el texto con código antes de
tocar la GPU. El trabajador de `procesamiento` hace el análisis como siempre y, si el video es de
`modo="validar"`, sigue con `validacion.validar_y_guardar`: pasos del video, emparejamiento y
reporte, guardado en `reportes` (uno por video). La pantalla consulta `GET /videos/{id}` y, cuando
`proceso` es `listo`, pide `GET /videos/{id}/reporte`.

El análisis se confirma en la base **antes** de empezar la validación: si la validación falla, la
transcripción de varios minutos no se pierde y el video queda en `error` con
`falló la etapa validacion (TipoDeExcepción)`, sin texto del video en el mensaje (misma regla que
el resto de `procesamiento`).

## Consecuencias

- **Positivas:** el MVP no necesita migración; la GPU se usa en un solo turno por video; la
  pantalla reutiliza el patrón de consulta que ya existe; el reporte se arma con el mismo
  `porcentaje` y `semaforo` que el diagnóstico de A y B, así que el producto y la medición no
  pueden divergir.
- **Negativas / riesgos:** un error de validación marca el video como `error`, aunque su análisis
  esté bien; el avance de la segunda mitad es grueso (`etapa="validacion"`, 95 %); para validar el
  mismo video contra otro SOP hay que volver a subirlo. El costo de GPU de revalidar incluye
  repetir la transcripción.
- **Seguimiento:** en S5, con la biblioteca (RF-05) y la pantalla de reprocesar, revisar si conviene
  la opción B: un `POST /videos/{id}/validar` que reutilice `videos.transcripcion` y
  `videos.pasos_video` y solo repita emparejamiento y reporte. `validacion.validar_y_guardar` ya
  está separada de la cola para que ese camino no obligue a tocar el análisis.

## Referencias

- Plan §5.1 (MVP de validación) y §5.3 (emparejamiento)
- ADR-010 (pasos del video), ADR-012 (cascada), ADR-013 (fusión), ADR-014 (un modelo a la vez),
  ADR-015 (SOP con plantilla), ADR-016 (marco del operador)
- `docs/dev/api.md` · `src/sopvid/plataforma/validacion.py` · `src/sopvid/lenguaje/reporte.py`

