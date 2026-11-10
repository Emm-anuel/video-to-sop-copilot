# ADR-020 · Afinidad y personas con MiniLM

- **Estado:** Propuesto
- **Fecha:** 2026-11-08
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

El documento SOP V1.0 pide dos revisiones más del video contra el SOP, además de los pasos:

- **§5.2 / RF-17, afinidad:** *antes de comparar pasos*, contrastar la ficha de contexto del video
  (actividad, lugar, equipos, propósito) con el objetivo, el alcance y el equipo del SOP, y dar una
  afinidad de 0 a 100 con su explicación. Con menos de 60, la app muestra "El video parece no
  corresponder a este SOP" y quien carga decide si continúa (video D de la sección 14).
- **§5.4 / RF-15, personas:** cada rol del SOP es *Presente*, *Mencionado* o *Ausente* entre las
  personas del video, y para cada paso emparejado el responsable del SOP *Coincide*, es *Distinto*
  o *No identificado* frente a quien lo hace (video C: "otra persona hace 1 paso").

Ya existen el contrato (P0: `Afinidad`, `RolReporte`, `ResponsableFila`, `ConteoReporte.personas_con_diferencias`
y el validador `ReporteValidacion._coherente`) y la ficha de contexto (P2, `percepcion/contexto.py`:
`Contexto` con `Dato` por campo y `Persona` con nombre, rol, participación, segundo y cita
verificada). Falta la lógica, el flujo de la advertencia y llenarlo en el reporte.

Restricciones:

- **Sin Gemma.** Todo es MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`, siempre en CPU, ADR-012)
  y código: el resultado no depende del dispositivo (RNF-07), solo de la ficha que entra.
- **General.** Nada en el código pensado para A, B, C o D: ni nombres, ni frases, ni equipos, ni
  umbrales ajustados para que un video pase. Los videos son pruebas de aceptación.
- **Umbrales en Settings** (RNF-14), marcados "sin calibrar" hasta tener C–E.
- **Regla 4.** Todo segundo y toda cita salen de la ficha (que ya los verificó contra la
  transcripción) o de la transcripción; ningún nombre que no esté en la ficha.

### Sonda del 8 nov (MiniLM real, textos inventados por el equipo)

Antes de proponer números se midieron cosenos con el SOP del fixture (`sop_filtro_agua.md`), la
ficha de A guardada en `docs/adr/datos/contexto/` y textos inventados de café y minisplit. Es una
sonda para elegir el diseño, no una calibración.

| Par | Coseno |
|---|---|
| "Técnico de mantenimiento" ~ "técnico de mantenimiento" | 0.97 |
| "Técnico de mantenimiento" ~ "técnica de mantenimiento" | 0.87 |
| "Técnico de mantenimiento" ~ "Técnico" | 0.79 |
| **"Técnico de mantenimiento" ~ "Supervisor de mantenimiento"** | **0.89** |
| "Técnico de mantenimiento" ~ "Supervisor de turno" | 0.73 |
| **"Técnico de mantenimiento. Ejecuta el cambio completo del cartucho." ~ "técnico de mantenimiento"** | **0.62** |
| núcleo: "técnico" ~ "supervisor" / "técnico" ~ "técnica" / "supervisor" ~ "supervisora" | 0.53 / 0.91 / 0.96 |
| núcleo: "técnico" ~ "operador" / "operador" ~ "operario" / "jefe" ~ "supervisor" | 0.44 / 0.61 / 0.81 |
| SOP del filtro (título + objetivo + alcance + equipo) ~ ficha de A | 0.75 |
| SOP del filtro ~ ficha inventada de minisplit / de café | 0.65 / 0.36 |
| Dos procedimientos distintos con "línea, máquina, botón, panel" / sin esas palabras | 0.69 / 0.57 |
| título del filtro ~ actividad de A / de minisplit / de café | 0.99 / 0.57 / 0.16 |

Tres hallazgos que cambian lo que se había pedido:

1. **El coseno del rol completo confunde puestos distintos del mismo área** (técnico y supervisor
   de mantenimiento, 0.89, más que "Técnico" solo, 0.79). Lo que distingue un rol es su núcleo
   ("técnico", "supervisor"), no el complemento ("de mantenimiento").
2. **La descripción del rol estorba:** el mismo rol con su descripción baja a 0.62. Comparar "rol +
   descripción" contra el rol de la persona dejaría casi todos los roles en *Ausente*.
3. **El coseno global no basta para la afinidad:** el procedimiento cercano (0.65) y el que solo
   comparte palabras genéricas (0.69) quedan cerca del mismo procedimiento (0.75). Hace falta
   comparar por campo y quitar las palabras genéricas.

## Opciones consideradas

**Afinidad**

| Opción | A favor | En contra |
|---|---|---|
| A · Coseno global × 100 (plan §5.3) | Lo más simple | Sin margen entre "mismo" (0.75) y "cercano" (0.65); las palabras genéricas lo suben; 0.36 daría 36 a algo sin relación |
| B · Global más comparación por campo, cada componente a 0–100 con un mapeo lineal, promedio ponderado por la evidencia de la ficha | Separa por campo; explicación armada con lo que se comparó; mapeo explícito en Settings | Más parámetros que calibrar (dos cortes del mapeo, un umbral de equipo, pesos) |
| C · Gemma como juez de afinidad | Entiende matices | Descartada: costo en CPU, no determinista (ADR-018) y se pidió sin Gemma |

**Roles**

| Opción | A favor | En contra |
|---|---|---|
| A · Coseno de "rol + descripción" contra el rol de la persona (lo pedido) | Usa toda la información del SOP | El mismo rol queda en 0.62: casi todo saldría *Ausente* |
| B · Coseno del rol completo | Simple | Técnico ~ supervisor de mantenimiento 0.89: *Coincide* falso |
| C · Igualdad normalizada o coseno de los **núcleos** del rol | Separa técnico de supervisor (0.53) y une técnico con técnica (0.91) | Ignora el complemento: "técnico de calidad" coincidiría con "técnico de mantenimiento" |
| C′ · Núcleo y, si los dos roles traen complemento, también el complemento (decidido el 8 nov) | Lo de C, y separa "ingeniera de calidad" de "ingeniero de procesos" | El coseno entre complementos es ruidoso ("turno" ~ "turno matutino" 0.58; "almacén" ~ "bodega" 0.53): se compara primero por palabras |

**Dónde se detiene la validación con afinidad baja**

| Opción | A favor | En contra |
|---|---|---|
| A · Después de segmentar, antes de emparejar (lo pedido) | Al continuar solo falta emparejar | Gasta la segmentación con Gemma (10 s en GPU, ~70 s en CPU) en un video que quizá no se continúa; al continuar, `revalidar` vuelve a segmentar de todos modos (ADR-019 no guarda la segmentación para reusarla) |
| B · Justo después de la ficha, antes de segmentar | La afinidad solo necesita la ficha y el SOP; no se gasta nada que no se use; el documento dice "antes de comparar pasos" | Al continuar, Gemma se vuelve a cargar (5-7 s en GPU, ~25 s en CPU) |

## Decisión

**Afinidad B, roles C′ y detenerse en B** (las tres decididas por el equipo el 8 nov, junto con
`RolReporte.con_pasos`, sección 5). Todo en dos módulos nuevos: `lenguaje/afinidad.py` y
`lenguaje/personas.py` (`emparejamiento.py` ya tiene 650 líneas).

### 1. Afinidad: `afinidad(sop, contexto, embedder) -> Afinidad | None`

**Textos.** Del SOP: título, `resumen.objetivo`, `resumen.alcance` y `resumen.equipo_operacion`
(si viene vacío, el equipo de los pasos sin repetir). Del video: `actividad`, `tema`, `proposito`
y los equipos de la ficha. Antes de vectorizar, a los dos lados se les quitan las **palabras
genéricas** que comparten procedimientos distintos: `afinidad.PALABRAS_GENERICAS` (línea, área,
máquina, equipo, botón, panel, planta, zona, estación, sección, sistema, unidad y sus plurales),
una constante del módulo comparada sin acentos ni mayúsculas. No es una lista de ningún video: es
vocabulario de planta que no distingue procedimientos. Un equipo que solo tiene palabras genéricas
no cuenta en ninguno de los dos lados.

**Componentes.** Cada uno se lleva a 0–100 con el mismo mapeo lineal:

```
m(c) = 100 · min(1, max(0, (c − AFINIDAD_COS_CERO) / (AFINIDAD_COS_CIEN − AFINIDAD_COS_CERO)))
```

| Componente | Qué compara | Valor | Peso |
|---|---|---|---|
| global | texto del SOP ~ texto del video | m(coseno) | 0.30 |
| actividad | título del SOP ~ `actividad` (si viene vacía, `tema`) | m(coseno) | 0.30 |
| objetivo | `objetivo` ~ `proposito` | m(coseno) | 0.20 |
| equipos | cada equipo del SOP contra su mejor equipo de la ficha | 100 × equipos del SOP con mejor coseno ≥ `AFINIDAD_UMBRAL_EQUIPO` / equipos del SOP | 0.20 |
| lugar | `resumen.lugar` ~ `lugar` | solo en la explicación | 0 |

El lugar pesa 0: el documento lo nombra, pero es el dato que más se equivoca (en ADR-018 Whisper
`small` hizo de "línea de enjuague" un "Clínica del jugo" con cita verificada) y dos procedimientos
distintos suelen compartir lugar. Aparece en la explicación.

**Evidencia.** Un dato inferido no debe mover la afinidad igual que uno dicho en el audio, pero
tampoco debe empujarla hacia abajo (que la ficha no esté segura no prueba que el video sea de otro
procedimiento). Por eso la evidencia multiplica el **peso** del componente, no su valor: factor
1.0 con confianza alta, 0.75 media y 0.5 baja o inferido. Los equipos de la ficha no traen
evidencia propia (Gemma los nombra sin cita) y van con 0.75. El componente global usa el promedio
de los factores de los campos que entraron a su texto.

```
afinidad = round( Σ wᵢ·eᵢ·mᵢ / Σ wᵢ·eᵢ )   sobre los componentes que se pudieron calcular
```

Un componente con un lado vacío no se calcula y su peso se reparte entre los demás. Pesos y
factores son constantes del módulo, documentadas aquí; los cortes del mapeo y los umbrales van en
Settings.

**Valores iniciales, sin calibrar:** `AFINIDAD_COS_CERO=0.30` (por debajo, nada en común: café
~ filtro 0.36 en global, 0.16 en actividad), `AFINIDAD_COS_CIEN=0.80` (mismo procedimiento: A
0.75 en global, 0.99 en actividad), `AFINIDAD_UMBRAL_EQUIPO=0.75` y `AFINIDAD_MIN=60` (ya
existe). Con la sonda, A daría ~85, el minisplit ~45 y el café ~5; se mide en la sección de
resultados.

**Explicación (la arma el código).** Una frase por componente, unidas con "; ":

- actividad: "actividad parecida al título" (m ≥ `AFINIDAD_MIN`) · "actividad distinta del título" ·
  "actividad no identificada en el video".
- objetivo: "propósito parecido al objetivo" · "propósito distinto del objetivo" · "objetivo no
  indicado en el SOP" · "propósito no identificado en el video".
- equipos: "4 de 7 equipos del SOP en el video (cartucho, cubeta, …)" (hasta tres nombres, los del
  SOP) · "ningún equipo en común" · "el SOP no lista equipo".
- lugar: "mismo lugar" · "lugar distinto" · "lugar no indicado en el SOP" · "lugar no mencionado
  en el video".
- "(dato inferido)" junto al campo cuya evidencia de la ficha es baja.

Los logs solo llevan el valor y los componentes, nunca la explicación (lleva nombres del SOP).

**Sin ficha** (aviso `contexto_sin_generar`) o con una ficha sin ningún campo comparable:
afinidad `None` y la validación sigue. Con la ficha reusada (ADR-019) la afinidad se recalcula: es
barata y depende de Settings.

### 2. Flujo con afinidad baja

```
ficha → afinidad ─┬─ None o ≥ AFINIDAD_MIN, o continuar=true → pasos → emparejar → personas → reporte
                  └─ < AFINIDAD_MIN y sin continuar → proceso="afinidad_baja" (se detiene)
```

- **Se detiene después de la ficha** (opción B): `validar` devuelve una `Validacion` detenida;
  Gemma se descarga como siempre (`finally`). El procesador guarda la ficha en `videos.contexto`,
  un `Reporte` con `afinidad` = valor, `cumplimiento` NULL (la columna ya acepta NULL) y en
  `resultado` un `DetencionAfinidad` del contrato (versión, `Afinidad`, umbrales, segundos, avisos y
  dispositivos), y deja `proceso="afinidad_baja"`, `etapa="afinidad"`. No hay reporte de pasos.
- **Migración `0005`:** agrega `afinidad_baja` a la CHECK de `videos.proceso` (`PROCESOS_VIDEO`).
  El downgrade pasa esos videos a `error` con un mensaje que dice repetir la validación.
- **`POST /videos/{id}/validar?continuar=true`** repite la validación sin Whisper y con la ficha
  guardada (ADR-019), sin detenerse: el reporte lleva la afinidad con `bajo_umbral=true` (el
  validador de P0 lo exige) y reemplaza a la detención. Sin `continuar`, se recalcula y se detiene
  otra vez si sigue baja. Se acepta en `listo`, `error` y `afinidad_baja`.
- **`GET /videos/{id}`** agrega `afinidad: Afinidad | None`: la de la detención con
  `afinidad_baja` y la del reporte con `listo`. **`GET /videos/{id}/reporte`** sigue en 409 mientras
  el proceso no sea `listo`.
- `frontend/README.md` documenta para la pantalla: con `proceso="afinidad_baja"`, mostrar "El
  video parece no corresponder a este SOP", el valor y la explicación, y un botón "Continuar de
  todos modos" que llama a `POST /videos/{id}/validar?continuar=true` y vuelve a consultar el
  estado.

### 3. Roles del SOP: `emparejar_roles(roles_sop, personas, embedder) -> list[RolReporte]`

**Roles:** `resumen.roles`; si viene vacío, los responsables distintos de los pasos.

**Cuándo un rol coincide con otro** (`personas.roles_coinciden`, la misma regla para roles y
responsables):

Cada rol se parte en **núcleo** y **complemento**, sin acentos, mayúsculas ni artículos (el, la,
los, las, un, una):

- **núcleo:** la primera palabra, en su forma base sin plural ni género ("técnico", "técnica",
  "técnicos" → "tecnic"; "supervisora", "supervisores" → "supervisor"; "jefe", "jefa" → "jef").
  En español el núcleo de un puesto va primero ("técnico de mantenimiento", "jefa de turno").
- **complemento:** las palabras que van después del primer "de" o "del" (sin artículos ni "y"), en
  la misma forma base; vacío si el rol no trae "de". Lo que va entre el núcleo y el "de" (p. ej.
  un adjetivo) no cuenta.

Dos roles coinciden si:

1. **Los núcleos se parecen:** forma base igual (similitud 1.0) o coseno MiniLM entre los núcleos
   ≥ `UMBRAL_ROL`; y
2. **si los dos traen complemento, los complementos también se parecen:** las mismas palabras
   base, o las de uno incluidas en las del otro ("turno" ⊂ "turno matutino"), o coseno entre los
   complementos ≥ `UMBRAL_ROL_COMPLEMENTO`. Si uno no trae complemento, basta el núcleo.

La similitud que se reporta es la menor de las dos que se compararon (1.0 si fueron iguales). La
descripción del rol no entra en la decisión (hallazgo 2). Valores iniciales, sin calibrar:
`UMBRAL_ROL=0.85` (ya existía; ahora sobre núcleos: técnico ~ técnica 0.91 sí; técnico ~
supervisor 0.53 y jefe ~ supervisor 0.81 no) y `UMBRAL_ROL_COMPLEMENTO=0.70` (mantenimiento ~
turno 0.51 y calidad ~ procesos 0.44 no; mantenimiento ~ reparaciones 0.68 y mantenimiento ~
limpieza 0.65 tampoco).

Casos que fijan las pruebas: técnico ~ técnico de mantenimiento → coincide (uno sin complemento);
técnico de mantenimiento ~ supervisor de mantenimiento → no (núcleos); ingeniera de calidad ~
ingeniero de procesos → no (complementos); la supervisora ~ supervisor de turno → coincide.

Limitaciones: sinónimos con palabras distintas que MiniLM no acerca no coinciden (operador ~
operario 0.61, almacén ~ bodega 0.53, jefe ~ supervisor 0.81); un rol con el núcleo después de un
adjetivo ("primer operador") o en inglés ("maintenance technician") toma la palabra equivocada como
núcleo; un complemento sin "de" ("técnico electricista", "operador senior") no se compara; la forma
base es un recorte de terminaciones, no un lematizador, y puede unir dos palabras distintas que
solo difieren en la vocal final.

**Estado de cada rol:** entre las personas de la ficha con rol que coincide, se elige la que
participa, después la de mayor similitud y después la que aparece antes. *Presente* si participa,
*Mencionado* si solo se le nombra, con el `t` y la `cita` de la persona (regla 4); sin ninguna,
*Ausente*.

**Confianza del rol** (campo nuevo `RolReporte.confianza`): la ficha no guarda si el rol de una
persona se dijo o se infirió, así que lo verifica el código: "alta" si el núcleo del rol aparece en
la cita de la persona; "media" si la persona salió de un fotograma (sin cita); "baja" si el rol no
aparece en su cita (Gemma lo infirió). Una persona con confianza baja cuenta, pero el rol queda con
confianza baja.

### 4. Responsable por paso emparejado

Va en los pares: Cumple, Parcial y zona_gris ("sin revisar"), estén o no fuera de orden (el
contrato ya los admite en `ESTADOS_PAR`). Falta y Sobra van sin él. Se comparan **roles**, no
nombres.

**a) Quién hizo el paso**, en este orden:

1. `PasoVideo.responsable`. En un paso fusionado con `responsables_distintos`, el del **original
   citado** (el más parecido al paso del SOP, que ya aporta el nombre, la cita y el segundo de la
   fila, ADR-013), con una nota que lista los demás; la búsqueda de nombres del punto 4 también
   se limita a su tramo. *Primero se propuso "el que suma más tiempo"; el video C lo descartó
   (ver Resultados): una fusión unió el original de quien cierra la llave con un fragmento más
   largo de otra persona, y salía un distinto falso con la cita del primero. Decidido el 8 nov.*
2. Si es el nombre de una persona de la ficha (el nombre, normalizado, aparece como palabras
   completas en el responsable): esa persona.
3. Si es un rol: la persona de la ficha cuyo rol coincide, si es una sola; si no, queda como **rol
   suelto**.
4. Si viene vacío o "No identificado": los nombres de las personas de la ficha que aparecen en la
   narración del tramo del paso (palabras con tiempo entre t_inicio y t_fin, el mismo corte del
   juez); si aparece uno solo, esa persona.
5. Si la ficha tiene una sola persona que participa: esa persona, como **narrador único**.

**b) Rol observado:** el de la persona; el rol suelto, tal cual.

**c) Estado:**

- *coincide* si el rol observado (el de la persona o el rol suelto) coincide con el del SOP.
- *distinto* solo si hay una persona **identificada y distinguible** cuyo rol no coincide:
  distinguible quiere decir que tiene nombre, o que la ficha tiene dos o más personas que
  participan. Con un solo narrador sin nombre no hay otra persona de quien distinguirlo: la
  diferencia de rol aparece en los roles (el del SOP, *Ausente*), no paso por paso.
- *no_identificado* en lo demás: sin persona, rol suelto que no coincide y no corresponde a nadie
  de la ficha, narrador único sin nombre con otro rol, o persona sin rol.

Esto cumple por construcción la regla de que con un solo narrador sin nombre un responsable
genérico ("el operador", "No identificado") da *coincide* o *no_identificado*, nunca *distinto*,
sin una lista de palabras genéricas de responsable.

**d) `observado`:** "Nombre (rol)" si la persona tiene nombre; si no, el rol. Solo nombres de la
ficha, que ya tienen cita verificada; nunca uno inventado.

**Nota** (campo nuevo `ResponsableFila.nota`): por qué camino se identificó (responsable, nombre en
la narración, narrador único) y los casos especiales (fusión con varios responsables, persona sin
rol). La pantalla puede mostrarla como ayuda.

### 5. Reporte y contrato

- `ResultadoValidacion` (lo que se guarda) gana `afinidad`, `roles` y `responsables` (uno por
  resultado de la clasificación, `None` fuera de los pares), opcionales: un reporte guardado antes
  se sigue leyendo, con `None` y listas vacías. `armar_reporte` los copia a `ReporteValidacion` y
  calcula `conteo.personas_con_diferencias`. El porcentaje (§5.6) no cambia.
- **`personas_con_diferencias`** = filas con responsable *distinto* + roles *Ausente* **que son
  responsables de algún paso del SOP** (decidido el 8 nov). Un rol de apoyo o de escalamiento (el
  "Supervisor de turno" del fixture, que solo atiende si algo falla) se muestra con su estado pero
  no suma: un video perfecto no debe mostrar una diferencia por un rol que el SOP no le pide a
  ningún paso. `RolReporte.con_pasos` dice si el rol es responsable de algún paso (comparado con
  la misma regla de roles); el validador `_coherente` de P0 cuenta solo los *Ausente* con
  `con_pasos`. El valor por defecto es `true`, así que la definición anterior se conserva para
  quien no lo llene.
- Campos nuevos, todos opcionales y compatibles: `Afinidad.componentes` (valor 0–100 por
  componente, para medir y para el paper), `RolReporte.confianza`, `RolReporte.persona`
  ("Nombre (rol)"), `RolReporte.similitud`, `RolReporte.con_pasos`, `ResponsableFila.nota` y el
  modelo `DetencionAfinidad`. Los JSON Schema se regeneran con `scripts/exportar_contrato.py`.
- Settings nuevas, sin calibrar: `AFINIDAD_COS_CERO`, `AFINIDAD_COS_CIEN`,
  `AFINIDAD_UMBRAL_EQUIPO` y `UMBRAL_ROL_COMPLEMENTO` (con `.env.example`), además de
  `AFINIDAD_MIN` y `UMBRAL_ROL`, que ya existen. `metadatos.umbrales` registra las nuevas.

## Consecuencias

- **Positivas:** la advertencia de §5.2 llega antes de gastar la segmentación; afinidad, roles y
  responsables son deterministas e iguales en CPU y GPU para la misma ficha; la explicación dice
  qué se comparó; "distinto" exige evidencia de otra persona, así que A y B no pueden dar un
  distinto falso por un responsable genérico.
- **Negativas / riesgos:**
  - Siete parámetros (dos cortes, un umbral de equipo, cuatro pesos) con pocos videos para
    calibrar. Los pesos quedan como constantes para no inflar Settings; si la calibración los
    mueve, pasan a Settings.
  - Todo depende de la ficha: si Gemma deja vacía la actividad o inventa un equipo, la afinidad lo
    hereda (la ficha varía entre corridas, ADR-018). Con fotogramas (RF-11), los equipos vistos
    entran por la misma vía.
  - Las limitaciones de la regla de roles (sección 3): sinónimos que MiniLM no acerca, núcleo que
    no va primero, complemento sin "de", forma base por recorte.
  - Los códigos de equipo ("B-201", el ejemplo del documento) no los entiende MiniLM; hoy no
    suman afinidad.
  - `distinto` depende de que la ficha capture a la segunda persona con nombre o rol; si no, el
    paso sale *no_identificado* (se prefiere no inventar una diferencia).
- **Seguimiento:** medir con A, B (y C, D cuando existan); calibrar los cortes y `UMBRAL_ROL` con
  C–E junto con los umbrales del emparejamiento (`scripts/calibrar_umbrales.py`).

## Decisiones del equipo (8 nov)

1. `personas_con_diferencias` cuenta solo los roles *Ausente* con pasos (`RolReporte.con_pasos`),
   con el cambio en el validador de P0.
2. La validación con afinidad baja se detiene después de la ficha, antes de segmentar.
3. Roles por núcleo y, cuando los dos lo traen, por complemento (opción C′, sección 3).
4. Tras medir el video C: el responsable de un paso fusionado es el del original citado, no el
   que suma más tiempo (sección 4).

## Resultados (8 nov 2026)

PC de referencia (RTX 2070 SUPER), Whisper `large-v3-turbo` en GPU, `gemma4:e4b-it-q4_K_M`,
MiniLM en CPU, valores por defecto (sin calibrar): `AFINIDAD_COS_CERO=0.30`,
`AFINIDAD_COS_CIEN=0.80`, `AFINIDAD_UMBRAL_EQUIPO=0.75`, `AFINIDAD_MIN=60`, `UMBRAL_ROL=0.85`,
`UMBRAL_ROL_COMPLEMENTO=0.70`.

**a) Fichas inventadas con MiniLM real** (`tests/test_afinidad.py -m lento`), contra
`sop_filtro_agua.md` salvo la última:

| Ficha | Afinidad | Componentes (global / actividad / objetivo / equipos) |
|---|---|---|
| Mismo procedimiento | 98 | 100 / 100 / 100 / 86 |
| Procedimiento cercano (minisplit) | **60** | 76 / 64 / 66 / 14 |
| Muy distinto (café) | 1 | 3 / 0 / 0 / 0 |
| Dos procedimientos que solo comparten "línea, máquina, botón, panel" | 16 | 20 / 27 / 8 / 0 |

**b) Videos reales** (`scripts/medir_afinidad.py`, una corrida por video, commit `f602c0f`;
datos en `docs/adr/datos/afinidad/afinidad-20261108-1515.*`):

| Video | Afinidad (componentes) | Se detiene | Roles del SOP | Responsables | Personas con dif. | Criterio |
|---|---|---|---|---|---|---|
| A contra el filtro | 75 (89 / 100 / 0 / 100) | no | técnico presente; supervisor ausente, sin pasos | 6 coincide | 0 | pasa |
| B contra el filtro | 94 (100 / 100 / — / 71) | no | técnico presente; supervisor ausente, sin pasos | 4 coincide | 0 | pasa |
| C contra el filtro | 97 (100 / 100 / — / 86) | no | técnico presente (Emanuel); supervisor presente (Sara), sin pasos | 5 coincide, 1 distinto (paso 4) | 1 | pasa |
| D contra el filtro | 19 (63 / 0 / 0 / 0) | **sí** | técnico ausente | — (al continuar: 6 *Falta*, 10 *Sobra*) | 1 | pasa |

Afinidad de las mismas fichas contra los SOP inventados:

| Ficha de | `sop_otro_procedimiento.md` (café) | `sop_procedimiento_cercano.md` (minisplit) |
|---|---|---|
| A | 3 | 39 |
| B | 12 | 55 |
| C | 6 | 50 |
| D | 0 | 6 |

Explicaciones que armó el código, p. ej. A contra el filtro: "actividad parecida al título;
propósito distinto del objetivo; 7 de 7 equipos del SOP en el video (Guantes de nitrilo, Lentes
de seguridad, Llave de carcasa, …); lugar no mencionado en el video"; D: "actividad distinta del
título; propósito distinto del objetivo; ningún equipo en común; lugar no mencionado en el video".

Lo que dicen los números:

1. **Margen de la afinidad.** El mismo procedimiento dio 75–97 con fichas reales; otro
   procedimiento (D), 19; el cercano, 39–55 con las fichas reales y 60 con la ficha inventada
   (justo en el umbral). El cercano se separa sobre todo por el equipo (1–2 de 5 o de 7): la
   actividad y el objetivo de "cambiar un filtro" se parecen. **Primer mapeo propuesto: dejar
   0.30 / 0.80 y `AFINIDAD_MIN=60`**: con los videos que hay, el hueco entre el mismo
   procedimiento (mínimo 75) y uno distinto o cercano (máximo 55 con fichas reales) contiene al
   60. Son cuatro videos de un solo SOP: falta calibrar con más procedimientos.
2. **El global solo no habría bastado:** D da 63 en el componente global (comparte vocabulario
   de planta con el filtro) y lo separan la actividad, el objetivo y el equipo. Confirma el
   hallazgo 3 de la sonda.
3. **Objetivo contra propósito es el componente más frágil.** En A dio 0: la ficha anotó el
   motivo ("porque el manómetro marca menos de 2 bar") y el SOP la meta ("sin fugas y con la
   presión restablecida"). En B y C la ficha dejó el propósito vacío (una corrida de B sí lo
   llenó: 95 en la primera medición, 94 en esta); el componente se omite y su peso se reparte. Es
   candidato a pesar menos al calibrar.
4. **MiniLM distingue mayúsculas:** "Lentes de seguridad" ~ "lentes de seguridad" da 0.55. La
   afinidad y los roles vectorizan en minúsculas, y los equipos y el lugar también coinciden si
   las palabras de uno están en el otro. **Seguimiento:** el emparejamiento de pasos (ADR-012)
   vectoriza el texto tal cual; revisar si conviene minúsculas al recalibrar sus umbrales.
5. **Roles.** En los cuatro videos todas las comparaciones se decidieron por el núcleo (técnico
   con técnico, forma base igual; supervisora con técnico, núcleos distintos): el complemento y
   `UMBRAL_ROL_COMPLEMENTO` solo se ejercitaron en las pruebas. **Propuesta: dejar
   `UMBRAL_ROL=0.85` y `UMBRAL_ROL_COMPLEMENTO=0.70`** hasta tener roles más variados. El
   "Supervisor de turno" del SOP queda ausente en A y B y presente en C, sin contar como
   diferencia (no es responsable de ningún paso).
6. **Video C.** La primera medición (commit `10172ba`) dio *distinto* en los pasos 2 y 4: el
   paso del video emparejado con SOP 2 era una fusión (ADR-013) del original de Emanuel cerrando
   la llave (el que da la cita) con un fragmento más largo en que entra Sara, y la regla "el que
   suma más tiempo" eligió a Sara. Con la regla del original citado (sección 4, decidida el 8
   nov) queda un solo *distinto*, el paso 4. En ese paso la segmentación escribió
   `PasoVideo.responsable = "Supervisora de turno"` y el camino fue el 3 de la sección 4.a (un rol
   que coincide con el de una sola persona de la ficha, Sara). El camino de los nombres en la
   narración no se ejercitó con videos reales, solo en las pruebas.
7. **D.** Se detiene tras la ficha (sin segmentar). Al continuar, los 6 pasos del SOP quedan en
   *Falta* y los del video en *Sobra* (intro y cierre marcados, ADR-016); el reporte lleva la
   afinidad con `bajo_umbral=true`.
8. **Regresión del MVP** (`scripts/medir_mvp.py`, A y B, 3 corridas, commit `10172ba`;
   `docs/adr/datos/mvp/mvp-20261108-1502.*`): B pasa 3 de 3 (66.67 %, *Falta* 2 y 6, el
   agregado como *Sobra*); A pasa 2 de 3 (100 %) y la otra no es válida por
   `pasos_sin_redactar` (Gemma dio una cita de 3 palabras), la variación de Gemma que ya registra
   ADR-018; este ADR no toca la segmentación. Ninguna corrida se detuvo por afinidad.

## Referencias

- Documento SOP V1.0, §5.2, §5.4, §5.6, §10 (esquema del reporte) y §14 (videos C y D); RF-15,
  RF-17, RNF-07, RNF-14.
- ADR-012 (MiniLM en CPU), ADR-016, ADR-018 (variación de la ficha), ADR-019 (repetir la
  validación sin Whisper).
