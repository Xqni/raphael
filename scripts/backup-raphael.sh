#!/bin/sh
# ARCH-7: backup ~/.raphael (token, memory DB, orb/profile state) + the
# config set into one timestamped tar.gz.
#
#   scripts/backup-raphael.sh                 # -> ~/raphael-backups/*.tar.gz
#   BACKUP_DIR=/tmp/x scripts/backup-raphael.sh   # tests / other destination
#   scripts/backup-raphael.sh --list
#
# Archive layout (explicit prefixes — restore knows where each goes):
#   .raphael/...            data dir contents
#   config/config.yaml      repo config
#   config/config.d/*.yaml  lane fragments
# Value-blind output: paths/counts only, NEVER file contents.
# Restore: scripts/restore-raphael.sh --from <archive>
set -eu
SRC_HOME="${RAPHAEL_HOME:-$HOME}"
DATA="$SRC_HOME/.raphael"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${BACKUP_DIR:-$HOME/raphael-backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [ "${1:-}" = "--list" ]; then
    [ -d "$DEST" ] || { echo "[backup] none yet ($DEST)"; exit 0; }
    ls -1 "$DEST"/raphael-*.tar.gz 2>/dev/null || echo "[backup] none yet ($DEST)"
    exit 0
fi

mkdir -p "$DEST"
OUT="$DEST/raphael-$STAMP.tar.gz"

# stage config under the config/ prefix
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/config/config.d"
[ -f "$ROOT/config.yaml" ] || { echo "[backup] missing $ROOT/config.yaml" >&2; exit 1; }
cp "$ROOT/config.yaml" "$STAGE/config/config.yaml"
for f in "$ROOT"/config.d/*.yaml; do
    [ -f "$f" ] && cp "$f" "$STAGE/config/config.d/"
done 2>/dev/null || true

if [ -d "$DATA" ]; then
    # exclude Electron caches (huge, regenerable) — keep state, drop junk
    tar -czf "$OUT" -C "$SRC_HOME" \
        --exclude='.raphael/*/Cache' \
        --exclude='.raphael/*/Code Cache' \
        --exclude='.raphael/*/GPUCache' \
        --exclude='.raphael/*/DawnCache' \
        .raphael -C "$STAGE" config
else
    tar -czf "$OUT" -C "$STAGE" config
fi
SIZE="$(du -h "$OUT" | cut -f1)"
NFILES="$(tar -tzf "$OUT" | wc -l)"
echo "[backup] OK $OUT ($SIZE, $NFILES entries)"
echo "[backup] data present: $([ -d "$DATA" ] && echo yes || echo 'no ~/.raphael — config only')"
echo "[backup] restore with: scripts/restore-raphael.sh --from $OUT"
