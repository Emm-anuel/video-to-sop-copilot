# Medición de la descripción de imágenes (ADR-024)

2026-11-11T00:46:58 · git `1d590bcdfedc93404aaaabeb7270a4b9406256f4` (con cambios sin commit) · prompt `fotogramas_v1` · lote 8 · lado 512 px · `gemma4:e4b-it-q4_K_M`. Videos del equipo (no del cliente). Gemma en frío en cada corrida, como en el procesador. Una corrida por combinación.

## Tiempo y estimación

Extra = imágenes + ficha con imágenes − ficha sin imágenes: lo que suma encender la opción. La estimación usa los `SEG_IMAGEN_*` de Settings al medir (GPU 1.2 s, CPU 10.7 s).

| Video | Dispositivo | N (descritas) | Imágenes s | Ficha con / sin s | Extra s | s por imagen (bruto / extra) | Estimado s | Error s | Tokens entrada / salida |
|---|---|---|---|---|---|---|---|---|---|
| video_a | gpu (gpu) | 6 (6) | 11.06 | 4.44 / 9.99 | 5.5 | 1.84 / 0.92 | 7.2 | 1.7 | 919 / 614 |
| video_b | gpu (gpu) | 6 (6) | 12 | 4.15 / 9.48 | 6.7 | 2 / 1.11 | 7.2 | 0.5 | 919 / 574 |
| video_c | gpu (gpu) | 6 (6) | 14.22 | 6.16 / 9.16 | 11.2 | 2.37 / 1.87 | 7.2 | -4 | 919 / 697 |
| video_d | gpu (gpu) | 6 (6) | 12.45 | 4.69 / 9.91 | 7.2 | 2.07 / 1.21 | 7.2 | 0 | 919 / 558 |
| video_e | gpu (gpu) | 8 (8) | 13.86 | 5.64 / 9.82 | 9.7 | 1.73 / 1.21 | 9.6 | -0.1 | 1091 / 725 |

**Recomendación (mediana del extra por imagen):** `SEG_IMAGEN_GPU=1.2`, `SEG_IMAGEN_CPU=—`.

## Ficha y afinidad con y sin imágenes

| Video | Dispositivo | Afinidad sin → con | Datos con fuente visual | Equipos solo sin / solo con | Mismas personas | Datos que cambian de valor |
|---|---|---|---|---|---|---|
| video_a | gpu | 72 → 95 | — | cartucho nuevo / boton rojo; cartucho de filtro de agua; manometro | sí | lugar; proposito; resumen |
| video_b | gpu | 95 → 95 | — | llave / telefono movil | sí | resumen |
| video_c | gpu | 97 → 97 | — | cartucho del filtro de agua; cartucho nuevo; equipo de proteccion / anillo de hule; bolsa de residuos; boton rojo; carcasa; cartucho de filtro; contenedor; cubo; recipiente; trapo seco; tuberia | no | actividad; lugar; resumen |
| video_d | gpu | 18 → 19 | — | banda transportadora; botella; etiquetas; portarrollos; puerta de acrilico / botellas; maquina de envasado; panel de control; rollo de etiquetas; rollo de material | sí | tema; lugar; resumen |
| video_e | gpu | — → — | — | herramienta de soporte de carcasa; llave de ajuste; manometro de presion; valvula de corte / boton rojo; equipo de medicion; herramienta de soporte; herramienta de soporte para carcasa de filtro; llave inglesa; manometro; valvula | sí | resumen |

## Descripciones (para revisar a mano)

Cada imagen con su segundo (puesto por el código), personas (conteo), equipos, texto legible y riesgos.

### video_a · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 11.25 | Se muestra la pantalla de un dispositivo móvil que está registrando el tiempo de un proceso. | 0 | — | 00:11:26; Vuelta; Vuelta 1; Reset manual; Alarmas; Cronómetro; Temperaturas | — |
| 33.75 | La pantalla del dispositivo móvil muestra el avance del tiempo del proceso. | 0 | — | 00:33:72; Vuelta; Vuelta 1; Reset manual; Alarmas; Cronómetro; Temperaturas | — |
| 56.25 | La pantalla del dispositivo móvil muestra el tiempo transcurrido en el proceso. | 0 | — | 00:56:20; Vuelta; Vuelta 1; Reset manual; Alarmas; Cronómetro; Temperaturas | — |
| 78.75 | La pantalla del dispositivo móvil indica el tiempo avanzado en la vuelta 1 del proceso. | 0 | — | 01:18:66; Vuelta; Vuelta 1; Reset manual; Alarmas; Cronómetro; Temperaturas | — |
| 101.25 | La pantalla del dispositivo móvil muestra el tiempo registrado en la vuelta 1 del proceso. | 0 | — | 01:41:20; Vuelta; Vuelta 1; Reset manual; Alarmas; Cronómetro; Temperaturas | — |
| 123.75 | La pantalla del dispositivo móvil muestra el tiempo total registrado en el proceso. | 0 | — | 02:03:66; Vuelta; Vuelta 1; Reset manual; Alarmas; Cronómetro; Temperaturas | — |

### video_b · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 9.554 | Se muestra la pantalla de un teléfono móvil con un temporizador en funcionamiento, indicando el tiempo transcurrido. | 0 | teléfono móvil | 00:09.43; Vuelta; Vuelta 1 | — |
| 28.661 | La pantalla de un teléfono móvil muestra un temporizador en curso, registrando el tiempo de la vuelta. | 0 | teléfono móvil | 00:28.53; Vuelta; Vuelta 1 | — |
| 47.768 | Un teléfono móvil exhibe un temporizador activo, mostrando el tiempo acumulado de la vuelta. | 0 | teléfono móvil | 00:47.64; Vuelta; Vuelta 1 | — |
| 66.875 | La pantalla de un teléfono móvil muestra el tiempo en curso, indicando el progreso de la vuelta. | 0 | teléfono móvil | 01:06.74; Vuelta; Vuelta 1 | — |
| 85.982 | Un teléfono móvil muestra el tiempo en curso, con un indicador de 'Detener' visible en la pantalla. | 0 | teléfono móvil | 01:25.83; Vuelta; Vuelta 1 | — |
| 105.089 | La pantalla de un teléfono móvil muestra el tiempo en curso, con opciones de control en la parte inferior. | 0 | teléfono móvil | 01:44.97; Vuelta; Vuelta 1 | — |

### video_c · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 16.761 | Un operador está trabajando en una instalación industrial, manipulando un equipo conectado a una tubería. | 1 | manómetro; contenedor; tubería | ENJUAGUE | Ninguno visible |
| 50.282 | El operador extiende su brazo para manipular un equipo que está conectado a una tubería, mientras hay un contenedor de nitrilo cerca. | 1 | manómetro; contenedor; tubería | ENJUAGUE; NITRILO | Ninguno visible |
| 83.803 | Un equipo de medición está montado en una pared, con una tubería que pasa por encima y un operador cerca. | 1 | manómetro; tubería | ENJUAGUE | Ninguno visible |
| 117.325 | Se muestra un sistema de tuberías con un equipo de medición y un brazo mecánico que se extiende hacia un punto de conexión. | 0 | manómetro; tubería | ENJUAGUE | Ninguno visible |
| 150.846 | Un operador con protección ocular está manipulando un equipo conectado a una tubería, utilizando un cubo y un recipiente. | 1 | manómetro; tubería; cubo | ENJUAGUE | Ninguno visible |
| 184.367 | El operador está realizando una operación de llenado o muestreo, utilizando un recipiente y un cubo bajo una tubería. | 1 | manómetro; tubería; cubo | ENJUAGUE | Ninguno visible |

### video_d · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 13.986 | Se observa una línea de producción con botellas y un operador interactuando con una máquina de envasado. | 1 | máquina de envasado; botellas | ENVASADO | — |
| 41.957 | Un operador señala una máquina de envasado que tiene un panel de control visible. | 1 | máquina de envasado; panel de control | ENVASADO; PAUSA; INICIO | — |
| 69.929 | El operador está manipulando un rollo de material en la máquina de envasado. | 1 | rollo de material; máquina de envasado | ENVASADO | — |
| 97.9 | El operador está interactuando con la máquina de envasado, señalando un componente. | 1 | máquina de envasado; panel de control | ENVASADO | — |
| 125.872 | Se muestra un rollo de material en la máquina de envasado, con un operador señalando el panel de control. | 1 | rollo de material; máquina de envasado; panel de control | ENVASADO; CALIBRADO; INICIO; PAUSA | — |
| 153.843 | El operador está interactuando con la máquina de envasado, señalando el panel de control que muestra diferentes estados. | 1 | máquina de envasado; panel de control | ENVASADO | — |

### video_e · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 14.204 | Se observa una línea de tubería con un equipo de medición conectado, y una persona está interactuando con este equipo. | 1 | manómetro; válvula | RINSE LINE | — |
| 42.612 | Una persona está manipulando un equipo de medición conectado a una línea de tubería, mientras se encuentra en un área industrial. | 1 | manómetro; válvula | RINSE LINE | — |
| 71.02 | Un operador con protección ocular está de pie junto a una línea de tubería y un equipo de medición, con un contenedor de guantes en una mesa. | 1 | manómetro; válvula | NITRILE; RINSE LINE | — |
| 99.428 | Se muestra un brazo mecánico o herramienta que está manipulando un equipo conectado a una línea de tubería, con un manómetro visible. | 0 | manómetro; válvula | RINSE LINE | — |
| 127.836 | Un manómetro está colocado sobre un equipo de medición, y se observa vapor saliendo de la parte superior del equipo. | 0 | manómetro; equipo de medición | — | — |
| 156.244 | Un operador con protección ocular está sosteniendo un recipiente y un cubo, mientras interactúa con un equipo de medición conectado a una línea de tubería. | 1 | manómetro; válvula | RINSE LINE | — |
| 184.652 | Un operador con protección ocular está manipulando un equipo de medición conectado a una línea de tubería, con un cubo y un recipiente cerca. | 1 | manómetro; válvula | RINSE LINE | — |
| 213.06 | Un manómetro está colocado sobre un equipo de medición, y se observa una flecha indicando dirección en el área de trabajo. | 0 | manómetro; equipo de medición | RINSE LINE | — |
