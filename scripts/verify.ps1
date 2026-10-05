<#
.SYNOPSIS
  Raphael — read-only environment verification (supervisor side).

.DESCRIPTION
  Checks python, supervisor entry point, config, wsl.exe, the Task Scheduler
  task, the Startup-folder fallback and the token FILE PATH (never reads or
  prints the token value). Touches nothing — safe to run any time.

  Exit codes: 0 = all PASS/WARN, 1 = at least one FAIL.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\verify.ps1
#>
param(
    [string]$TaskName = "Raphael"
)

$ErrorActionPreference = "Continue"
function Row([string]$status, [string]$name, [string]$detail) {
    Write-Host ("  [{0,-4}] {1,-22} {2}" -f $status, $name, $detail)
}

$fail = 0; $warn = 0; $pass = 0
function Bump([string]$status) {
    if ($status -eq "FAIL") { $script:fail++ }
    elseif ($status -eq "WARN") { $script:warn++ }
    else { $script:pass++ }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Write-Host "Raphael supervisor verify — repo=$repoRoot"

# python
$py = Get-Command python.exe -ErrorAction SilentlyContinue
if ($py) {
    $ver = & $py.Source --version 2>&1 | Out-String
    Row "PASS" "python.exe" "$($py.Source) ($($ver.Trim()))"
    Bump "PASS"
} else {
    Row "FAIL" "python.exe" "not on PATH — install Python 3.10+ (BLOCKED: nothing auto-installed)"
    Bump "FAIL"
}

# entry point
$entry = Join-Path $repoRoot "supervisor\main.py"
if (Test-Path $entry) {
    Row "PASS" "supervisor entry" $entry; Bump "PASS"
} else {
    Row "FAIL" "supervisor entry" "missing: $entry"; Bump "FAIL"
}

# config
$cfg = Join-Path $repoRoot "config.yaml"
if (Test-Path $cfg) {
    Row "PASS" "config.yaml" $cfg; Bump "PASS"
} else {
    Row "WARN" "config.yaml" "absent — supervisor falls back to built-in defaults"; Bump "WARN"
}

# scripts present
$scripts = @("setup.ps1", "setup-startup.ps1", "uninstall.ps1", "setup.sh", "token-gen.sh") |
    ForEach-Object { Join-Path (Join-Path $repoRoot "scripts") $_ }
$missing = $scripts | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Row "FAIL" "scripts" "missing: $($missing -join ', ')"; Bump "FAIL"
} else {
    Row "PASS" "scripts" "setup/setup-startup/uninstall/verify (ps1) + setup/token-gen (sh)"; Bump "PASS"
}

# wsl.exe
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($wsl) {
    Row "PASS" "wsl.exe" $wsl.Source; Bump "PASS"
} else {
    Row "FAIL" "wsl.exe" "not on PATH — WSL bring-up cannot run"; Bump "FAIL"
}

# scheduled task
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Row "PASS" "task '$TaskName'" "State=$($task.State) Trigger=$($task.Triggers[0].CimClass.CimClassName)"
    Bump "PASS"
} else {
    Row "WARN" "task '$TaskName'" "not registered yet — run scripts\setup.ps1 (orchestrator/user registers)"; Bump "WARN"
}

# startup fallback
$startupDir = [Environment]::GetFolderPath("Startup")
$hasLnk = Test-Path (Join-Path $startupDir "Raphael Supervisor.lnk")
$hasCmd = Test-Path (Join-Path $startupDir "Raphael Supervisor.cmd")
if ($hasLnk -or $hasCmd) {
    Row "PASS" "startup entry" "$startupDir (lnk=$hasLnk cmd=$hasCmd)"; Bump "PASS"
} else {
    Row "WARN" "startup entry" "absent (optional fallback — scripts\setup-startup.ps1)"; Bump "WARN"
}

# token FILE PATH only — content is never read or printed
if ($env:APPDATA) {
    $tok = Join-Path (Join-Path $env:APPDATA "Raphael") "token"
    if (Test-Path $tok) {
        Row "PASS" "token file (path)" "$tok exists (value not read)"; Bump "PASS"
    } else {
        Row "WARN" "token file (path)" "$tok missing — run scripts/token-gen.sh in WSL"; Bump "WARN"
    }
} else {
    Row "WARN" "token file (path)" "%APPDATA% unset"; Bump "WARN"
}

Write-Host "VERIFY RESULT: PASS=$pass WARN=$warn FAIL=$fail"
if ($fail -gt 0) { exit 1 }
exit 0
