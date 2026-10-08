# router → brain-core: register the foreground hook (AUD-05, your half)
Status: OPEN

## What
`brain.router.set_foreground_check(fn)` exists and is now ENFORCED
(production path): with no hook registered, `chat()`, `chat(stream=True)`,
`vision()` and legacy `complete()` all refuse with
`E_OFFLINE / foreground_unknown` (zero egress) — `providers.require_foreground`
default true. **The live stack therefore refuses cloud chat until the hook is
registered.** What I need from you (one call at startup, next to the other
seams):

```python
# brain/app.py lifespan (or wherever set_private_mode-equivalents are wired)
from brain.router import set_foreground_check
set_foreground_check(_focused_window_name)   # sync, cheap, never raises
```

Contract for `_focused_window_name()`:
- returns the focused window/app name as `str`, or `None` when it cannot be
  determined — `None` (or blank) = UNKNOWN = router REFUSES (that is the
  point of AUD-05; the old code allowed it);
- must be cheap & non-blocking: cache the last known value (e.g. body's
  `foreground_info` pushed/refreshed at most once a second) — do NOT do a
  WS round-trip inside the callable;
- exceptions are caught by the router (guarded) and count as UNKNOWN;
- pc-control/body is the likely data source (their `foreground_info`;
  see Bug F in docs/BUGS-WAVE2.md for its current state) — coordinate the
  cache on your side.

Interim if you need the stack up before wiring: `config.d/<lane>.yaml` cannot
touch this (authority), so the documented escape is the integrator's
`config.yaml → router.require_foreground: false` — explicitly an interim.

## Why
AUDIT-2026-10-07 AUD-05 (P0): `privacy.foreground_window()` returned `None`
for both "unwired" and "unknown", and `blocklist_hit` treated `None` as
"no block" → cloud egress with an unverifiable focused window (password
manager in focus would have been sent to the cloud). Fail-closed is now
router-side; the *data* is your half.

## Impact
- Test harnesses are unaffected: under `PYTEST_CURRENT_TEST` an unwired hook
  counts as a known synthetic `pytest-window` (documented in
  `privacy.foreground_status()`), so all suites stay green (router 201+2,
  brain 216, root 214+7 verified after this change).
- Router tests covering both paths: `brain/router/tests/test_foreground_gate.py`
  (10, incl. production-path tests that force the pytest default off).
- Zero protocol change; `E_OFFLINE` already in §10 and spoken set.
