<#
.SYNOPSIS
  Raphael — Task Scheduler registration (logon task "Raphael").

.DESCRIPTION
  Idempotent (safe to re-run = repair): detects an existing "Raphael" task,
  removes and re-registers it with the exact required settings.

  WRITES THE schtasks / Register-ScheduledTask COMMANDS BUT ACTS ONLY WHEN
  RUN WITHOUT -DryRun. The build agents themselves never execute schtasks —
  registration is performed by the orchestrator/user running this script.

  Battery note (researched against learn.microsoft.com Task Scheduler schema,
  2026-10-05): there is NO "DisallowBatteryStop" element in the documented
  settingsType schema. The equivalent "don't stop on battery" behaviour is
  DisallowStartIfOnBatteries=false + StopIfGoingOnBatteries=false, set here
  via -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries.

.PARAMETER DryRun
  Print the exact commands and planned settings, change nothing.
.PARAMETER WhatIf
  Synonym for -DryRun (Task-Scheduler-style dry run).

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1 -DryRun
.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
param(
    [switch]$DryRun,
    [switch]$WhatIf,
    [string]$TaskName = "Raphael",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$dry = $DryRun -or $WhatIf

function Say([string]$msg, [string]$level = "INFO") {
    Write-Host ("[{0}] {1} {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $level, $msg)
}
function Dry([string]$msg) {
    Write-Host ("[DRYRUN] " + $msg)
}

# --- resolve repo + entry point ------------------------------------------
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$supervisorPy = Join-Path $repoRoot "supervisor\main.py"
if (-not (Test-Path $supervisorPy)) {
    Say "BLOCKED: supervisor\main.py not found at $supervisorPy" "ERROR"
    exit 1
}

# --- locate python (never installs anything) -----------------------------
if (-not $PythonExe) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($found) { $PythonExe = $found.Source }
}
if (-not $PythonExe) {
    Say "BLOCKED: python.exe not on PATH (and -PythonExe not supplied). Install Python 3.10+ yourself or pass -PythonExe; nothing is auto-installed." "ERROR"
    exit 2
}
Say "python: $PythonExe"
Say "entry : $supervisorPy"

# Working directory: Task Scheduler refuses UNC working dirs; python resolves
# everything from __file__ anyway, so fall back to the profile dir on UNC.
$workDir = $repoRoot
if ($repoRoot.StartsWith("\\")) {
    Say "repo path is UNC ($repoRoot) — task WorkingDirectory will be $env:USERPROFILE (cmd.exe cannot use UNC cwd)" "WARN"
    $workDir = $env:USERPROFILE
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$actionLine = '"{0}" "{1}"' -f $PythonExe, $supervisorPy

# --- build task objects (validates the cmdlets in BOTH modes) ------------
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$supervisorPy`"" -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 10 `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

$batteryFlags = ($settings.CimInstanceProperties |
    Where-Object { $_.Name -in "DisallowStartIfOnBatteries", "StopIfGoingOnBatteries" } |
    ForEach-Object { "$($_.Name)=$($_.Value)" }) -join " "

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

# --- print the plan -------------------------------------------------------
$schtasksCmd = 'schtasks /Create /TN "{0}" /TR \"{1}\" /SC ONLOGON /RU "{2}" /RL LIMITED /F' -f `
    $TaskName, $actionLine, $user
Say "planned task: Name=$TaskName User=$user Trigger=AtLogOn LogonType=Interactive"
Say "settings    : $batteryFlags (battery-stop disabled) | RestartInterval=PT1M RestartCount=10 | StartWhenAvailable=True | MultipleInstances=IgnoreNew | ExecutionTimeLimit=PT0S (no 72h auto-kill)"
if ($existing) {
    Say "existing task: '$TaskName' State=$($existing.State) — will unregister + re-register (idempotent)" "WARN"
} else {
    Say "existing task: none — will register fresh"
}
Write-Host ""
Dry "schtasks equivalent (printed only; schtasks cannot express restart/battery/multi-instance settings):"
Dry "  $schtasksCmd"
Dry "command actually executed when run WITHOUT -DryRun:"
Dry "  Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false   # only if the task already exists"
Dry "  Register-ScheduledTask -TaskName `"$TaskName`" ``"
Dry "      -Action   (Execute=$PythonExe, Arguments=`"$supervisorPy`", WorkingDirectory=$workDir) ``"
Dry "      -Trigger  (AtLogOn -User `"$user`") ``"
Dry "      -Settings (AllowStartIfOnBatteries, DontStopIfGoingOnBatteries, StartWhenAvailable, ``"
Dry "                  RestartInterval=PT1M, RestartCount=10, MultipleInstances=IgnoreNew, ``"
Dry "                  ExecutionTimeLimit=PT0S) ``"
Dry "      -Principal (UserId=$user, LogonType=Interactive, RunLevel=Limited) -Force"
Dry "no changes made in dry-run mode."

if ($dry) { exit 0 }

# --- register (only when a human/orchestrator runs this) -----------------
if ($existing) {
    Say "removing existing task '$TaskName' for idempotent re-create"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Raphael supervisor — logon bring-up + health watchdog (supervisor/main.py)" `
    -Force | Out-Null

$verify = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Say "registered OK: TaskName=$($verify.TaskName) State=$($verify.State) " `
    "Trigger=$($verify.Triggers[0].CimClass.CimClassName) " `
    "NextRun=$($info.NextRunTime) LastResult=$($info.LastTaskResult)"
Say "run now (manual test):  schtasks /Run /TN `"$TaskName`"   # executed by the user, not by this build agent"
exit 0
