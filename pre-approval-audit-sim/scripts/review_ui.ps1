# Launch the Streamlit reviewer dashboard (Windows / PowerShell).
# Run from the repo root:  ./scripts/review_ui.ps1
# Assumes a batch has been run (scripts/run_batch.py) so the queue is populated.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
python -m streamlit run review_ui/app.py
