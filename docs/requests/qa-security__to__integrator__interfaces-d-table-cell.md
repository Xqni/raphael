# qa-security → integrator: interfaces-d-table-cell
Status: OPEN

## What
Minor doc self-consistency in `docs/INTERFACES.md` §d: the router row's body
lock cell reads `` `…_body_router.lock` `` but per the documented expansion
rule (`<main-name>_<instance>`, main-name = `raphael_body`) it should be
`` `…_router.lock` `` (expanding to `%TMP%\raphael_body_router.lock`). As
written, `…` must mean different prefixes for different rows
(`%TMP%\raphael` for the router row vs `%TMP%\raphael_body` for later rows),
which is what the table test had to special-case:
`tests/regression/test_instance_isolation.py::
test_interfaces_instance_table_is_collision_free` accepts both forms.

## Why
The table is the machine-readable contract for instance derivation
(`…__instance-derivation` requests quote it); an ambiguous expansion invites
off-by-prefix lock bugs when lanes implement §d.

## Impact
Docs-only one-character fix (or add a footnote defining `…` per column).
