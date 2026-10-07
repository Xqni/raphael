# pc-control → infra: instance-env-supervisor
Status: DONE

## Decision (coord inbox 2026-10-06, integrator → infra)
APPROVED (owner = infra, told in its inbox) — supervisor `MUTEX_NAME`
derived from `RAPHAEL_INSTANCE` and `RAPHAEL_INSTANCE`/`RAPHAEL_PORT`/
`RAPHAEL_TOKEN_PATH` passed through to children; `main` behavior unchanged.
Infra implements it in `supervisor/**`; the Body-side derivation
(`body/win/instance.py::supervisor_mutex()`) stays as is.

## What
Two small supervisor changes (supervisor/ = infra lane):

1. **Derive `MUTEX_NAME` from `RAPHAEL_INSTANCE`** — `supervisor/main.py`
   hardcodes `MUTEX_NAME = "Raphael_Supervisor"`, but INTERFACES §d specifies
   `Raphael_Supervisor_<instance>` for lanes. The Body-side derivation exists
   (`body/win/instance.py::supervisor_mutex()`), ready to import or mirror:

   ```python
   inst = os.environ.get("RAPHAEL_INSTANCE", "").strip()
   MUTEX_NAME = "Raphael_Supervisor" if not inst or inst == "main" \
       else f"Raphael_Supervisor_{inst}"
   ```

2. **Keep/forward `RAPHAEL_INSTANCE` to child processes** (body, brain, orb).
   Child processes inherit the environment today as long as nobody strips
   it — so this is mostly a "do not unset it" + document requirement; when
   supervisor ever builds an explicit env for `body_cmd`, include
   `RAPHAEL_INSTANCE`, `RAPHAEL_PORT` (instance port from INTERFACES §d,
   `pc-control` → 8903) and `RAPHAEL_TOKEN_PATH` if set.

## Why
AGENT_RULES §5 ("never start the stack on default ports, set
RAPHAEL_INSTANCE=<lane>") + INTERFACES §d. Without (1) two supervisors in
one session collide on the single named mutex (second instance silently
exits "already running"); without (2) a lane body would connect to the MAIN
port 8765 with the MAIN token — breaking isolation in both directions.

## Impact
- supervisor/main.py is infra-owned; pc-control changes none of it.
- `main` behavior unchanged (`RAPHAEL_INSTANCE` unset → same mutex name,
  same port 8765, same token paths).
- Body side is already done (body/win/instance.py + tests
  `body/win/tests/test_pc_instance.py`).
