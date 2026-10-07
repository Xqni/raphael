# Builds the Body's PINNED Python venv (Wave 2 task: system Python 3.10 is
# EOL around 2026-10 — the Body must not run on it).
#
# *** USER-run on Windows. No admin needed (per-user Python + per-user    ***
# *** venv). Agents do not run installers that download software — this   ***
# *** script exists for the user / integrator to execute.                 ***
#
# What it does:
#   1. Picks the newest installed interpreter >= 3.12 (py -3.13, py -3.12).
#      None found -> prints the exact install commands and exits 1
#      (it never downloads Python by itself).
#   2. Creates/reuses %LOCALAPPDATA%\Raphael\body-venv with that interpreter.
#   3. pip installs scripts/body-requirements.txt (fully pinned).
#   4. Verifies every Body dependency imports, and prints the interpreter.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\install-body-venv.ps1
#   ... -VenvPath D:\somewhere\body-venv        (custom location)
#   ... -Force                                  (recreate existing venv)
#
# Supervisor integration: paths.body_cmd `python ...` is transparently
# remapped to this venv's python.exe when it exists (supervisor
# body_script), config paths.body_venv overrides the location. Until it
# exists the Body keeps running on the system interpreter and the
# supervisor selfcheck warns (`body venv` row).
param(
    [string]$VenvPath = (Join-Path $env:LOCALAPPDATA 'Raphael\body-venv'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReqFile = Join-Path $Here 'body-requirements.txt'

function Say([string]$m) { Write-Host "[install-body-venv] $m" }

# ---- 1. interpreter >= 3.12 -----------------------------------------------
$PyExe = $null
foreach ($ver in @('3.13', '3.12')) {
    try {
        $candidate = (& py "-$ver" -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $candidate) {
            $PyExe = $candidate.Trim()
            Say "interpreter: py -$ver -> $PyExe"
            break
        }
    } catch { /* try next */ }
}
if (-not $PyExe) {
    Say "NO Python >= 3.12 found (py -3.13 / py -3.12 both failed)."
    Say "Install one yourself (pick ONE), then re-run this script:"
    Say "  winget install --id Python.Python.3.13   (per-user default)"
    Say "  or https://www.python.org/downloads/ (run installer: 'Add python.exe"
    Say "       to PATH' OFF, 'Install for all users' OFF -> no admin needed)"
    exit 1
}

# ---- 2. venv ---------------------------------------------------------------
$PyInVenv = Join-Path $VenvPath 'Scripts\python.exe'
if ((Test-Path $PyInVenv) -and $Force) {
    Say "-Force: removing existing venv at $VenvPath"
    Remove-Item -Recurse -Force $VenvPath
}
if (-not (Test-Path $PyInVenv)) {
    Say "creating venv: $VenvPath"
    & $PyExe -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { Say "ERROR: venv creation failed"; exit 1 }
} else {
    Say "reusing existing venv: $VenvPath"
    # If the venv was built on an EOL interpreter, refuse to layer onto it.
    $VenvVer = & $PyInVenv -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($VenvVer -and [version]$VenvVer -lt [version]'3.12') {
        Say "ERROR: existing venv is Python $VenvVer (< 3.12) — re-run with -Force"
        exit 1
    }
}

# ---- 3. pinned install -----------------------------------------------------
if (-not (Test-Path $ReqFile)) { Say "ERROR: missing $ReqFile"; exit 1 }
Say "installing pinned requirements (scripts/body-requirements.txt)"
& $PyInVenv -m pip install --disable-pip-version-check --no-cache-dir -r $ReqFile
if ($LASTEXITCODE -ne 0) { Say "ERROR: pip install failed"; exit 1 }

# ---- 4. verification -------------------------------------------------------
$verify = @'
import sys, pywinauto, comtypes, keyboard, mss, PIL, numpy, sounddevice, win32clipboard
print("imports OK on Python %s.%s.%s" % sys.version_info[:3])
'@
& $PyInVenv -c $verify
if ($LASTEXITCODE -ne 0) { Say "ERROR: dependency import verification failed"; exit 1 }

Say "DONE."
Say "  venv       : $VenvPath"
Say "  interpreter: $(& $PyInVenv -c 'import sys; print(sys.version.split()[0])')"
Say "  supervisor : body_cmd 'python ...' now resolves to this venv"
Say "               (override location: config.yaml paths.body_venv)"
