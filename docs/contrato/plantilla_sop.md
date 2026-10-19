# Título del procedimiento

<!--
Plantilla del SOP de referencia en Markdown o TXT (RF-03). sopvid.lenguaje.sop_markdown la
convierte con código, sin LLM, al esquema SOP (docs/contrato/sop.schema.json).

Obligatorio: la línea "# Título" y la sección "## Pasos" con al menos un paso. Todo lo demás es
opcional: las secciones o claves que no apliquen se borran o se dejan vacías, y en el SOP quedan
vacías (nada se inventa).

- Secciones y claves se reconocen sin importar mayúsculas, acentos ni puntuación.
- Tiempos en minutos: "0.5" y "0,5" valen lo mismo.
- Las listas (equipo de un paso, validación) se separan con "," o ";".
- Estos comentarios se ignoran al convertir; se pueden dejar o borrar.
- En TXT: la primera línea no vacía es el título y cada sección va sola en su línea con dos
  puntos ("Resumen:", "Pasos:").
-->

## Resumen
<!--
Una clave por línea, "- Clave: valor". Claves: Objetivo, Alcance, Responsable, Lugar,
Horario (o Frecuencia, u Horario / frecuencia) y Duración total (min).
El Responsable de aquí se usa en los pasos que no traen el suyo (con confianza media). En TXT
puede ir suelto, sin guion: "Responsable: Técnico de mantenimiento".
-->
- Objetivo:
- Alcance:
- Responsable:
- Lugar:
- Horario:
- Duración total (min):

## Roles
<!-- Uno por línea: "- Nombre del rol: qué hace". -->

## Equipo
<!-- También "## Equipo de operación". Uno por línea: "- Nombre: para qué sirve". -->

## Riesgos
<!--
Uno por línea: "- Nivel: descripción. Paso: N. Control: cómo se controla".
Nivel: Alto, Medio o Bajo. "Paso" y "Control" son opcionales; N es el número del paso de abajo.
-->

## En caso de falla
<!-- Una por línea: "- Situación: qué hacer". -->

## Pasos
<!--
También "## Procedimiento". Un subtítulo por paso, "### 1. Nombre" o "### Paso 1: Nombre", con el
nombre en infinitivo ("Cerrar la llave de paso"). Debajo, la descripción en texto libre y estas
claves, todas opcionales:

- Responsable: (si falta, se hereda el del resumen)
- Equipo: Elemento 1, Elemento 2
- Validación: Punto 1; Punto 2      (también "Puntos de validación")
- Tiempo (min): 0.5                 (también "Duración")

Sin subtítulos también vale una lista numerada, "1. Nombre", con la descripción y las claves en
las líneas siguientes. Los pasos se numeran 1, 2, 3…; si hay saltos o repetidos, se renumeran en
orden y se avisa.
-->

### 1. Escribir el nombre del paso en infinitivo

- Responsable:
- Equipo:
- Validación:
- Tiempo (min):
