# SOP generado · medición 2026-11-10 11:52

Commit `584bd7cdd76c363dc32a9fd1dc644b708dd72f43` (12 archivos con cambios sin commit) · LLM `gemma4:e4b-it-q4_K_M` · `LLM_DISPOSITIVO=cpu` · GPU NVIDIA GeForce RTX 2070 SUPER

Agrupación `sop_generado_agrupar_v2` · candado no (`UMBRAL_FUSION=0.55`)

## Punto 0: dónde quedó Gemma

```
NAME                    ID              SIZE      PROCESSOR    CONTEXT    RUNNER      UNTIL               
gemma4:e4b-it-q4_K_M    dc35e8d9c606    1.9 GB    100% CPU     8192       llamacpp    29 minutes from now
```

## Corridas

| Video | n | Gemma | VRAM MiB | Pasos del video | Pasos del SOP | Ficha s | Pasos s | SOP s | Total Gemma s | Advertencias |
|---|---|---|---|---|---|---|---|---|---|---|
| video_e | 1 | cpu | 1835 | 18 | 15 | 63.66 | 153.29 | 259.25 | 476.2 | 0 |

## Agrupación (etiqueta de Gemma por paso del video → grupos)

| Video | n | Etiquetas | Grupos | Fuera | Cortes del candado |
|---|---|---|---|---|---|
| video_e | 1 | `i o N N N N N N N N N N N N N N N x` | 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 | 1 introduccion, 2 comentario, 18 cierre | — |

Etiquetas: N nuevo, c continua, i introducción, x cierre, e entrevistador, o comentario.

## Llamadas (segundos · tokens de salida · tokens/s)

- video_e [1]: contexto 63.66 s · 369 · 13.9; segmentacion 45.05 s · 550 · 17.5; segmentacion 108.24 s · 1414 · 15.7; agrupar 41.91 s · 344 · 17.79; pasos 61.75 s · 668 · 14.69; pasos 36.91 s · 498 · 14.89; resumen 52.88 s · 408 · 14.76; claves 65.8 s · 692 · 15.53

Idioma de video_e: `en` (confianza 1.00)

## Cuadro resumen y tabla de pasos · video_e

- titulo: Reemplazo de cartucho de filtro de agua en línea de enjuague
- objetivo: Cambiar el cartucho sin fugas y recuperar la presión de trabajo.
- alcance: Cubre solo el filtro de cartucho montado en la pared en la línea de enjuague. No incluye reemplazar la carcasa del filtro o la válvula de corte.
- lugar: Línea de enjuague
- horario: Cada 3 meses o cuando el manómetro marca menos de 2 bar
- responsable: Técnico de mantenimiento
- roles: ['Técnico de mantenimiento']
- equipo: 16
- riesgos: 2
- en_caso_de_falla: 1
- duracion_total_min: 2.8
- pasos_en_infinitivo: 15
- pasos: 15
- puntos_clave: 8
- palabras_clave: 13
- inferidos: 16

## Resumen RNF-05

Principal: por tramos (dentro del tramo de un solo paso de referencia, ±1 s, en orden). Secundarios: uno a uno (húngaro, más estricto) y cobertura en orden.

| Corrida | Pasos generados | RNF-05 por tramos | Uno a uno | Cobertura en orden |
|---|---|---|---|---|
| video_e [1] | 15 | 15 (100.0 %) | 6 (40.0 %) | 6 de 6 (100.0 %) |

## RNF-05 · video_e [1]: por tramos 15 de 15 (100.0 %); uno a uno 6 (40.0 %); referencia cubierta 6 de 6, faltan []; cubierta en orden [1, 2, 3, 4, 5, 6]

| Paso | Nombre | Tramo s | Dentro del paso de ref. | Correcto (tramos) | Par uno a uno | Estado | Coseno | Fuera de orden | En su tramo | Correcto (uno a uno) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Poner equipo de protección personal | 52.5–75.5 | 1 | sí | 1 Ponerse guantes y lentes | Cumple | 0.792 | no | sí | sí |
| 2 | Cerrar válvula de corte antes filtro | 77.3–100.4 | 2 | sí | 2 Cerrar la llave de paso | Cumple | 0.714 | no | sí | sí |
| 3 | Liberar presión del sistema | 102.1–110.8 | 3 | sí | None  | Sobra | None | no | no | no |
| 4 | Colocar cubo debajo del filtro | 111.4–117.5 | 3 | sí | None  | Sobra | None | no | no | no |
| 5 | Presionar botón rojo en carcasa | 118.2–131.3 | 3 | sí | 3 Liberar la presión | Cumple | 0.864 | no | sí | sí |
| 6 | Retirar carcasa con llave | 133.8–145.9 | 4 | sí | None  | Sobra | None | no | no | no |
| 7 | Sacar cartucho viejo en bolsa | 147.8–153.2 | 4 | sí | None  | Sobra | None | no | no | no |
| 8 | Verificar anillo de goma | 153.2–163.8 | 4 | sí | 4 Retirar la carcasa y el cartucho usado | Parcial | 0.663 | no | sí | sí |
| 9 | Instalar cartucho nuevo | 165.6–169.6 | 5 | sí | None  | Sobra | None | no | no | no |
| 10 | Retirar envoltura colocar centro | 170.0–176.4 | 5 | sí | 5 Colocar el cartucho nuevo | Parcial | 0.708 | no | sí | sí |
| 11 | Enroscar perno con llave | 176.4–187.4 | 5 | sí | None  | Sobra | None | no | no | no |
| 12 | Abrir válvula tubo lentamente | 188.4–192.8 | 6 | sí | None  | Sobra | None | no | no | no |
| 13 | Verter aire botón rojo | 193.3–198.3 | 6 | sí | 6 Abrir la llave y revisar fugas | Parcial | 0.698 | no | sí | sí |
| 14 | Verificar junta guante conexión | 200.2–205.5 | 6 | sí | None  | Sobra | None | no | no | no |
| 15 | Comprobar fugas y presión | 205.5–219.8 | 6 | sí | None  | Sobra | None | no | no | no |
