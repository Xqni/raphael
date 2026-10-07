# tests/run_all.ps1 — Windows entry point (Body unit tests, no GUI).
#
#   .\tests\run_all.ps1
#
# Runs only the Windows-relevant subset: tests/body_win (lock + hotkey
# envelope unit tests — no real hotkeys registered, no microphone, no GUI)
# plus the dependency-light conformance checks. The full mock harness
# (contract/regression/security) runs on Ubuntu CI (tests/run_all).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m pytest -q (Join-Path $PSScriptRoot "body_win")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m pytest -q (Join-Path $PSScriptRoot "conformance")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "run_all.ps1: OK"
