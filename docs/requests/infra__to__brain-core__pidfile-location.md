# infra → brain-core: pidfile-location
Status: DONE   (SUPERSEDED — decision recorded by requester from coord bus 2026-10-06)

## Decision (coord bus, integrator/brain-core, 2026-10-06)

SUPERSEDED / fulfilled differently: brain-core's `app.py` already writes
`config.pidfile()` (`<data-dir>/brain.pid`) plus the legacy `/tmp` dual-write
for `main` — so supervisor and brain resolve the same path without the
proposed env-var plumbing. INTERFACES §d now names `brain/config.py::pidfile()`
as the single source. This lane mirrored that source (WSL-side spelling,
parity-tested in `supervisor/tests/test_pc_control_requests.py`).

## What

`brain/app.py` lifespan (lines ~58-66) hardcodes:

```python
with open('/tmp/raphael-brain.pid', 'w') as _pf:
    _pf.write(str(os.getpid()))
```

Proposed:

```python
# Proper per-user location (INTERFACES §d / request infra__to__integrator
# __pidfile-location.md); supervisor exports RAPHAEL_PIDFILE in process mode.
# Legacy /tmp path kept as the default until the integrator flips §d.
pid_path = os.environ.get('RAPHAEL_PIDFILE', '/tmp/raphael-brain.pid')
try:
    with open(pid_path, 'w') as _pf:
        _pf.write(str(os.getpid()))
except OSError:
    pass
```

The supervisor already exports an absolute
`RAPHAEL_PIDFILE="$HOME/.raphael[/instance]/brain.pid"` in its process-mode
spawn (so `~` never reaches Python), and its recycle/stop logic reads the
new path FIRST with the legacy `/tmp` path as fallback — no coordination
needed, both orders work.

## Why

Session brief task 3 (replace `/tmp` pidfile): `/tmp` is world-writable;
this write is the remaining `/tmp` toucher once the supervisor moved. Also
required for instance isolation: without it, every lane instance would
still fight over `/tmp` names (your own lane task #2 lists pidfile
derivation under `RAPHAEL_INSTANCE` — env override slots into the same fix).

## Impact

One file in your lane (`brain/app.py`), guarded try/except, default
unchanged → zero behavior change until the env var is present (tests, direct
`uvicorn` runs). No Core Guard semantics touched. Status quo stays fully
working either way — this is cleanup + hardening, not a blocker.
