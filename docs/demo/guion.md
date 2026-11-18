# Guion de la demo (recorrido completo)

Un recorrido de punta a punta, de la biblioteca de SOP al SOP generado, con lo que debe salir en cada
paso. Es el que se corrió el 17 nov en el clon limpio (`sopvid-limpia`, todo en Docker) y, para el
paso 2, también con la API en el host y GPU. Los números salen de ese ensayo; **Gemma no es
determinista** (A dio 91.67 % una vez y 100 % tres), así que la demo se ensaya antes y, si algo
sale distinto, se muestran los reportes ya procesados (plan B al final).

NDA: los videos y el SOP en Word **no están en el repo**. Van en una carpeta fuera de Git
(aquí `..\sopvid-material\`). Capturas y PDF generados tampoco entran a Git si muestran rostros.

## 0. Antes de empezar

- Todo arriba: `.\scripts\levantar.ps1` (README §5). `Invoke-RestMethod http://localhost:8000/health`
  con `db` y `llm` en `ok` y `avisos` vacío (si no, faltan claves en `.env`).
- Claves en `.env`: `CLAVE_CARGA` (SOP, videos, reportes, PDF) y `CLAVE_BUSQUEDA` (`/buscar`).
- Modo generar **sin imágenes** (ADR-024; decisión del 13 nov): las descripciones de imágenes inventan
  objetos que llegan al SOP (RNF-06, #16). La casilla "Describir imágenes" de `/nuevo` va apagada y la
  API recibe `analizar_imagenes=false`.
- Con la API en Docker, Whisper transcribe en CPU: 0.58–0.63× la duración del video con los modelos
  ya descargados (A de 2:15: 78 s; E de 3:47: 144 s). **La primera vez** suma ~2 min de descarga de
  Whisper y MiniLM, y la primera conversión de SOP ~1.5 min de carga de Gemma. Calienta todo antes.

Variables de PowerShell para los comandos de abajo (desde la raíz del repo):

```powershell
$m = "..\sopvid-material"                                  # VIDEO-A.mp4, VIDEO-E.mp4, sop_filtro_agua.docx
$c = ((Get-Content .env | ? { $_ -match '^CLAVE_CARGA=' }) -split '=',2)[1]
$b = ((Get-Content .env | ? { $_ -match '^CLAVE_BUSQUEDA=' }) -split '=',2)[1]
$api = "http://localhost:8000"; $hc = @{ "X-Clave-Acceso" = $c }; $hb = @{ "X-Clave-Acceso" = $b }
```

## 1. SOP en Word a la biblioteca (RF-01, RF-05)

```powershell
$sop = curl.exe -s -H "X-Clave-Acceso: $c" -F "archivo=@$m\sop_filtro_agua.docx" "$api/sops" | ConvertFrom-Json
do { Start-Sleep 3; $e = Invoke-RestMethod "$api/sops/$($sop.id)/estado" -Headers $hc; $e.estado } until ($e.estado -in "listo","error")
@(Invoke-RestMethod "$api/sops" -Headers $hc) | % { $_ } | ft id, codigo, origen, titulo, videos_validados
```

Esperado: `estado: listo`, `metodo: llm` (un Word no sigue la plantilla), 6 pasos, 0 advertencias. Un
SOP cargado entra a la biblioteca solo. Tarda 25 s con Gemma ya cargada; **2 min 43 s la primera vez**
(101 s son la carga del modelo).

## 2. Video A validado (RF-13 a RF-20)

```powershell
$v = curl.exe -s -H "X-Clave-Acceso: $c" -F "archivo=@$m\VIDEO-A.mp4" -F "titulo=Demo A" -F modo=validar -F "sop_id=$($sop.id)" -F idioma=es "$api/videos" | ConvertFrom-Json
do { Start-Sleep 3; $s = Invoke-RestMethod "$api/videos/$($v.id)" -Headers $hc; "$($s.proceso) $($s.etapa) $($s.progreso)%" } until ($s.proceso -in "listo","error","afinidad_baja")
$r = Invoke-RestMethod "$api/videos/$($v.id)/reporte" -Headers $hc
"$($r.cumplimiento) % $($r.semaforo)"; $r.filas | group estado | ft Name, Count
```

Esperado: **≥ 90 %, verde, sin *Falta*** (ensayo: 100 % tres veces y 91.67 % una; 5–6 *Cumple*,
0–1 *Parcial*, 5–7 *Sobra*; afinidad 74). `metadatos.dispositivos`: Whisper `cpu` y Gemma `gpu` en
Docker; Whisper `gpu` con la API en el host. Tiempo con los modelos en caché: Docker 78 s; host con
GPU 35 s.

## 3. PDF del reporte y QR (RF-29, RF-30)

```powershell
curl.exe -s -H "X-Clave-Acceso: $c" -o reporte_A.pdf "$api/videos/$($v.id)/pdf"      # fuera del repo
```

Esperado: 4 páginas, tamaño carta, 5 QR (uno por hallazgo que no es un *Cumple* limpio), cada uno con
`<APP_URL_PUBLICA>/v/<id>?t=<segundo>&k=<token>` y el mismo enlace escrito debajo. El token abre ese
video y su miniatura **sin clave**; con el token de otro video, uno alterado o sin token, 401. Para
escanear con un celular: `APP_URL_PUBLICA=http://<IP>:4200` en `.env`, reiniciar la API,
**regenerar el PDF** y la regla de firewall del README ("QR del PDF con el celular"). Ensayo: el
celular abrió `/v/<id>` con el video en el segundo 49.

## 4. Publicar y buscar (RF-32 a RF-37)

```powershell
Invoke-RestMethod "$api/videos/$($v.id)/publicar" -Method Post -Headers $hc | ft publicado, palabras_indexadas
foreach ($q in "manometro","cartuchos","llave de paso") {
  $x = Invoke-RestMethod "$api/buscar" -Method Post -Headers $hb -ContentType "application/json" -Body (@{ consulta = $q } | ConvertTo-Json)
  "{0}: {1} coincidencias, segundos {2}" -f $q, $x.total, (($x.resultados | % { $_.t_inicio }) -join ", ")
}
```

Esperado, con **solo un** video A publicado: «manometro» 3, «cartuchos» 4, «llave de paso» 2 (en 6 a
12 ms del lado del servidor). Si publicas más de un video, se suman las coincidencias de cada uno. La clave de
carga **no** abre `/buscar` (401) y viceversa.

## 5. Descargas (RF-31)

```powershell
curl.exe -s -H "X-Clave-Acceso: $c" -OJ "$api/videos/$($v.id)/download/srt"          # también txt y json
```

Esperado: `demo_a.srt` con 24 bloques, UTF-8, índices desde 1 y tiempos `HH:MM:SS,mmm`.

## 6. E en modo generar, sin imágenes (RF-22 a RF-27)

```powershell
$e = curl.exe -s -H "X-Clave-Acceso: $c" -F "archivo=@$m\VIDEO-E.mp4" -F "titulo=Demo E" -F modo=generar -F analizar_imagenes=false "$api/videos" | ConvertFrom-Json
do { Start-Sleep 3; $s = Invoke-RestMethod "$api/videos/$($e.id)" -Headers $hc; "$($s.proceso) $($s.etapa)" } until ($s.proceso -in "listo","error")
$g = Invoke-RestMethod "$api/sops/$($s.sop_id)" -Headers $hc
"pasos: $($g.sop.pasos.Count) · advertencias: $(($g.advertencias | % { $_.tipo }) -join ', ')"
Invoke-RestMethod "$api/sops/$($s.sop_id)/biblioteca" -Method Post -Headers $hc | ft codigo, en_biblioteca
curl.exe -s -H "X-Clave-Acceso: $c" -OJ "$api/sops/$($s.sop_id)/pdf"
```

Esperado: video en inglés (227 s), SOP en español de unos 13 pasos con cuadro resumen, palabras clave
y evidencia por dato (las citas se quedan en inglés: son lo que dijo el operador); guardado en la
biblioteca con código nuevo; PDF de 4 páginas con un QR a `/v/<id>?t=0.0&k=…`. Tarda 144 s en Docker
(86 s de Whisper en CPU). Desde la pantalla, antes de guardar: editar (unir, reordenar, quitar con
deshacer).

**Riesgo conocido (#32):** en el ensayo salió la advertencia `sin_traducir`: un término de las
palabras clave quedó sin traducir al español. Pasa en ~1 de 3 corridas. Si pasa en vivo, se corrige
en el editor y se explica; no es de las imágenes.

## 7. Pantalla: lo que no se comprueba por la API

Lo que Emmanuel recorre en el navegador (`http://localhost:4200`, claves de `.env`):

- Inicio y barra principal; `/acceso` con clave equivocada y correcta; una vista con la clave de la otra.
- `/nuevo`: tres modos, consentimiento, casilla de imágenes apagada, estimación de tiempo, subida por partes.
- Procesando: etapas, TXT en vivo y paso al resultado.
- Reporte: semáforo, tabla, y que **al hacer clic en una fila el video salta a su segundo**; "Cómo se obtuvo".
- `/sops` (biblioteca, borrar uno en uso da 409 explicado) y el editor del SOP generado.
- `/videos`: publicar, descargas (TXT, SRT, JSON, PDF).
- `/buscar`: chat, filtros por SOP y video, resultado que abre el video en el segundo exacto, "Ver SOP".
- `/v/<id>?t=&k=` desde el celular, con una **captura a 360 px** de ancho.

## Plan B

- Procesar A, B y E antes y mostrar lo guardado: `GET /videos` los lista y cada reporte abre sin
  volver a procesar. Repetir la validación con la misma segmentación da el mismo porcentaje
  (`POST /videos/{id}/validar`, ADR-022).
- Si el modelo no responde: `/health` con `llm` distinto de `ok` → `docker compose logs ollama`;
  `docker compose exec ollama ollama ps` dice si quedó en GPU o CPU.
- Si hay prisa y videos largos: la API en el host con GPU (README, opción D).
