#!/bin/sh
# OPTIONAL SEC-2 hardener: install the WSLg-shadow boot chain ROOT-OWNED.
#
# *** HUMAN step, run with sudo. Agents NEVER run this (AGENT_RULES §12). ***
#   sudo scripts/wslg-shadow/install-rooted.sh            # install/refresh
#   sudo scripts/wslg-shadow/install-rooted.sh --now      # + run once now
#        scripts/wslg-shadow/install-rooted.sh --dry-run  # preview (no sudo)
#   sudo scripts/wslg-shadow/uninstall-rooted.sh          # rollback
#
# What it does (idempotent — safe to re-run after any repo update):
#   1. payload -> /usr/local/lib/raphael (root:root, 0755/0644):
#        wslg-boot.sh (this unit's ExecStart), wslg-install.sh,
#        weston-wrapper
#   2. writes root-owned SHA256SUMS (pins for step-2/3 verification)
#   3. renders the unit from the repo template, substituting the pinned
#      sha of wslg-boot.sh, and installs it to /etc/systemd/system
#      (0644 root:root) — the unit verifies that pin BEFORE exec
#   4. systemd-analyze verify (best effort) + daemon-reload + enable
#      (enable only; --now also runs it once NOW — weston restarts, GUI blinks)
#
# Replaces the pre-SEC-2 unit whose ExecStart pointed at the USER-writable
# /home/dami/scripts/raphael-wslg-shadow.sh (confirmed live 2026-10-07).
# After installing, the old file is orphaned — remove it yourself:
#   rm -f ~/scripts/raphael-wslg-shadow.sh
set -eu

SRC="$(cd "$(dirname "$0")" && pwd)"
LIB=/usr/local/lib/raphael
UNIT_DST=/etc/systemd/system/raphael-wslg-shadow.service
UNIT_SRC="$SRC/raphael-wslg-shadow.service"

DO_NOW=0
DRY=0
for arg in "$@"; do
    case "$arg" in
        --now)     DO_NOW=1 ;;
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $arg (see --help)" >&2; exit 2 ;;
    esac
done

say() { printf '[install-rooted] %s\n' "$*"; }
die() { printf '[install-rooted] ERROR: %s\n' "$*" >&2; exit 1; }

for f in boot-hook.sh install.sh weston-wrapper raphael-wslg-shadow.service; do
    [ -f "$SRC/$f" ] || die "missing source: $SRC/$f"
done

if [ "$DRY" -eq 1 ]; then
    say "DRY RUN (no changes):"
    say "  install -d -o root -g root -m 0755 $LIB"
    say "  install boot-hook.sh   -> $LIB/wslg-boot.sh   (0755 root:root)"
    say "  install install.sh     -> $LIB/wslg-install.sh (0644 root:root)"
    say "  install weston-wrapper -> $LIB/weston-wrapper  (0644 root:root)"
    say "  sha256sum pins -> $LIB/SHA256SUMS (root:root 0644)"
    say "  render $UNIT_SRC -> $UNIT_DST (substitute @BOOT_SHA@ @LIB@)"
    say "  systemd-analyze verify; systemctl daemon-reload; enable"
    say "sha of wslg-boot.sh would be: $(sha256sum "$SRC/boot-hook.sh" | cut -d' ' -f1)"
    exit 0
fi

[ "$(id -u)" -eq 0 ] || die "needs root — re-run: sudo $0 $*"

install -d -o root -g root -m 0755 "$LIB"
install -o root -g root -m 0755 "$SRC/boot-hook.sh"   "$LIB/wslg-boot.sh"
install -o root -g root -m 0644 "$SRC/install.sh"     "$LIB/wslg-install.sh"
install -o root -g root -m 0644 "$SRC/weston-wrapper" "$LIB/weston-wrapper"
( cd "$LIB" && sha256sum wslg-install.sh weston-wrapper > SHA256SUMS \
  && chown root:root SHA256SUMS && chmod 0644 SHA256SUMS )
say "payload installed root-owned under $LIB (SHA256SUMS pinned)"

BOOT_SHA="$(sha256sum "$LIB/wslg-boot.sh" | cut -d' ' -f1)"
STAGE="$(mktemp)"
trap 'rm -f "$STAGE"' EXIT
sed -e "s|@BOOT_SHA@|$BOOT_SHA|g" -e "s|@LIB@|$LIB|g" "$UNIT_SRC" > "$STAGE"
grep -q "exec $LIB/wslg-boot.sh" "$STAGE" || die "unit render failed"
install -o root -g root -m 0644 "$STAGE" "$UNIT_DST"
say "unit installed: $UNIT_DST (pins $BOOT_SHA)"

if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$UNIT_DST" >/dev/null 2>&1 \
        || say "WARN: systemd-analyze verify reported issues (see: systemd-analyze verify $UNIT_DST)"
fi
systemctl daemon-reload
if systemctl is-enabled raphael-wslg-shadow >/dev/null 2>&1; then
    say "already enabled (idempotent)"
else
    systemctl enable raphael-wslg-shadow
    say "enabled (runs at boot)"
fi
if [ "$DO_NOW" -eq 1 ]; then
    systemctl restart raphael-wslg-shadow
    say "ran now — check: systemctl status raphael-wslg-shadow / /tmp/raphael-wslg-shadow.log"
else
    say "next WSL boot uses the hardened chain (use --now to run immediately)"
fi
say "leftovers to clean up yourself (old chain): rm -f ~/scripts/raphael-wslg-shadow.sh"
say "rollback: sudo scripts/wslg-shadow/uninstall-rooted.sh"
