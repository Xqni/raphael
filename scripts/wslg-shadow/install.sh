#!/bin/sh
# Installs the weston wrapper (idempotent) with BACKUP-FIRST, then restarts
# weston so WSLGd respawns it through the wrapper. Runs as root inside the
# WSLg system distro (wsl.exe --system -u root). State survives until
# wsl --shutdown (system distro overlay resets); the user-distro boot service
# raphael-wslg-shadow re-runs this on every WSL boot.
set -e
BACKUP_DIR="$1"
REAL=/usr/bin/weston
WRAPPED=/usr/bin/weston.bin
WRAPPER_SRC=/mnt/wslg/raphael-shadow-fix/weston-wrapper

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
  cp "$WRAPPER_SRC" "$REAL"
  chmod 755 "$REAL"
  echo "INSTALLED"
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
grep "enable_window_shadow_remoting" /mnt/wslg/weston.log | tail -2
