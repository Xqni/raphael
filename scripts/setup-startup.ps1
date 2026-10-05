<#
.SYNOPSIS
  Raphael -- Startup-folder fallback (used when Task Scheduler registration
  is unavailable). Drops a "Raphael Supervisor.lnk" into shell:startup.

.DESCRIPTION
  Idempotent: re-running overwrites the existing shortcut.
  -DryRun / -WhatIf prints what would be written and changes nothing.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup-startup.ps1 -DryRun
#>
param(
    [switch]$DryRun,
    [switch]$WhatIf,
    [string]$PythonExe = "",
    [string]$LnkName = "Raphael Supervisor"
)

$ErrorActionPreference = "Stop"
$dry = $DryRun -or $WhatIf

function Say([string]$msg, [string]$level = "INFO") {
    Write-Host ("[{0}] {1} {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $level, $msg)
}
function Dry([string]$msg) { Write-Host ("[DRYRUN] " + $msg) }

$repoRoot = Split-Path -Parent $PSScriptRoot
$supervisorPy = Join-Path $repoRoot "supervisor\main.py"
if (-not (Test-Path $supervisorPy)) {
    Say "BLOCKED: supervisor\main.py not found at $supervisorPy" "ERROR"
    exit 1
}
if (-not $PythonExe) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($found) { $PythonExe = $found.Source }
}
if (-not $PythonExe) {
    Say "BLOCKED: python.exe not on PATH and -PythonExe not given -- nothing auto-installed." "ERROR"
    exit 2
}

$startupDir = [Environment]::GetFolderPath("Startup")   # shell:startup
$lnkPath = Join-Path $startupDir "$LnkName.lnk"
$cmdPath = Join-Path $startupDir "$LnkName.cmd"
$workDir = $repoRoot
if ($repoRoot.StartsWith("\\")) { $workDir = $env:USERPROFILE }

Say "startup dir : $startupDir"
Say "shortcut    : $lnkPath"
Say "target      : $PythonExe `"$supervisorPy`""
Say "working dir : $workDir  (WindowStyle=7 minimized)"
if (Test-Path $lnkPath) { Say "existing entry found -- will overwrite (idempotent)" "WARN" }

if ($dry) {
    Dry "WScript.Shell.CreateShortcut(`"$lnkPath`")"
    Dry "  TargetPath      = $PythonExe"
    Dry "  Arguments       = `"$supervisorPy`""
    Dry "  WorkingDirectory= $workDir"
    Dry "  WindowStyle     = 7 (minimized)"
    Dry "  .Save()"
    Dry "fallback if COM unavailable -- write `"$cmdPath`" containing:"
    Dry '  @echo off'
    Dry "  start `"`" /min `"$PythonExe`" `"$supervisorPy`""
    Dry "no changes made in dry-run mode."
    exit 0
}

$madeLnk = $false
try {
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnkPath)
    $sc.TargetPath = $PythonExe
    $sc.Arguments = "`"$supervisorPy`""
    $sc.WorkingDirectory = $workDir
    $sc.WindowStyle = 7
    $sc.Description = "Raphael supervisor (logon fallback for Task Scheduler 'Raphael')"
    $sc.Save()
    $madeLnk = Test-Path $lnkPath
} catch {
    Say "shortcut creation failed ($($_.Exception.Message)) -- falling back to .cmd" "WARN"
}

if (-not $madeLnk) {
    $lines = @("@echo off", "start `"`" /min `"$PythonExe`" `"$supervisorPy`"")
    [System.IO.File]::WriteAllLines($cmdPath, $lines)
    Say "wrote fallback startup script: $cmdPath"
} else {
    Say "wrote startup shortcut: $lnkPath"
}
Say "startup entry active at next logon (Task Scheduler 'Raphael' remains the primary path)."
exit 0
