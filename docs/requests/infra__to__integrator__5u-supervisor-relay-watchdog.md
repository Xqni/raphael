# infra → integrator: 5u-supervisor-relay-watchdog
Status: APPROVED (pre-approved by coordinator decision [50] — Wave 5U §5.7
task 2: "supervisor IS pinned: request + integrator approval + clean-tree
manifest update"; this file is the required request record)

## What

Core-Guard-pinned `supervisor/**` changes for Wave 5U §5.7 (design-review
finding 3 + #12), already in flight on `agent/infra`:

1. **Helper watchdog** (commit `9062703`): `_spawn_relay_helper` (single
   spawn path), `_helper_alive` (exact-argv pgrep at watchdog cadence only),
   `_relay_watchdog_loop` (sleep-first, probe every
   `RAPHAEL_RELAY_WATCHDOG_INTERVAL` default 60 s, respawn on death,
   probe/respawn errors logged never fatal), armed in
   `start_brain_relay`; plus the helper-side accept-loop guard ported to
   `scripts/wsl-relay.py` (not pinned).
2. **Finding #12 (this batch):** helper re-resolves its bind address
   (`hostname -I`) on an interval and exits cleanly if the address vanished
   — safe *because* the watchdog now exists (review's stated ordering).
3. Manifest updates run from a **clean tree after `git add`** (lesson from
   `f89d20a`: an update before tracking misses new files in the aggregate).

## Why

Recurring relay wedges (2026-10-08 AND 2026-10-09 clean-cycle rescues) —
one leg of the relay had the zombie-listener guard and a supervisor, the
WSL helper had neither (design-review finding 3). SUPERVISOR is
Core-Guard-pinned (manifest `supervisor/**` aggregate), hence this request.

## Impact

Supervisor-only behavior additions; loopback defaults, ports, Core Guard
rules and the scheduled task all untouched. Manifest diff = the
`supervisor/**` + (if touched) single-line entries, verified entry-level in
each re-pin commit. Tests: `supervisor/tests/test_relay_watchdog.py` +
existing relay/watchdog suites.
