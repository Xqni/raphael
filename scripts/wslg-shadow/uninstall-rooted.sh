#!/bin/sh
# ROLLBACK for the SEC-2 WSLg-shadow hardening.
#
# *** HUMAN step, run with sudo. Agents NEVER run this. ***
#   sudo scripts/wslg-shadow/uninstall-rooted.sh           # full rollback
#        scripts/wslg-shadow/uninstall-rooted.sh --dry-run # preview
#
# Removes (idempotent — missing files are fine):
#   - /etc/systemd/system/raphael-wslg-shadow.service (disable + delete)
#   - /usr/local/lib/raphael/ (root-owned payload + pins)
# It does NOT touch the weston wrapper already installed in the WSLg
# system distro, nor the backup on /mnt/wslg. To restore STOCK weston
# (human, needs the backup made backup-first):
#   wsl.exe --system -u root sh -c 'cp -a /mnt/wslg/raphael-shadow-fix/weston.bin.orig /usr/bin/weston && rm -f /usr/bin/weston.bin'
# (system distro resets on `wsl --shutdown` anyway — the wrapper does not
# survive that; this command fixes a mid-cycle state.)
# Re-install: sudo scripts/wslg-shadow/install-rooted.sh
set -eu

LIB=/usr/local/lib/raphael
UNIT=/etc/systemd/system/raphael-wslg-shadow.service

DRY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $arg (see --help)" >&2; exit 2 ;;
    esac
done

say() { printf '[uninstall-rooted] %s\n' "$*"; }

if [ "$DRY" -eq 1 ]; then
    say "DRY RUN (no changes):"
    say "  systemctl disable --now raphael-wslg-shadow (if present)"
    say "  rm -f $UNIT && systemctl daemon-reload"
    say "  rm -rf $LIB"
    say "rollback of the weston wrapper (only if you want stock weston):"
    say "  wsl.exe --system -u root sh -c 'cp -a /mnt/wslg/raphael-shadow-fix/weston.bin.orig /usr/bin/weston && rm -f /usr/bin/weston.bin'"
    exit 0
fi

[ "$(id -u)" -eq 0 ] || { echo "[uninstall-rooted] needs root — re-run: sudo $0 $*" >&2; exit 1; }

if [ -f "$UNIT" ]; then
    systemctl disable --now raphael-wslg-shadow 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    say "unit removed: $UNIT"
else
    say "unit absent (already rolled back)"
fi
if [ -d "$LIB" ]; then
    rm -rf "$LIB"
    say "payload removed: $LIB"
else
    say "payload absent (already rolled back)"
fi
say "weston wrapper state untouched — see --help for the stock-weston restore command"
say "re-install: sudo scripts/wslg-shadow/install-rooted.sh"
