#!/bin/sh
# SEC-1: install/uninstall the advisory pre-commit hook that runs the
# personal-data scanner (staged files, advisory — exit 0 always unless
# --strict is added to the hook line yourself).
#
# NOTE (coordinate, not tracked): .git/hooks/ lives in the SHARED git dir
# (all lane worktrees). The hook is advisory + fast (<1s) and prints only
# file:line/rule ids. Uninstall with --uninstall. CI wiring (strict) is
# qa-security's — see docs/requests/infra__to__qa-security__ci-personal-scan.md.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
# worktrees: hooks dir is the common git dir — resolve it
if git -C "$ROOT" rev-parse --git-common-dir >/dev/null 2>&1; then
    COMMON="$(git -C "$ROOT" rev-parse --git-common-dir)"
    case "$COMMON" in /*) : ;; *) COMMON="$ROOT/$COMMON" ;; esac
    HOOK="$COMMON/hooks/pre-commit"
fi

if [ "${1:-}" = "--uninstall" ]; then
    if [ -f "$HOOK" ] && grep -q "scan_personal" "$HOOK"; then
        rm -f "$HOOK"
        echo "[git-hooks] removed pre-commit hook (scan_personal)"
    else
        echo "[git-hooks] no scan_personal hook present"
    fi
    exit 0
fi

mkdir -p "$(dirname "$HOOK")"
if [ -f "$HOOK" ] && ! grep -q "scan_personal" "$HOOK"; then
    echo "[git-hooks] REFUSING: an unrelated pre-commit hook already exists at $HOOK" >&2
    exit 1
fi
cat > "$HOOK" <<'EOF'
#!/bin/sh
# SEC-1 advisory: personal-data scan over staged files (locations only).
# Never blocks (exit 0) — strictness lives in CI (qa-security).
repo_root="$(git rev-parse --show-toplevel)"
python3 "$repo_root/scripts/scan_personal.py" --staged || true
exit 0
EOF
chmod +x "$HOOK"
echo "[git-hooks] installed advisory pre-commit hook -> $HOOK"
