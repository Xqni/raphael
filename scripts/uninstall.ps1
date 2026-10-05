<#
.SYNOPSIS
  Raphael — uninstall: removes the Task Scheduler task, the Startup-folder
  entry, and stops Raphael processes (supervisor / body / orb / keepalive).

.DESCRIPTION
  Prints every action it takes ("REMOVED:", "STOPPED:", "NOT FOUND:").
  -DryRun / -WhatIf prints the exact commands and changes nothing.
  Only processes whose CommandLine matches Raphael-owned patterns are
  stopped — nothing else on the machine is touched.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -DryRun
#>
param(
    [switch]$DryRun,
    [switch]$WhatIf,
    [string]$TaskName = "Raphael",
    [switch]$KeepProcesses
)

$ErrorActionPreference = "Continue"
$dry = $DryRun -or $WhatIf

function Say([string]$msg, [string]$level = "INFO") {
    Write-Host ("[{0}] {1} {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $level, $msg)
}
function Dry([string]$msg) { Write-Host ("[DRYRUN] " + $msg) }

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startupDir = [Environment]::GetFolderPath("Startup")

Write-Host "=== Raphael uninstall plan ($([string]$(if ($dry) { 'DRY RUN' } else { 'LIVE' }))) ==="

# --- 1. scheduled task ----------------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($dry) {
        Dry "Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
        Say "WOULD REMOVE task '$TaskName' (State=$($task.State))"
    } else {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Say "REMOVED scheduled task '$TaskName'"
    }
} else {
    Say "NOT FOUND scheduled task '$TaskName' (already removed)"
}

# --- 2. startup entries ---------------------------------------------------
$entries = @()
foreach ($path in @((Join-Path $startupDir "Raphael Supervisor.lnk"),
                    (Join-Path $startupDir "Raphael Supervisor.cmd"))) {
    if (Test-Path $path) { $entries += $path }
}
if ($entries.Count -eq 0) {
    Say "NOT FOUND startup entry (checked Raphael Supervisor.lnk/.cmd in $startupDir)"
}
foreach ($entry in $entries) {
    if ($dry) {
        Dry "Remove-Item -LiteralPath `"$entry`" -Force"
        Say "WOULD REMOVE startup entry: $entry"
    } else {
        Remove-Item -LiteralPath $entry -Force
        Say "REMOVED startup entry: $entry"
    }
}

# --- 3. processes ---------------------------------------------------------
$patterns = @(
    'supervisor[\\/]main\.py',          # supervisor itself
    'body[\\/]win[\\/]main\.py',        # Windows Body
    'body[\\/]orb',                     # Electron orb (this repo's orb dir)
    'while :; do sleep 3600'            # supervisor's WSL keep-alive
)
if ($KeepProcesses) {
    Say "KeepProcesses set — skipping process termination"
} else {
    $targets = @()
    $all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine }
    foreach ($p in $all) {
        foreach ($pat in $patterns) {
            if ($p.CommandLine -match $pat) { $targets += $p; break }
        }
    }
    if ($targets.Count -eq 0) {
        Say "NOT FOUND any Raphael process (supervisor/body/orb/keepalive not running)"
    }
    foreach ($p in $targets) {
        $label = "$($p.Name) pid=$($p.ProcessId)"
        if ($dry) {
            Dry "Stop-Process -Id $($p.ProcessId) -Force   # $label"
            Say "WOULD STOP $label"
        } else {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                Say "STOPPED $label"
            } catch {
                Say "FAILED to stop $label : $($_.Exception.Message)" "ERROR"
            }
        }
    }
}

# --- 4. note --------------------------------------------------------------
Say "uninstall complete — repo files, config.yaml, logs/ and tokens are left in place."
Say "re-create the logon entry later with: scripts\setup.ps1  (task) or scripts\setup-startup.ps1 (Startup folder)"
Say "tokens removed only manually: %APPDATA%\Raphael\token and ~/.raphael/token"
exit 0
