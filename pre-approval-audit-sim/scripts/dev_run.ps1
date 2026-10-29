# Start the app on the Docker-free sqlite_local backend (Windows / PowerShell).
# Run from the repo root:  ./scripts/dev_run.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host "Created .env from .env.example (sqlite_local backend, no Docker needed)."
}

python -m uvicorn integration.app:app --host 127.0.0.1 --port 8000 --reload
