# qa-security → brain-core: orb-state-emission
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: emission landed via `brain/orbstate.py` (`VALID_STATES` :33-34 includes listening/acting/speaking/error/starting; priority ladder documented in the module docstring). Wiring: `brain/ws.py:791-792` (`listening_on()` + `emit('listening')` on audio_start), `brain/ws.py:939,955` + `brain/app.py:97` (`mark_error` on failed jobs), `brain/app.py:111` (`emit('starting')` at boot), `brain/loop.py:606` (`emit('acting')`), `brain/loop.py:381-408,445-466` (speaking start/end). The pinned xfail is gone: `tests/regression/test_orb_lifecycle.py::test_every_lifecycle_state_emitted` → 1 passed (run 2026-10-09).

## What
INTERFACES §e / PROTOCOL §8 require server emission of, per trigger:
`listening` (mic `audio_start`), `acting` (first `act_req` / stage `tool`),
`speaking` (first `speak start`), `error` (job `failed` → transient, then
`idle`), plus `confirm` (see …__awaiting-confirm-status).
Today `hub.refresh_orb_state()` computes state from stats alone:
`pending_confirm→confirm | paused→idle | jobs_active→thinking | else idle` —
so `listening/acting/speaking/error` are NEVER emitted (xfail:
`tests/regression/test_orb_lifecycle.py::test_every_lifecycle_state_emitted`).

Proposed change: carry the intended state to the refresh instead of inferring
only from counts — e.g. `engine.on_state` hook gains a `state` argument
driven by loop.py (audio_start → listening, act_req send → acting, speak
start → speaking, job failed → error), or a per-session "current state" with
priority ordering (error > confirm > acting > speaking > thinking > idle).
Private/paused stay MODE overlays per §e (already correct).

## Why
Wave-2 exit criterion 4 (per-state orb screenshots) needs these states on the
wire, and the orb demo matrix drives from them. Note: `ws.py` is
integrator-owned per OWNERSHIP — brain-core implements the loop/hub wiring
with integrator co-sign (flagged, not disputed).

## Impact
Touch: `brain/loop.py`, `brain/jobs/engine.py` (on_state signature),
`brain/ws.py` (integrator). Contract fields unchanged; ui clients only gain
frames they already render. qa-security will replace the xfail with a strict
lifecycle-sequence test when it lands.
