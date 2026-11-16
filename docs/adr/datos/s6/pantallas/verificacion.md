# Recorrido de `/videos` y `/buscar` (pantallas 6 y 7, #27, #28, #29)

16 nov 2026, rama `feat/s6`. API en el host (`uvicorn sopvid.plataforma.api.main:app --port 8000`,
sin Ollama: publicar y buscar no lo usan), Postgres en Docker y `ng serve` en 4200. Lo manejó
Edge headless por CDP (clics y teclado reales) con un script fuera del repo, a 1280 × 900 y con la
ventana emulada a 360 × 780. El video es **Recorrido A** (id 9686, grabado por el equipo: el cuadro
muestra un cronómetro en un teléfono, sin rostros ni nombres). Cada captura se revisó antes de
guardarla.

## Lo que se comprobó

| Paso | Resultado |
|---|---|
| `/videos`: 39 videos, del más reciente al más antiguo | Modo, SOP, cumplimiento con semáforo, estado, fecha, imágenes y publicado en cada fila (01, 03) |
| "Quitar de la búsqueda" y luego "Publicar" en A | "Quitado de la búsqueda." y "Publicado: 271 palabras indexadas en la búsqueda."; la fila pasa a "Publicado · 16 nov 2026" (02) |
| `/buscar`: «manometro» (acento escrito sin él) | 3 coincidencias en 1 video, resaltado «manómetro» en 00:08, 01:00 y 02:05 |
| «cartuchos» (plural; en A se dice en singular) | 4 coincidencias: 00:04, 01:15, 01:32, 02:12 |
| «llave de paso» (frase de 3 palabras) | 2 coincidencias: 00:32 y 01:50 |
| Enter envía y el foco vuelve a la caja | En las tres consultas |
| Clic en el resultado de 00:32 | El video aparece en la misma pantalla con `src=/api/videos/9686/video`; tras 1.5 s de reproducción, `currentTime` 33.4 s y el cronómetro del cuadro marca 00:33.33 (04) |
| A 360 px, clic en el de 01:50 | `currentTime` 112.2 s tras 1.2 s, el cronómetro marca 01:52.14; resultados debajo de la conversación (05) |
| "Ver SOP" | `/api/sops/9297/pdf?ver=true` con `target=_blank`; es el único enlace de la pantalla |
| Salir a `/videos` y volver | Las tres consultas siguen en la conversación |
| Filtro por SOP a 360 px | Chip «SOP: SOP-9297 · Cambio del cartucho del filtro de agua ×» y "Quitar filtros" (06) |
| Desborde horizontal y objetivos | Ninguno a 1280 ni a 360 en las dos pantallas; ningún botón, enlace o campo visible mide menos de 36 px de alto |
| Barra y menú de carga en `/buscar` | No aparecen |

Lo que encontró el recorrido y se corrigió antes de estas capturas: a 360 px un `<select>` de
filtro con opciones largas desbordaba 42–54 px (ahora no tiene ancho propio) y la conversación no
abría en el último mensaje al volver.

Observado en el recorrido y corregido después (16 nov): en «cartuchos», la última coincidencia
resaltaba «cartucho.» con el punto. Desde entonces `rango` no incluye los signos de puntuación del
inicio de la primera palabra ni del final de la última (`lenguaje/busqueda.py`,
`_sin_signos_en_bordes`); la frase se queda igual. Las capturas son de antes del cambio, que no
afecta a ninguna de ellas.

## Capturas

- `01-videos-escritorio.png`: la lista a 1280.
- `02-videos-publicar-a-271-palabras.png`: A recién publicado.
- `03-videos-360.png`: tarjetas a 360.
- `04-buscar-escritorio-llave-de-paso-al-segundo.png`: conversación, video en el segundo y resultados.
- `05-buscar-360-resultados-debajo.png`: página completa a 360.
- `06-buscar-360-filtro-sop.png`: el filtro por SOP como chip a 360.
