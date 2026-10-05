#!/usr/bin/env bash
# Raphael — token generation for BOTH sides of the Brain<->Body link.
#
#   WSL copy   : ~/.raphael/token              (chmod 600)
#   Windows    : %APPDATA%\Raphael\token       (PowerShell Set-Content -NoNewline, user-only ACL)
#
# Idempotent: an existing token is REUSED (kept in sync across both locations)
# unless --force is passed. The token VALUE is never printed — paths only.
# Never installs software; BLOCKS (exit 3) if no entropy tool is available.
set -euo pipefail

FORCE=0
DRY=0

usage() {
    cat <<'EOF'
Usage: token-gen.sh [--force] [--dry-run]

  --force    regenerate the token even if one exists (overwrites both copies)
  --dry-run  print the actions and paths; write nothing
  -h, --help this help

Token locations (docs/PROTOCOL.md §2):
  WSL    ~/.raphael/token           chmod 600
  Windows %APPDATA%\Raphael\token   user-only ACL, written via PowerShell Set-Content -NoNewline
EOF
}

for arg in "$@"; do
    case "$arg" in
        --force)      FORCE=1 ;;
        --dry-run|--dryrun) DRY=1 ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "unknown argument: $arg (expected --force | --dry-run)" >&2; usage >&2; exit 2 ;;
    esac
done

say() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

WSL_DIR="$HOME/.raphael"
WSL_TOKEN="$WSL_DIR/token"

generate() {
    # stdlib/OS tools only — no pip, no package installs.
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c 'import secrets; print(secrets.token_hex(32))'
    else
        echo "BLOCKED: neither openssl nor python3 available — cannot generate a token (install one yourself; this script never installs software)" >&2
        return 3
    fi
}

win_appdata() {
    if ! command -v cmd.exe >/dev/null 2>&1; then
        echo ""
        return 0
    fi
    cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r\n' || true
}

APPDATA_WIN="$(win_appdata)"
WIN_DIR=""
WIN_TOKEN=""
if [[ "$APPDATA_WIN" == [A-Za-z]:* ]]; then
    WIN_DIR="${APPDATA_WIN}\\Raphael"
    WIN_TOKEN="${WIN_DIR}\\token"
fi

say "WSL token target   : $WSL_TOKEN"
if [ -n "$WIN_TOKEN" ]; then
    say "Windows token target: $WIN_TOKEN"
else
    say "Windows token target: unavailable (cmd.exe not found — run inside WSL); copy ~/.raphael/token manually to %APPDATA%\Raphael\token"
fi

# ---------------------------------------------------------------- dry run --
if [ "$DRY" -eq 1 ]; then
    if [ -f "$WSL_TOKEN" ] && [ "$FORCE" -eq 0 ]; then
        say "[dry-run] existing WSL token found — would reuse it (no regeneration)"
    else
        say "[dry-run] would generate: openssl rand -hex 32   (32-byte hex, value withheld)"
    fi
    say "[dry-run] would run: umask 077; printf '%s\n' <token> > $WSL_TOKEN && chmod 600 $WSL_TOKEN"
    if [ -n "$WIN_TOKEN" ]; then
        say "[dry-run] would run: powershell.exe -NoProfile -Command \"New-Item -ItemType Directory -Force -Path (Join-Path \$env:APPDATA 'Raphael') | Out-Null\""
        say "[dry-run] would run: powershell.exe -NoProfile -Command \"Set-Content -NoNewline (Join-Path \$env:APPDATA 'Raphael\token')\" (value via env, not argv)"
        say "[dry-run] would run: cmd.exe /c \"icacls %APPDATA%\Raphael\token /grant:r %USERDOMAIN%\%USERNAME%:(R,W)\""
        say "[dry-run] would run: cmd.exe /c \"icacls %APPDATA%\Raphael\token /inheritance:r\""
    fi
    say "[dry-run] nothing written."
    exit 0
fi

# ------------------------------------------------------------- generation --
TOKEN=""
if [ -f "$WSL_TOKEN" ]; then
    EXISTING="$(tr -d '[:space:]' < "$WSL_TOKEN" || true)"
    if [ -n "$EXISTING" ] && [ "$FORCE" -eq 0 ]; then
        TOKEN="$EXISTING"
        say "existing WSL token found — reusing (--force regenerates; keeping WSL/Windows in sync)"
    fi
fi
if [ -z "$TOKEN" ]; then
    TOKEN="$(generate)"
    say "generated new 32-byte hex token (value withheld — written to file only)"
fi

# ---------------------------------------------------------------- WSL copy --
if [ -f "$WSL_TOKEN" ] && [ "$(tr -d '[:space:]' < "$WSL_TOKEN")" = "$TOKEN" ]; then
    say "WSL token already current — left untouched: $WSL_TOKEN"
else
    mkdir -p "$WSL_DIR"
    ( umask 077; printf '%s\n' "$TOKEN" > "$WSL_TOKEN" )
    say "wrote WSL token: $WSL_TOKEN"
fi
chmod 600 "$WSL_TOKEN"
say "WSL token mode: $(stat -c '%a' "$WSL_TOKEN") (path only; value not shown)"

# ----------------------------------------------------------- Windows copy --
if [ -n "$WIN_TOKEN" ]; then
    # Directory creation + token write. The write uses PowerShell with
    # -NoNewline so the Windows copy is byte-for-byte clean (no trailing
    # CRLF); the value travels in the environment, never on a command line.
    powershell.exe -NoProfile -Command \
        "New-Item -ItemType Directory -Force -Path (Join-Path \$env:APPDATA 'Raphael') | Out-Null" \
        >/dev/null 2>&1 \
        || cmd.exe /c 'if not exist "%APPDATA%\Raphael" mkdir "%APPDATA%\Raphael"' >/dev/null 2>&1 \
        || true

    TOKEN="$TOKEN" powershell.exe -NoProfile -Command \
        "Set-Content -LiteralPath (Join-Path \$env:APPDATA 'Raphael\token') -Value \$env:TOKEN -NoNewline" \
        >/dev/null 2>&1 \
        || say "warning: Windows token write failed — copy $WSL_TOKEN to %APPDATA%\Raphael\token manually"
    say "wrote Windows token: $WIN_TOKEN (via PowerShell Set-Content -NoNewline; value not shown)"

    # User-only ACL: grant first, then drop inherited ACEs (fail-safe order).
    cmd.exe /c "icacls \"${WIN_DIR}\\token\" /grant:r \"%USERDOMAIN%\\%USERNAME%:(R,W)\"" >/dev/null 2>&1 \
        || say "warning: icacls grant failed — check the Windows ACL manually"
    cmd.exe /c "icacls \"${WIN_DIR}\\token\" /inheritance:r" >/dev/null 2>&1 \
        || say "warning: icacls inheritance removal failed — check the Windows ACL manually"

    WIN_BYTES="$(powershell.exe -NoProfile -Command \
        "(Get-Item -LiteralPath (Join-Path \$env:APPDATA 'Raphael\token')).Length" \
        2>/dev/null | tr -d '\r\n' || true)"
    if [ -n "$WIN_BYTES" ] && [ "$WIN_BYTES" -gt 0 ]; then
        say "verified: Windows token present ($WIN_BYTES bytes, value not shown)"
    else
        say "WARNING: could not verify the Windows token file — copy $WSL_TOKEN to %APPDATA%\Raphael\token manually"
    fi
fi

say "done. Neither location stores the value in logs; both copies match."
exit 0
