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
| `/nuevo` (y `/` redirige ahí) | **Subir SOP y video (opcional):** `POST /sops` (202) y, sin esperar la conversión, el video por partes (`POST /uploads`, desde el 12 nov) y `POST /videos` con `upload_id`, `modo=validar` y `sop_id`; consulta el estado del SOP cada 2 s y navega al avance (`/videos/:id/procesando`, desde el 12 nov) cuando los dos terminan. Con **"No tengo SOP"**, solo el video con `modo=generar` | Emmanuel | Hecho (7 nov): `src/app/nuevo/`. PDF, Word y `POST /sops` asíncrono desde el 8 nov; "No tengo SOP" desde el 9 nov (sección "SOP generado") |
| `/videos/:id/sop` | **SOP generado y su editor (RF-26):** avance y, al terminar, el editor del SOP (sección "Editor del SOP") | Emmanuel (base y RF-26, tomado de Sara el 10 nov) | Hecho (9 nov, solo lectura; editor desde el 11 nov): `src/app/sop/` |
| `/sops` | **Biblioteca de SOP (RF-05):** búsqueda, filtro por origen, ver o editar, usar para validar, eliminar y subir (sección "Biblioteca y Nuevo análisis") | Emmanuel | Hecho (12 nov): `src/app/biblioteca/` |
| `/sops/:id` | **Revisar el SOP convertido (RF-04):** el mismo editor en modo SOP de referencia; con `?video=N` ofrece revalidar ese video después de guardar | Emmanuel | Hecho (11 nov): `src/app/sop/sop-editor.ts` |

**Criterio del MVP:** en la pantalla del reporte, el video **A** sale en verde con 100 % y sin
*Falta*; el **B** muestra *Falta* en los pasos 2 y 6 (sin segundo) y una *Sobra* (limpiar la
carcasa) que, al darle clic, salta a ~74 s.

### `/nuevo` no es provisional

El único componente provisional fue el del reporte, que reemplaza RF-20. `/nuevo` se queda: es la
base de la pantalla **"Nuevo análisis"** del documento SOP V1.0 y en S5 se amplía sobre el mismo
componente, sin rehacerlo. Hoy cubre el camino del MVP: un SOP nuevo en Markdown, TXT, PDF o
Word (desde el 8 nov), modo `validar` y subida simple. Le falta:

| Qué falta | RF | Responsable | Semana |
|---|---|---|---|
| ~~Elegir un SOP de la biblioteca~~ Hecho el 12 nov: tres modos (biblioteca, subir, generar), consentimiento y casilla de imágenes | RF-07, RF-02 | Emmanuel | S5 |
| Lista de videos (`/videos`, pantalla 6): título, fecha, modo, estado, porcentaje con semáforo e imágenes, con enlace al reporte o al SOP generado. Falta `GET /videos` | — | Emmanuel | S6 |
| ~~Mostrar el SOP convertido para corregirlo~~ Hecho el 11 nov: enlace "Revisar y corregir el SOP" a `/sops/:id?video=N` (el video no espera; se revalida desde el editor) | RF-04 | Emmanuel | S5 |
| Subida por partes de 16 MB con reintentos, en lugar de la subida simple | RF-06 | Emmanuel | S5 |
| Avance en vivo por etapa y transcripción parcial (hoy el avance se ve en la pantalla del reporte mientras procesa) | RF-08 | Emmanuel | S5 |

Responsables desde el reparto del 10 nov ([registro de decisiones](../docs/plan/plan.md#registro-de-decisiones)).

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
- **Listo sin advertencias** y video subido: navega al avance (`/videos/:id/procesando`, desde el 12 nov; antes, al reporte).
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

Pantalla mínima para probar el modo generar; **se pule con RF-26** (Emmanuel desde el 10 nov) (editar, agregar, quitar y
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
- Desde el 11 nov la vista de solo lectura es el editor (sección siguiente). Pendiente: repetir la
  generación (`POST /videos/{id}/generar`) desde la pantalla.

## Editor del SOP (RF-26 y RF-04, 11 nov, ADR-025)

Un solo componente, `SopEditor` (`src/app/sop/sop-editor.ts`), para los dos casos:

- **SOP generado** (`/videos/:id/sop`): `SopGenerado` sigue el avance y, con `listo`, monta el
  editor con el `sop_id` del video. Miniatura por paso (`GET /videos/{id}/thumb?t=`,
  `loading="lazy"`; con la advertencia `sin_imagen` no se pide), tramo del video de cada paso y
  segundos de puntos y palabras clave como botones que abren el video en ese segundo (un
  `<dialog>` con el reproductor, `preload="none"`).
- **SOP de referencia** (`/sops/:id`, ruta directa al editor): advertencias agrupadas por `tipo`
  con su línea, aviso "lo convirtió el modelo, revísalo" con `metodo: "llm"` y "Usar para validar"
  (`/nuevo?sop=ID`). Con `?video=N`, después de guardar ofrece "Revalidar el video N"
  (`POST /videos/{id}/validar`, reusa la segmentación y no repite Whisper). **El video no espera
  la corrección:** se valida en cuanto el SOP está listo (los pasos del video se extraen sin ver el
  SOP, regla 5) y la cola de un trabajador nunca espera a una persona. `/nuevo` muestra el enlace
  "Revisar y corregir el SOP" cuando el SOP quedó con advertencias o lo convirtió el modelo.

Cómo funciona:

- **Borrador y funciones puras** (`src/app/sop/edicion.ts`, pruebas en `edicion.spec.ts`): cada
  paso lleva una `clave` estable y los riesgos apuntan a esa clave, así que reordenar, unir o
  quitar no rompe su `paso`. `aSop` pone los números 1..n y el `paso` de cada riesgo al
  guardar; la persona no escribe el número. `t_inicio` y `t_fin` no se editan (regla 4).
- **Unir con el siguiente paso** (`unirConSiguiente`): nombre del primero (el foco va a su campo);
  descripciones unidas; equipo, puntos de validación, evidencia y campos inferidos sin repetir;
  tiempo sumado; tramo del video con el **mínimo y el máximo** de los dos (en el caso normal, el
  `t_inicio` del primero y el `t_fin` del segundo; así un par reordenado no deja el rango al
  revés ni da 422) y la miniatura sale de ese `t_inicio`; **confianza la menor**; `cita` y
  `fuente` del primero (la del segundo sigue en `evidencia`); los riesgos del segundo pasan al
  unido. Si los responsables difieren, pregunta cuál usar y el elegido sale de `campos_inferidos`.
- **Quitar con deshacer** (pila de la sesión; el último paso no se quita), **agregar** (vacío,
  inferido con confianza baja y `revisado`, porque lo escribió una persona) y **reordenar**
  arrastrando el asa (⠿, HTML5 nativo, sin CDK) o con ▲ ▼.
- **Lo que hay que revisar (RF-25):** un campo en `campos_inferidos`, o un dato con fuente
  `inferido` o confianza baja o media, lleva color **y** una leyenda de texto ("Inferido",
  "Confianza media"). Editarlo o pulsar "Confirmar" lo marca `revisado: true` (ADR-025) y, en un
  paso, lo saca de `campos_inferidos`; la fuente, la confianza y la cita no cambian. Lo revisado
  ya no se resalta, también al recargar. Quitar un elemento de una lista borra su evidencia;
  cambiar a mano el responsable o el tiempo borra la de ese campo.
- **Cuadro resumen:** título, versión y los cinco datos como texto (vacío → `null`); equipo de
  operación y roles como chips (`src/app/sop/chips.ts`); riesgos (con nivel, paso y control) y
  qué hacer en caso de falla como filas con agregar y quitar. Personas, solo lectura. La duración
  total se muestra como quedará al guardar (`PUT /sops/{id}` la pone al día, ADR-025): **la que
  narró el operador, si la hay** (`generacion.duracion_narrada`, ADR-021: gana e incluye pausas);
  si no, la suma de los pasos si todos tienen tiempo, la del documento si ninguno y vacía si solo
  algunos. La pantalla dice de cuál salió.
- **Puntos clave:** se editan y se quitan. **Palabras clave:** solo lectura (las menciones las
  cuenta el código), como tarjetas (`src/app/sop/palabras-clave.ts`): término, categoría y
  menciones arriba y los segundos abajo, en varias líneas. Si el componente mide 34 rem o más
  (container query, no el ancho de la ventana), se alinean como una tabla.
- **Guardar:** `PUT /sops/{id}` con el SOP completo y luego `GET /sops/{id}` para comprobar que
  el orden, las listas y los números quedaron como se veían (`huella`: JSON con claves ordenadas
  y sin la duración total). Un 422 lista cada campo ("Paso 4 · nombre: …", `erroresPorCampo` en
  `api/errores.ts`) y lo marca sin perder lo editado; un 409 dice "el SOP todavía no está listo".
  "Guardar en la biblioteca", "Descargar .md" (`GET /sops/{id}.md`) y "Usar para validar" quedan
  deshabilitados con cambios sin guardar. Salir con cambios pregunta (`sinGuardar` en las dos
  rutas y `beforeunload`).
- **360 px (RNF-13):** los pasos son tarjetas, no una tabla, y las rejillas se abren en dos
  columnas desde 40 rem. Todo lo que se toca mide al menos 24 px (WCAG 2.5.8): la × de los chips
  y los segundos, 36 px; el asa de arrastre, 28 × 36 (en un teléfono se reordena con ▲ ▼).
  Revisado el 12 nov en Edge headless a 360 × 780 con el build de producción: ningún desborde
  horizontal, también tras unir, reordenar y agregar un chip de 70 caracteres sin espacios, y el
  diálogo del video cabe (322 × 218 px). Los estilos de los controles del formulario están en `src/styles.scss`
  bajo `app-sop-editor`, para que los chips los compartan.
- `generacion.grupos` no se toca: registra cómo agrupó el modelo, no lo que editó la persona.

## Biblioteca y Nuevo análisis (RF-05, RF-07, 12 nov)

Menú en `app.html`: **Biblioteca** (`/sops`) y **Nuevo análisis** (`/nuevo`), con
`routerLinkActive` y `aria-current`.

**`/sops` (`src/app/biblioteca/`).** `GET /sops` da los SOP listos y guardados con cuántos videos
se validaron con cada uno. Búsqueda por título o código sin acentos ni mayúsculas
(`biblioteca/filtro.ts`, la usa también `/nuevo`) y filtro por origen. Por SOP: **Ver o editar**
(`/sops/:id`), **Usar para validar** (`/nuevo?sop=ID`) y **Eliminar** con confirmación en la propia
fila (sin `confirm()`), que avisa que en un SOP cargado se borra también el archivo original y que
no se puede deshacer. `DELETE /sops/{id}` responde 409 si algún video o reporte lo usa: la fila
muestra el `mensaje` de la API en ámbar ("no se puede eliminar: 1 video lo usa como
referencia…"); `mensajeDeError` ya trata el 409 como una frase de la API. **Subir SOP** (uno o
varios) usa `POST /sops` y deja una fila provisional que consulta el estado cada 2 s; con `listo`
recarga la lista y marca el SOP como nuevo (con advertencias o `metodo: llm`, enlace "Revísalo");
con `error`, el mensaje y **Descartar**, que borra ese SOP (nadie lo usa).

**`/nuevo`, tres modos excluyentes** (radios): **De la biblioteca** (`SelectorSop`, búsqueda y
lista con alto máximo; `POST /videos` con ese `sop_id`, sin `POST /sops`, y al 202 al avance),
**Subir uno ahora** (el flujo de siempre) y **No tengo SOP** (modo generar). Empieza en la
biblioteca si tiene algo; si está vacía o no responde, en "Subir uno ahora". `?sop=ID` llega en la
biblioteca con ese SOP elegido. Título y **consentimiento (RNF-16)** obligatorios en los tres: la casilla confirma que las
personas grabadas dieron su consentimiento y avisa que sus rostros y voces son datos personales
(LFPDPPP). El documento del patrocinador no da texto literal; esta redacción es la del equipo.

**Casilla de imágenes (ADR-024).** Aparece al elegir el video. Antes de subirlo, el navegador lee
la duración y si hay imagen (`api/metadatos-video.ts`: `<video preload="metadata">`, token
`METADATOS_VIDEO` para sustituirlo en las pruebas) y se pide `GET /videos/estimacion` con el modo y
el `sop_id` (solo en "De la biblioteca"); se repite al cambiar de video, de modo o de SOP
(`toObservable` + `switchMap`). La casilla arranca con `analizar_imagenes_defecto` hasta que la
persona la toca. Prendida: "≈ N imágenes · +X s" (los segundos del `dispositivo` probable; con
`dispositivo_supuesto`, "(estimado)") y, sin GPU o si no se supo, el `aviso` del servidor en
ámbar. **Nunca se deshabilita por falta de GPU**; sí con `videoWidth === 0` ("este archivo no
tiene imagen"), y entonces la estimación va con `sin_imagen=true`. `analizar_imagenes` viaja
siempre en `POST /videos`, también en `false` (`SubidaVideo.analizarImagenes` es obligatorio).

**360 px (RNF-13).** La biblioteca son tarjetas y, desde 60 rem del propio componente (container
query), filas de tabla con cabecera; en `/nuevo` la lista de SOP es una columna flex (una rejilla
con alto máximo encima las filas). Todo lo que se toca mide 36 px. Revisado el 12 nov en Edge
headless a 360 × 780 y 1280 con el build de producción y 29 SOP (8 inventados de títulos largos,
uno de 100 caracteres sin espacios): ningún desborde horizontal ni objetivo menor de 36 px en la
biblioteca (búsqueda, filtro, confirmación, aviso 409, fila provisional en error y descartada) ni
en `/nuevo` en los tres modos (con imagen, casilla prendida y archivo solo de audio).

## Procesando: avance en vivo por etapa (RF-08, 12 nov)

**Una sola fuente del avance: `src/app/avance/`.** `AvanceVideo` (servicio que provee cada
componente en `providers`, así muere con él) consulta `GET /videos/{id}` cada 1.5 s y se detiene
con `listo`, `error` y `afinidad_baja`, con `detener()` y al destruirse el componente. Sin red o
con un 5xx reintenta con espera creciente (1.5, 3, 6… hasta 30 s) y lo dice ("Reintento N en
X s"); un 404 detiene la consulta con el mensaje. El porcentaje que expone nunca retrocede dentro
de un seguimiento (100 con `listo`) y mide el tiempo en la pantalla. `etapas.ts` es la única tabla
de nombres de etapa (también la usa "Cómo se obtuvo" del reporte) y el orden por modo. La usan
Procesando, el reporte y el SOP generado; antes cada uno tenía su tabla y su intervalo.

**`/videos/:id/procesando` (`src/app/procesando/`).** Etapas en el orden real (validar:
duracion, audio, transcripcion, [fotogramas], contexto, segmentacion, emparejamiento, reporte;
generar: las tres primeras, [fotogramas], contexto, segmentacion, sop_pasos, sop_resumen,
sop_claves), cada una pendiente, en curso, hecha, falló o detenida. `fotogramas` aparece solo con
`analizar_imagenes` de `GET /videos/{id}` (columna `videos.analizar_imagenes`, migración 0007,
guardada ya resuelta). Durante esa etapa: "8 de 20 imágenes · faltan ~2 min", con la cuenta de
la API tal cual (`imagenes_hechas` e `imagenes_total`, al día por lote) y lo que falta con los
segundos por imagen de `GET /videos/estimacion` (se pide una vez; sin ella, solo la cuenta). El
número salta de varias en varias porque así se describen, y la pantalla no habla de lotes. Dispositivo: el plan de `GET /health` (Whisper GPU o CPU; Gemma CPU forzada, GPU, o "lo
decide Ollama"). Transcripción en vivo: `GET /videos/{id}/transcripcion.txt` cada 2 s mientras
Whisper puede escribir (una lectura más al pasar de la transcripción), con desplazamiento
automático si la persona está al final y "Descargar TXT" (el parcial, tal como va).

- **Al terminar** (`replaceUrl`, para que "atrás" no regrese aquí): validar → reporte; generar
  → `/videos/:id/sop`; `afinidad_baja` → reporte, donde está el aviso con "Continuar".
- **Error:** el mensaje de la API tal cual y "Reprocesar", que llama a `POST /videos/{id}/validar`
  o `/generar` según el modo: nunca repite Whisper (ADR-019). Si no hay análisis guardado (p. ej.
  "interrumpido por reinicio" durante la transcripción), muestra el 409 de la API ("vuelve a
  subirlo") y el enlace a Nuevo análisis. No hay endpoint `/reprocesar`.
- `/nuevo` navega aquí al enviar en los tres modos (con advertencias del SOP subido, el botón es
  "Ver el avance"). No va en el menú: es de un video. El reporte y el SOP generado enlazan aquí
  ("Ver el avance por etapa").
- **360 px (RNF-13):** una columna; desde 40 rem del componente los datos van en fila. Objetivos
  de 36 px. Revisado el 12 nov en Edge headless con el build de producción y la API simulada
  (video en proceso con imágenes, en error de Gemma en modo generar e interrumpido por reinicio,
  título de 90 caracteres y una palabra de 70 sin espacios en la transcripción) dentro de un marco
  de 360 × 780 (Edge headless no baja de ~480 px de ventana) y a 1280: ningún desborde horizontal
  ni objetivo menor de 36 px.

**Sondeo, no SSE ni WebSocket.** Con un solo trabajador y pocas pantallas abiertas, cada consulta
es una lectura por id. Así lo pidió el issue #9; SSE queda como propuesta, sin implementar.

## Subida por partes y AVI (RF-06, 12 nov, issue #10)

`/nuevo` sube el video **siempre por partes** (`src/app/subida/`), en los tres modos; un video
chico es una sola parte. La subida simple de la API (`archivo` en `POST /videos`) se queda para los
scripts y las pruebas; la pantalla ya no la usa.

- **Flujo:** `POST /uploads` (`{nombre, tamano}`; la API responde `tamano_parte`, 16 MB) →
  `PUT /uploads/{id}?offset=N` con `Blob.slice`, una parte tras otra → `POST /videos` con
  `upload_id` y los mismos campos de siempre (`titulo`, `modo`, `sop_id`, `idioma`,
  `analizar_imagenes`, que viaja siempre). Al 202 sigue igual: a `/videos/:id/procesando`.
- **Reintentos:** cada parte se reintenta hasta 3 veces con espera de 1, 2 y 4 s ("Reintento 1 de
  3 en 1 s"). Antes de cada reintento se pregunta `GET /uploads/{id}`: si la parte sí llegó (se
  perdió la respuesta) no se repite. Un 409 trae `detail.offset` y se sigue desde ahí. 404, 413 y
  415 no se reintentan.
- **Si aun así falla:** "Se perdió la conexión con la API después de 3 reintentos. Van 1.0 de 3.0
  MB; al reintentar, la subida sigue desde ahí", con **Reintentar la subida** (retoma el mismo
  `upload_id` desde `GET /uploads/{id}`, nunca desde 0) y **Cancelar**. Si la subida ya no está en
  la API (se canceló o caducó), el reintento abre otra.
- **Barra:** porcentaje y "X de Y MB" (MiB, como `SUBIDA_MAX_MB`), con el avance dentro de la parte
  en vuelo. **Cancelar** aborta la parte en vuelo y borra lo recibido (`DELETE /uploads/{id}`,
  RNF-09); elegir otro video o un SOP que no se pudo convertir también la borra. El SOP subido ahora
  queda guardado: al validar de nuevo solo se sube el video.
- **Arrastrar y soltar:** el de siempre, sobre el `<input type=file>` nativo; no hay zona propia.
- **AVI:** se acepta y se analiza, pero Chrome y Edge no lo reproducen. El reporte y el diálogo del
  video del editor del SOP lo dicen ("El navegador no reproduce este formato") con **Descargar el
  video**, y los segundos siguen a la vista. Como `MediaError` 4 llega igual con un archivo que
  falta, se pide su primer byte (`Range: bytes=0-0`, `ApiService.videoDisponible`) antes de decir
  "formato" (`src/app/api/reproductor.ts`). Pasar el AVI a MP4 sin recodificar queda para S6.
- **360 px (RNF-13):** Cancelar y Reintentar miden 40 px de alto; el porcentaje y los MB bajan de
  línea antes que desbordar. Revisado el 12 nov en Edge headless (DevTools, 360 × 780 y 1280) con
  el build de producción y la API simulada, un archivo de 3 MB en partes de 1 MB y un título de 66
  caracteres: subida en curso, fallando (red cortada tras la primera parte, tres reintentos) y
  cancelada. Ningún desborde horizontal ni objetivo nuevo menor de 36 px. A 1280 px, la fila de la
  casilla "Analizar también las imágenes" (PS3) mide 24 px de alto: queda anotado, no se tocó.
- Pruebas: `subida/partes.spec.ts` (partidor), `subida/subida.service.spec.ts` (orden, reintento,
  reanudación, 409, 413, cancelar) y `nuevo/nuevo.spec.ts`.

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
- Commits en español con Conventional Commits (`feat(frontend): …`). El repositorio de
  desarrollo es público (10 nov): ni material del cliente ni texto literal del documento del
  patrocinador en commits, issues o PR.
