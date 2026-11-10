# SOP generado · medición 2026-11-10 00:31

Commit `95d7d404096528607a0da720bcc5a82f5c4c9542` (10 archivos con cambios sin commit) · LLM `gemma4:e4b-it-q4_K_M` · `LLM_DISPOSITIVO=cpu` · GPU NVIDIA GeForce RTX 2070 SUPER

## Punto 0: dónde quedó Gemma

```
NAME                    ID              SIZE      PROCESSOR    CONTEXT    RUNNER      UNTIL               
gemma4:e4b-it-q4_K_M    dc35e8d9c606    1.9 GB    100% CPU     8192       llamacpp    29 minutes from now
```

## Corridas

| Video | n | Gemma | VRAM MiB | Pasos del video | Pasos del SOP | Ficha s | Pasos s | SOP s | Total Gemma s | Advertencias |
|---|---|---|---|---|---|---|---|---|---|---|
| video_e | 1 | cpu | 1806 | 18 | 5 | 60.39 | 155.06 | 213.29 | 428.75 | 0 |

## Llamadas (segundos · tokens de salida · tokens/s)

- video_e [1]: contexto 60.39 s · 369 · 14.1; segmentacion 45.77 s · 550 · 17.2; segmentacion 109.28 s · 1414 · 15.5; agrupar 31.8 s · 137 · 13.25; pasos 75.94 s · 754 · 13.2; resumen 49.2 s · 377 · 14.7; claves 56.34 s · 586 · 15.54

Idioma de video_e: `en` (confianza 1.00)

## Cuadro resumen y tabla de pasos · video_e

- titulo: Reemplazo de cartucho de filtro de agua en línea de enjuague
- objetivo: Cambiar el cartucho sin fugas y recuperar la presión de trabajo.
- alcance: Cubre solo el filtro de cartucho montado en la pared en la línea de enjuague. No incluye reemplazar la carcasa del filtro o la válvula de corte.
- lugar: Línea de enjuague
- horario: Cada 3 meses o cuando el manómetro marca menos de 2 bar
- responsable: Técnico de mantenimiento
- roles: ['Técnico de mantenimiento']
- equipo: 15
- riesgos: 2
- en_caso_de_falla: 1
- duracion_total_min: 3.0
- pasos_en_infinitivo: 5
- pasos: 5
- puntos_clave: 7
- palabras_clave: 10
- inferidos: 5

## RNF-05 · video_e [1]: 3 de 5 pasos generados correctos (60.0 %); referencia cubierta 4 de 6, faltan [4, 5]

| Paso | Nombre | Tramo s | Referencia | Estado | Coseno | Fuera de orden | En su tramo | Correcto |
|---|---|---|---|---|---|---|---|---|
| 1 | Poner equipo de protección personal | 52.5–75.5 | 1 Ponerse guantes y lentes | Cumple | 0.792 | no | sí | sí |
| 2 | Cerrar válvula de corte antes filtro | 77.3–100.4 | 2 Cerrar la llave de paso | Cumple | 0.719 | no | sí | sí |
| 3 | Liberar presión y reemplazar cartucho | 102.1–187.4 | 3 Liberar la presión | Parcial | 0.565 | no | no | no |
| 4 | Abrir válvula lentamente y verificar fugas | 188.4–219.8 | 6 Abrir la llave y revisar fugas | Cumple | 0.8 | no | sí | sí |
| 5 | Finalizar reemplazo de cartucho | 221.3–225.0 | None  | Sobra | None | no | no | no |
