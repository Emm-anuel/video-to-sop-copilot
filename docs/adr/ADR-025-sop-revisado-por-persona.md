# ADR-025 · SOP revisado por una persona: `revisado` en el contrato y duración total al guardar

- **Estado:** Aceptado
- **Fecha:** 2026-11-11 (duración narrada y recorte del SOP, 12 nov)
- **Autores:** Emmanuel Merida
- **Decisores:** equipo

---

## Contexto

El editor del SOP (RF-26 para el generado, RF-04 para el convertido de PDF o Word) resalta lo
inferido y lo de confianza baja o media (RF-25) para que alguien lo revise. Hacían falta dos
cosas que el contrato no tenía:

1. **Decir "lo revisó una persona".** En un paso basta con sacar el campo de `campos_inferidos`,
   pero los datos del cuadro resumen, los riesgos, las fallas y los puntos clave solo tienen
   `fuente` y `confianza`. Sin un campo nuevo, el resaltado volvía al recargar.
2. **La duración total después de editar.** Si alguien quita o agrega pasos,
   `resumen.duracion_total_min` se queda con el valor de antes. Es un número visible, sale en el
   PDF (S6) y `tiempos.esperado_total` lo usa como referencia del reporte.

## Opciones (punto 1)

| Opción | A favor | En contra |
|---|---|---|
| A · `revisado: bool = False` en `Dato`, `Riesgo`, `Falla`, `PuntoClave` y `PasoSOP` | Conserva `fuente`, `confianza` y cita (RF-25 pide decir de dónde sale el dato); valor por defecto, los JSON guardados siguen validando | Un campo más en cinco modelos |
| B · `"persona"` como valor de `FuenteSOP` | Sin campo nuevo | Pierde de dónde salió el dato |

## Decisión

- **A.** `revisado` se pone en `true` cuando una persona edita o confirma el dato en el editor.
  Un dato revisado ya no se resalta, y eso persiste al recargar. `fuente`, `confianza`, `cita` y
  `t` no cambian. En un paso, `revisado` se refiere a la confianza del paso; cada campo sin
  evidencia sigue en `campos_inferidos` hasta que se edite o se confirme. Al unir dos pasos,
  el resultado queda revisado solo si los dos lo estaban.
- **Duración total:** `PUT /sops/{id}` la pone al día por código
  (`tiempos.con_duracion_recalculada`), para que no quede mintiendo si se quitan pasos, sin pisar
  la evidencia del operador:
  1. **Con total narrado** (`generacion.duracion_narrada`): se conserva. Lo narrado gana
     (ADR-021) e incluye pausas que la suma de los pasos no captura.
  2. **Sin él y con todos los pasos cronometrados:** la suma de `tiempo_esperado_min`.
  3. **Sin tiempos en los pasos:** el que había (un SOP cargado que solo da el total del
     documento).
  4. Con tiempo solo en algunos pasos (p. ej. uno agregado a mano sin tiempo): `null`, porque una
     suma parcial engañaría (la misma regla que `tiempos.esperado_total`).

  El editor muestra la duración con esta misma regla y dice de dónde sale (narrada o suma).
- **`generacion.grupos` no se toca:** registra lo que hizo el modelo, no lo que editó la persona
  (lo dice su descripción en el contrato).

## Consecuencias

- Nada del emparejamiento, el juez, la afinidad ni los tiempos lee `revisado`, así que marcarlo
  no mueve el porcentaje. Lo que sí lo mueve es el contenido editado (nombre y descripción se
  vectorizan, ADR-012).
- **`revisado` nunca va en un esquema del LLM** (regla 4): si se colara, Gemma podría marcar como
  revisado por una persona un dato que inventó. Los esquemas que van a Ollama son modelos
  `*Libre` aparte del contrato; `tests/test_esquemas_llm.py` recorre todos (y descubre los
  nuevos) y falla si alguno lo lleva.
- **Recortar el SOP de referencia sube el cumplimiento.** El porcentaje (§5.6, `reporte.porcentaje`)
  es (Cumple + 0.5 × (Parcial + fuera de orden)) / pasos del SOP, y un *Sobra* no resta. Si
  alguien quita del SOP un paso que el operador sí hace, baja el denominador y ese tramo del video
  queda como *Sobra*, sin castigo: el porcentaje sube sin que el video haya cambiado. Es inherente
  a la fórmula, no un error del editor. Unir pasos también cambia el porcentaje (el paso unido se
  vectoriza con las dos descripciones), y reordenar mal lo baja (fuera de orden vale 0.5). Para
  medir RNF-05 con un SOP editado se unen pasos, no se quitan, y el número oficial es el de
  `scripts/medir_sop_generado.py` por tramos contra el SOP escrito a mano, no el cumplimiento del
  reporte.
- La plantilla Markdown (`GET /sops/{id}.md`) no lleva `revisado`, igual que la evidencia: solo
  viaja en el JSON.
- Esquemas regenerados (`sop.schema.json` y `contexto.schema.json`, que usa `Dato`), tipos del
  frontend (`npm run tipos`) y fixtures con `"revisado": false`.
