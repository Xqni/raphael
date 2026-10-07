# brain-core → integrator: brain pidfile moved out of /tmp (INTERFACES §d touch)

From: brain-core lane. Date: 2026-10-06. Kind: contract-table update request (I implemented the derivation my Wave-2 brief asked for; the §d table still shows the old paths).

## What changed (brain/config.py, already committed on `agent/brain-core`)

- `config.pidfile()` now derives **`<data-dir>/brain.pid`** for every instance:
  `main` → `~/.raphael/brain.pid`, lane → `~/.raphael/<instance>/brain.pid`.
  Reason (from my brief: "Instance isolation: port, pidfile (move out of /tmp)"):
  `/tmp` is world-writable and shared across instances/users — symlink-unsafe,
  and today's fixed name `/tmp/raphael-brain.pid` collides between instances.
- **Zero behavior change for the real stack:** instance `main` still ALSO
  writes the legacy `/tmp/raphael-brain.pid` (`config.legacy_pidfile()`), so
  `supervisor/main.py` (reads/writes that path at spawn/recycle, lines ~507/779)
  keeps working untouched. Lanes never write `/tmp` at all.

## Proposed change (yours to apply — I don't edit INTERFACES/supervisor)

1. `docs/INTERFACES.md` §d "brain pidfile" column:
   `main` → `~/.raphael/brain.pid` (+ legacy `/tmp/raphael-brain.pid` until infra cutover);
   lanes → `~/.raphael/<instance>/brain.pid` (no /tmp entries).
2. `supervisor/**` (infra lane): spawn/recycle should read
   `brain.config.pidfile()` instead of the hardcoded `/tmp/raphael-brain.pid`
   (env: `RAPHAEL_INSTANCE` must be exported for the spawned process).

## Until then

Nothing breaks: main dual-writes, lanes are isolated, tests cover both
(`brain/tests/test_config.py::test_main_instance_zero_change`,
`::test_lane_instances_derive`).
