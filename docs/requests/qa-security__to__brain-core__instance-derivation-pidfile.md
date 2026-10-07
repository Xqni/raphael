# qa-security → brain-core: instance-derivation-pidfile
Status: OPEN

## What
`brain/app.py` lifespan writes `'/tmp/raphael-brain.pid'` hardcoded — per
INTERFACES §d it must derive `/tmp/raphael-brain_<instance>.pid` from
`RAPHAEL_INSTANCE` (main/unset keeps today's path).
Tripwire: `tests/regression/test_instance_isolation.py::
test_runtime_code_derives_from_raphael_instance` (xfail).

Proposed change:
```python
inst = os.environ.get('RAPHAEL_INSTANCE') or ''
path = f'/tmp/raphael-brain_{inst}.pid' if inst else '/tmp/raphael-brain.pid'
```
(or call the shared derivation helper once infra lands `…__instance-derivation`).

## Why
Every TestClient lifespan / second brain instance silently overwrites MAIN's
pidfile — supervisor recycles processes on that file, so a lane test run could
trigger a kill of the real brain. qa-security's suite currently GUARDS
against the write (conftest + subprocess bootstrap raise OSError on that
path) instead of depending on correct behavior.

## Impact
Touch: `brain/app.py` only. Supervisors reading the pidfile must follow the
same derivation (infra request `…__instance-derivation` covers the reader side).
