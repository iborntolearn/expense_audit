# Launch the business dashboard (Windows / PowerShell).
# Run from the repo root:  ./scripts/dashboard.ps1
# Populate the store first with scripts/run_batch.py (and scripts/report.py for
# the ops tab's model/latency panel).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
python -m streamlit run dashboard/app.py --server.port 8502
