<#
.SYNOPSIS
    Levanta SOPVID con docker compose y usa la GPU NVIDIA solo si existe (ADR-018).

.DESCRIPTION
    Detecta la GPU con nvidia-smi y revisa que Docker tenga el runtime "nvidia". Si las dos cosas
    están, suma docker-compose.gpu.yml y Ollama corre Gemma en la GPU. Si falta alguna, levanta el
    compose base y Gemma corre en CPU: mismo modelo y mismo resultado, solo más lento (RNF-07).
    La api dentro de Docker sigue en CPU (ADR-014).

    Uso, desde la raíz del repo:
        .\scripts\levantar.ps1              # api + base + Ollama, con GPU si hay
        .\scripts\levantar.ps1 -Build       # reconstruye la imagen de la api
        .\scripts\levantar.ps1 -Cpu         # Ollama en CPU aunque haya GPU (para medir)
        .\scripts\levantar.ps1 -SinLLM      # solo api + base (sin el profile llm)
        .\scripts\levantar.ps1 -Detener     # detiene todo, conserva datos y modelos
        .\scripts\levantar.ps1 -Plan        # solo dice qué haría, sin levantar nada

    Para ver dónde quedó Gemma tras la primera petición:
        docker compose exec ollama ollama ps    # columna PROCESSOR
#>
param(
    [switch]$Build,
    [switch]$Cpu,
    [switch]$SinLLM,
    [switch]$Detener,
    [switch]$Plan
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".env")) {
    Write-Error "Falta .env: copia .env.example a .env antes de levantar."
}

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
    exit 0
}
docker compose @argumentos
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($modo -eq "CPU" -and -not $SinLLM) {
    Write-Host "Gemma va a correr en CPU: más lento, mismo resultado (ADR-018)."
}
Write-Host "Listo. Salud: curl.exe http://127.0.0.1:8000/health"
