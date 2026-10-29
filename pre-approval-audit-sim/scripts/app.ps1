# Launch the unified operator application (Dashboard / Review / Settings).
# Run from the repo root:  ./scripts/app.ps1
# Populate the store first with scripts/run_batch.py (and scripts/report.py for
# the dashboard's ops tab).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
python -m streamlit run streamlit_app.py --server.port 8501
