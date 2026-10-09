# evolution-persona → brain-core: shadow-instance-row
Status: OPEN

## What
Add a `shadow` row to the instance-derivation table in `docs/INTERFACES.md` (d) and make sure the
derivation code (instance → port / pidfile / body lock / supervisor mutex / orb userData / CDP /
data-dir) handles an instance name that is **not** a lane name:

| instance | WS/REST port | brain pidfile | body lock | supervisor mutex | orb single-instance | CDP | data-dir |
|---|---|---|---|---|---|---|---|
| `shadow` | 8911 (next free) | `/tmp/raphael-brain_shadow.pid` | `%TMP%\raphael_body_shadow.lock` | `Raphael_Supervisor_shadow` | `~/.raphael/shadow/orb/` | 9411 | `~/.raphael/shadow/` |

Derivation rule stays generic (`<main-name>_<instance>`, `9400 + index`, `~/.raphael/<instance>/`) —
we only need `shadow` covered by the table so lanes share one source of truth rather than each
hardcoding a port (INTERFACES (d): "code must read the derivation, never hardcode a port/lock/path").

## Why
Wave 4 self-evolution infrastructure (`docs/evolution/01-self-evolution-infra.md` §3) verifies every
candidate change in a shadow instance (`RAPHAEL_INSTANCE=shadow`, mock Body) before any promote.
Without a defined row, a lane would have to invent port/lock values — exactly what instance
isolation exists to prevent (AGENT_RULES §5). Wave 4 exit criteria depend on it.

## Impact
- No behavior change for `main` or any lane instance; purely additive (one new name + its values).
- Not a Core Guard change (no auth/kill/pause/private/allow-list semantics touched).
- If `8911`/`9411` collide with a planned lane, any free value is fine — the lane owns the choice,
  we only need the derivation to be honored.

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: `docs/INTERFACES.md:81` carries the `shadow` row in the instance-derivation table (port 8911 / CDP 9411 / `~/.raphael/shadow/` data-dir, pidfile per the generic data-dir derivation). The sanctioned edit is recorded in `tests/ownership_exceptions.txt` ("docs/INTERFACES.md =brain-core # 2026-10-07 integrator decision … shadow row").
