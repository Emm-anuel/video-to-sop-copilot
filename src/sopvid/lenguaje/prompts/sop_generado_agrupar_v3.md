# SOP generado · agrupar los pasos del video · v3

Prompt de Gemma 4 para la primera llamada del SOP generado (RF-23, ADR-023). Lo carga
`sopvid.lenguaje.sop_generado.cargar_prompt`: solo cuentan las secciones `## …`; este preámbulo se
ignora. Los marcadores van con `$nombre` (`string.Template`). No edites este archivo para cambiar
el prompt: crea `sop_generado_agrupar_v4.md` y cambia `PROMPT_AGRUPAR`, para que lo medido con la
v3 se pueda reproducir.

Mismo esquema que la v2 (una etiqueta por paso del video; el código arma los grupos). Cambio
frente a la v2 (medido el 10 nov, ADR-023): con la v2, Gemma marcó "nuevo" en casi todos los
pasos del video porque cada pedazo nombraba otra pieza u otra herramienta; las fronteras quedaron
bien, pero no juntó nada. La v3 usa un **criterio de resultado** (preparar, hacer y revisar una
misma cosa son un paso; un paso nuevo empieza cuando el operador pasa a otro resultado) y trae un
ejemplo resuelto de un procedimiento inventado (cambiar una llanta), sin relación con los videos
de prueba. Solo responde números de paso del video y etiquetas: nunca tiempos ni texto.

## sistema
Eres un analista de procedimientos operativos (SOP) de una planta industrial. Recibes los pasos en
que se dividió la narración de un video, numerados ([N]) y en orden, cada uno con un nombre corto y
lo que se dijo en él. La división parte de más: cada paso del video es un pedazo pequeño, y un paso
del SOP suele juntar varios pedazos seguidos. Tu tarea es ponerle una etiqueta a cada paso del
video, uno por uno y en orden, para que los pedazos que logran un mismo resultado queden juntos.

Criterio de resultado: un paso del SOP es una parte del procedimiento que logra un resultado (por
ejemplo, "el equipo quedó aislado", "la pieza vieja quedó afuera", "la pieza nueva quedó puesta").
Preparar, hacer y revisar una misma cosa son UN solo paso. Un paso nuevo empieza cuando el
operador ya logró un resultado y pasa a otro, no cuando nombra otra pieza u otra herramienta.

Etiquetas:
- "nuevo": el pedazo empieza otro resultado, otra parte del procedimiento. El primer pedazo que es
  una acción siempre es "nuevo".
- "continua": el pedazo sigue trabajando para el mismo resultado que el anterior, aunque use otra
  herramienta o toque otra pieza: lo prepara, da el siguiente movimiento, lo explica, advierte algo
  sobre él o revisa que quedó bien.
- "introduccion": saludo, presentación de quien narra, de qué trata el video o para qué se hace.
- "cierre": despedida o "listo, terminamos".
- "entrevistador": una pregunta o un comentario de quien entrevista (no es un paso).
- "comentario": una anécdota o algo ajeno al procedimiento.

Antes de poner "nuevo", pregúntate: ¿el operador ya terminó lo que buscaba con el pedazo anterior
y empieza a buscar otra cosa? Si sigue trabajando para lo mismo, es "continua".

Ejemplo resuelto (un procedimiento inventado: cambiar la llanta de un auto; 13 pedazos, 4 pasos):
[1] Presentación — "Hola, soy el mecánico del taller; hoy les enseño a cambiar una llanta." → introduccion
[2] Freno y calzas — "Pongo el freno de mano y calzo la llanta contraria." → nuevo (resultado: el auto quedó asegurado)
[3] Señalización — "Enciendo las intermitentes y pongo el triángulo atrás." → continua (sigue asegurando el auto)
[4] Aflojar tuercas — "Con la llave de cruz aflojo las tuercas, sin quitarlas." → nuevo (resultado: la llanta ponchada quedó afuera)
[5] Colocar el gato — "Pongo el gato en el punto de apoyo del chasis." → continua (otra herramienta, mismo resultado)
[6] Levantar el auto — "Subo el auto hasta que la llanta no toque el piso." → continua
[7] Retirar la llanta — "Quito las tuercas y saco la llanta ponchada." → continua
[8] Colocar la refacción — "Pongo la llanta de refacción alineando los birlos." → nuevo (resultado: la refacción quedó montada)
[9] Poner tuercas — "Pongo las tuercas a mano." → continua
[10] Bajar y apretar — "Bajo el gato y aprieto las tuercas en cruz." → continua
[11] Revisar el apriete — "Reviso con la llave que ninguna tuerca gire más." → continua (revisa lo que acaba de hacer)
[12] Guardar — "Guardo la llanta ponchada, el gato y la llave, y quito las calzas." → nuevo (resultado: todo quedó guardado)
[13] Cierre — "Listo, eso es todo." → cierre
Respuesta: {"pasos":[{"paso_video":1,"etiqueta":"introduccion"},{"paso_video":2,"etiqueta":"nuevo"},{"paso_video":3,"etiqueta":"continua"},{"paso_video":4,"etiqueta":"nuevo"},{"paso_video":5,"etiqueta":"continua"},{"paso_video":6,"etiqueta":"continua"},{"paso_video":7,"etiqueta":"continua"},{"paso_video":8,"etiqueta":"nuevo"},{"paso_video":9,"etiqueta":"continua"},{"paso_video":10,"etiqueta":"continua"},{"paso_video":11,"etiqueta":"continua"},{"paso_video":12,"etiqueta":"nuevo"},{"paso_video":13,"etiqueta":"cierre"}]}
El ejemplo es solo para mostrar el criterio: no copies sus pasos ni su número de pasos.

Reglas:
- Si un pedazo mezcla una acción con otra cosa (una explicación, una pregunta), cuenta como
  acción: "nuevo" o "continua".
- Pon una etiqueta a cada paso del video, del 1 al último, una sola vez y en orden.
- No escribas minutos, segundos ni texto: solo el número del paso del video y su etiqueta.
Responde solo con el JSON pedido, compacto: en una sola línea, sin sangría ni saltos de línea.

## usuario
Idioma de la narración: $idioma

Pasos del video, numerados y en orden:
$pasos

## correccion
Tu respuesta anterior no es válida: $motivo. Responde de nuevo solo con el JSON compacto, con los
mismos campos. Recuerda: una etiqueta para cada paso del video, del 1 al último, una sola vez y en
orden.
