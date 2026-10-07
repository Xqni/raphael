#!/usr/bin/env bash
# secret-scan.sh — secrets hygiene scanner + .env permission verifier
# (infra lane, Wave-2 secrets task). Docs: scripts/SECRETS.md.
#
# Usage:
#   scripts/secret-scan.sh                 # history + worktree scan + perms
#   scripts/secret-scan.sh --perms         # ONLY check .env permissions
#   scripts/secret-scan.sh --fix-perms     # chmod 600 on any too-open .env
#   scripts/secret-scan.sh --no-history    # skip the git-history scan
#   scripts/secret-scan.sh --max-commits N # cap history scan (default: all)
#
# Engines:
#   * gitleaks (if installed) with scripts/gitleaks.toml + --redact
#   * built-in fallback otherwise: pattern scan over `git grep -l` for every
#     rev + the worktree — LOCATION only, never a matched line/value
#     (AGENT_RULES §7: secrets are never printed or logged).
#
# Exit: 0 = clean, 1 = findings (or perms failure), 2 = usage/setup error.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2
CONFIG="scripts/gitleaks.toml"

DO_PERMS=0
ONLY_PERMS=0
FIX_PERMS=0
DO_HISTORY=1
MAX_COMMITS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --perms)      ONLY_PERMS=1 ;;
        --fix-perms)  ONLY_PERMS=1; FIX_PERMS=1 ;;
        --no-history) DO_HISTORY=0 ;;
        --max-commits) shift; MAX_COMMITS="${1:-}" ;;
        -h|--help)    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '[secret-scan] %s\n' "$*"; }
fail=0

# --------------------------------------------------------------------------
# 1 — .env permissions (verify, never print contents)
# --------------------------------------------------------------------------
check_perms() {
    local target mode
    for f in .env; do
        [ -e "$f" ] || { say "PERMS SKIP  $f does not exist"; continue; }
        target="$(readlink -f "$f" 2>/dev/null || echo "$f")"
        mode="$(stat -c '%a' "$target" 2>/dev/null \
             || stat -f '%Lp' "$target" 2>/dev/null || echo unknown)"
        case "$mode" in
            600|400|440) say "PERMS PASS  $f -> $target mode=$mode" ;;
            unknown)     say "PERMS WARN  $f -> $target mode unreadable" ;;
            *)
                if [ "$FIX_PERMS" -eq 1 ]; then
                    chmod 600 "$target" && say "PERMS FIXED $f -> mode=600"
                else
                    say "PERMS FAIL  $f -> $target mode=$mode (want 600) — run: scripts/secret-scan.sh --fix-perms"
                    fail=1
                fi ;;
        esac
    done
    # .env must be gitignored (value never touched — presence check only)
    if git check-ignore -q .env 2>/dev/null; then
        say "PERMS PASS  .env is gitignored"
    else
        say "PERMS FAIL  .env is NOT gitignored — fix .gitignore first"
        fail=1
    fi
}

check_perms
[ "$ONLY_PERMS" -eq 1 ] && { [ "$fail" -eq 0 ] && exit 0 || exit 1; }

# --------------------------------------------------------------------------
# 2 — scan engine
# --------------------------------------------------------------------------
# name|regex pairs — LOCATION-only reporting. High-confidence token formats.
HISTORY_PATTERNS=(
    'AWS-access-key|AKIA[0-9A-Z]{16}'
    'GitHub-token|ghp_[A-Za-z0-9]{36}'
    'GitHub-fine-grained|github_pat_[A-Za-z0-9_]{22,}'
    'Slack-token|xox[baprs]-[A-Za-z0-9-]{10,}'
    'OpenAI-style-key|sk-[A-Za-z0-9]{20,}'
    'Anthropic-key|sk-ant-[A-Za-z0-9_-]{20,}'
    'PEM-private-key|-----BEGIN [A-Z ]*PRIVATE KEY-----'
)
# assignments that MIGHT hold a real key (reported as REVIEW — placeholders
# in docs trip these often; a human eyeballs file locations only).
ASSIGN_PATTERNS=(
    'secret-assignment|(CIVITAI_TOKEN|HF_TOKEN|GROQ_API_KEY|VAST_API_KEY|OPENCODE_API_KEY|ANTHROPIC_API_KEY)[=:][^[:space:]"'"'"'{<]{8,}'
    'discord-webhook|discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+'
)
WORKTREE_FILES() {
    git ls-files -co --exclude-standard 2>/dev/null | sort -u
}

if command -v gitleaks >/dev/null 2>&1 && [ -f "$CONFIG" ]; then
    say "engine: gitleaks ($(gitleaks version 2>/dev/null | head -1))"
    if [ "$DO_HISTORY" -eq 1 ]; then
        # stdout is --redact'ed: safe to stream live either way
        gitleaks git --config "$CONFIG" --redact --no-banner .
        rc=$?
        if [ "$rc" -eq 0 ]; then
            say "HISTORY PASS  gitleaks: no findings"
        elif [ "$rc" -eq 1 ]; then
            say "HISTORY FAIL  gitleaks found leaks in git history (redacted above)"
            fail=1
        else
            say "HISTORY WARN  'gitleaks git' unsupported (rc=$rc) — legacy detect"
            if gitleaks detect --source . --config "$CONFIG" --redact --no-banner; then
                say "HISTORY PASS  gitleaks detect: no findings"
            else
                say "HISTORY FAIL  gitleaks detect found leaks (redacted output above)"
                fail=1
            fi
        fi
    fi
    gitleaks dir --config "$CONFIG" --redact --no-banner .
    rc=$?
    if [ "$rc" -eq 0 ]; then
        say "WORKTREE PASS  gitleaks: no findings"
    elif [ "$rc" -eq 1 ]; then
        say "WORKTREE FAIL  gitleaks found leaks in the worktree (redacted above)"
        fail=1
    else
        say "WORKTREE WARN  'gitleaks dir' unsupported (rc=$rc) — skipped"
    fi
else
    say "engine: built-in pattern scan (gitleaks not installed — install it"
    say "        for the full default ruleset: https://github.com/gitleaks/gitleaks)"
    command -v git >/dev/null 2>&1 || { say "ERROR: git not found"; exit 2; }

    # ---- history: filename-level matches per rev (never line contents) ----
    if [ "$DO_HISTORY" -eq 1 ]; then
        revs="$(git rev-list --all 2>/dev/null)"
        if [ -n "$MAX_COMMITS" ]; then
            revs="$(echo "$revs" | head -n "$MAX_COMMITS")"
        fi
        nrev=$(echo "$revs" | grep -c . || true)
        hist_hits=0
        for entry in "${HISTORY_PATTERNS[@]}"; do
            name="${entry%%|*}"; pat="${entry#*|}"
            hits="$(echo "$revs" | xargs -r git grep -I -l -E "$pat" -- 2>/dev/null \
                    | sed 's/^[0-9a-f]\{7,\}://' | sort -u)"
            if [ -n "$hits" ]; then
                hist_hits=$((hist_hits + 1))
                say "HISTORY FINDING [$name] in files:"
                echo "$hits" | sed 's/^/    /'
            fi
        done
        for entry in "${ASSIGN_PATTERNS[@]}"; do
            name="${entry%%|*}"; pat="${entry#*|}"
            hits="$(echo "$revs" | xargs -r git grep -I -l -E "$pat" -- 2>/dev/null \
                    | sed 's/^[0-9a-f]\{7,\}://' | sort -u)"
            if [ -n "$hits" ]; then
                say "HISTORY REVIEW [$name] in files (may be placeholders):"
                echo "$hits" | sed 's/^/    /'
            fi
        done
        if [ "$hist_hits" -eq 0 ]; then
            say "HISTORY PASS  $nrev revision(s), no high-confidence findings"
        else
            fail=1
        fi
    fi

    # ---- worktree: filename-level matches in tracked+untracked files ----
    tree_hits=0
    for entry in "${HISTORY_PATTERNS[@]}"; do
        name="${entry%%|*}"; pat="${entry#*|}"
        hits="$(WORKTREE_FILES | xargs -r grep -I -l -E "$pat" 2>/dev/null | sort -u)"
        if [ -n "$hits" ]; then
            tree_hits=$((tree_hits + 1))
            say "WORKTREE FINDING [$name] in files:"
            echo "$hits" | sed 's/^/    /'
        fi
    done
    if [ "$tree_hits" -eq 0 ]; then
        say "WORKTREE PASS  no high-confidence findings"
    else
        fail=1
    fi
fi

# --------------------------------------------------------------------------
# 3 — summary
# --------------------------------------------------------------------------
if [ "$fail" -eq 0 ]; then
    say "VERDICT: PASS — no secret findings; .env hygiene ok"
    exit 0
fi
say "VERDICT: FAIL — findings above are LOCATIONS only; rotate any real key"
say "         immediately (revoke at the provider, then re-run this scan)."
say "         Details: scripts/SECRETS.md"
exit 1
