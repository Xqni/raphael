# qa-security → pc-control: instance-derivation-body
Status: DONE (ALREADY-DONE for pc-control's files — evidence below; tripwire
still xfail on brain-core's `brain/app.py` half)

## Response (pc-control, 2026-10-08)

- **`body/win/main.py` — ALREADY-DONE.** `main.py:21`:
  `LOCK_PATH = _instance.body_lock_path()` (body/win/instance.py derives
  `%TMP%\raphael_body.lock` for main, `%TMP%\raphael_body_<instance>.lock`
  when `RAPHAEL_INSTANCE` is set; byte-identical main default, covered by
  `body/win/tests/test_pc_instance.py`).
- **`body/win/ws_client.py` — ALREADY-DONE.** The hardcoded
  `CONFIG_URL = "ws://127.0.0.1:8765/ws"` constant no longer exists:
  `ws_client.py:161` `async with websockets.connect(instance.ws_url())` and
  `ws_client.py:208` `url = instance.ws_url()` — §d port table (8901-8910),
  `RAPHAEL_PORT` env override wins, unknown instance without a port RAISES
  (never defaults). Token paths are per-instance too
  (`instance.token_candidates()`).
- **CDP port (9333 → 9400+idx)** — not pinned in any pc-control file (grep:
  no `9333` in body/win/** or brain/tools/pc/**); orb-side.
- **Tripwire status:** `tests/regression/test_instance_isolation.py::
test_runtime_code_derives_from_raphael_instance` still XFAILs, but the ONLY
checked file missing the `RAPHAEL_INSTANCE` literal is
  **`brain/app.py` (0 references)** — brain-core's pidfile. The other four:
  main.py 1, ws_client.py 1, brain/run.py 2, supervisor/main.py 19 ✓.

## What
INTERFACES §d requires derived per-instance values; pc-control-owned files
hardcode the `main` ones:
- `body/win/main.py`: `LOCK_PATH = %TMP%/raphael_body.lock` → must derive
  `%TMP%\raphael_body_<instance>.lock` when `RAPHAEL_INSTANCE` is set;
- `body/win/ws_client.py`: `CONFIG_URL = "ws://127.0.0.1:8765/ws"` → derive
  the §d port (8901–8910) from `RAPHAEL_INSTANCE` (env override wins);
- CDP port for orb/debug tooling (9333 → 9400+idx per §d) wherever pc-control
  pins it.
Tripwire: `tests/regression/test_instance_isolation.py::
test_runtime_code_derives_from_raphael_instance` (xfail).

## Why
Without this, a lane Body instance grabs MAIN's lock file (reports "already
running") and connects to MAIN's brain — cross-instance interference, the
exact collision §d exists to prevent.

## Impact
Touch: `body/win/main.py`, `body/win/ws_client.py`. Unset env = current
behavior. Coordinate port derivation with infra's shared helper
(`qa-security__to__infra__instance-derivation`) if it lands first.
