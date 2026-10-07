#!/usr/bin/env bash
# OPTIONAL installer for brain/raphael-brain.service (+ optional sudoers
# snippet). Documentation: scripts/README.md, scripts/NETWORK-SECURITY.md.
#
# *** USER-run only. Agents NEVER execute this — it needs sudo. ***
# *** (AGENT_RULES §12: no elevated commands by agents.)          ***
#
# Why OPTIONAL: the supervisor's default `brain_mode: auto` is root-less
# PROCESS mode (it spawns uvicorn itself and only talks systemctl when this
# unit is installed). Install the unit only when you want systemd to own the
# brain's restarts. Profile cloud_temp: the unit has NO Ollama dependency.
#
# Usage:
#   sudo scripts/install-brain-unit.sh            # stage + install + daemon-reload
#   sudo scripts/install-brain-unit.sh --enable   # also enable (start on WSL boot)
#   sudo scripts/install-brain-unit.sh --now      # also enable --now (start now)
#   sudo scripts/install-brain-unit.sh --sudoers  # also install the tightly
#                                                 # scoped NOPASSWD snippet
#                                                 # (paths.wsl_sudo: true only)
#
# Nothing here touches Task Scheduler, .wslconfig, or the disabled "Raphael"
# task. --enable/--now start the BRAIN UNIT inside WSL only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$ROOT/brain/raphael-brain.service"
UNIT_DST="/etc/systemd/system/raphael-brain.service"
SUDOERS_SRC="$ROOT/scripts/brain-sudoers.snippet"
SUDOERS_DST="/etc/sudoers.d/raphael-brain"

DO_ENABLE=0
DO_NOW=0
DO_SUDOERS=0

for arg in "$@"; do
    case "$arg" in
        --enable)  DO_ENABLE=1 ;;
        --now)     DO_NOW=1 ;;
        --sudoers) DO_SUDOERS=1 ;;
        -h|--help) tail -n +2 "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $arg (see --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '[install-brain-unit] %s\n' "$*"; }
die()  { printf '[install-brain-unit] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "run inside WSL (Linux only)"
[ -f "$UNIT_SRC" ] || die "unit source missing: $UNIT_SRC"
[ "$(id -u)" -eq 0 ] || die "needs root — re-run: sudo $0 $*"

USER_NAME="$(id -un)"
SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"
VENV_PY="$ROOT/brain/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    say "WARN: $VENV_PY not found — the unit will fail until brain/.venv exists"
fi

# ---- stage the unit with THIS machine's paths (template has hardcoded ones)
STAGE="$(mktemp)"
trap 'rm -f "$STAGE"' EXIT
sed -E \
    -e "s|^User=.*|User=${USER_NAME}|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=${ROOT}|" \
    -e "s|^Environment=PATH=.*|Environment=PATH=${ROOT}/brain/.venv/bin:/usr/local/bin:/usr/bin:/bin|" \
    -e "s|^ExecStart=.*|ExecStart=${VENV_PY} -m brain.run|" \
    "$UNIT_SRC" > "$STAGE"
grep -q "^ExecStart=${VENV_PY} -m brain.run$" "$STAGE" \
    || die "stage failed: ExecStart not substituted"
grep -q "^WorkingDirectory=${ROOT}$" "$STAGE" \
    || die "stage failed: WorkingDirectory not substituted"
say "staged unit: user=${USER_NAME} repo=${ROOT}"

# ---- install + reload (never enable/start unless asked) -------------------
install -m 644 "$STAGE" "$UNIT_DST"
"$SYSTEMCTL" daemon-reload
say "installed $UNIT_DST (NOT enabled, NOT started — brain still runs via"
say "supervisor process mode until you opt in)"

# ---- optional: scoped NOPASSWD snippet (paths.wsl_sudo: true only) --------
if [ "$DO_SUDOERS" -eq 1 ]; then
    [ -f "$SUDOERS_SRC" ] || die "snippet missing: $SUDOERS_SRC"
    command -v visudo >/dev/null || die "visudo not found"
    SNIPPET="$(mktemp)"
    sed -E \
        -e "s|^<USER> |${USER_NAME} ALL|" \
        -e "s|/usr/bin/systemctl|${SYSTEMCTL}|g" \
        "$SUDOERS_SRC" > "$SNIPPET"
    if visudo -cf "$SNIPPET" >/dev/null; then
        install -m 440 "$SNIPPET" "$SUDOERS_DST"
        say "installed $SUDOERS_DST (validated: restart/start/stop of"
        say "'raphael-brain' only — no general systemctl or shell grant)"
    else
        rm -f "$SNIPPET"
        die "visudo validation FAILED — sudoers NOT installed"
    fi
    rm -f "$SNIPPET"
fi

# ---- optional lifecycle ----------------------------------------------------
if [ "$DO_NOW" -eq 1 ]; then
    "$SYSTEMCTL" enable --now raphael-brain
    sleep 1
    "$SYSTEMCTL" --no-pager status raphael-brain || true
elif [ "$DO_ENABLE" -eq 1 ]; then
    "$SYSTEMCTL" enable raphael-brain
    say "enabled: the brain will start on the next WSL boot"
else
    say "next steps (your call):"
    say "  sudo systemctl enable --now raphael-brain   # boot + now"
    say "  sudo systemctl status raphael-brain"
    say "  scripts/brain-sudoers.snippet               # only if paths.wsl_sudo"
fi
say "supervisor picks the unit up automatically (brain_mode: auto checks"
say "LoadState on its next bring-up)."
