# 05 — Tier behavior + probation: implemented semantics

Status: **IMPLEMENTED & PASSING 2026-10-07** (Wave 5 primary lane task). Code:
`brain/persona/tiers.py` (extended), `brain/persona/probation.py` (new);
tests `brain/persona/tests/{test_tier_behavior,test_probation}.py`.
Design source: `02-persona-tiers.md` §2/§2.1; test plan `04-tier-switch-test-plan.md`
(unchanged — Layer A/B/C still cover the config switch itself).

## Autonomy = deny-by-default (`PROACTIVE_ZONE`)

| tier | proactive job classes |
|---|---|
| `great_sage` | **∅** — proposes only |
| `raphael` | `notice`, `reminder`, `status_check`, `memory_maintenance` |
| `ciel` | raphael's ∪ `file_analysis`, `web_research`, `digest`, `schedule_scan`, `summarize` |

- `can_start_proactive()` returns False for anything not explicitly listed —
  unknown classes, wrong tier, bogus/missing tier (fails closed to `great_sage`).
- Authority classes (`shell_write`, `purchase`, `send_message`, `delete`,
  `publish_public`, `spend`, `secrets`, `install`, `system_settings`,
  `make_public_repo`) appear in **no** list at **no** tier — asserted by test —
  matching addendum §14: capabilities yes, authority never.

## Unlock criteria = evaluated, never applied (`evaluate_unlock`)

- `great_sage → raphael`: ≥7 days since last severity-1, tests green at LKG,
  job success ≥95%, zero unhandled confirm timeouts, + user approval.
- `raphael → ciel`: ≥30 days stable, every auto-promoted probation passed,
  zero rollbacks in window, + user approval.
- `ready=True` means *eligible for a proposal*; `user approval` is the one
  criterion `ready` never absorbs — a tier raise still needs the user's yes
  (config write to `config.d/evolution-persona.yaml persona.tier`).

## Probation + automatic rollback (`probation.py`)

State: `<instance data-dir>/persona_probation.json` (RAPHAEL_HOME-aware, runtime,
never git). Semantics, each test-pinned:

1. `start()` only after an unlock (lower → higher). A demotion or no-op raises.
2. `record(ok=True)` counts cycles; non-ok doesn't; `fatal=True` (severity-1,
   auto-promoted-change rollback, confirm-timeout regression) ⇒ **failed now**,
   sticky — later clean events can't resurrect it.
3. `evaluate()` passes only when the window has **both** its job count **and**
   its hour span with no fatal event; window expired without enough evidence ⇒
   **failed** (earned autonomy is re-earned, not kept by default).
4. Failure ⇒ `demotion_target()` one step down (floor `great_sage`) and
   `apply_tier()` rewrites **only** the `tier:` line in the lane fragment —
   comments/other keys byte-preserved (round-trip tested against the real
   `config.d/evolution-persona.yaml`).
5. Demotion only ever LOWERS autonomy → permitted automatically; raising a tier
   remains a user-approved proposal (hard rule 1).

## Test output (real, 2026-10-07)

```
$ tests/.venv/bin/python -m pytest brain/persona/tests -q
56 passed in 0.13s
$ python3 tests/core_guard.py
Core Guard OK (4 files byte-stable)
```

## Not here (needs shared contracts — request first, per wave-5 rules)

- Answer/Notice/Report **frame** wiring (`notice` frame emitters are brain-core's;
  formats ride existing `speak`/`subtitle`/`notice` — no new frame needed).
- Analysis/Simulation `task_kind` values (brain-core jobs + orb `shape_map`).
- `minds[]` parallel-minds field on `orb_state` (integrator PROTOCOL + orb).
