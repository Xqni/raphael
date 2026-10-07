# infra → qa-security: ci-supervisor-tests
Status: ACCEPTED   (decision recorded by requester from coord bus 2026-10-06)

## Decision (coord bus, integrator→qa-security, 2026-10-06)

APPROVED — qa-security told (in their inbox) to include `supervisor/tests`
in the root/CI command:
`tests/.venv/bin/python -m pytest -q tests supervisor/tests`
(66 lane tests / 154 combined with `tests/` + `body/` as of 2026-10-06
post-rebase), and to consider superseding the `tests/supervisor` relay mocks
with `supervisor/tests/test_relay_bind.py` coverage. Awaiting their CI
implementation (their lane).

## What

The infra lane's synthetic suite lives at **`supervisor/tests/`** (30 tests,
stdlib + pytest only, no network beyond a refused localhost probe, never
executes a real kill). Please include it in the root test/CI command when
you build `.github/workflows`:

```bash
tests/.venv/bin/python -m pytest -q tests/ supervisor/tests/
```

(or add a root `conftest.py`-level invocation of your choice — the tests
are self-contained: own `conftest.py` puts the repo root on `sys.path` and
scrubs `RAPHAEL_INSTANCE/PORT/PROFILE/BIND` per test).

## Why

Your lane owns `tests/**` at the root; the ownership rule puts
inside-my-folder tests in the lane's folder, so the documented
`cd tests && pytest` command doesn't collect them. Without an explicit
include they'd silently never run in CI (and my status log runs them
manually today: `tests/.venv/bin/python -m pytest supervisor/tests -q` →
`30 passed`).

## Impact

Additive — no changes to your files requested, just a CI include. Also
useful for you: `tests/supervisor/test_relay_parsing.py` and
`test_tcp_splice.py` are mocks *of* supervisor logic; the real logic is now
covered in `supervisor/tests/test_relay_bind.py` (bind-address audit), so
you may want to supersede those mocks at your leisure.
