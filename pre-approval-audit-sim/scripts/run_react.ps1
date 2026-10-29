# Start the React + FastAPI stack (Veriflow) - Windows / PowerShell.
# Run from the repo root:  ./scripts/run_react.ps1
#
# Launches two servers, each in its own window:
#   - FastAPI backend  (integration.app:app) on http://127.0.0.1:8002
#   - Vite dev server  (web/)                on http://localhost:5173
#
# Uses the checked-in portable Node runtime (no system Node install needed)
# and the project's .venv Python. Close either window (or Ctrl+C in it) to
# stop that service; re-run this script to start both again.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host "Created .env from .env.example (sqlite_local backend, no Docker needed)."
}

$venvPython = "$root\.venv\Scripts\python.exe"
$nodeExe    = "$root\.node-runtime\node-v20.20.2-win-x64\node.exe"
$viteJs     = "$root\web\node_modules\vite\bin\vite.js"

if (-not (Test-Path $venvPython)) { throw "Python venv not found at $venvPython - run: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e `".[dev]`"" }
if (-not (Test-Path $nodeExe))    { throw "Portable Node runtime not found at $nodeExe" }
if (-not (Test-Path $viteJs))     { throw "web/node_modules not found - run: cd web; & `"$nodeExe`" (Join-Path (Split-Path $nodeExe) 'npm.cmd') install" }

Write-Host "Starting FastAPI backend on http://127.0.0.1:8002 ..."
Start-Process -FilePath $venvPython -ArgumentList @(
    "-m", "uvicorn", "integration.app:app",
    "--host", "127.0.0.1", "--port", "8002", "--reload",
    "--app-dir", $root
) -WorkingDirectory $root

Write-Host "Starting Vite dev server on http://localhost:5173 ..."
Start-Process -FilePath $nodeExe -ArgumentList @(
    $viteJs, "$root\web", "--port", "5173"
) -WorkingDirectory "$root\web"

Write-Host ""
Write-Host "Veriflow is starting in two new windows:"
Write-Host "  API : http://127.0.0.1:8002/health"
Write-Host "  App : http://localhost:5173"
Write-Host "Close either window (or Ctrl+C inside it) to stop that service."
