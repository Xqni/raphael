#!/usr/bin/env bash
# Wave 5U — Wave A live demo driver (integrator).
# Run AFTER the Wave-A merge queue is fully landed.
# House rule: ONE stack only — pre-flight sweep, start, verify, teardown verified.
set -uo pipefail
cd "$(dirname "$0")/.."

say()  { printf '\n=== %s ===\n' "$*"; }
fail() { printf 'DEMO FAIL: %s\n' "$*"; exit 1; }

# ---------------------------------------------------------------- pre-flight
say "P1 pre-flight sweep (stray stacks must be 0)"
STRAY=0
pgrep -f "uvicorn brai[n].app"  >/dev/null && { echo "stray brain";  STRAY=1; }
pgrep -f "tools.api_[s]erver"   >/dev/null && { echo "stray fish";   STRAY=1; }
pgrep -f "conduc[t]or"          >/dev/null && { echo "stray relay";  STRAY=1; }
pgrep -f "wsl-rela[y]"          >/dev/null && { echo "stray wsl-relay"; STRAY=1; }
EC=$(powershell.exe -NoProfile -Command "(Get-Process electron -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -dc 0-9)
[ "${EC:-0}" != "0" ] && { echo "stray electron x$EC"; STRAY=1; }
[ "$STRAY" = "1" ] && fail "stray stack procs present — stop them first (raphael stop + kill strays)"
echo "sweep clean (0 strays)"

# ---------------------------------------------------------------- start
say "P2 start stack"
python3 scripts/raphael_cli.py start || fail "raphael start"
python3 scripts/raphael_cli.py status || fail "status after start"

# ---------------------------------------------------------------- checks
say "P3 Wave-A feature surface"
python3 scripts/raphael_cli.py tier || echo "(tier verb unavailable)"
python3 scripts/raphael_cli.py latency || echo "(no latency samples yet — expected before first turn)"

cat <<'EOF'
P4 LIVE HUMAN DEMO (integrator runs, owner repeats at wake):
  1. Voice: "Raphael, delete notes.txt"
     -> expect REFUSAL: typed/click confirm required (high-risk class), NO deletion.
  2. Voice: "yes"        -> expect STILL refused (voice-yes never auto-confirms HIGH).
  3. Orb confirm card appears -> CLICK Approve -> act dispatches (or decline).
  4. raphael latency     -> prints derived stages (stt/routing/llm_first_token/...).
  5. Voice: "open youtube" then "search lofi" -> navigate IN PLACE (no 2nd tab).
EOF

read -r -p "Run P4 checks by hand, then type 'pass' when verified (or 'abort'): " ANS
[ "$ANS" = "pass" ] || { echo "demo not marked pass — leaving stack up for manual retry"; exit 1; }

# ---------------------------------------------------------------- teardown
say "P5 teardown verified"
python3 scripts/raphael_cli.py stop || fail "raphael stop"
sleep 3
for p in "uvicorn brai[n].app" "tools.api_[s]erver" "conduc[t]or" "wsl-rela[y]"; do
  pgrep -f "$p" >/dev/null && { echo "still alive: $p"; exit 1; }
done
echo "DEMO PASS — teardown verified (0 strays)."
# Leave one healthy stack UP for the owner's wake (plan: she must be usable).
say "P6 fresh start for wake-up"
python3 scripts/raphael_cli.py start && python3 scripts/raphael_cli.py status \
  && echo "STACK UP — ready for the owner." \
  || echo "WARN: wake-up start failed — investigate before leaving."
