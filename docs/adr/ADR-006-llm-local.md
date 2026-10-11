# ADR-006 · LLM local servido con Ollama en Docker: Gemma 4 E4B en desarrollo, Gemma 4 mayor en producción si hay GPU de 24 GB

- **Estado:** Propuesto
- **Fecha:** 2026-10-11
- **Autores:** Emmanuel Merida
- **Decisores:** equipo (la variante de producción depende de que el patrocinador confirme la GPU de 24 GB)

---

## Contexto

El MVP usa un LLM para segmentar la narración en pasos ([ADR-010](ADR-010-segmentacion-pasos-llm.md))
y, más adelante, para el chat RAG y el borrador de SOP. Restricciones: costo cero, pesos abiertos
servidos localmente, el NDA nombra a Gemma 4 como base y **el LLM nunca escribe un timestamp**. El
brief propone Gemma 4 26B A4B (~16 GB en 4 bits), que necesita la GPU de 24 GB que el patrocinador
aún no confirma (plan, pregunta 8).

El equipo desarrolla en una **RTX 2070 SUPER de 8 GB** (Turing, compute 7.5; driver 616.92, CUDA 13.4)
que además usa el escritorio de Windows (1.5–1.7 GB ocupados), con i7-10700K y 32 GB de RAM. En
esa GPU no cabe ningún Gemma 4 de 12B o más sin repartirse con la CPU.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| **Servidor:** Ollama en Docker (imagen fijada) | Mismo `docker compose` en todas las máquinas; versión fijada; GPU verificada desde el contenedor | Una capa más; en Windows depende de Docker Desktop + WSL2 |
| **Servidor:** Ollama nativo en Windows | Sin Docker; instalación simple | Versión y configuración por máquina; no reproduce el despliegue |
| **Servidor:** llama.cpp o vLLM directo | Control fino | Más configuración y otra imagen que mantener; Ollama 0.40 ya usa llama.cpp por dentro |
| **Modelo:** `gemma4:e2b-it-q4_K_M` | Cabe holgado (3.2 GB); el más rápido | Segmenta mal: marca cada segmento como paso (F1 0.33) |
| **Modelo:** `gemma4:e4b-it-q4_K_M` | Familia que pide el NDA; cabe completo (4.9 GB); rápido (MTP); buena calidad | Usa ~1 GB de VRAM en el proyector de visión que no usamos |
| **Modelo:** `gemma4:e4b-it-qat` | Menos VRAM que q4_K_M (4.3 GB) | Sin cabeza MTP: 1.5–1.8× más lento al generar; calidad igual o algo menor |
| **Modelo:** `qwen3.5:9b-q4_K_M` | Mejor F1 de segmentación (0.92) | **No cabe**: 31/33 capas en GPU (32/33 con FA), 27–34 tok/s; cortes inestables entre repeticiones; no es la familia del NDA |
| **Modelo:** `qwen3:8b-q4_K_M` | Solo texto; cabe | Caché KV de 1.1 GB; cita un id inexistente en RAG (1–2 de 3); más lento |

## Decisión

**Despliegue (desarrollo y producción): Ollama en Docker** con `ollama/ollama:0.40.2` fijada, bajo el
profile `llm` de `docker-compose.yml` (ver [docs/dev/llm.md](../dev/llm.md)). Ollama nativo queda como
respaldo documentado (`LLM_BASE_URL_API=http://host.docker.internal:11434`). El cliente habla con
`/api/chat` vía httpx y pasa un JSON Schema en `format`; temperatura 0, semilla fija, `think: false`.
No se midió Ollama nativo para comparar: Docker ya cumple (todas las capas en GPU, VRAM medida).

### Desarrollo (GPU de 8 GB): `gemma4:e4b-it-q4_K_M`, con flash attention encendido

- Es el único Gemma 4 que cabe completo con buena calidad: 43/43 capas en GPU, 4.9 GB de VRAM real
  (de ~6.3 GB libres), F1 de fronteras 0.83, RAG 3/3 con la cita correcta, 9/10 hechos en el resumen.
- Flash attention **reduce el tiempo a primer token a la mitad o menos** (3.3 → 1.5 s al segmentar)
  sin cambiar la calidad y con algo menos de VRAM. Se propone encenderlo
  (`OLLAMA_FLASH_ATTENTION=1`). **Aplicado** como valor por defecto del compose el 11 oct 2026.
- `LLM_MODEL=gemma4:e4b-it-q4_K_M` es el valor por defecto desde el 11 oct 2026.
- `gemma4:e2b-it-q4_K_M`, el valor anterior de `LLM_MODEL`, sirve para probar la integración, pero no
  para segmentar (marca los 60 segmentos como pasos).
- Caché KV en q8_0: no hace falta con Gemma 4 (su caché pesa 0.17 GB). Solo ahorra en `qwen3:8b`
  (1.15 → 0.6 GB) y ahí no cambió la calidad.

### Producción (GPU de 24 GB, pendiente de confirmar con el patrocinador)

- **Candidato: `gemma4:26b-a4b-it-qat` (16 GB)**, el modelo del brief, o `gemma4:12b-it-qat` (7.2 GB)
  si la GPU se comparte con faster-whisper. **No está medido**: la decisión de producción queda
  pendiente hasta correr `scripts/benchmark_llm.py` en esa GPU con las mismas tareas.
- Si la GPU de 24 GB no se confirma, producción usa la misma configuración que desarrollo.

## Resultados del benchmark

Medido el 11 oct 2026 con Ollama 0.40.2 en la RTX 2070 SUPER. Una transcripción **inventada** de
1,470 palabras (60 segmentos, 12 pasos marcados a mano): (a) resumir, (b) segmentar en pasos eligiendo
números de segmento, (c) responder solo con 8 fragmentos y citar su id. Cada modelo: descarga de la
GPU, VRAM libre registrada, una corrida de calentamiento descartada y **3 repeticiones; se reporta la
mediana**. `num_ctx=8192`, temperatura 0, semilla 42, `think: false`. Resultados crudos (incluye la
VRAM libre antes de cada repetición y las salidas) en [datos/benchmark_llm/](datos/benchmark_llm/).
Reproducir: `python scripts/benchmark_llm.py --tabla`.

### Rendimiento (flash attention apagado; el compose lo enciende desde el 11 oct)

| Modelo | MTP¹ | Disco | Capas en GPU² | VRAM real³ | `/api/ps`⁴ | Carga⁵ | TTFT (b) | tok/s (a) | Total (a) / (b) / (c) |
|---|---|---|---|---|---|---|---|---|---|
| `gemma4:e2b-it-q4_K_M` | **sí** | 4.6 GB | 36/36 | 3.19 GiB | 0.23 GiB | 10.6 s | 1.46 s | 123 | 5.4 / 13.2 / 1.1 s |
| `gemma4:e4b-it-q4_K_M` | **sí** | 6.6 GB | 43/43 | 4.88 GiB | 0.26 GiB | 8.6 s | 3.33 s | 91 | 7.0 / 8.2 / 2.2 s |
| `gemma4:e4b-it-qat` | no | 6.1 GB | 43/43 | 4.33 GiB | 2.88 GiB | 7.6 s | 3.39 s | 62 | 9.3 / 13.3 / 2.6 s |
| `qwen3:8b-q4_K_M` | no | 5.2 GB | 37/37 | 5.93 GiB | 5.94 GiB | 5.7 s | 4.29 s | 46 | 13.8 / 12.6 / 3.1 s |
| `qwen3.5:9b-q4_K_M` | no | 6.6 GB | **31/33** | 6.09 GiB | 9.46 GiB | 14.5 s | 3.29 s | **27** | 15.3 / 15.2 / 2.6 s |

¹ **MTP infla los tok/s**: Ollama activa sola la decodificación especulativa con la cabeza MTP que
traen esas etiquetas. A tamaño parecido, `e4b-it-q4_K_M` (MTP) genera 1.5–1.8× más rápido que
`e4b-it-qat` (sin MTP); no comparar tok/s entre filas con y sin MTP como si fuera solo el modelo.
² Logs de llama-server (`offloaded N/M layers`). En Gemma 4 E2B/E4B, 2.1–2.7 GiB de tablas de
embeddings por capa quedan en RAM por diseño; no es un reparto. `qwen3.5:9b` sí se reparte.
³ Diferencia de `nvidia-smi` antes y después de cargar: incluye modelo, caché KV, proyector de visión
(~1 GB en los multimodales), cabeza MTP y contexto CUDA. VRAM libre antes de cargar: 6,288–6,473 MiB.
⁴ **No confiable en 0.40.2** con el runner llamacpp: subestima los Gemma con MTP y en `qwen3.5` supera
la VRAM total. Se guarda solo como registro.
⁵ Carga con los pesos en la caché del sistema. **En frío** (después de reiniciar el contenedor o de
leer otros modelos) se midieron 36–86 s: `LLM_TIMEOUT_S` sube de 120 a 180 s por esto (un
calentamiento con 120 s agotó el tiempo: 85.7 s de carga más la generación).

### Calidad (indicativa: una sola transcripción)

> **Las diferencias de F1 son indicativas.** Hay una sola transcripción (n=1) con 12 pasos: un corte
> de más o de menos mueve el F1 entre 0.03 y 0.08, del orden de las diferencias entre e4b, qwen3 y
> qwen3.5. La elección de modelo se revisa con los resultados de la Fase 4 (tres transcripciones,
> heurística vs. `gemma4:e4b-it-q4_K_M` vs. `qwen3.5:9b-q4_K_M`).

| Modelo | (a) hechos clave (de 10) | (b) JSON válido | (b) ids, orden y sin duplicados | (b) pasos (12 reales) | (b) F1 ±1 segmento | (c) ids existen | (c) cita el fragmento correcto |
|---|---|---|---|---|---|---|---|
| `gemma4:e2b-it-q4_K_M` | 8 | 3/3 | 3/3 | 60 | 0.33 | 3/3 | 3/3 |
| `gemma4:e4b-it-q4_K_M` | 9 | 3/3 | 3/3 | 17 | 0.83 | 3/3 | 3/3 |
| `gemma4:e4b-it-qat` | 9 | 3/3 | 3/3 | 19 | 0.77 | 3/3 | 3/3 |
| `qwen3:8b-q4_K_M` | 8 | 3/3 | 3/3 | 16 | 0.86 | **2/3** | 3/3 |
| `qwen3.5:9b-q4_K_M` | 9 | 3/3 | 3/3 | 14 | **0.92** | 3/3 | 3/3 |

- Con FA apagado ningún modelo omitió un inicio de paso real: todos los errores son pasos de más.
  Dos de ellos (bloqueo eléctrico y medición de holgura) los marcan casi todos y son discutibles en
  la anotación manual. La excepción es `qwen3.5:9b` con FA: en 2 de 3 repeticiones omitió dos pasos
  (limpieza e inspección; bitácora) y sus cortes cambian entre repeticiones.
- El JSON Schema en `format` funcionó en el 100 % de las respuestas (incluida la lista de nivel
  superior de la tarea b). Los fallos son de contenido: `qwen3:8b` citó un id inexistente (3) o
  repitió el mismo.

### Flash attention (FA) y caché KV en q8_0

| Modelo | Variante | TTFT (b) | tok/s (a) | Total (b) | VRAM real | F1 (b) | (c) ids existen |
|---|---|---|---|---|---|---|---|
| `gemma4:e4b-it-q4_K_M` | FA apagado | 3.33 s | 91 | 8.2 s | 4.88 GiB | 0.83 | 3/3 |
| | **FA encendido** | **1.52 s** | 93 | 6.2 s | 4.70 GiB | 0.83 | 3/3 |
| `gemma4:e4b-it-qat` | FA apagado | 3.39 s | 62 | 13.3 s | 4.33 GiB | 0.77 | 3/3 |
| | **FA encendido** | **1.34 s** | 65 | 10.7 s | 4.21 GiB | 0.80 | 3/3 |
| `qwen3:8b-q4_K_M` | FA apagado | 4.29 s | 46 | 12.6 s | 5.93 GiB | 0.86 | 2/3 |
| | **FA encendido** | **2.49 s** | 50 | 9.7 s | 5.90 GiB | 0.86 | 1/3 |
| | FA + KV q8_0 | 2.16 s | 48 | 10.2 s | **5.38 GiB** | 0.83 | 1/3 |
| `qwen3.5:9b-q4_K_M` | FA apagado | 3.29 s | 27 | 15.2 s | 6.09 GiB (31/33 capas) | 0.92 | 3/3 |
| | FA encendido | 2.68 s | 33 | 9.6 s | 6.01 GiB (**32/33 capas**) | 0.91 | 3/3 |

FA acelera sobre todo la lectura del prompt (TTFT −42 a −60 % en los modelos que caben completos),
que es lo que domina al segmentar transcripciones largas; la generación cambia poco. Con FA,
`qwen3.5:9b` **sigue sin caber completo** (32/33 capas en GPU; 6.01 GiB con 6.47 GiB libres): gana
velocidad (27 → 33 tok/s) pero sigue por debajo de los Gemma y su carga en frío fue de 53 s.

## Consecuencias

- **Positivas:** LLM local a costo cero, reproducible con un `docker compose --profile llm up -d`;
  salida estructurada confiable con JSON Schema; segmentación útil (F1 0.83) en el hardware de
  desarrollo; el mismo script mide la GPU de producción cuando exista.
- **Negativas / riesgos:**
  - 8 GB dejan ~1.3 GB libres con `e4b` cargado: faster-whisper y el LLM no deben estar en la GPU al
    mismo tiempo (la transcripción por lotes va a Colab, como dice el plan).
  - El proyector de visión ocupa ~1 GB que el MVP no usa; no encontramos una opción de Ollama para omitirlo.
  - Carga en frío de 36–86 s: la primera petición tras arrancar es lenta (`OLLAMA_KEEP_ALIVE=30m`).
  - MTP y FA dependen de la versión de Ollama: al subir la versión hay que repetir el benchmark.
  - Calidad medida con una sola transcripción inventada (n=1): es una señal, no una evaluación.

## Seguimiento

1. ~~Aprobar `LLM_MODEL=gemma4:e4b-it-q4_K_M` y `OLLAMA_FLASH_ATTENTION=1` como valores por defecto
   de desarrollo~~: aprobados por el equipo y aplicados el 11 oct 2026 (caché KV sigue en f16).
2. Con la GPU de 24 GB confirmada: correr el benchmark con `gemma4:26b-a4b-it-qat` y `gemma4:12b-it-qat`
   y cerrar la decisión de producción.
3. Revisar la elección de modelo con los resultados de la Fase 4 (tres transcripciones) y, en F2,
   con videos propios anotados a mano. Fase 4 hecha: ver
   [ADR-010](ADR-010-segmentacion-pasos-llm.md#prototipo-y-resultados-preliminares-11-oct-2026);
   `LLM_MODEL` no cambia hasta resolver lo pendiente con el patrocinador.
4. ~~Medir `qwen3.5:9b` con FA encendido~~: hecho; no cabe completo (32/33 capas). Se mantiene como
   comparación de calidad en la Fase 4, no como modelo de desarrollo.

## Pendiente con el patrocinador

Resultados de segmentación en pasos de la Fase 4 (3 transcripciones inventadas, 30 pasos, prompt
v1, FA encendido; indicativo, n=3). Detalle en ADR-010.

| Modelo | Capas en GPU (8 GB) | F1 ±1 segmento | F1 ±2 s | Pasos de más / omitidos | s por transcripción |
|---|---|---|---|---|---|
| `gemma4:e4b-it-q4_K_M` (desarrollo) | 43/43 | 0.741 | 0.691 | 21 / 0 | 5.2 |
| `gemma4:12b-it-qat` | 37/49 | 0.763 | 0.763 | 17 / 1 | 49.8 |
| `qwen3.5:9b-q4_K_M` | 32/33 | 0.947 | 0.842 | 0 / 3 | 6.2 |
| Heurística (respaldo) | — | 0.667 | 0.456 | 8 / 11 | < 0.01 |

- **En 8 GB, `gemma4:e4b` sobre-segmenta**: sirve como borrador para la corrección del experto, no
  como segmentación final.
- **`qwen3.5:9b` segmenta mejor, pero no es Gemma 4**: el NDA (cl. 1) nombra a Gemma 4 como base;
  usarlo requiere aprobación escrita del patrocinador.
- **`gemma4:12b-it-qat` no cabe en 8 GB** (37/49 capas, 6,247 MiB), tarda ~50 s por transcripción
  y apenas mejora a `e4b`.
- **Propuesta:** con la GPU de 24 GB, probar `gemma4:26b-a4b-it-qat` (el modelo del brief) con
  `scripts/benchmark_llm.py` y `scripts/evaluar_segmentacion.py`, y decidir entre ese modelo y pedir
  la excepción para `qwen3.5`. `LLM_MODEL` sigue en `gemma4:e4b-it-q4_K_M` mientras tanto.

## Referencias

- Brief y NDA cl. 1 (Gemma 4 como base); plan §2 (ADRs) y pregunta 8 (GPU de 24 GB).
- [ADR-010](ADR-010-segmentacion-pasos-llm.md) (segmentación con LLM), [docs/dev/llm.md](../dev/llm.md).
- Datos: [datos/benchmark_llm/](datos/benchmark_llm/) · script: `scripts/benchmark_llm.py` · fixture:
  `tests/fixtures/transcripciones/cambio_cuchilla.json`.
- `fa_off.json` corrió con `LLM_TIMEOUT_S=120` (no se registraba aún); `fa_on` y `fa_on_kv_q8` con 300.
