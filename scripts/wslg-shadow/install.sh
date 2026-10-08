#!/bin/sh
# Installs the weston wrapper (idempotent) with BACKUP-FIRST + PIN-VERIFIED
# wrapper bytes, then restarts weston so WSLGd respawns it through the
# wrapper. Runs as root inside the WSLg SYSTEM distro (wsl.exe --system),
# receiving this script itself over a tar pipe from the root-owned
# /usr/local/lib/raphael staging area (SEC-2: root never reads a
# user-writable filesystem as code).
#
# Usage: wslg-install.sh BACKUP_DIR WRAPPER_PATH WRAPPER_SHA256
#   WRAPPER_PATH must be the staged root-owned copy
#   (/usr/local/lib/raphael/weston-wrapper); WRAPPER_SHA256 is the pin from
#   the root-owned SHA256SUMS. Both are REQUIRED — the legacy implicit
#   /mnt/wslg source was the SEC-2 hole and is gone.
#
# State survives until `wsl --shutdown` (system distro overlay resets);
# the user-distro boot service re-runs this on every WSL boot.
# Backup-first: the original weston binary is copied to the persistent
# shared mount BEFORE any modification (data only, never executed).
set -e
BACKUP_DIR="$1"
WRAPPER_PATH="${2:-}"
WRAPPER_SHA="${3:-}"
REAL=/usr/bin/weston
WRAPPED=/usr/bin/weston.bin

if [ -z "$BACKUP_DIR" ] || [ -z "$WRAPPER_PATH" ] || [ -z "$WRAPPER_SHA" ]; then
  echo "ERROR: usage: $0 BACKUP_DIR WRAPPER_PATH WRAPPER_SHA256 (SEC-2: no implicit sources)"
  exit 2
fi
if [ ! -f "$WRAPPER_PATH" ]; then
  echo "ERROR: wrapper source missing: $WRAPPER_PATH"
  exit 2
fi
# SEC-2: verify the pin BEFORE this root process copies anything over the
# compositor binary. Mismatch = refuse, loudly.
echo "$WRAPPER_SHA  $WRAPPER_PATH" | sha256sum -c - >/dev/null || {
  echo "ERROR: weston-wrapper sha256 MISMATCH — refusing to install (SEC-2)"
  exit 3
}

if [ -f "$WRAPPED" ]; then
  echo "ALREADY_INSTALLED (wrapper active, real binary at $WRAPPED)"
else
  if [ -z "$BACKUP_DIR" ]; then echo "ERROR: backup dir arg required (backup-first rule)"; exit 2; fi
  mkdir -p "$BACKUP_DIR"
  echo "Backing up $REAL -> $BACKUP_DIR/weston.bin.orig"
  cp -a "$REAL" "$BACKUP_DIR/weston.bin.orig"
  echo "  $(ls -la "$BACKUP_DIR/weston.bin.orig")" >> "$BACKUP_DIR/MANIFEST.md"
  echo "- moved /usr/bin/weston -> /usr/bin/weston.bin; installed wrapper (kills enable_window_shadow_remoting)" >> "$BACKUP_DIR/MANIFEST.md"
  mv "$REAL" "$WRAPPED"
  cp "$WRAPPER_PATH" "$REAL"
  chmod 755 "$REAL"
  echo "INSTALLED (pin verified: $WRAPPER_SHA)"
fi

# Restart weston: WSLGd supervises it and auto-restarts through the wrapper.
PID=$(pidof weston weston.bin 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "Restarting weston (pid $PID) — brief GUI blink expected"
  kill "$PID"
  sleep 3
fi
for i in 1 2 3 4 5 6; do
  if pidof weston weston.bin >/dev/null 2>&1; then break; fi
  sleep 1
done
echo "--- weston.log shadow flag after respawn ---"
grep "enable_window_shadow_remoting" /mnt/wslg/weston.log | tail -2 || true
