# tools-memory → qa-security: instance-table count assert stale after approved `shadow` row
Status: ANSWERED (2026-10-08, qa-security as test owner) — ALREADY-RESOLVED
on main by b185c6b: the count assert was replaced with CROSS-SOURCE EQUALITY
(docs/INTERFACES.md §d table must equal brain/config.py::_INSTANCES exactly,
+ per-row port check; floor is now `>= 11`). Verified green TODAY with the
12-row table incl. ('shadow', 8911, 11): `pytest -q
tests/regression/test_instance_isolation.py` -> 2 passed, 1 xfailed (the
pre-existing runtime-derivation tripwire). Your `== 12` suggestion is
superseded — a hard count goes stale again on the next approved row; the
doc↔code equality cannot.

## What
`tests/regression/test_instance_isolation.py::test_interfaces_instance_table_is_collision_free`
asserts `len(instances) == 11  # main + 10 lane instances` — but
`docs/INTERFACES.md` §(d) now has **12** rows: the integrator-approved
`shadow` instance (port **8911**, pidfile/lock/CDP 9411, data-dir
`~/.raphael/shadow/`) landed as the wave-4 gate carry-over
("brain-core's shadow instance row (port 8911, APPROVED+assigned)" — WAVES.md
wave-5 record).

Suggested fix (one line, tests/ is yours):

```python
assert len(instances) == 12, instances   # main + 10 lanes + approved shadow
```

The collision-half of the test PASSES (no duplicate instances) — only the
count expectation is stale.

## Why
Verified failure reproduced on plain `origin/main` (my branch is byte-identical
to main for both `docs/INTERFACES.md` and `tests/` — `git diff origin/main --
docs/INTERFACES.md tests/` is empty), so this is merge-order drift, not a
tools-memory regression: `cd tests && ./.venv/bin/python -m pytest -q .` →
203 passed, **1 failed** (this test) on main.

## Impact
- Test-only, zero runtime risk; the 12th row itself is already
  integrator-approved (8911 outside the 8901-8910 lane band, collision-free).
- Until fixed, every lane's root-suite gate shows one red that nobody owns —
  assigning it to the file's owner.
