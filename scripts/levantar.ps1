<#
.SYNOPSIS
    Levanta SOPVID de punta a punta con docker compose: de un clon recién hecho a la demo.

.DESCRIPTION
    Hace, en este orden, lo que antes eran pasos sueltos del README:
      1. Crea .env desde .env.example si falta, con claves de acceso nuevas (CLAVE_CARGA,
         CLAVE_BUSQUEDA y SECRETO_ENLACES). Un .env que ya existe no se toca.
      2. Detecta la GPU NVIDIA con nvidia-smi y revisa que Docker tenga el runtime "nvidia". Si las
         dos cosas están, suma docker-compose.gpu.yml y Ollama corre Gemma en la GPU. Si falta alguna,
         Gemma corre en CPU: mismo modelo y mismo resultado, solo más lento (ADR-018, RNF-07).
         La api dentro de Docker siempre transcribe en CPU (ADR-014).
      3. Levanta la base, la api, el frontend y Ollama (el modelo se descarga una sola vez, ~6.6 GB).
      4. Espera a que la api responda, aplica las migraciones y espera a que Gemma esté descargado
         (/health con "llm": "ok").
      5. Carga Gemma una vez para que la primera conversión de SOP no pague la carga en frío.

    Uso, desde la raíz del repo:
        .\scripts\levantar.ps1              # todo lo anterior
        .\scripts\levantar.ps1 -Build       # reconstruye la imagen de la api
        .\scripts\levantar.ps1 -Cpu         # Ollama en CPU aunque haya GPU (para medir)
        .\scripts\levantar.ps1 -SinLLM      # solo api + base + frontend (sin Ollama)
        .\scripts\levantar.ps1 -SoloEnv     # crea .env y sale, para editarlo antes de levantar
        .\scripts\levantar.ps1 -NoEsperar   # levanta y sale, sin migrar ni esperar al modelo
        .\scripts\levantar.ps1 -SinCalentar # no carga Gemma al final
        .\scripts\levantar.ps1 -Detener     # detiene todo, conserva datos y modelos
        .\scripts\levantar.ps1 -Plan        # solo dice qué haría, sin escribir ni levantar nada

    Con -NoEsperar la migración queda a tu cargo: docker compose exec api alembic upgrade head.
    Para ver dónde quedó Gemma tras la primera petición:
        docker compose exec ollama ollama ps    # columna PROCESSOR
#>
param(
    [switch]$Build,
    [switch]$Cpu,
    [switch]$SinLLM,
    [switch]$Detener,
    [switch]$Plan,
    [switch]$SoloEnv,
    [switch]$NoEsperar,
    [switch]$SinCalentar
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$inicio = Get-Date

function Get-GpuNvidia {
    # Nombre de la primera GPU, o $null si no hay nvidia-smi, driver o GPU.
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) { return $null }
    try {
        $salida = & $smi.Source --query-gpu=name --format=csv,noheader 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $salida) { return $null }
        return ($salida | Select-Object -First 1).Trim()
    } catch {
        return $null
    }
}

function Test-RuntimeNvidia {
    # True si Docker puede pasar la GPU a un contenedor (Docker Desktop con WSL2 o NVIDIA Container Toolkit).
    try {
        $runtimes = docker info --format "{{json .Runtimes}}" 2>$null
        return ($LASTEXITCODE -eq 0 -and $runtimes -match '"nvidia"')
    } catch {
        return $false
    }
}

function Get-ValorEnv([string]$Clave, [string]$Defecto) {
    # Valor de CLAVE en .env sin el comentario de la línea; $Defecto si no está o está vacío.
    if (-not (Test-Path ".env")) { return $Defecto }
    foreach ($linea in Get-Content ".env" -Encoding UTF8) {
        if ($linea -match "^\s*$([regex]::Escape($Clave))=(.*)$") {
            $valor = ($Matches[1] -replace '\s+#.*$', '').Trim()
            if ($valor) { return $valor }
        }
    }
    return $Defecto
}

function Get-TextoAleatorio([int]$Bytes) {
    # Texto url-safe sacado del generador criptográfico del sistema (no hace falta Python).
    $b = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($b) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($b).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function New-ArchivoEnv {
    # Copia .env.example a .env y llena las tres claves vacías. Devuelve las dos claves cortas.
    $texto = [IO.File]::ReadAllText((Join-Path $PWD ".env.example"), [Text.Encoding]::UTF8)
    $carga = "carga-" + (Get-Random -Minimum 1000 -Maximum 9999)
    $busqueda = "busca-" + (Get-Random -Minimum 1000 -Maximum 9999)
    $enlaces = Get-TextoAleatorio 32
    $texto = $texto -replace "(?m)^CLAVE_CARGA=[ \t]*(#.*)?\r?$", "CLAVE_CARGA=$carga"
    $texto = $texto -replace "(?m)^CLAVE_BUSQUEDA=[ \t]*(#.*)?\r?$", "CLAVE_BUSQUEDA=$busqueda"
    $texto = $texto -replace "(?m)^SECRETO_ENLACES=[ \t]*(#.*)?\r?$", "SECRETO_ENLACES=$enlaces"
    [IO.File]::WriteAllText((Join-Path $PWD ".env"), $texto, (New-Object Text.UTF8Encoding($false)))
    return @($carga, $busqueda)
}

function Get-Salud([int]$Puerto) {
    # Respuesta de GET /health como objeto, o $null si la api todavía no responde.
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Puerto/health" -TimeoutSec 5
    } catch {
        return $null
    }
}

function Write-Paso([string]$Texto) {
    Write-Host ("[{0:mm\:ss}] {1}" -f ((Get-Date) - $inicio), $Texto)
}

# ── 1. .env ──
$hayEnv = Test-Path ".env"
if (-not $hayEnv) {
    if (-not (Test-Path ".env.example")) {
        Write-Error "No encuentro .env.example: ejecuta el script desde un clon completo del repo."
    }
    if ($Plan) {
        Write-Host "Se crearía .env desde .env.example con CLAVE_CARGA, CLAVE_BUSQUEDA y SECRETO_ENLACES nuevas."
    } else {
        $claves = New-ArchivoEnv
        Write-Paso "Creé .env con claves nuevas. Clave de carga: $($claves[0]) · clave de búsqueda: $($claves[1])"
        Write-Host "           Quedan en .env (no versionado); SECRETO_ENLACES, que firma los QR, también."
    }
} else {
    $vacias = @("CLAVE_CARGA", "CLAVE_BUSQUEDA", "SECRETO_ENLACES") | Where-Object { -not (Get-ValorEnv $_ "") }
    if ($vacias) {
        Write-Host "Aviso: $($vacias -join ', ') vacía(s) en .env; esas vistas quedan abiertas (README, claves de acceso)."
    }
}
if ($SoloEnv) {
    if ($hayEnv) { Write-Host ".env ya existe: no se toca." }
    exit 0
}

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker no responde: abre Docker Desktop y vuelve a intentar."
}

$archivos = @("-f", "docker-compose.yml")
$perfil = if ($SinLLM) { @() } else { @("--profile", "llm") }

if ($Detener) {
    docker compose @archivos --profile llm down
    exit $LASTEXITCODE
}

# ── 2. GPU o CPU ──
$gpu = Get-GpuNvidia
$modo = "CPU"
if ($SinLLM) {
    $modo = "ninguno"
    $motivo = "sin el profile llm: no se levanta Ollama"
} elseif ($Cpu) {
    $motivo = "se pidió -Cpu"
} elseif (-not $gpu) {
    $motivo = "no se detectó GPU NVIDIA (nvidia-smi)"
} elseif (-not (Test-RuntimeNvidia)) {
    $motivo = "hay GPU ($gpu) pero Docker no tiene el runtime nvidia (revisa WSL2 en Docker Desktop)"
} else {
    $archivos += @("-f", "docker-compose.gpu.yml")
    $modo = "GPU"
    $motivo = $gpu
}

Write-Host "Ollama en $modo · $motivo"
$argumentos = $archivos + $perfil + @("up", "-d")
if ($Build) { $argumentos += "--build" }
if ($Plan) {
    Write-Host "docker compose $($argumentos -join ' ')"
    if (-not $NoEsperar) {
        $despues = "Después: espera a /health y aplica las migraciones"
        if (-not $SinLLM) { $despues += ", espera a que Gemma esté descargado y lo carga una vez" }
        Write-Host "$despues."
    }
    exit 0
}

# ── 3. Levantar ──
Write-Paso "Levantando (la primera vez construye la imagen de la api, unos 3 min)…"
docker compose @argumentos
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($modo -eq "CPU" -and -not $SinLLM) {
    Write-Host "Gemma va a correr en CPU: más lento, mismo resultado (ADR-018)."
}

$puerto = [int](Get-ValorEnv "APP_PORT" "8000")
$web = [int](Get-ValorEnv "WEB_PORT" "4200")

if ($NoEsperar) {
    Write-Host "Listo (sin esperar). Salud: curl.exe http://127.0.0.1:$puerto/health"
    exit 0
}

# ── 4. Esperar a la api, migrar y esperar al modelo ──
Write-Paso "Esperando a la api…"
$limite = (Get-Date).AddMinutes(3)
while (-not (Get-Salud $puerto)) {
    if ((Get-Date) -gt $limite) {
        Write-Error "La api no respondió en 3 min. Revisa: docker compose logs api"
    }
    Start-Sleep -Seconds 3
}

Write-Paso "Aplicando migraciones…"
docker compose @archivos exec -T api alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Error "Falló la migración. Revisa: docker compose logs api db" }

if (-not $SinLLM) {
    Write-Paso "Esperando a Gemma (la primera vez descarga ~6.6 GB: 5-10 min según la red)…"
    $limite = (Get-Date).AddMinutes(40)
    $ultimo = Get-Date
    while ($true) {
        $salud = Get-Salud $puerto
        if ($salud -and $salud.llm -eq "ok") { break }
        if ((Get-Date) -gt $limite) {
            Write-Error "Gemma no quedó lista en 40 min. Revisa: docker compose logs ollama-pull"
        }
        if (((Get-Date) - $ultimo).TotalSeconds -ge 30) {
            $ultimo = Get-Date
            $registro = docker compose @archivos --profile llm logs ollama-pull --tail 3 2>$null | Out-String
            $avance = [regex]::Matches($registro, '\d+% [^\r\n]*?\d+(\.\d+)? [MG]B/[\d.]+ [MG]B') | Select-Object -Last 1
            Write-Paso ("Descargando… " + $(if ($avance) { $avance.Value } else { "(sin detalle aún)" }))
        }
        Start-Sleep -Seconds 5
    }
    Write-Paso "Gemma descargado."

    # ── 5. Primera carga ──
    if (-not $SinCalentar) {
        $modelo = Get-ValorEnv "LLM_MODEL" "gemma4:e4b-it-q4_K_M"
        Write-Paso "Cargando Gemma una vez (la primera carga en un disco nuevo tarda ~1.5 min)…"
        try {
            # keep_alive 0: carga, genera un token y lo suelta, para no ocupar la VRAM de Whisper.
            $cuerpo = @{ model = $modelo; prompt = "ok"; stream = $false; keep_alive = 0; options = @{ num_predict = 1 } } |
                ConvertTo-Json -Depth 3
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post -Body $cuerpo `
                -ContentType "application/json" -TimeoutSec 600 | Out-Null
        } catch {
            Write-Host "Aviso: no pude cargar Gemma de antemano ($($_.Exception.Message)); la primera conversión será más lenta."
        }
    }
}

$salud = Get-Salud $puerto
Write-Paso "Listo."
Write-Host ("  Estado: db={0} · llm={1}" -f $salud.db, $salud.llm)
Write-Host "  Web:    http://localhost:$web"
Write-Host "  API:    http://localhost:$puerto/docs"
Write-Host "  Claves de acceso: CLAVE_CARGA y CLAVE_BUSQUEDA de .env"
Write-Host "  La primera vez que subas un video, la api descarga Whisper (~1.6 GB) y MiniLM (~0.5 GB): unos 2-3 min más."
