# =============================================================================
#  AIDEN v2.0 — Start Script  (Windows PowerShell)
#  Usage:  .\start.ps1 [-Setup] [-Docker] [-Stop]
#
#  Flags:
#    -Setup    Force reinstall of Python dependencies
#    -Docker   Use Docker for MongoDB instead of a local mongod
#    -Stop     Kill all AIDEN processes and exit
# =============================================================================

param(
    [switch]$Setup,
    [switch]$Docker,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

# ── Colour helpers ────────────────────────────────────────────────────────────
function Write-Info    { param($m) Write-Host "[AIDEN]  $m" -ForegroundColor Cyan }
function Write-Ok      { param($m) Write-Host "[OK]     $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "[!]      $m" -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host "[ERROR]  $m" -ForegroundColor Red }
function Write-Header  {
    param($m)
    Write-Host ""
    Write-Host ("=" * 50) -ForegroundColor Cyan
    Write-Host "  $m" -ForegroundColor Cyan
    Write-Host ("=" * 50) -ForegroundColor Cyan
    Write-Host ""
}

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir    = Join-Path $ScriptDir ".venv"
$PidDir     = Join-Path $ScriptDir ".pids"
$LogDir     = Join-Path $ScriptDir "logs"
$ApiPort    = 8000
$UiPort     = 3000

New-Item -ItemType Directory -Force -Path $PidDir  | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir  | Out-Null

# ── Stop mode ─────────────────────────────────────────────────────────────────
if ($Stop) {
    Write-Header "Stopping AIDEN"
    Get-ChildItem "$PidDir\*.pid" | ForEach-Object {
        $name = $_.BaseName
        $pid  = Get-Content $_.FullName
        try {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Write-Ok "Stopped $name (PID $pid)"
        } catch { Write-Warn "$name already stopped" }
        Remove-Item $_.FullName -Force
    }
    if ($Docker) {
        Write-Info "Stopping Docker services..."
        docker compose -f "$ScriptDir\deploy\docker-compose.yml" down 2>$null
    }
    Write-Ok "All services stopped."
    exit 0
}

# ── Banner ────────────────────────────────────────────────────────────────────
Clear-Host
Write-Host @"
    ___    _________  _______   __
   /   |  /  _/ __ \/ ____/ | / /
  / /| |  / // / / / __/ /  |/ /
 / ___ |_/ // /_/ / /___/ /|  /
/_/  |_/___/_____/_____/_/ |_/

  v2.0 - AI Intelligent Daily Executive Navigator
"@ -ForegroundColor Cyan

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
Write-Header "Checking Prerequisites"

# Python 3.11+
try {
    $pyVer = python --version 2>&1
    if ($pyVer -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]; $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
            Write-Err "Python 3.11+ required (found $pyVer). Install from https://python.org"
            exit 1
        }
        Write-Ok "Python $major.$minor"
    }
} catch {
    Write-Err "Python not found. Install from https://python.org"
    exit 1
}

# Docker
if ($Docker) {
    try {
        $dv = docker --version
        Write-Ok "Docker found"
    } catch {
        Write-Err "--Docker flag set but Docker not found. Install from https://docker.com"
        exit 1
    }
}

# ── 2. Environment file ───────────────────────────────────────────────────────
Write-Header "Environment Configuration"

$EnvFile    = Join-Path $ScriptDir ".env"
$EnvExample = Join-Path $ScriptDir ".env.example"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-Warn ".env not found — copied from .env.example"
        Write-Warn "Please edit .env and fill in GEMINI_API_KEY + JWT_SECRET, then re-run."
        Write-Host ""
        Write-Host "  Opening .env in Notepad..." -ForegroundColor Yellow
        Start-Process notepad $EnvFile -Wait
    } else {
        Write-Err ".env.example not found. Cannot create .env automatically."
        exit 1
    }
}

# Parse .env into a hashtable
$EnvVars = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match "^\s*([^#=]+?)\s*=\s*(.*)\s*$") {
        $EnvVars[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
    }
}

$GeminiKey = $EnvVars["GEMINI_API_KEY"]
$JwtSecret = $EnvVars["JWT_SECRET"]

if ([string]::IsNullOrWhiteSpace($GeminiKey) -or $GeminiKey -eq "your_gemini_api_key_here") {
    Write-Err "GEMINI_API_KEY is not set in .env"
    exit 1
}
if ([string]::IsNullOrWhiteSpace($JwtSecret) -or $JwtSecret -eq "your_jwt_secret_min_32_characters_required_here") {
    Write-Err "JWT_SECRET is not set in .env"
    Write-Host "  Generate one in PowerShell:" -ForegroundColor Yellow
    Write-Host "  python -c `"import secrets; print(secrets.token_urlsafe(32))`"" -ForegroundColor Cyan
    exit 1
}
if ($JwtSecret.Length -lt 32) {
    Write-Err "JWT_SECRET must be at least 32 characters (currently $($JwtSecret.Length))"
    exit 1
}

$ApiPort = if ($EnvVars["API_PORT"]) { [int]$EnvVars["API_PORT"] } else { 8000 }
$UiPort  = if ($EnvVars["UI_PORT"])  { [int]$EnvVars["UI_PORT"]  } else { 3000  }

Write-Ok ".env loaded and validated"

# ── 3. Virtual Environment ────────────────────────────────────────────────────
Write-Header "Python Environment"

if (-not (Test-Path $VenvDir) -or $Setup) {
    Write-Info "Creating virtual environment..."
    python -m venv $VenvDir
    Write-Ok "Virtual environment created at .venv\"
}

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipExe    = Join-Path $VenvDir "Scripts\pip.exe"
$UvicornExe = Join-Path $VenvDir "Scripts\uvicorn.exe"

$InstalledFlag = Join-Path $VenvDir ".installed"
if (-not (Test-Path $InstalledFlag) -or $Setup) {
    Write-Info "Installing dependencies (1-2 min on first run)..."
    & $PipExe install --quiet --upgrade pip
    & $PipExe install --quiet -e $ScriptDir
    New-Item -ItemType File -Path $InstalledFlag -Force | Out-Null
    Write-Ok "Dependencies installed"
} else {
    Write-Ok "Dependencies already installed (use -Setup to reinstall)"
}

# ── 4. MongoDB ────────────────────────────────────────────────────────────────
Write-Header "Starting MongoDB"

if ($Docker) {
    Write-Info "Starting MongoDB via Docker Compose..."
    docker compose -f "$ScriptDir\deploy\docker-compose.yml" up -d mongo
    Write-Info "Waiting for MongoDB..."
    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        try {
            docker exec aiden_mongo mongosh --eval "db.adminCommand('ping')" 2>$null | Out-Null
            Write-Ok "MongoDB is ready (Docker)"
            $ready = $true; break
        } catch { Start-Sleep 2 }
    }
    if (-not $ready) { Write-Err "MongoDB did not start in time."; exit 1 }
} else {
    $mongodPath = Get-Command mongod -ErrorAction SilentlyContinue
    if ($mongodPath) {
        $testPing = mongosh --eval "db.adminCommand('ping')" --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Info "Starting local mongod..."
            $mongoData = Join-Path $ScriptDir "data\mongodb"
            New-Item -ItemType Directory -Force -Path $mongoData | Out-Null
            $mongoLog  = Join-Path $LogDir "mongodb.log"
            Start-Process mongod -ArgumentList `
                "--dbpath `"$mongoData`" --port 27017 --logpath `"$mongoLog`"" `
                -WindowStyle Hidden
            Start-Sleep 3
            Write-Ok "Local mongod started"
        } else {
            Write-Ok "MongoDB already running"
        }
    } else {
        Write-Err "mongod not found. Options:"
        Write-Warn "  1. Run with -Docker flag (requires Docker Desktop)"
        Write-Warn "  2. Install MongoDB Community: https://www.mongodb.com/try/download/community"
        exit 1
    }
}

# ── 5. ChromaDB directory ─────────────────────────────────────────────────────
$ChromaPath = if ($EnvVars["CHROMA_PATH"]) { $EnvVars["CHROMA_PATH"] } else { ".\data\chroma" }
New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "data\chroma") | Out-Null
Write-Ok "ChromaDB data directory ready"

# ── 6. FastAPI Backend ────────────────────────────────────────────────────────
Write-Header "Starting FastAPI Backend"

$ApiLog     = Join-Path $LogDir "api.log"
$ApiPidFile = Join-Path $PidDir "api.pid"

# Kill stale API
if (Test-Path $ApiPidFile) {
    $oldPid = Get-Content $ApiPidFile
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Remove-Item $ApiPidFile -Force
}

Set-Location $ScriptDir

# Load .env into current process environment so uvicorn inherits it
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match "^\s*([^#=]+?)\s*=\s*(.*)\s*$") {
        [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"').Trim("'"))
    }
}

$ApiProc = Start-Process -FilePath $UvicornExe `
    -ArgumentList "src.api.main:app --host 0.0.0.0 --port $ApiPort --workers 1" `
    -RedirectStandardOutput $ApiLog `
    -RedirectStandardError  $ApiLog `
    -PassThru -WindowStyle Hidden

$ApiProc.Id | Out-File $ApiPidFile -Force
Write-Info "API starting (PID $($ApiProc.Id))..."

$started = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest "http://localhost:$ApiPort/health" -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { Write-Ok "FastAPI backend running"; $started = $true; break }
    } catch { Start-Sleep 1 }
}
if (-not $started) {
    Write-Err "API did not start. Check log: $ApiLog"
    Get-Content $ApiLog -Tail 20 | Write-Host
    exit 1
}

Write-Host "  http://localhost:$ApiPort      (API)" -ForegroundColor Green
Write-Host "  http://localhost:$ApiPort/docs (API Docs)" -ForegroundColor Green

# ── 7. UI File Server ─────────────────────────────────────────────────────────
Write-Header "Starting UI"

$UiLog     = Join-Path $LogDir "ui.log"
$UiPidFile = Join-Path $PidDir "ui.pid"

if (Test-Path $UiPidFile) {
    $oldPid = Get-Content $UiPidFile
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Remove-Item $UiPidFile -Force
}

$UiDir  = Join-Path $ScriptDir "ui_react"
$UiProc = Start-Process -FilePath python `
    -ArgumentList "-m http.server $UiPort" `
    -WorkingDirectory $UiDir `
    -RedirectStandardOutput $UiLog `
    -RedirectStandardError  $UiLog `
    -PassThru -WindowStyle Hidden

$UiProc.Id | Out-File $UiPidFile -Force
Start-Sleep 1

if (-not $UiProc.HasExited) {
    Write-Ok "UI server running"
    Write-Host "  http://localhost:$UiPort (UI)" -ForegroundColor Green
} else {
    Write-Err "UI server failed. Check: $UiLog"
}

# ── 8. Open browser ───────────────────────────────────────────────────────────
Start-Sleep 1
Start-Process "http://localhost:$UiPort"

# ── 9. Summary ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("=" * 50) -ForegroundColor Green
Write-Host "  AIDEN v2.0 is running!" -ForegroundColor Green
Write-Host ("=" * 50) -ForegroundColor Green
Write-Host ""
Write-Host "  UI        http://localhost:$UiPort" -ForegroundColor Cyan
Write-Host "  API       http://localhost:$ApiPort" -ForegroundColor Cyan
Write-Host "  API Docs  http://localhost:$ApiPort/docs" -ForegroundColor Cyan
Write-Host "  API Log   $ApiLog" -ForegroundColor DarkGray
Write-Host "  UI Log    $UiLog" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  To stop:  .\start.ps1 -Stop" -ForegroundColor Yellow
Write-Host ""

# Tail the API log
Write-Info "Streaming API logs (Ctrl+C to stop tailing — services keep running):"
Get-Content $ApiLog -Wait
