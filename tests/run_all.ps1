# tests/run_all.ps1 — Windows entry point (Body unit tests, no GUI).
#
#   .\tests\run_all.ps1
#
# Order: CONFORMANCE FIRST — the docs/PROTOCOL parsers are encoding-
# sensitive on Windows (cp1252 decode of UTF-8 markers; integrator glue
# d9915fc) and must fail fast before the body tests. CI mirrors this as the
# dedicated conformance matrix line (ubuntu + windows).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m pytest -q (Join-Path $PSScriptRoot "conformance")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest -q (Join-Path $PSScriptRoot "body_win")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "run_all.ps1: OK"
