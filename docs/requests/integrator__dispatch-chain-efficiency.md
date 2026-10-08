# integrator — dispatch-chain efficiency and stale-session recovery
Status: FIXED + VERIFIED (user request 2026-10-08; conductor suite 40 passed, Core Guard 20 files green)

## User ask
"optimize the dispatch chain so it works correctly and efficiently without wasting tokens"

## Verified findings
1. `Conductor.runs_last_hour()` counted every `ping`/`ping-integrator` record against
   `runs_per_hour` (12), so after 12 existing-session prompts all later dispatch stopped
   even though those prompts spawn no new process.
2. `wake_lane()` applied headless `active_count` and hourly process caps BEFORE checking
   for a registered session, blocking low-cost context-preserving pings.
3. `coord.find_session()` used `opencode api get /api/session?limit=200` and read
   `session.location.directory`; OpenCode v2 `opencode session list --format json` reports
   `directory` at the top level, so fallback discovery missed valid lane sessions.
4. `_try_ping()` required a JSON `data` envelope even on successful zero-body responses,
   then retried with `delivery=queue`, risking a duplicate paid turn.

## Approved implementation
- `runs_per_hour` counts only spawned `headless`/`integrator` runs.
- Existing-session pings bypass headless capacity and process-run limits.
- Per-lane ping cooldown (default 60s) coalesces duplicate bursts; events remain in inbox.
- Session discovery uses the supported CLI and accepts top-level `directory` plus legacy
  nested `location.directory`.
- Any zero-exit API prompt is treated as accepted (no duplicate retry on empty 204).
- 404 stale IDs still clear and fall through to the guarded headless path; actual spawned
  work still obeys max_parallel_runs, runs_per_hour, lane locks, and backoff.

## Core Guard
`tools/conductor/**` is SEC-7 hash-covered. Re-pin only with this request:
`python3 tests/core_guard.py --update --approval docs/requests/integrator__dispatch-chain-efficiency.md`.

## Tests
Unit tests cover ping-at-capacity, pings excluded from headless budget, duplicate-ping
coalescing, 404 headless fallback, zero-body success not retried, and OpenCode-v2
top-level session-directory discovery.

## Live dispatch verification (2026-10-08)

After restarting only the conductor (Raphael stack unchanged/down), `coord ping --lane router` found the registered session via its persisted id and returned `coord: pinged router (...)` in one prompt. Conductor log shows the new process booted after this patch. Full battery is dispatched to GitHub Actions; no local heavy suites were run.

## Addendum: autonomous keepalive (same user ask — "cron jobs ... fully autonomous")

`tools/conductor/keepalive.py` (Core Guard covered under this approval):
- `dispatch` — ensures conductor is running, pings lanes that have pending events or
  unread inbox AND an inactive session (5-min per-lane cooldown), wakes the integrator
  after 10 min of idleness-with-pending. **Never writes state.json** (a whole-state write
  reverted every cursor on 2026-10-08 — regression test enforces this); its own cooldown
  lives in `keepalive-state.json`.
- `usage` — rolling 5h/weekly/monthly Go-spend ESTIMATES from the value-blind
  `brain/router/usage.jsonl` (budgets seeded $12/$30/$60, adjustable in
  `usage-watch.json`; no unauthenticated console API exists, so estimates are the
  early-warning layer), limit hits detected from recorded `FreeUsageLimit`/rate error
  codes, then an hourly 1-token availability probe (key read from .env, never printed)
  whose success = RESET → attention + integrator wake.
- Cron (appended to the user's crontab, existing entries preserved):
  `*/10 * * * * ... keepalive.py dispatch` and `*/20 * * * * ... keepalive.py usage`.
- Tests: `tools/conductor/tests/test_keepalive.py` (window math, hit-state roundtrip,
  ping decisions incl. paused/active/cooldown, never-rewrite-state regression).
