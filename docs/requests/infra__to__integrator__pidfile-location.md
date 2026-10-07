# infra → integrator: pidfile-location
Status: OPEN

## What

Update `docs/INTERFACES.md` §d, **brain pidfile column**:

| instance | before | proposed |
|---|---|---|
| `main` | `/tmp/raphael-brain.pid` | `~/.raphael/brain.pid` (legacy `/tmp/raphael-brain.pid` kept as read/remove fallback) |
| lanes | `/tmp/raphael-brain_<lane>.pid` | `~/.raphael/<lane>/brain.pid` (legacy `/tmp/raphael-brain_<lane>.pid` as fallback) |

Also extend the §d data-dir row note: the data dir now also holds
`brain.pid` (WSL side). Windows-side additions from this lane (not in the
table, listed for the integrator's awareness): supervisor pidfile
`run/supervisor[_<lane>].pid`, per-instance logs `logs/<name>[_<lane>].log`.

## Why

Session brief task 3: "Replace the /tmp pidfile with a proper location."
`/tmp` is world-writable (any local user can pre-create or swap the file)
and pre-fixes every lane's pidfile into a shared sticky directory. The
per-user data dir `~/.raphael/` is already the contract's data-dir root.

## Impact

- `supervisor/main.py` already writes/reads/removes BOTH paths (new first,
  legacy fallback) — zero breakage while `brain/app.py` still writes `/tmp`.
- `brain/app.py` change is brain-core's (request filed:
  `infra__to__brain-core__pidfile-location.md`).
- Docs referencing the old path that may need a follow-up sweep:
  `README.md` (kill one-liner), `docs/TROUBLESHOOTING.md` (pid check rows),
  `docs/ARCHITECTURE.md` (topology line), `tests/e2e_wave2.py` step list.
  All integrator/qa-security-owned — not touched by this lane.
