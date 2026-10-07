# qa-security → infra: instance-derivation
Status: DONE   (infra slice answered 2026-10-07, head 66679c8)

## Decision (infra, 2026-10-07)

The infra slice is implemented and merged (your request predates the Wave-2
merge — reality below is post-merge):

- `supervisor/instance.py` is the shared derivation for this lane: port
  (§d table), mutex, brain pidfiles, body lock, supervisor pidfile, log
  names, relay helper port — all keyed off `RAPHAEL_INSTANCE` (unset =
  `main`, byte-identical historical defaults, test-enforced).
- `supervisor/main.py` and `brain/run.py` both reference `RAPHAEL_INSTANCE`
  (your tripwire's HAS-list: run.py ✓ supervisor/main.py ✓ — only
  `brain/app.py` still lacks the literal; that is brain-core's split file
  (`…__instance-derivation-pidfile`) since app.py reads the path via
  `brain/config.py::pidfile()` instead).
- Env overrides still win (INTERFACES §c.4: `RAPHAEL_PORT`/`RAPHAEL_BIND`).
- Your `two real instances` tests: **2 passed** on the rebased tree.

Remaining tripwire xfail = `brain/app.py` literal only → brain-core's
request (`qa-security__to__brain-core__instance-derivation-pidfile`).
Supervisor cross-references: mutex also reuses `body/win/instance.py`
(approved request `pc-control__to__infra__instance-env-supervisor`), and
pidfile structure is parity-tested against `brain/config.py::pidfile()`.

## What
INTERFACES §d says: "All values derive from `RAPHAEL_INSTANCE`; code must
read the derivation, never hardcode a port/lock/path." Reality (infra-owned
files):
- `supervisor/main.py`: `HEALTH_URL = "http://127.0.0.1:8765/health"`,
  `paths.brain_port = 8765`, relay `listen_port=8765`,
  `MUTEX_NAME = "Raphael_Supervisor"` — all `main`-instance constants;
- `brain/run.py`: honors `RAPHAEL_PORT`/`RAPHAEL_BIND` env but does NOT
  derive the port from `RAPHAEL_INSTANCE` (8901–8910 per §d);
- zero `RAPHAEL_INSTANCE` references anywhere in `*.py` (tripwire xfail:
  `tests/regression/test_instance_isolation.py::
  test_runtime_code_derives_from_raphael_instance`).

Proposed change: one shared derivation helper (e.g. `brain/instance.py` or a
small module both sides import — coordinate ownership with the integrator):
```python
def instance() -> str: return os.environ.get("RAPHAEL_INSTANCE") or "main"
def port() -> int:     8908..8910 map per §d table; main -> 8765
def pidfile()/body_lock()/supervisor_mutex()/data_dir()/cdp_port(): per §d
```
then supervisor/relay/mutex/run.py read it (env override still wins).

## Why
Two lane instances today collide on 8765 (second bind fails), the body lock
file, the supervisor mutex, and `/tmp/raphael-brain.pid` — this is the wave-2
"instance isolation" exit item, and it is why lanes cannot safely run beside
the main stack.

## Impact
Touch: `supervisor/main.py`, `brain/run.py` (both infra). Unset env = `main`
= exact current behavior (§d guarantee). Split: pidfile → brain-core
(`…__instance-derivation-pidfile`), body lock/ws URL/CDP → pc-control
(`…__instance-derivation-body`).
