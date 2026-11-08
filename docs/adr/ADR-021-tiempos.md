# ADR-021 · Tiempos: duración narrada o medida, solo *excede* cuenta

- **Estado:** Aprobado por el equipo (8 nov)
- **Fecha:** 2026-11-08
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

El documento SOP V1.0 (§5.5, RF-16) pide comparar la duración de cada paso del video con el tiempo
esperado del SOP, la duración total con la del SOP, y el horario o la frecuencia del SOP con lo que se
dice en el video. El video C de la sección 14 lo evalúa: un paso tarda el doble y debe salir
exactamente un *Excede*.

El contrato ya estaba (P0): `TiempoFila` (esperado, observado, origen `narrado` | `medido`, estado
`en_tiempo` | `excede` | `menor` | `sin_referencia`, cita), `TiempoTotal`, `Horario` (con
`no_mencionado`) y `ConteoReporte.pasos_fuera_de_tiempo`. `TOLERANCIA_TIEMPO = 0.20` ya estaba en
`Settings` (RNF-14). Falta la lógica.

Restricciones:

- **Sin LLM.** El LLM no calcula ni escribe tiempos (regla 4 de CLAUDE.md). Todo es código sobre la
  transcripción y los pasos del video; MiniLM solo para comparar el horario.
- **General.** Nada pensado para A, B, C o D: ni frases, ni duraciones, ni tolerancias. Esos videos
  son pruebas de aceptación.
- **El video también es en inglés** (video E): la detección de la duración narrada entiende español
  e inglés.

## Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| A. Solo el tiempo medido (t_fin − t_inicio del paso) | Simple, siempre disponible | Una espera con corte o en silencio ("espero 5 minutos") no se ve en el video |
| B. La duración narrada siempre gana sobre la medida | Respeta lo que dice el operador | "Esto tarda 30 segundos" (lo que *debería* tardar) esconde un paso que tardó 70 s: el *Excede* se pierde |
| **C. La narrada gana solo si es ≥ la medida** | Cubre las esperas; el video es una cota inferior de lo que tardó | Una narración que exagera alarga el paso (se ve en la cita) |

Para detectar la duración narrada: (1) cualquier cantidad con unidad de tiempo, (2) con disparador
en una lista blanca, (3) con lista negra de acciones breves ("presionar", "mantener"). La 1 toma "tres
segundos" de un botón; la 3 depende de adivinar todas las acciones. Se elige la 2.

## Decisión

### 1. Duración observada de un paso

- **Medida:** `(t_fin − t_inicio) / 60` del paso del video ya fusionado (ADR-013). Un paso fusionado
  usa su tramo completo (del primer inicio al último fin de sus originales, como lo deja `fusionar`);
  personas, en cambio, usa el original citado (ADR-020). `t_fin` es el fin del último segmento del
  paso: la pausa hasta el siguiente paso no se mide.
- **Narrada:** si en el tramo hay una duración narrada (regla de abajo) y es **≥ la medida**, esa es
  la observada, con `origen="narrado"` y su cita. Si es menor, gana la medida (`origen="medido"`, sin
  cita): el video muestra que el paso tardó al menos eso.
- La intro y el cierre del operador (ADR-016) son pasos del video aparte, marcados en un *Sobra*:
  nunca caen dentro del tramo de un par. Una intro solo entraría en el paso 1 si MiniLM la fusiona con
  él (coseno ≥ `UMBRAL_FUSION`), es decir, si habla del paso.

### 2. Regla de la duración narrada (`lenguaje/tiempos.py`, `duracion_narrada`)

Sobre los segmentos que **empiezan** dentro del tramo, en una copia del texto en minúsculas y sin
acentos (de la misma longitud, para cortar la cita del texto original):

1. **Cantidad + unidad de tiempo.** Unidades: segundo(s)/seg, minuto(s)/min, hora(s)/hr y
   second(s)/sec, minute(s)/min, hour(s)/hr (sin "s" ni "h" sueltas). Cantidades en cifra (`5`,
   `1.5`, `1,5`) o en letra de 0 a 99 en español ("veinticinco", "treinta y cinco") e inglés
   ("twenty-five"); "un/una/a/an" = 1. Fracciones y giros: "medio minuto", "media hora", "un cuarto
   de hora", "un minuto y medio", "un par de", "half a minute", "half an hour", "a quarter of an
   hour", "a minute and a half", "one and a half", "a couple of". Rangos ("entre 5 y 10", "de 5 a 10",
   "5-10", "between 5 and 10", "5 to 10") dan el punto medio. Compuestas ("un minuto y treinta
   segundos", "2 minutes and 30 seconds") se suman.
2. **Disparador obligatorio (lista blanca).** La cantidad solo cuenta si en la misma cláusula (sin
   `. ; : ? !` de por medio) y a lo más 6 palabras antes hay un verbo o sustantivo de duración:
   tardar, durar/duración, demorar, tomar, llevar, esperar/espera, aguardar, dejar, reposar/reposo;
   take, last, wait, let, leave, sit, rest. También cuenta "N minutos de espera / de reposo" y
   "a N-minute wait".
3. **"durante", "por" y "for" no son disparadores por sí solos:** solo pueden ir entre el disparador y
   la cantidad ("espero durante 5 minutos", "wait for 5 minutes"). "Mantengo presionado el botón
   durante tres segundos" y "presiono tres segundos el botón" no cuentan. "2 bar" y "un cuarto de
   vuelta" no tienen unidad de tiempo y nunca cuentan.
4. Si hay varias, la del segmento más temprano del tramo (y dentro de él, la primera).
5. La cita es el fragmento literal desde el disparador hasta la unidad; el segundo, el inicio de su
   segmento (regla 4).

**Ante la duda, no se usa:** es preferible caer al tiempo medido que tomar una cantidad equivocada.

### 3. Estado de un paso

`comparar(esperado, observado, tolerancia)`: sin esperado (o esperado ≤ 0) → `sin_referencia`;
dentro de ±`TOLERANCIA_TIEMPO` × esperado (inclusive) → `en_tiempo`; arriba → `excede`; abajo →
`menor`. El observado se redondea a dos decimales antes de comparar, para que el estado cuadre con lo
que se muestra. Solo los pares (Cumple, Parcial, *sin revisar*, con o sin fuera de orden) llevan
tiempo; Falta y Sobra van sin tiempo (un Sobra no tiene esperado).

**Solo *excede* cuenta en `pasos_fuera_de_tiempo`.** *Menor* se muestra, pero es más rápido de lo
esperado, no un incumplimiento. El porcentaje de cumplimiento (§5.6) no cambia: el tiempo se muestra
junto a él.

### 4. Total y horario

- **Total:** suma de los observados de los pares (Falta y Sobra no suman) contra
  `resumen.duracion_total_min`; si el SOP no lo trae, contra la suma de los esperados, solo si todos
  los pasos tienen tiempo (una suma parcial engañaría). Sin ninguno de los dos, `sin_referencia`.
- **Horario:** el `horario_frecuencia` del SOP contra el `horario_mencionado` de la ficha (solo si
  trae su segundo; uno inferido no es evidencia). Sin horario en el SOP → `sin_referencia`; el SOP lo
  define y el video no → `no_mencionado` (contrato de P0). Si los dos están: `coincide` si una
  alternativa del SOP (partido en ", o", ";" y " o cuando") está contenida en lo dicho o al revés,
  tras normalizar (minúsculas, sin acentos, números en letra a cifra), o si el coseno MiniLM en
  minúsculas (como ADR-020) es ≥ `UMBRAL_HORARIO` (0.75, sin calibrar); si no, `distinto`. Sin
  calcular fechas. La cita es el segmento de la transcripción que empieza en ese segundo.

Si la validación se detiene por afinidad baja (ADR-020), no se calculan tiempos.

## Consecuencias

- **Positivas:** todo tiempo sale de la transcripción y es reproducible (no depende de Gemma más que
  por las fronteras de los pasos). La tolerancia y el umbral del horario están en `Settings` y se
  registran en `Umbrales` del reporte.
- **Negativas / riesgos:**
  - Las fronteras de los pasos son de Gemma (ADR-010): un paso partido en dos y no fusionado deja un
    pedazo como *Sobra* y subestima la medida; uno que absorbe al siguiente la sobreestima.
  - La medida no incluye la pausa después del último segmento del paso.
  - El disparador no sabe de qué habla ("el agua tarda 3 segundos en salir" se toma, aunque al ser
    menor que la medida no cambia nada). "Caliento durante 5 minutos" no se detecta (sin verbo de
    duración) y cae a la medida. Números en letra solo hasta 99; "un ratito" o "unos cuantos minutos"
    se ignoran a propósito.
  - Con SOP de pasos cortos (0.5 min) y ±20 %, una narración ágil sale *menor* en casi todos los
    pasos; no cuenta como incumplimiento, pero se ve en el reporte.
- **Seguimiento:** medición con A, B y C (abajo). Calibrar `UMBRAL_HORARIO` cuando haya más SOP con
  horario.

## Medición

_Se llena con `scripts/medir_tiempos.py` (commit de la medición)._

## Referencias

- Documento SOP V1.0, §5.5, §5.6 y §14; RF-16, RNF-14.
- ADR-010 (fronteras de los pasos), ADR-013 (fusión), ADR-016 (intro y cierre), ADR-020 (afinidad y
  MiniLM en minúsculas).
