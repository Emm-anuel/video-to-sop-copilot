# frontend

Interfaz web de SOPVID en Angular (componentes standalone, sin librerías de estado ni de UI).
Consume la API de `sopvid.plataforma.api`; el contrato de rutas está en
[`docs/dev/api.md`](../docs/dev/api.md).

> **Estado al 7 nov 2026:** la base del proyecto Angular y la pantalla `/nuevo` están en `main`
> (`9363bbd`). La pantalla del reporte (RF-20) se construye sobre esa base: haz `git pull` antes de
> empezar y **no generes otro proyecto** en esta carpeta.

## Pantallas del MVP (8 nov 2026)

El MVP de validación tiene **una pantalla obligatoria** y una opcional. Las otras cinco del
documento SOP V1.0 (biblioteca, nuevo análisis completo, avance en vivo, SOP generado y búsqueda)
son de S5 y S6.

| Ruta | Qué hace | Responsable | Estado |
|---|---|---|---|
| `/videos/:id/reporte` | **Reporte de validación (RF-20):** semáforo, resumen, tabla paso a paso con cita y segundo, y el video al lado que salta al segundo de cada fila | Sara | Versión de respaldo de Emmanuel en la rama feat/reporte-rf20-respaldo; si Sara entrega la suya, se elige una antes de unir a main |
| `/nuevo` (y `/` redirige ahí) | **Subir SOP y video (opcional):** `POST /sops` y luego `POST /videos` con `modo=validar` y `sop_id`; al recibir el 202 navega al reporte | Emmanuel | Hecho (7 nov): `src/app/nuevo/`. Falta adaptarla a `POST /sops` asíncrono (sección siguiente) |

**Criterio del MVP:** en la pantalla del reporte, el video **A** sale en verde con 100 % y sin
*Falta*; el **B** muestra *Falta* en los pasos 2 y 6 (sin segundo) y una *Sobra* (limpiar la
carcasa) que, al darle clic, salta a ~74 s.

### `/nuevo` no es provisional

El único componente provisional fue el del reporte, que reemplaza RF-20. `/nuevo` se queda: es la
base de la pantalla **"Nuevo análisis"** del documento SOP V1.0 y en S5 se amplía sobre el mismo
componente, sin rehacerlo. Hoy cubre solo el camino del MVP: un SOP nuevo en Markdown o TXT, modo
`validar` y subida simple. Le falta:

| Qué falta | RF | Semana |
|---|---|---|
| Elegir el modo: SOP de la biblioteca, subir uno nuevo o sin SOP (modo `generar`) | RF-07, RF-02 | S5 |
| Leer el SOP en PDF y Word, no solo Markdown o TXT | RF-01 | S5 |
| Mostrar el SOP convertido para corregirlo antes de validar | RF-04 | S5 |
| Subida por partes de 16 MB con reintentos, en lugar de la subida simple | RF-06 | S5 |
| Avance en vivo por etapa y transcripción parcial (hoy el avance se ve en la pantalla del reporte mientras procesa) | RF-08 | S5 |

## Subir un SOP: flujo asíncrono (desde el 7 nov, rama `feat/sop-pdf-word`)

`POST /sops` ya no convierte en la petición: el SOP se convierte en el trabajador de la API, con
la plantilla (al instante) o con Gemma 4 (≈ 25 s con GPU, 2-3.5 min solo con CPU). Acepta `.md`,
`.txt`, `.pdf` y `.docx`. La forma de la respuesta está en
[`docs/contrato/sop_estado.schema.json`](../docs/contrato/sop_estado.schema.json) (`EstadoSop`);
genera los tipos desde ahí, igual que el reporte.

1. **Subir:** `POST /sops` (multipart, campo `archivo`).
   - **202** con `EstadoSop` (`estado: "en_cola"`) y la cabecera `Location: /sops/{id}/estado`.
   - **415** (extensión), **413** (tamaño) o **422** (no se puede leer: PDF escaneado, archivo
     dañado, texto que no es UTF-8): muestra `detail` tal cual y no consultes nada.
2. **Consultar el estado cada 2 s:** `GET /sops/{id}/estado` hasta que `estado` sea `listo` o
   `error`. Mientras sea `en_cola` o `convirtiendo`, un aviso de "convirtiendo el SOP…" basta;
   `en_cola` puede durar si hay un video procesándose (el SOP va antes que el siguiente video, pero
   no interrumpe el que está en curso).
3. **Mostrar el resultado:**
   - `listo`: el `titulo` y las `advertencias` (no detienen el flujo). Agrúpalas por `tipo`
     (`paso_sin_evidencia`, `infinitivo`, `numeracion`, `tiempos`, `valor_invalido`…); `linea`
     solo viene si el SOP siguió la plantilla. Si `metodo` es `"llm"`, conviene decir que lo
     convirtió el modelo y que vale la pena revisarlo (RF-04).
   - `error`: muestra `mensaje` tal cual (ya dice qué hacer: volver a subirlo, usar la plantilla,
     dividirlo). El SOP no se puede usar; hay que subir otro.
4. **Ver el SOP:** `GET /sops/{id}` da el SOP del contrato; **409** mientras no esté listo.

Con el video:

- **SOP primero, video después** (lo que hace `/nuevo` hoy): se puede mandar `POST /videos` con el
  `sop_id` **sin esperar** a que el SOP esté listo; el video espera a su SOP en la cola. Si el SOP
  ya está en `error`, `POST /videos` da 422. Para mostrar las advertencias, consulta el estado del
  SOP como en el paso 2, en paralelo con el avance del video.
- **SOP adjunto al video (RF-02):** `POST /videos` con el campo `sop` (archivo) en lugar de
  `sop_id`. Responde 202 con `sop_id`; consulta `GET /sops/{sop_id}/estado` como arriba. Si la
  conversión falla, el video queda en `proceso: "error"` con el mensaje del SOP en `error`.

Qué cambia para `/nuevo`: `POST /sops` responde 202 (no 201) y en ese momento `titulo` viene en
`null` y `advertencias` vacía; el resto del flujo sigue funcionando porque el video espera al SOP.
Para mostrar las advertencias y el error del SOP hay que agregar el paso 2.

## Pantalla del reporte (RF-20): lo que hay que saber

Todo lo necesario ya existe en el backend; no hace falta esperar a nadie.

- **Forma del JSON:** [`docs/contrato/reporte.schema.json`](../docs/contrato/reporte.schema.json)
  (`ReporteValidacion`). Genera los tipos de TypeScript desde el esquema, no a mano.
- **Ejemplos para trabajar sin backend:** `tests/fixtures/reporte_ejemplo.json` (71.43 %, amarillo,
  con todos los casos: Cumple, fuera de orden, Parcial con justificación, Falta, Sobra, intro y
  cierre) y `tests/fixtures/reporte_ejemplo_provisional.json` (juez caído, un par "sin revisar").
  No los edites a mano: se regeneran con `scripts/ejemplo_reporte.py`.
- **Rutas que usa la pantalla:**
  - `GET /videos/{id}`: `proceso` (`en_cola`, `procesando`, `listo`, `error`), `etapa`, `progreso`.
  - `GET /videos/{id}/reporte`: el reporte; **409** mientras no está listo (consultar el estado cada
    3 s), 404 si el video no tiene reporte.
  - `GET /videos/{id}/video`: el archivo del video con soporte de `Range` (206), así el reproductor
    puede saltar a cualquier segundo. Existe desde el 7 nov (commit `a40b124`).
- **Reglas de presentación:**
  - Muestra `cumplimiento` y `semaforo` tal como vienen. **No recalcules el semáforo** en el front:
    el backend lo calcula con el porcentaje sin redondear.
  - `fuera_de_orden` es una **marca** sobre una fila, no un estado aparte; `conteo.cumple` ya
    incluye los que van fuera de orden.
  - Las filas con `marco_operador` (intro y cierre) van en gris y no cuentan como *Sobra*.
  - Una fila *Falta* no tiene `t_inicio`: no lleva enlace al video.
  - Si `provisional` es verdadero, muestra un aviso con `metadatos.avisos`.
  - **Campos de S5** (contrato listo desde el 7 nov; en producción llegan en `null`, `[]` o 0
    hasta que exista su lógica, así que la pantalla debe aguantar los dos casos; en los ejemplos
    vienen llenos):
    - `afinidad`: `{valor, explicacion, bajo_umbral}`; con `bajo_umbral`, el aviso "El video
      parece no corresponder a este SOP" (§5.2).
    - Por fila, solo en pares: `responsable` (`coincide` / `distinto` / `no_identificado`) y
      `tiempo` (`en_tiempo` / `excede` / `menor` / `sin_referencia`, origen `narrado` o
      `medido`).
    - `roles` (`presente` / `mencionado` / `ausente`, con su segundo), `tiempo_total` y `horario`.
    - `conteo.personas_con_diferencias` y `conteo.pasos_fuera_de_tiempo` van junto al porcentaje
      (§5.6).
    - Ficha de contexto y SOP generado: `tests/fixtures/contexto_ejemplo.json` y
      `tests/fixtures/sop_generado_ejemplo.json` (esquemas en `docs/contrato/contexto.schema.json`
      y `sop.schema.json`).
  - La miniatura de RF-20 depende de los fotogramas (S5): deja el espacio, sin imagen.
- **Saltar al segundo:** `reproductor.currentTime = fila.t_inicio` y `play()`. Los segundos salen de
  la transcripción, nunca de un modelo (regla 4 de `CLAUDE.md`).

## Desarrollo

**Requisito:** Node 24 LTS (`^24.15.0`, en `package.json` › `engines`; `.nvmrc` dice `24`) y npm.
Angular 22 se usa con `npx`, sin instalar nada global.

La API no tiene CORS. `ng serve` usa el proxy de `proxy.conf.json` (ya configurado en
`angular.json`): reenvía `/api` a `http://localhost:8000` sin el prefijo. El código siempre llama
a `/api/...` (`src/app/api/api.service.ts`).

```powershell
# API en el host (con GPU si hay), desde la raíz del repo; ver docs/dev/api.md
uvicorn sopvid.plataforma.api.main:app --host 127.0.0.1 --port 8000
# en otra terminal
cd frontend
npm install
npx ng serve              # http://localhost:4200 (con el proxy)
npx ng test --watch=false # Vitest con jsdom, sin navegador
npx ng build              # dist/sopvid
npm run tipos             # regenera src/app/api/reporte-validacion.ts desde el esquema
```

- **Tipos:** `ReporteValidacion` (y `FilaReporte`, `ConteoReporte`, `Aviso`…) están en
  `src/app/api/reporte-validacion.ts`, generado con `json-schema-to-typescript` desde
  `docs/contrato/reporte.schema.json`. Se versiona y no se edita a mano: si cambia el esquema,
  `npm run tipos`. `SopCreado`, `VideoCreado` y `EstadoVideo` van a mano en `src/app/api/tipos.ts`.
- **Errores:** `mensajeDeError` (`src/app/api/errores.ts`) convierte un `HttpErrorResponse` en un
  mensaje en español (sin conexión, 413, 415, 422 con el detalle de la API, 404).
- **Estructura:** `src/app/nuevo/` (subir SOP y video), `src/app/reporte-provisional/` (estado y
  porcentaje mientras llega RF-20; se reemplaza en `app.routes.ts`).

Para probar con datos reales: en `/nuevo`, sube `tests/fixtures/sop_filtro_agua.md` y el video A
o B (viven fuera de git, en `media/` o donde los tenga cada quien). La validación necesita Ollama
arriba (ver `docs/dev/llm.md`); sin él, el video termina en `error` con "LLM no disponible".

## Reglas

- **NDA:** ningún video, audio, SOP ni captura del cliente entra al repo. Tampoco los videos A y B
  del equipo: viven fuera de git.
- No subas `node_modules`, `dist` ni `.angular`.
- Antes de empezar una pantalla, toma su issue y revisa `main`, para no hacer dos veces el mismo
  trabajo.
- Commits en español con Conventional Commits (`feat(frontend): …`). Push solo cuando el repo esté
  privado.
