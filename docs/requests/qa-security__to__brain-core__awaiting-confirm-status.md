# qa-security → brain-core: awaiting-confirm-status
Status: OPEN

## What
`brain/loop.py` section 1 sets the `pending_confirm` column and EMITS a
`job_event(awaiting_confirm)` but never `store.transition(rowid,
'awaiting_confirm')`. Consequences:
- `store.get_job()['status']` stays `running` while a confirmation is pending
  → PROTOCOL §5 state machine violated; `/jobs`, `GET /jobs/{id}`, `job_get`
  all lie;
- `engine.stats()['jobs_pending_confirm']` (counts status ==
  `awaiting_confirm`) is always 0 → `refresh_orb_state()` can never compute
  state `confirm` → the orb never shows amber (INTERFACES §e, PROTOCOL §9.1).

Proposed change: in loop section 1, before/with the emit:
`store.transition(rowid, 'awaiting_confirm', stage='routing', progress=0.1)`
(and after resolution, the existing cancel/done transitions already handle
running→terminal — verify `store.transition` allows `running →
awaiting_confirm → running/done/cancelled`).

## Why
Review §1.4 C4 / §1.9 X3 input. Pinned by xfails:
`tests/regression/test_orb_lifecycle.py::test_orb_confirm_state_while_awaiting`
and `::test_job_snapshot_reports_awaiting_confirm`.

## Impact
Touch: `brain/loop.py` (+ maybe a guard in `brain/jobs/store.py::transition`).
Risk: clients that filter on `status=='running'` — none in-repo do (orb uses
stats, body ignores job_event status details). Both xfails flip green.

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: the proposed transition landed — `brain/loop.py:523` `store.transition(rowid, 'awaiting_confirm', stage='routing', ...)` immediately followed by the emit at :526. Both pinned tests now pass without xfail: `tests/regression/test_orb_lifecycle.py::test_orb_confirm_state_while_awaiting` + `::test_job_snapshot_reports_awaiting_confirm` → "2 passed" (run 2026-10-09).
