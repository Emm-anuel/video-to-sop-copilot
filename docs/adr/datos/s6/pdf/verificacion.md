# Verificación de los PDF del reporte y del SOP generado (RF-29, RF-30)

15 nov 2026, rama `feat/s6`, issues #21 y #22. Los PDF no se versionan (`.gitignore`): llevan
miniaturas, citas y nombres del video. Se regeneran con la API sobre la base local:

```powershell
curl.exe -OJ http://127.0.0.1:8000/videos/9686/pdf   # A, reporte (modo validar)
curl.exe -OJ http://127.0.0.1:8000/videos/9689/pdf   # E, SOP generado (modo generar)
curl.exe -OJ http://127.0.0.1:8000/videos/9691/pdf   # E contra su SOP, reporte
```

## Videos usados

Del recorrido completo desde la pantalla del 13 nov (`docs/adr/datos/s5/`), grabados por el
equipo:

| Video | id | Modo | SOP | Hojas | QR |
|---|---|---|---|---|---|
| A | 9686 | validar | SOP-9297 | 4 | 5 (uno por hallazgo) |
| E | 9689 | generar | SOP-9298 (generado) | 4 | 1 (portada, t=0) |
| E contra su SOP | 9691 | validar | SOP-9299 | 5 | 6 (uno por hallazgo) |

Se generaron con `APP_URL_PUBLICA` por defecto (`http://localhost:4200`).

## Los 12 QR contra su enlace en texto

Cada hoja se rasterizó a escala 3 con pypdfium2 y se leyó con `zxing-cpp` 2.3.0, instalado en un
venv temporal fuera del proyecto (no es dependencia). El texto decodificado se comparó con el
enlace clicable (`page.hyperlinks` de pdfplumber) del mismo bloque: **12 de 12 iguales**, en el
mismo orden.

| PDF | Hoja | QR decodificado = enlace en texto |
|---|---|---|
| 9686 | 3 | `http://localhost:4200/v/9686?t=49.2` |
| 9686 | 3 | `http://localhost:4200/v/9686?t=51.5` |
| 9686 | 3 | `http://localhost:4200/v/9686?t=66.9` |
| 9686 | 4 | `http://localhost:4200/v/9686?t=68.5` |
| 9686 | 4 | `http://localhost:4200/v/9686?t=110.0` |
| 9689 | 1 | `http://localhost:4200/v/9689?t=0.0` |
| 9691 | 4 | `http://localhost:4200/v/9691?t=153.2` |
| 9691 | 4 | `http://localhost:4200/v/9691?t=193.3` |
| 9691 | 4 | `http://localhost:4200/v/9691?t=133.8` |
| 9691 | 4 | `http://localhost:4200/v/9691?t=147.8` |
| 9691 | 4 | `http://localhost:4200/v/9691?t=165.6` |
| 9691 | 5 | `http://localhost:4200/v/9691?t=188.4` |

El orden de 9691 es el de las filas del reporte (primero los pares, luego los *Sobra*), no el
cronológico.

## El cronómetro de A contra `t` (RNF-03, ±1 s)

El video A se grabó con un cronómetro de celular a cuadro, arrancado al inicio del video. La
miniatura de cada hallazgo del PDF muestra la lectura del cronómetro en ese segundo:

| `t` del QR (s) | Cronómetro en la miniatura | Diferencia |
|---|---|---|
| 49.2 | 00:49.20 | 0.00 s |
| 51.5 | 00:51.45 | 0.05 s |
| 66.9 | 01:06.77 (último dígito borroso: 70–77) | ≤ 0.2 s |
| 68.5 | 01:08.46 (último dígito borroso: 46–56) | ≤ 0.1 s |
| 110.0 | 01:49.93 | 0.07 s |

Todas dentro de ±1 s. El QR lleva el segundo con un decimal (`url_video`). La miniatura sale del
`t_inicio` guardado o de la guardada a ≤ 1 s (`miniaturas.miniatura_en`, la misma de `/thumb`).

## Docker

`docker compose build api` y, desde el contenedor
(`docker compose run --rm --no-deps api python -c …` con `TestClient` sobre `create_app`),
`GET /videos/9686/pdf`:

| Corrida | Resultado |
|---|---|
| Con `./media` del host montado en `/app/media` (solo lectura) | 200, 4 hojas, 5 miniaturas, fuentes `DejaVuSans` y `DejaVuSans-Bold` embebidas (subconjunto), reportlab 5.1.0, `salidas/fuentes/` en la imagen con su `LICENSE` |
| Sin montar `media` (volumen de compose, sin el archivo del video) | 200, sin miniaturas y sin hueco: la evidencia va sin esa columna; QR, enlace y cita se quedan |

La primera corrida sacó la fecha en UTC (13/11/2026 05:12 contra 12/11/2026 23:12 en el host).
Con `TZ: ${TZ:-America/Mexico_City}` en el servicio `api` de `docker-compose.yml`, la fecha
dentro del contenedor es la misma que en el host.

## Pruebas automáticas

`tests/test_pdf.py` (22 pruebas, con `reporte_ejemplo*.json`, `sop_generado_ejemplo.json` y
videos sintéticos de ffmpeg): secciones en el orden de §13 y "Página X de Y" en cada hoja, acentos,
ñ, ° y ☐, la URL de cada QR (la que recibe `dibujo_qr`) igual a la de su enlace, asterisco solo en
lo inferido sin revisar, ningún carácter fuera de la página con citas de 600 caracteres, video sin
imagen, y 404 y 409 de `GET /videos/{id}/pdf` y `GET /sops/{id}/pdf`.

## Pendiente

Escanear un QR de cada PDF con un celular en la misma red (`APP_URL_PUBLICA` con la IP del
equipo).
