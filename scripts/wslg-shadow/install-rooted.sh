#!/bin/sh
# OPTIONAL SEC-2 hardener: install the WSLg-shadow boot chain ROOT-OWNED.
#
# *** HUMAN step, run with sudo. Agents NEVER run this (AGENT_RULES §12). ***
# *** The unit stays DISABLED by default: re-enabling on this machine      ***
# *** requires a FRESH human approval (coordinator decision 2026-10-07 —   ***
# *** the live unit was disabled by the human and must stay that way).     ***
#   scripts/wslg-shadow/install-rooted.sh --dry-run   # preview (no sudo)
#   sudo scripts/wslg-shadow/install-rooted.sh        # install, DISABLED
#   sudo scripts/wslg-shadow/install-rooted.sh --enable    # + arm (approval!)
#   sudo scripts/wslg-shadow/install-rooted.sh --enable --now
#   sudo scripts/wslg-shadow/uninstall-rooted.sh      # rollback/retire
#
# What it does (idempotent — safe to re-run after any repo update):
#   1. payload -> /usr/local/lib/raphael (root:root, 0755/0644):
#        wslg-boot.sh (this unit's ExecStart), wslg-install.sh,
#        weston-wrapper
#   2. writes root-owned SHA256SUMS (pins for step-2/3 verification)
#   3. renders the unit from the repo template, substituting the pinned
#      sha of wslg-boot.sh, and installs it to /etc/systemd/system
#      (0644 root:root) — the unit verifies that pin BEFORE exec
#   4. FAILS LOUD if the rendered unit would execute anything outside the
#      root-owned /usr/local/lib/raphael tree (no /home, no /mnt) — the
#      SEC-2 class of bug cannot be re-introduced by a bad render
#   5. systemd-analyze verify (best effort) + daemon-reload; enable ONLY
#      with --enable/--now (fresh human approval), --now also runs it once
#
# ARCH-1 retirement trigger: when the orb goes Windows-native, run
# uninstall-rooted.sh and delete scripts/wslg-shadow/ (see README).
set -eu

SRC="$(cd "$(dirname "$0")" && pwd)"
LIB=/usr/local/lib/raphael
UNIT_DST=/etc/systemd/system/raphael-wslg-shadow.service
UNIT_SRC="$SRC/raphael-wslg-shadow.service"

DO_NOW=0
DO_ENABLE=0
DRY=0
for arg in "$@"; do
    case "$arg" in
        --now)     DO_NOW=1; DO_ENABLE=1 ;;
        --enable)  DO_ENABLE=1 ;;
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
    say "  FAIL-LOUD path audit on the rendered unit (must be $LIB only)"
    say "  systemd-analyze verify; systemctl daemon-reload"
    say "  enable: NO (default — needs --enable + fresh human approval)"
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
# FAIL LOUD (SEC-2): the rendered unit may only ever exec root-owned tree
if grep -E '^(ExecStart|ExecStartPre)=' "$STAGE" | grep -vq "$LIB/"; then
    die "rendered unit references a path outside $LIB — REFUSING to install"
fi
if grep -E '^(ExecStart|ExecStartPre)=' "$STAGE" | grep -qE '/home/|/mnt/'; then
    die "rendered unit would exec user-writable content — REFUSING (SEC-2)"
fi
install -o root -g root -m 0644 "$STAGE" "$UNIT_DST"
say "unit installed: $UNIT_DST (pins $BOOT_SHA, path-audit PASSED)"

if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$UNIT_DST" >/dev/null 2>&1 \
        || say "WARN: systemd-analyze verify reported issues (see: systemd-analyze verify $UNIT_DST)"
fi
systemctl daemon-reload
if [ "$DO_ENABLE" -eq 1 ]; then
    systemctl enable raphael-wslg-shadow
    say "ENABLED (fresh human approval assumed)"
    if [ "$DO_NOW" -eq 1 ]; then
        systemctl restart raphael-wslg-shadow
        say "ran now — check: systemctl status raphael-wslg-shadow / /tmp/raphael-wslg-shadow.log"
    fi
else
    if systemctl is-enabled raphael-wslg-shadow >/dev/null 2>&1; then
        systemctl disable raphael-wslg-shadow
        say "unit left DISABLED (policy: re-enable needs fresh human approval)"
    else
        say "unit left DISABLED (default — use --enable only with approval)"
    fi
fi
say "leftovers to clean up yourself (old chain): rm -f ~/scripts/raphael-wslg-shadow.sh"
say "rollback: sudo scripts/wslg-shadow/uninstall-rooted.sh"
