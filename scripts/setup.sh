#!/usr/bin/env bash
# Raphael — WSL-side setup (idempotent, safe to re-run).
#
# What this script EXECUTES: only the token generation (scripts/token-gen.sh).
# What it PRINTS: venv build steps + the raphael-brain.service unit file and
# its install instructions. It NEVER runs sudo, apt, pip, and NEVER writes
# /etc/systemd — system-level changes are blocked by policy (BLOCKED-by-design)
# and are performed manually by the orchestrator/user after approval.
set -euo pipefail

DRY=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run|--dryrun) DRY=1 ;;
        --force)            FORCE=1 ;;
        -h|--help)
            cat <<'EOF'
Usage: setup.sh [--dry-run] [--force]

  --dry-run  print every action (including token steps) without writing
  --force    pass through to token-gen.sh (regenerate token)
  -h, --help this help

Windows side (run by the orchestrator/user, NOT by this script):
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1 -DryRun
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
EOF
            exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
say() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

say "Raphael WSL setup — repo=$REPO_ROOT user=$(whoami) dry_run=$DRY"

# ----------------------------------------------------------- environment ---
say "environment:"
if command -v python3 >/dev/null 2>&1; then
    say "  python3: $(python3 --version 2>&1)"
else
    say "  BLOCKED: python3 missing — install it yourself (this script never installs packages)"
    exit 3
fi
if command -v cmd.exe >/dev/null 2>&1; then
    say "  windows interop: cmd.exe available ($(cmd.exe /c 'echo %OS%' 2>/dev/null | tr -d '\r\n'))"
else
    say "  windows interop: cmd.exe NOT available — Windows token copy will be skipped"
fi

# ------------------------------------------------------ STEP 1: venv (print) -
say "STEP 1 — brain Python venv (PRINT ONLY, nothing executed):"
say "  python3 -m venv $REPO_ROOT/brain/.venv"
say "  $REPO_ROOT/brain/.venv/bin/pip install -r $REPO_ROOT/brain/requirements.txt"
if [ -d "$REPO_ROOT/brain/.venv" ]; then
    say "  (venv already exists — re-run would skip this step: idempotent)"
fi
say "  [BLOCKED] pip installs are NOT executed here — brain-dev/orchestrator installs dependencies after approval."

# --------------------------------------------- STEP 2: systemd unit (print) -
say "STEP 2 — raphael-brain systemd unit (PRINT ONLY — /etc/systemd is never written by automation):"
cat <<UNIT
# ---------------------------------------------------------------
# /etc/systemd/system/raphael-brain.service   (save manually as root)
[Unit]
Description=Raphael Brain (FastAPI, localhost:8765)
After=network-online.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$REPO_ROOT/brain
ExecStart=$REPO_ROOT/brain/.venv/bin/python $REPO_ROOT/brain/app.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
# ---------------------------------------------------------------
UNIT
say "install instructions (run MANUALLY as root — not executed by this script):"
say "  sudo tee /etc/systemd/system/raphael-brain.service   # paste the block above, Ctrl-D"
say "  sudo systemctl daemon-reload"
say "  sudo systemctl enable --now raphael-brain"
say "  systemctl is-active raphael-brain          # expected: active"
say "  note: adjust ExecStart if brain-dev's entry point differs (app.py vs 'uvicorn app:app')."
say "  note: the supervisor probes 'systemctl is-active raphael-brain' — restarts may need NOPASSWD sudo for user '$(whoami)' (config.yaml: paths.wsl_sudo / supervisor.wsl_sudo)."

# ------------------------------------------------------ STEP 3: token (runs) -
say "STEP 3 — token generation (writes ~/.raphael/token 0600 + %APPDATA%\\Raphael\\token):"
if [ "$DRY" -eq 1 ]; then
    bash "$SCRIPT_DIR/token-gen.sh" --dry-run
else
    if [ "$FORCE" -eq 1 ]; then
        bash "$SCRIPT_DIR/token-gen.sh" --force
    else
        bash "$SCRIPT_DIR/token-gen.sh"
    fi
fi

# ------------------------------------------------------------- summary ------
say "SUMMARY — done (re-runnable). Next steps are run by the orchestrator/user:"
say "  1. Windows task registration : powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1 -DryRun   (then without -DryRun)"
say "  2. Windows startup fallback  : powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup-startup.ps1"
say "  3. verify                    : powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\verify.ps1"
say "  4. supervisor self-check     : python3 supervisor/main.py --selfcheck"
say "policy: no sudo / apt / pip / systemctl changes are ever executed by this script (BLOCKED by design)."
exit 0
