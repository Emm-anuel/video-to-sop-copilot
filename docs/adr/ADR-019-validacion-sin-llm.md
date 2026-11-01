# ADR-019 · Validar sin LLM: error reprocesable antes de empezar, reporte provisional a medias

- **Estado:** Aprobado por el equipo
- **Fecha:** 2026-10-27
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

La validación de un video (modo validar) encadena, después de transcribir, dos etapas con Gemma 4
en Ollama: los pasos del video (RF-13, ADR-010) y el juez de la zona gris (ADR-012, punto 3).
Las dos ya degradan sin excepción cuando Ollama no responde:

- `segmentar` cae a la heurística de palabras de transición y pausas (`Segmentacion.metodo =
  "heuristica"`), que sobre- o sub-segmenta más que el LLM.
- `JuezGemma` devuelve un juicio de respaldo `"llm_no_disponible"` y el par queda en
  `zona_gris` ("sin revisar"), que vale 0 en el porcentaje (RF-19, SOP V1.0 §5.6).
- Si responde la llamada de fronteras pero no la de redacción, hay pasos sin redactar: nombre =
  título, cita vacía y confianza baja (`Segmentacion.pasos_sin_redactar`).

El resultado es un reporte completo con un porcentaje bajo y un semáforo rojo que parece un
hallazgo sobre el operador cuando es una falla del sistema. Para el MVP (plan §5.1) el criterio de
A y B depende de la segmentación con el LLM.

La transcripción (Whisper) es la etapa cara en CPU y no depende de Ollama: no debe repetirse por
una caída del LLM.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A · Revisar Ollama antes de segmentar: si no responde, error reprocesable (el análisis queda guardado) y `POST /videos/{id}/validar` repite solo la validación. Si se cae a medias, el reporte se guarda marcado como provisional, con avisos | No hay rojos falsos por una caída al inicio; no se repite Whisper; una caída breve a medias no tira el trabajo, y la pantalla la distingue | Un endpoint más; un reporte provisional puede leerse como definitivo si la pantalla ignora la marca |
| B · Siempre reporte, con avisos | Lo más simple | Rojos engañosos cada vez que Ollama está abajo |
| C · Siempre error si algo usó el respaldo | Nunca hay reporte degradado | Tira trabajo hecho por una caída breve; sin reporte no hay nada que revisar (ADR-008) |

## Decisión

**A.**

1. Después de guardar el `Analisis`, la validación (`sopvid.lenguaje.validacion.validar`) llama
   a `ClienteLLM.disponible()` (plazo `LLM_HEALTH_TIMEOUT_S`). Si Ollama no responde o no tiene el modelo, el video queda en
   `proceso="error"` con un mensaje que lo dice; la transcripción sigue guardada.
2. `POST /videos/{id}/validar` vuelve a encolar solo la validación (segmentar → emparejar →
   reporte), sin Whisper. Acepta videos de modo validar con el análisis guardado y en `error` o
   `listo` (un reporte provisional también se puede repetir); 409 si está en cola o procesando,
   o si no hay análisis (hay que volver a subir el video). El reporte nuevo reemplaza al anterior.
3. Si Ollama falla después de la revisión, el reporte se guarda con `metadatos.avisos`:
   `segmentacion_heuristica` (con el motivo), `juez_sin_revisar` (cuántos pares quedaron en
   zona_gris) o `pasos_sin_redactar` (cuántos pasos sin cita). `ReporteValidacion.provisional`
   es `true` si hay al menos un aviso. La regla del porcentaje no cambia.
4. Al terminar la etapa del LLM, con o sin error, la validación llama a `ClienteLLM.descargar()`
   (`keep_alive: 0`): Ollama suelta el modelo de la memoria (VRAM o RAM) antes del siguiente
   Whisper (ADR-014). No depende de que haya GPU; si Ollama no responde, solo se registra.

## Consecuencias

- **Positivas:** una caída de Ollama al inicio no produce un reporte; reprocesar cuesta solo la
  etapa del LLM; la pantalla marca los reportes provisionales sin leer los avisos.
- **Negativas / riesgos:** la cola vive en memoria (un reinicio deja el video en error, como hoy)
  y el reproceso no guarda historial: el reporte anterior se reemplaza. Descargar el modelo tras
  cada video obliga a una carga en frío en el siguiente (decenas de segundos, `docs/dev/llm.md`).
- **Seguimiento:** medir con los videos C–E cuánto tarda la carga en frío entre videos; si pesa,
  descargar solo antes de un Whisper en GPU.

## Referencias

- ADR-017 (validar en el mismo trabajo que el análisis; este ADR nació como ADR-017 y se renumeró
  al integrar las dos ramas el 1 nov).
- ADR-006 (LLM local), ADR-008 (revisión humana), ADR-010 (pasos del video), ADR-012 (juez de la
  zona gris), ADR-014 (modelos en secuencia); plan §5.1; documento SOP V1.0 §5.6 y RNF-07.
