# Medición de la descripción de imágenes (ADR-024)

2026-11-11T00:12:00 · git `1d590bcdfedc93404aaaabeb7270a4b9406256f4` (con cambios sin commit) · prompt `fotogramas_v1` · lote 8 · lado 512 px · `gemma4:e4b-it-q4_K_M`. Videos C, D y E del equipo (no del cliente). Gemma en frío en cada corrida, como en el procesador. Una corrida por combinación.

## Tiempo y estimación

Extra = imágenes + ficha con imágenes − ficha sin imágenes: lo que suma encender la opción. La estimación usa los `SEG_IMAGEN_*` de Settings al medir (GPU 1.5 s, CPU 15.0 s).

| Video | Dispositivo | N (descritas) | Imágenes s | Ficha con / sin s | Extra s | s por imagen (bruto / extra) | Estimado s | Error s | Tokens entrada / salida |
|---|---|---|---|---|---|---|---|---|---|
| video_c | gpu (gpu) | 6 (6) | 13.16 | 4.3 / 15.15 | 2.3 | 2.19 / 0.39 | 9 | 6.7 | 936 / 602 |
| video_d | gpu (gpu) | 6 (6) | 11.18 | 5.08 / 8.47 | 7.8 | 1.86 / 1.3 | 9 | 1.2 | 936 / 552 |
| video_e | gpu (gpu) | 8 (8) | 13.81 | 5.23 / 9.52 | 9.5 | 1.73 / 1.19 | 12 | 2.5 | 1108 / 676 |
| video_c | cpu (cpu) | 6 (6) | 67.66 | 54.18 / 57.97 | 63.9 | 11.28 / 10.65 | 90 | 26.1 | 936 / 596 |
| video_d | cpu (cpu) | 6 (6) | 74.87 | 51.35 / 49.04 | 77.2 | 12.48 / 12.86 | 90 | 12.8 | 936 / 776 |
| video_e | cpu (cpu) | 8 (8) | 87.94 | 62.06 / 66.7 | 83.3 | 10.99 / 10.41 | 120 | 36.7 | 1108 / 789 |

**Recomendación (mediana del extra por imagen):** `SEG_IMAGEN_GPU=1.2`, `SEG_IMAGEN_CPU=10.7`.

## Ficha y afinidad con y sin imágenes

| Video | Dispositivo | Afinidad sin → con | Datos con fuente visual | Equipos solo sin / solo con | Mismas personas | Datos que cambian de valor |
|---|---|---|---|---|---|---|
| video_c | gpu | 97 → 94 | — | cartucho del filtro de agua; cartucho nuevo; equipo de proteccion; llave de paso / accesorio; anillo de hule; boton rojo; carcasa; cartucho de filtro; contenedor; cubo; recipiente; tuberia | no | resumen |
| video_d | gpu | 18 → 17 | — | banda transportadora; panel; portarrollos; puerta de acrilico / panel de control; panel de control de la maquina de envasado; placa de despegue; rollo de material; soporte | sí | resumen |
| video_e | gpu | — → — | — | bolsa de desecho; boton rojo; guantes de proteccion; herramienta de soporte; llave inglesa; soporte de carcasa; toalla de papel; valvula de corte / bol; bomba; contenedor; herramienta; housing grant; llave; supervisor snp; taza de papel de cocina; unidad | sí | tema; lugar; resumen |
| video_c | cpu | 97 → 97 | — | cartucho del filtro de agua; cartucho nuevo; equipo de proteccion; plastico / anillo de hule; bolsa de residuos; boton rojo; carcasa; cartucho de filtro; contenedor; cubo; tubo; valvula | no | actividad; tema; resumen |
| video_d | cpu | 17 → 21 | — | banda transportadora; panel; portarrollos; puerta de acrilico / maquina de envasado; panel de control; rollo de etiquetas; rollo de material; soporte | sí | tema; proposito; resumen |
| video_e | cpu | — → — | — | barra de extension; cartucho de filtro; housing grant; llave / bol; boton rojo; cartucho de filtro de agua; equipo de proceso; herramienta de soporte de carcasa; llave inglesa; recipiente de desecho; supervisor snp; tijera de plastico de embalaje; tubo de corte de valvula | sí | actividad; tema; lugar; resumen |

## Descripciones (para revisar a mano)

Cada imagen con su segundo (puesto por el código), personas (conteo), equipos, texto legible y riesgos.

### video_c · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 16.761 | Un operador está realizando una tarea en un área industrial, utilizando un equipo de medición y un contenedor. | 1 | manómetro; contenedor | ENJUAGUE | falta de guantes |
| 50.282 | Un operador extiende su brazo hacia un receptáculo, mientras hay un contenedor de material cerca. | 1 | contenedor | NITRILO | — |
| 83.803 | Se observa un equipo de medición y una tubería con un accesorio conectado, junto a un recipiente. | 0 | manómetro; tubería; accesorio | — | — |
| 117.325 | Un operador con protección ocular está manipulando un equipo de medición y un recipiente con un líquido. | 1 | manómetro; recipiente | ENJUAGUE | — |
| 150.846 | Un operador con protección ocular está manipulando un equipo de medición y un recipiente, con un cubo cerca. | 1 | manómetro; recipiente; cubo | ENJUAGUE | — |
| 184.367 | Un operador con protección ocular está manipulando un equipo de medición y un recipiente, con un cubo cerca. | 1 | manómetro; recipiente; cubo | ENJUAGUE | — |

### video_d · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 13.986 | Un operador está interactuando con un panel de control en una línea de producción. El operador está señalando un componente del equipo. | 1 | panel de control | ENVASADO | — |
| 41.957 | Un operador está señalando un panel de control de una máquina de envasado. El operador está realizando una inspección o ajuste. | 1 | panel de control | ENVASADO; PAUSA; INICIO | — |
| 69.929 | Un operador está señalando un rollo de material en una máquina de envasado. El operador está supervisando el proceso de empaquetado. | 1 | rollo de material | ENVASADO | — |
| 97.9 | Un operador está señalando un panel de control de la máquina de envasado. El operador está monitoreando el estado de la producción. | 1 | panel de control | ENVASADO | — |
| 125.872 | Un operador está señalando un panel de control de la máquina de envasado. El operador está interactuando con la interfaz de la máquina. | 1 | panel de control | ENVASADO; CALIBRADO; INICIO; PAUSA | — |
| 153.843 | Un operador está señalando un panel de control de la máquina de envasado. El operador está supervisando el proceso de envasado. | 1 | panel de control | ENVASADO | — |

### video_e · gpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 14.204 | Un operador está trabajando en una línea de proceso, manipulando un equipo conectado a una tubería. | 1 | manómetro; contenedor | RINSE LINE | falta de guantes o lentes cuando la tarea los pide a la vista |
| 42.612 | Un operador está trabajando en una línea de proceso, manipulando un equipo conectado a una tubería. | 1 | manómetro; contenedor | RINSE LINE | falta de guantes o lentes cuando la tarea los pide a la vista |
| 71.02 | Un operador con protección ocular está en una zona de trabajo, cerca de un contenedor y una superficie con etiquetas. | 1 | contenedor | NITRILE | — |
| 99.428 | Un equipo de proceso está siendo manipulado, con una herramienta de color rojo y un contenedor conectado a una tubería. | 0 | herramienta | — | — |
| 127.836 | Un equipo de proceso está siendo manipulado, con una herramienta de color rojo y un contenedor conectado a una tubería. | 0 | herramienta | — | — |
| 156.244 | Un operador con protección ocular está manipulando un equipo de proceso, utilizando un contenedor y un cubo. | 1 | contenedor; cubo | RINSE LINE | — |
| 184.652 | Un equipo de proceso está siendo inspeccionado, mostrando un manómetro y vapor saliendo de una unidad. | 0 | manómetro | — | — |
| 213.06 | Un equipo de proceso está siendo inspeccionado, mostrando un manómetro y una unidad con un líquido. | 0 | manómetro; unidad | RINSE LINE; 0 bar | — |

### video_c · cpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 16.761 | Un operador está trabajando en una instalación industrial, manipulando tuberías y equipos de medición. | 1 | manómetro; tubo; contenedor | ENJUAGUE | falta de guantes |
| 50.282 | Un operador está realizando una tarea en una superficie de trabajo, utilizando un recipiente y un material etiquetado. | 1 | contenedor | NITRILO | — |
| 83.803 | Se observa un sistema de tuberías con un mecanismo de conexión y un medidor de presión en un entorno industrial. | 0 | manómetro; tubo; válvula | — | — |
| 117.325 | Un operador con protección ocular está manipulando un equipo de tuberías, utilizando un recipiente y un cubo. | 1 | contenedor; cubo | ENJUAGUE | — |
| 150.846 | Un operador con protección ocular está manipulando un equipo de tuberías, utilizando un recipiente y un cubo. | 1 | contenedor; cubo | ENJUAGUE | — |
| 184.367 | Un operador con protección ocular está manipulando un equipo de tuberías, utilizando un recipiente y un cubo. | 1 | contenedor; cubo | ENJUAGUE | — |

### video_d · cpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 13.986 | Un operador está manipulando una máquina de envasado, interactuando con un panel de control y un rollo de material. | 1 | máquina de envasado; panel de control; rollo de material | ENVASADO | — |
| 41.957 | El operador está realizando una inspección o ajuste en la máquina de envasado, señalando el panel de control. | 1 | máquina de envasado; panel de control | ENVASADO; EN MARCHA; PAUSA; INICIO | — |
| 69.929 | El operador está interactuando con la máquina de envasado, enfocándose en el rollo de material y el panel de control. | 1 | máquina de envasado; rollo de material; panel de control | ENVASADO; PAUSA; INICIO | — |
| 97.9 | El operador está ajustando o revisando la máquina de envasado, con su mano apuntando hacia el mecanismo de la máquina. | 1 | máquina de envasado; panel de control | ENVASADO; CALIBRADO; PAUSA; INICIO | — |
| 125.872 | El operador está realizando una operación en la máquina de envasado, con su mano sobre el panel de control. | 1 | máquina de envasado; panel de control | ENVASADO; PAUSA; INICIO | — |
| 153.843 | El operador está supervisando la máquina de envasado, con su mano sobre el panel de control, mientras el material avanza. | 1 | máquina de envasado; panel de control | ENVASADO | — |

### video_e · cpu

| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |
|---|---|---|---|---|---|
| 14.204 | Un operador está trabajando en una línea de proceso, manipulando un equipo conectado a una tubería. | 1 | manómetro; equipo de proceso | RINSE LINE | — |
| 42.612 | Un operador está manipulando un equipo de proceso conectado a una tubería, vistiendo equipo de protección. | 1 | manómetro; equipo de proceso | RINSE LINE | — |
| 71.02 | Un operador con equipo de protección está de pie junto a una mesa, con un recipiente etiquetado. | 1 | — | NITRILE | — |
| 99.428 | Un brazo mecánico está manipulando un equipo de proceso conectado a una tubería, con un operador cerca. | 1 | equipo de proceso | RINSE LINE | — |
| 127.836 | Un manómetro está colocado sobre un equipo de proceso, con vapor saliendo de él. | 0 | manómetro; equipo de proceso | 1 2 3 4 5 6 bar | — |
| 156.244 | Un operador está manipulando un equipo de proceso, sosteniendo un recipiente y un cubo. | 1 | equipo de proceso | RINSE LINE | — |
| 184.652 | Un operador está manipulando un equipo de proceso, sosteniendo un recipiente y un cubo, con un manómetro visible. | 1 | equipo de proceso; manómetro | RINSE LINE | — |
| 213.06 | Un equipo de proceso está conectado a una tubería, con un manómetro y un recipiente debajo. | 0 | manómetro; equipo de proceso | 0 1 2 3 4 5 6 bar | — |
