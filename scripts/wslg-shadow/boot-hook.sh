#!/bin/bash
# Raphael WSLg shadow boot payload (SEC-2) — installed ROOT-OWNED at
# /usr/local/lib/raphael/wslg-boot.sh by install-rooted.sh. This repo copy
# is the SOURCE; never install it to a user-writable path.
#
# Why the rewrite (SEC-2, confirmed 2026-10-07): the previous chain was
#   unit(/etc, root) -> /home/<wsl-user>/scripts/... (USER-writable) ->
#   wsl --system -u root sh -c 'sh /mnt/wslg/.../install.sh' (user-writable)
#   -> cp user bytes over /usr/bin/weston      = local privilege escalation.
#
# New trust chain (3 steps, every hop root-owned or verified):
#   1. the unit pins THIS file's sha256 before exec (root-owned unit);
#   2. THIS file runs `sha256sum -c SHA256SUMS` (root-owned pins) over
#      wslg-install.sh + weston-wrapper;
#   3. payloads reach the WSLg SYSTEM distro through a tar PIPE (stdin) —
#      root there never reads /mnt/wslg; it re-verifies the pins, and
#      wslg-install.sh verifies the wrapper pin again before any
#      /usr/bin/weston mutation.
# Backup DATA (weston.bin.orig) still lands on /mnt/wslg — data only,
# never executed.
#
# Install (human, sudo):   scripts/wslg-shadow/install-rooted.sh
# Rollback (human, sudo):  scripts/wslg-shadow/uninstall-rooted.sh
set -euo pipefail

LIB="${RAPHAEL_WSLG_LIB:-/usr/local/lib/raphael}"
WSL="${RAPHAEL_WSL:-/mnt/c/WINDOWS/system32/wsl.exe}"
BACKUP="${RAPHAEL_WSLG_BACKUP:-/mnt/wslg/raphael-shadow-fix}"
LOG=/tmp/raphael-wslg-shadow.log

cd "$LIB"
# step 2 — root-owned pins (installed only by install-rooted.sh, root:root)
sha256sum -c SHA256SUMS

mkdir -p "$BACKUP"   # backup destination (written, never read back as code)

# step 3 — verified transfer: tar over stdin; the system distro verifies
# the pins AGAIN before executing anything, then runs the staged installer
# with the backup dir as $1. `|| true` keeps boot semantics (log, don't
# block the boot unit) — failures are visible in $LOG.
tar -cf - SHA256SUMS wslg-install.sh weston-wrapper \
  | "$WSL" --system -u root sh -c '
      set -e
      D=/usr/local/lib/raphael
      mkdir -p "$D"
      tar -C "$D" -xf -
      cd "$D"
      sha256sum -c SHA256SUMS
      sh wslg-install.sh "$1" "$D/weston-wrapper"
    ' sh "$BACKUP" >>"$LOG" 2>&1 || {
      echo "raphael-wslg-shadow: boot install failed (see $LOG)" >&2
      exit 0   # boot unit stays green; details in the log
    }
