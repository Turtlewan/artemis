# launch-artemis.ps1 - start the Artemis brain, then open the desktop client.
# Goal: one double-click launches the whole app, with no manual terminals.
#   1. Start the brain HTTP API (artemis serve) hidden in the background (if not already up).
#   2. Wait until it answers /healthz.
#   3. Open the Tauri client: the built release exe if present, else `tauri dev`.
# Requires uv + Python on this machine (the dev box has them). Not a portable installer.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot   # scripts dir -> repo root
$port = if ($env:ARTEMIS_BRAIN_PORT) { $env:ARTEMIS_BRAIN_PORT } else { "8030" }
$health = "http://127.0.0.1:$port/healthz"

function Test-BrainUp {
    try {
        $r = Invoke-WebRequest -Uri $health -TimeoutSec 2 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

# 1. Start the brain if it isn't already serving.
if (Test-BrainUp) {
    Write-Host "Artemis brain already running on port $port."
} else {
    Write-Host "Starting Artemis brain (artemis serve) on port $port ..."
    $serveArgs = @("run", "artemis", "serve", "--port", $port)
    Start-Process -FilePath "uv" -ArgumentList $serveArgs -WorkingDirectory $repo -WindowStyle Hidden
}

# 2. Wait for health (up to 90s; a cold start compiles/loads).
$deadline = (Get-Date).AddSeconds(90)
while (-not (Test-BrainUp)) {
    if ((Get-Date) -gt $deadline) {
        Write-Error "Brain did not become healthy within 90s. Try: uv run artemis serve --port $port"
        exit 1
    }
    Start-Sleep -Milliseconds 500
}
Write-Host "Brain is up."

# 3. Open the client: prefer a built release exe, fall back to dev mode.
$releaseDir = Join-Path $repo "client\src-tauri\target\release"
$exe = Get-ChildItem -Path $releaseDir -Filter "*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch "build|deps" } | Select-Object -First 1

if ($null -ne $exe) {
    Write-Host "Opening client: $($exe.FullName)"
    Start-Process -FilePath $exe.FullName
} else {
    Write-Host "No built client exe found; launching dev mode (npm run tauri dev)."
    $clientDir = Join-Path $repo "client"
    $devArgs = @("run", "tauri", "dev")
    Start-Process -FilePath "npm" -ArgumentList $devArgs -WorkingDirectory $clientDir -WindowStyle Hidden
}

Write-Host "Artemis launched."
