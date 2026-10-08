#!/bin/sh
# ARCH-7: restore a backup-raphael.sh archive (explicit member prefixes).
#
#   scripts/restore-raphael.sh --from <archive> [--root DIR] [--yes]
#
#   --root DIR  restore .raphael under DIR and config/config.* under
#               DIR (TEST mode: supervisor/tests/test_backup_restore.py
#               points this at a temp dir; default = $HOME + repo root)
#   --yes       no interactive confirm (required in test mode)
#
# SAFETY: the current ~/.raphael (if present) is copied aside to
# ~/.raphael.pre-restore.<ts> BEFORE anything is written — always undoable.
# Value-blind output: paths/counts only, never contents.
set -eu
FROM=""
HOME_DIR="${RAPHAEL_HOME:-$HOME}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TESTMODE=0
YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --from) shift; FROM="${1:-}" ;;
        --root) shift; HOME_DIR="${1:-}"; TESTMODE=1 ;;
        --yes)  YES=1 ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done
if [ "$TESTMODE" -eq 1 ]; then
    REPO="$HOME_DIR"   # tests: config restores INSIDE the temp root
fi
[ -n "$FROM" ] && [ -f "$FROM" ] || { echo "[restore] --from <archive> required" >&2; exit 2; }

say() { printf '[restore] %s\n' "$*"; }
tar -tzf "$FROM" >/dev/null || { echo "[restore] NOT a readable tar.gz: $FROM" >&2; exit 1; }

if [ "$YES" -ne 1 ]; then
    printf '[restore] restore %s -> data:%s config:%s. Continue? [y/N] ' \
        "$FROM" "$HOME_DIR" "$REPO"
    read -r ans || true
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { say "aborted"; exit 1; }
fi

# safety copy of current data (the undo button)
if [ -d "$HOME_DIR/.raphael" ]; then
    BAK="$HOME_DIR/.raphael.pre-restore.$(date +%Y%m%d-%H%M%S)"
    cp -a "$HOME_DIR/.raphael" "$BAK"
    say "current data copied aside -> $BAK"
fi

mkdir -p "$HOME_DIR" "$REPO"
if tar -tzf "$FROM" | grep -q '^\.raphael/'; then
    tar -xzf "$FROM" -C "$HOME_DIR" .raphael
    [ -f "$HOME_DIR/.raphael/token" ] && chmod 600 "$HOME_DIR/.raphael/token" || true
fi
if tar -tzf "$FROM" | grep -q '^config/'; then
    tar -xzf "$FROM" -C "$REPO" --strip-components=1 config
fi
N="$(tar -tzf "$FROM" | wc -l)"
say "restored $N entries from $FROM (data -> $HOME_DIR, config -> $REPO)"
say "undo: rm -rf '$HOME_DIR/.raphael' && mv '<pre-restore dir>' '$HOME_DIR/.raphael'"
