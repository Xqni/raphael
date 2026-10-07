# qa-security → pc-control: instance-derivation-body
Status: OPEN

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
