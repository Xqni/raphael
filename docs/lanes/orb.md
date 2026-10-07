# orb — lane task list (owner: orb lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/orb.md. Requests to you: `ls docs/requests/*__to__orb__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md current_wave: 2)

- [ ] **W2.0 Instance isolation** — derive CDP port, single-instance key/userData, WS port + token path from `RAPHAEL_INSTANCE` (INTERFACES §d: orb row = WS 8906, CDP 9406, userData `~/.raphael/<instance>/orb/`). No hardcoded ports.
- [ ] **W2.1 FIX: orb graphics do not change between states** (diagnose end-to-end, no guessing):
  - [ ] build `npm run orb:trace` — mock-brain WS server in `body/orb/test/` replaying the full `orb_state` sequence (starting, idle, listening, thinking, acting, speaking, confirm, error, reconnecting, offline, private/paused modes); logs frames received / state applied / uniform+weight values per frame.
  - [ ] run it through the existing CDP screenshot harness; capture every state.
  - [ ] check the listed likely causes (frames arriving, state-name mismatch, layer-weight mapping, crossfade/dt, frame-time governor, reduced_motion/rest_motion, renderer pause/throttle, amplitude wiring).
  - [ ] automated test that FAILS when two states render near-identical (pixel-diff threshold).
  - [ ] save per-state screenshots (dark/light/busy) to `docs/orb/`.
  - [ ] if the Brain isn't emitting `orb_state`, file `docs/requests/orb__to__brain-core__<slug>.md` with frame-trace evidence and keep going.
- [ ] **W2.2 Full state mapping per docs/PROTOCOL §8** — all lifecycle states, private/paused overlays, jobs_active dots, shape_hint morphs, amplitude reactivity (mic for listening, TTS for speaking), subtitle, provider/model in right-click menu.
- [ ] **W2.3 Typed input (TODO §3e)** — double-click opens a text box -> `command` frame (`source: orb`). Menu: pause/resume, private on/off, restart, open logs, job list/cancel.

## Wave 2 leftovers (from the pre-existing lane list)
- [ ] Renderer coverage: every INTERFACES §e state renders distinctly (incl. mode overlays private/paused, jobs_active dots, provider/model). *(absorbed into W2.2)*
- [ ] Fake-brain harness drives full transition sequences *(absorbed into W2.1)*
- [ ] Refresh per-state screenshot matrix (docs/orb/matrix) = Wave 2 exit evidence. *(absorbed into W2.1)*
- [ ] Demo/CDP runs use instance-derived userData + CDP port. *(= W2.0)*
- [x] State-machine unit tests green (baseline re-run each task).

## Wave 3 (do not start early — AGENT_RULES §11)
- Answer Mode polish per docs/ORB_REBUILD_TASK.md; sub-orb indicators for parallel jobs; confirm-state UX (amber + readable question).

## Wave 4
- Reconnect/offline visual robustness, reduced-motion correctness, trace tool kept as a regression test.

## Wave 5
- Notice/Report/Answer visual flourishes; per-persona-tier palette (great_sage, raphael, ciel) via config.

## Never
- No performance optimization work (WAVES global constraint).
