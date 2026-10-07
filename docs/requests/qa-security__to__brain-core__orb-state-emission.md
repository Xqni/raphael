# qa-security → brain-core: orb-state-emission
Status: OPEN

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
