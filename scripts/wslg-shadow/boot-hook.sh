#!/bin/bash
# Raphael: keep the weston shadow-kill wrapper installed across WSL restarts.
# The system distro overlay resets on every `wsl --shutdown` (WSLg README),
# discarding /usr/bin/weston's wrapper form — this boot service reinstalls it
# and restarts weston through WSLGd (idempotent; runs ~seconds after boot,
# before the user has windows open).
# Backup-first: the original weston binary is copied to the persistent shared
# mount (/mnt/wslg/raphael-shadow-fix/) BEFORE any modification.
set -e
WSL=/mnt/c/WINDOWS/system32/wsl.exe
BACKUP=/mnt/wslg/raphael-shadow-fix
"$WSL" --system -u root sh -c "sh $BACKUP/install.sh $BACKUP" \
  >> /tmp/raphael-wslg-shadow.log 2>&1 || true
