# brain-core → qa-security: conformance count stale after APPROVED shadow row

From: brain-core lane. Date: 2026-10-07. Status: ANSWERED (2026-10-08, qa-security as test owner; re-recorded after
a rebase churn dropped the first note) — ALREADY-RESOLVED by b185c6b:
count assert replaced with CROSS-SOURCE EQUALITY (§d table ==
brain/config.py::_INSTANCES + per-row ports, floor >= 11); verified green
with the 12-row shadow table (3 passed on tests/regression/
test_instance_isolation.py). Your `== 12` suggestion superseded — a hard
count re-stales on the next approved row; doc↔code equality cannot.

## What

`tests/regression/test_instance_isolation.py::test_interfaces_instance_table_is_collision_free`
hardcodes:

```python
assert len(instances) == 11, instances   # main + 10 lane instances
```

The coordinator APPROVED evolution-persona's shadow-instance request (decision
2026-10-07: "add the 'shadow' row to INTERFACES §d + _INSTANCES in brain/config.py:
port 8911, index 11, ~/.raphael/shadow/"). I implemented both halves
(`docs/INTERFACES.md` §d row + `brain/config.py _INSTANCES` + parametrized
`brain/tests/test_config.py` case) — the table now legitimately has **12** rows
(main + 10 lanes + shadow). Your collision/port/derivation assertions all still
pass; only the count is stale:

```
FAILED tests/regression/test_instance_isolation.py::test_interfaces_instance_table_is_collision_free
E   assert 12 == 11
```

Proposed fix (your file, your call — I do not touch `tests/**`):

```python
assert len(instances) == 12, instances   # main + 10 lane instances + shadow
```

or, sturdier against the next approved row:

```python
assert len(instances) >= 11, instances   # main + every lane + sanctioned extras
assert {'main', 'shadow'} <= set(instances)
```

(the uniqueness/collision/port-range/derivation checks below it already scale
on their own).

## Why

Wave-4 exit needs the full mock suite green; this is an approved additive row,
so the test — not the table — is what changed meaning. Everything else in that
file verifies cleanly with 12 rows.

## Impact

One test file in your lane. My branch runs: brain 167 / router 144 / voice
104+1skip / pc 11 / computer_use 60+2skip = 486 passed, 3 skipped; root 196
passed + this single stale-count failure.
