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
| `/nuevo` (y `/` redirige ahí) | **Subir SOP y video (opcional):** `POST /sops` (202) y, sin esperar la conversión, `POST /videos` con `modo=validar` y `sop_id`; consulta el estado del SOP cada 2 s y navega al reporte cuando los dos terminan. Con **"No tengo SOP"**, solo el video con `modo=generar` | Emmanuel | Hecho (7 nov): `src/app/nuevo/`. PDF, Word y `POST /sops` asíncrono desde el 8 nov; "No tengo SOP" desde el 9 nov (sección "SOP generado") |
| `/videos/:id/sop` | **SOP generado (mínima, solo lectura):** avance, cuadro resumen, tabla de pasos, puntos y palabras clave con menciones, lo inferido resaltado y "Guardar en la biblioteca" | Emmanuel (base) · Sara (RF-26) | Hecho (9 nov): `src/app/sop/`. Sin edición: la pule Sara con RF-26 |

**Criterio del MVP:** en la pantalla del reporte, el video **A** sale en verde con 100 % y sin
*Falta*; el **B** muestra *Falta* en los pasos 2 y 6 (sin segundo) y una *Sobra* (limpiar la
carcasa) que, al darle clic, salta a ~74 s.

### `/nuevo` no es provisional

El único componente provisional fue el del reporte, que reemplaza RF-20. `/nuevo` se queda: es la
base de la pantalla **"Nuevo análisis"** del documento SOP V1.0 y en S5 se amplía sobre el mismo
componente, sin rehacerlo. Hoy cubre el camino del MVP: un SOP nuevo en Markdown, TXT, PDF o
Word (desde el 8 nov), modo `validar` y subida simple. Le falta:

| Qué falta | RF | Semana |
|---|---|---|
| Elegir un SOP de la biblioteca (el modo `generar` ya está: casilla "No tengo SOP") | RF-07, RF-02 | S5 |
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

### Cómo lo hace `/nuevo` (desde el 8 nov, Emmanuel)

Cambio mínimo sobre el mismo componente, sin librerías nuevas (`src/app/nuevo/`):

- El selector del SOP acepta `.md`, `.txt`, `.pdf` y `.docx`.
- Con el 202 de `POST /sops` arrancan **en paralelo** la subida del video (`POST /videos` con el
  `sop_id`, sin esperar la conversión) y la consulta de `GET /sops/{id}/estado` cada 2 s
  (`SONDEO_SOP_MS`, con `timer` + `switchMap` + `takeWhile` de RxJS). Mientras el SOP está en
  `en_cola` o `convirtiendo` se ve "Convirtiendo el SOP…".
- **Listo sin advertencias** y video subido: navega al reporte, como antes.
- **Listo con advertencias:** las muestra (y "lo convirtió el modelo, vale la pena revisarlo" si
  `metodo` es `llm`) y cambia "Validar" por **"Ver el reporte"**, para que se alcancen a leer.
- **Error:** muestra `mensaje` tal cual, cancela la subida si seguía y olvida el SOP: el
  reintento vuelve a subir un SOP y el video. Si el video ya había subido, avisa que no se
  validará con ese SOP (en el backend ese video termina en `error` con el mensaje del SOP).
- Si falla el video y el SOP está bien, el reintento sube solo el video con el mismo `sop_id`
  (la consulta del SOP sigue mientras tanto).
- `EstadoSop` (antes `SopCreado`) va a mano en `src/app/api/tipos.ts`, con `estadoSop(id)` en
  `ApiService`. Pruebas en `nuevo.spec.ts`, con temporizadores falsos de Vitest
  (`vi.useFakeTimers({ shouldAdvanceTime: true })` y `vi.advanceTimersByTimeAsync`).

## Pantalla del reporte (RF-20): lo que hay que saber

Todo lo necesario ya existe en el backend; no hace falta esperar a nadie.

- **Forma del JSON:** [`docs/contrato/reporte.schema.json`](../docs/contrato/reporte.schema.json)
  (`ReporteValidacion`). Genera los tipos de TypeScript desde el esquema, no a mano.
- **Ejemplos para trabajar sin backend:** `tests/fixtures/reporte_ejemplo.json` (71.43 %, amarillo,
  con todos los casos: Cumple, fuera de orden, Parcial con justificación, Falta, Sobra, intro y
  cierre) y `tests/fixtures/reporte_ejemplo_provisional.json` (juez caído, un par "sin revisar").
  No los edites a mano: se regeneran con `scripts/ejemplo_reporte.py`.
- **Rutas que usa la pantalla:**
  - `GET /videos/{id}`: `proceso` (`en_cola`, `procesando`, `listo`, `error`, `afinidad_baja`),
    `etapa`, `progreso` y `afinidad` (sección siguiente).
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
    - `afinidad`: `{valor, explicacion, bajo_umbral, componentes}` (desde el 8 nov, ADR-020); con
      `bajo_umbral`, el aviso "El video parece no corresponder a este SOP" (§5.2). En un reporte
      `bajo_umbral` solo llega si quien cargó decidió continuar (sección siguiente). `null` si el
      video no tiene ficha de contexto.
    - Por fila, solo en pares: `responsable` (desde el 8 nov, ADR-020: `coincide` / `distinto` /
      `no_identificado`, con `esperado`, `observado` como "Nombre (rol)" o el rol, y una `nota`
      que dice cómo se identificó a la persona; muéstrala como ayuda, p. ej. en un tooltip) y
      `tiempo` (desde el 8 nov, ADR-021: `en_tiempo` / `excede` / `menor` / `sin_referencia`,
      con `esperado_min` y `observado_min` en minutos y `origen`: `medido` es la duración del
      paso en el video; `narrado`, la que dijo el operador, con su frase en `cita`). Solo
      `excede` es un incumplimiento; `menor` es más rápido de lo esperado: muéstralo, pero sin
      alarma.
    - `rescatado` (desde el 9 nov, ADR-022, solo en pares): el paso del video se armó con varios
      fragmentos que habían quedado como *Sobra*, para un paso del SOP que iba a salir en
      *Falta*, y el juez lo confirmó. Márcalo (p. ej. "armado con fragmentos") para que quien
      revisa sepa que la cita es de uno de ellos y el segundo es el del primero.
    - `roles` (desde el 8 nov: `presente` / `mencionado` / `ausente`, con su segundo para saltar
      al video, `persona` y `confianza`; con `confianza: "baja"` el rol lo infirió el modelo, no
      se dijo). Un rol ausente con `con_pasos: false` (de apoyo, p. ej. un supervisor que solo
      atiende si algo falla) se muestra, pero no es una diferencia.
    - `tiempo_total` (desde el 8 nov: la suma de lo observado en los pares frente al total del
      SOP; Falta y Sobra no suman) y `horario` (`coincide` / `distinto` / `no_mencionado` /
      `sin_referencia`, con lo que se dijo en el video, su segundo y su frase).
    - `conteo.personas_con_diferencias` (responsables `distinto` más roles ausentes con pasos) y
      `conteo.pasos_fuera_de_tiempo` (solo las filas `excede`) van junto al porcentaje (§5.6).
      El tiempo no cambia el porcentaje.
    - Ficha de contexto y SOP generado: `tests/fixtures/contexto_ejemplo.json` y
      `tests/fixtures/sop_generado_ejemplo.json` (esquemas en `docs/contrato/contexto.schema.json`
      y `sop.schema.json`).
  - La miniatura de RF-20 depende de los fotogramas (S5): deja el espacio, sin imagen.
- **Saltar al segundo:** `reproductor.currentTime = fila.t_inicio` y `play()`. Los segundos salen de
  la transcripción, nunca de un modelo (regla 4 de `CLAUDE.md`).

## Afinidad baja: "El video parece no corresponder a este SOP" (desde el 8 nov, ADR-020)

Antes de comparar pasos, el backend compara la ficha de contexto del video con el SOP (RF-17,
§5.2). Si la afinidad queda bajo 60 (`AFINIDAD_MIN`), **la validación se detiene** y quien cargó
el video decide si continúa.

**Ya implementado, en mínimo (8 nov, Emmanuel):** `reporte.ts` deja de consultar con
`afinidad_baja` (constante `FINALES`), la plantilla muestra el aviso (`.afinidad-baja`, con las
clases de `.avisos`) con el valor y la explicación, y el botón "Continuar de todos modos" llama a
`ApiService.continuarValidacion(id)` y reinicia la consulta (`consultar.next(id)`); mientras se
envía queda deshabilitado y, si falla, sale el error en español. `tipos.ts` agrega
`afinidad_baja` a `Proceso` y `afinidad` a `EstadoVideo`. Pruebas en `reporte.spec.ts`
("afinidad baja"). Para Sara, si quiere pulirlo: el estilo propio del aviso, un enlace "Elegir
otro SOP" a `/nuevo`, mostrar la afinidad con `bajo_umbral` junto al porcentaje del reporte. `reporte-validacion.ts` ya se regeneró el 8 nov con los tiempos
(ADR-021): trae `Afinidad.componentes`, los campos nuevos de `RolReporte` y `ResponsableFila.nota`.

1. Mientras consultas `GET /videos/{id}` cada 3 s, el video puede terminar en
   `proceso: "afinidad_baja"` (con `etapa: "afinidad"`) en lugar de `listo` o `error`. **Es un
   estado final: deja de consultar.**
2. En ese estado, `GET /videos/{id}` trae `afinidad`:

   ```json
   {"valor": 12, "bajo_umbral": true,
    "explicacion": "actividad distinta del título; propósito distinto del objetivo; ningún equipo en común; lugar distinto",
    "componentes": {"global": 20, "actividad": 0, "objetivo": 8, "equipos": 0}}
   ```

   Muestra "El video parece no corresponder a este SOP", el valor (de 0 a 100), la `explicacion`
   tal cual (la arma el código, en frases separadas por "; ") y dos botones:
   - **Continuar de todos modos:** `POST /videos/{id}/validar?continuar=true` (202, el video vuelve
     a `en_cola`); retoma la consulta del estado. No repite la transcripción ni la ficha. El
     reporte que sale lleva la misma `afinidad`, con `bajo_umbral: true`: muéstrala junto al
     porcentaje para que se vea que se validó a pesar del aviso.
   - **Cancelar / elegir otro SOP:** volver a `/nuevo`. No hay que borrar nada.
3. `GET /videos/{id}/reporte` responde **409** con `{"proceso": "afinidad_baja"}` mientras el
   video esté así: no hay reporte de pasos.
4. `componentes` es para depurar y para el paper; no hace falta mostrarlo.
5. Con `listo`, `GET /videos/{id}` también trae la `afinidad` del reporte (o `null` si el video no
   tuvo ficha de contexto: entonces la validación siguió sin advertir).

## SOP generado: "No tengo SOP" y `/videos/:id/sop` (9 nov, ADR-023)

Pantalla mínima para probar el modo generar; **Sara la pule con RF-26** (editar, agregar, quitar y
reordenar pasos) sobre el mismo componente.

- **`/nuevo`:** la casilla "No tengo SOP" oculta el campo del SOP y el botón dice "Generar SOP".
  Sube solo el video con `modo=generar` (`ApiService.subirVideo` sin `sopId`) y, con el 202,
  navega a `/videos/:id/sop`.
- **`/videos/:id/sop` (`src/app/sop/`):** consulta `GET /videos/{id}` cada 3 s y muestra la etapa
  (contexto, pasos del video, redacción de los pasos, del cuadro resumen, de las claves). Con
  `listo`, pide `GET /videos/{id}/sop` (el `SOP`) y `GET /sops/{sop_id}` (código, advertencias y
  `en_biblioteca`). Muestra:
  - el cuadro resumen (objetivo, alcance, responsable, lugar, horario, duración total, versión,
    equipo, roles, personas, riesgos y qué hacer en caso de falla);
  - la tabla de pasos (N.º, nombre, descripción, responsable, equipo, puntos de validación,
    tiempo y el tramo del video);
  - los puntos clave con su segundo y las palabras clave con sus menciones y sus segundos.
  - **Lo inferido va resaltado** (fondo amarillo y borde punteado): un dato del resumen, riesgo o
    falla con `fuente: "inferido"`, un campo del paso en `campos_inferidos` o un elemento de
    equipo o de validación cuya `evidencia` es inferida. Al pasar el cursor se ve la fuente, la
    confianza, el segundo y la cita (en el idioma del video).
  - "Guardar en la biblioteca" llama a `POST /sops/{id}/biblioteca`; desde ahí el SOP sirve como
    `sop_id` en otro `POST /videos` (antes, la API responde 422).
- Tipos: `src/app/api/sop.ts` se genera desde `docs/contrato/sop.schema.json` con
  `npm run tipos:sop` (`npm run tipos` genera los dos). No se edita a mano.
- Pendiente (RF-26): edición con `PUT /sops/{id}` (la API ya valida el SOP completo y responde
  422 si no cumple el contrato), descargar el Markdown (`GET /sops/{id}.md`) y repetir la
  generación (`POST /videos/{id}/generar`).
- **Para Sara (RF-26, 10 nov): el editor necesita "Unir con el siguiente paso".** La agrupación
  predeterminada (v2, ADR-023) encuentra bien dónde empieza y termina cada paso y no inventa ni
  mezcla pasos, pero el SOP sale más detallado que uno escrito a mano (unos 15 pasos contra 6 en
  el video E): quien revisa junta pasos. En cada fila (menos la última), un botón que una el paso
  con el siguiente en el mismo `PasoSOP`:
  - `t_inicio` del primero y `t_fin` del segundo (los tiempos salen del video: no se escriben a
    mano);
  - nombre del primero, editable; descripciones unidas en orden;
  - `equipo`, `puntos_validacion`, `evidencia` y `campos_inferidos` unidos sin repetir;
    `tiempo_esperado_min`, la suma; `cita`, `fuente` y `confianza`, las del primero;
  - renumerar los pasos (1…n) y el `paso` de cada riesgo del resumen: el que apuntaba al segundo
    pasa al paso unido y los de después bajan uno.
  Se guarda con el mismo `PUT /sops/{id}`. Lo contrario ("Partir") no hace falta para este caso.

## Desarrollo

**Requisito:** Node 24 LTS (`^24.15.0`, en `package.json` › `engines`; `.nvmrc` dice `24`) y npm.
Angular 22 se usa con `npx`, sin instalar nada global.

La API no tiene CORS. `ng serve` usa el proxy de `proxy.conf.js` (ya configurado en
`angular.json`): reenvía `/api` a la API sin el prefijo. El destino sale de la variable `API_URL`
(por defecto `http://localhost:8000`). El código siempre llama a `/api/...`
(`src/app/api/api.service.ts`).

**En Docker (sin Node en el host ni otra terminal).** `docker compose up -d` (o `make up`) levanta
también el servicio `web`: `ng serve` en <http://localhost:4200>, con `./frontend` montado y
recarga en caliente al guardar. El proxy apunta a la API de compose (`http://api:8000`). Con
`make up-gpu` la API corre en el host y el proxy apunta a `http://host.docker.internal:8000`.

- Logs y errores de compilación: `docker compose logs -f web`.
- `node_modules` y `.angular` del contenedor viven en volúmenes propios (Linux), separados de los
  de Windows. `npm ci` corre solo si cambió `package-lock.json`.
- Tras `npm install <paquete>` en el host, `docker compose restart web` lo instala en el
  contenedor. Si algo queda raro: `docker compose down` y `docker volume rm sopvid_web_node_modules`.
- Los cambios se detectan por sondeo (`--poll`, 2 s por defecto; `WEB_POLL_MS` en `.env`): los
  archivos montados desde Windows no avisan al contenedor.
- Tests, build y `npm run tipos` siguen en el host o con
  `docker compose exec web npx ng test --watch=false`.

**En el host (Node 24 instalado):**

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
  `npm run tipos`. `EstadoSop`, `VideoCreado` y `EstadoVideo` van a mano en `src/app/api/tipos.ts`.
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
