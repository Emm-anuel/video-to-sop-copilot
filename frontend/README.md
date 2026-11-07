# frontend

Interfaz web de SOPVID en Angular (componentes standalone, sin librerías de estado ni de UI).
Consume la API de `sopvid.plataforma.api`; el contrato de rutas está en
[`docs/dev/api.md`](../docs/dev/api.md).

> **Estado al 7 nov 2026:** la carpeta todavía no tiene el proyecto Angular. Emmanuel lo crea el
> 7 nov con la base y la pantalla `/nuevo`. Sara construye la pantalla del reporte (RF-20) sobre esa
> base: haz `git pull` antes de empezar y **no generes otro proyecto** en esta carpeta.

## Pantallas del MVP (8 nov 2026)

El MVP de validación tiene **una pantalla obligatoria** y una opcional. Las otras cinco del
documento SOP V1.0 (biblioteca, nuevo análisis completo, avance en vivo, SOP generado y búsqueda)
son de S5 y S6.

| Ruta | Qué hace | Responsable | Estado |
|---|---|---|---|
| `/videos/:id/reporte` | **Reporte de validación (RF-20):** semáforo, resumen, tabla paso a paso con cita y segundo, y el video al lado que salta al segundo de cada fila | Sara | Versión de respaldo de Emmanuel en la rama feat/reporte-rf20-respaldo; si Sara entrega la suya, se elige una antes de unir a main |
| `/nuevo` (y `/` redirige ahí) | **Subir SOP y video (opcional):** `POST /sops` y luego `POST /videos` con `modo=validar` y `sop_id`; al recibir el 202 navega al reporte | Emmanuel | Hecho (7 nov): `src/app/nuevo/` |

**Criterio del MVP:** en la pantalla del reporte, el video **A** sale en verde con 100 % y sin
*Falta*; el **B** muestra *Falta* en los pasos 2 y 6 (sin segundo) y una *Sobra* (limpiar la
carcasa) que, al darle clic, salta a ~74 s.

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
  - `afinidad` llega en `null` hasta S5: ocúltala o pon "pendiente".
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
