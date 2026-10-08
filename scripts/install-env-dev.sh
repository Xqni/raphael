#!/bin/sh
# SEC-5: create/refresh the per-worktree `.env.dev` (dev lanes read this;
# the real `.env` stays for the live-stack process only).
#
#   scripts/install-env-dev.sh            # write .env.dev (mode 600)
#   scripts/install-env-dev.sh --target DIR   # tests / other trees
#
# Idempotent: refuses to clobber a hand-edited .env.dev unless --force.
# NEVER copies the real .env (no secret ever enters .env.dev).
# Coordinate: .gitignore must contain `.env.dev` (request
# infra__to__integrator__sec5-env-dev-and-docs.md) — we LOUD-WARN if not.
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR=""
FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --target) shift; TARGET_DIR="${1:-}" ;;
        --force)  FORCE=1 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done
TARGET_DIR="${TARGET_DIR:-$(cd "$SRC/.." && pwd)}"
OUT="$TARGET_DIR/.env.dev"
TPL="$SRC/env.dev.template"

[ -f "$TPL" ] || { echo "[env-dev] missing template: $TPL" >&2; exit 1; }

if [ -f "$OUT" ] && [ "$FORCE" -eq 0 ]; then
    if cmp -s "$TPL" "$OUT"; then
        echo "[env-dev] $OUT already up to date"
    else
        echo "[env-dev] $OUT exists and differs (hand-edited?) — kept; use --force to reset"
    fi
else
    cp "$TPL" "$OUT"
    chmod 600 "$OUT"
    echo "[env-dev] wrote $OUT (mode 600)"
fi

# never gitignored? -> loud warning (needs the integrator .gitignore line)
if git -C "$TARGET_DIR" check-ignore -q "$OUT" 2>/dev/null; then
    echo "[env-dev] PASS .env.dev is gitignored"
else
    echo "[env-dev] WARN .env.dev is NOT gitignored yet — request pending:" 
    echo "           docs/requests/infra__to__integrator__sec5-env-dev-and-docs.md"
fi

# guard: refuse if someone copied real-looking values in
if grep -E '^[A-Z0-9_]+=.+' "$OUT" \
        | grep -vE '^(RAPHAEL_LOG_LEVEL|RAPHAEL_INSTANCE)=' \
        | grep -q .; then
    echo "[env-dev] FAIL non-empty value(s) detected in $OUT — dev env must stay valueless:" >&2
    grep -nE '^[A-Z0-9_]+=.+' "$OUT" | sed 's/=.*$/=<redacted>/' >&2 || true
    exit 1
fi
echo "[env-dev] value-blind check PASS (no non-empty keys)"
