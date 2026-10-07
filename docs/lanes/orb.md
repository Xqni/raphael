# orb — lane task list (owner: orb lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/orb.md. Requests to you: `ls docs/requests/*__to__orb__*.md`.

Merge-order position: see docs/WAVES.md

Base spec: `docs/ORB_REBUILD_TASK.md`. The fidelity pass below REFINES it (never contradicts it).
Run everything with `RAPHAEL_INSTANCE=orb`.

## Already finished (verified — see docs/status/orb.md)

- [x] **W2.0 instance isolation** — WS/CDP/token/userData derive from `RAPHAEL_INSTANCE`.
- [x] **W2.1 "orb graphics don't change between states"** — `npm run orb:trace`
      harness (mock Brain + CDP + frame trace), root causes fixed, pixel-diff
      gate `npm run orb:diff` **PASS: 91/91 pairs, noise floor 0.000**.
      Request filed to brain-core (emission).
- [x] **W2.2 state mapping** — mode overlays (private teal / paused steel),
      jobs dots, server `shape_hint`, TTS amplitude cleared, listening
      amplitude channel, subtitle, provider/model plumbed to the menu.
- [ ] **W2.3 typed input + menu** — NOT done; deferred, see "Deferred" below.

## Fidelity pass (current)

- [ ] **§1 startup spin-down** — diagnose then make rotation physical:
      `angle += omega*dt` (never reset/eased), omega = exponential approach to
      rest with `orb.startup.spin_tau_ms` (1200-1800), C1 at the hand-off,
      dt clamped to 50 ms, build progress eased and overlapping the spin-down,
      governor silent during startup. Evidence: `npm run orb:trace` records
      omega/angle/core brightness/layer weights through `starting -> idle` +
      assertions; `docs/orb/startup-curve.png`, `docs/orb/startup-filmstrip.png`.
- [ ] **§2 cheap motion blur** — velocity-gated analytic 4-6 tap angular blur
      (or low-res feedback trail), premultiplied-alpha clean on white/dark/busy,
      `orb.motion_blur: auto|off|low|high`, off when `reduced_motion`, scaled
      by quality tier and by the governor. Report in `docs/orb/PERFORMANCE.md`
      (idle unchanged; active +<=25%).
- [ ] **§3 fidelity upgrades** — core (hot centre + wide bloom + faint warm
      tint + 4-6 diffraction spikes); idle Sage Core; thinking (fewer lines,
      not tangled yarn); speaking (saturated gold #FFB000/#FF9A1F/#FFE08A,
      12-sided ring, 2 counter-rotating glyph rings, diamond frame, radial
      streaks); private = base brightness + teal ring; details (fewer/larger
      panes, slightly thicker lines, 85-90% of content_px); `orb.vibrance`
      (default 1.15); verify every other state; **extend the pixel-diff test so
      EVERY pair of states differs — failing the test = failing the task.**
- [ ] **§4 quality gates** — per-state screenshots dark/light/busy in
      `docs/orb/` (replace old), filmstrip for speaking (amp low/high) +
      thinking, transparency check with blur on (no box/fringe/clipping),
      performance report, governor not regressed.
- [ ] **§5 theme hook** — `orb.theme: raphael|ciel|custom` + palette tokens
      read by the shaders, reserved `evolve_stage` on `orb_state` (documented,
      inert), `docs/orb/THEMES.md`.
- [ ] **§6 hand-off** — `docs/status/orb.md` with what changed, evidence,
      known gaps, cross-lane requests. Then stop.

## Deferred (was Wave-2 W2.3, not part of the fidelity pass)

- [ ] Typed input: double-click -> text box -> `command` frame
      (`source: orb`); menu items pause/resume, private on/off, restart,
      open logs, job list/cancel. IPC plumbing already exists
      (`sendCommand`/`requestJobList`/`cancelJob`/`sendControl` in preload;
      `sendCommand`/`requestJobList`/`cancelJob` in ws-status) — only the
      renderer UI + native menu are missing. Needs mouse hit-testing through
      `setIgnoreMouseEvents` first.

## Never
- No performance optimization work beyond what §2 measures (WAVES global constraint).
- Never commit reference imagery; `assets/orb-reference/` stays gitignored.
- Do not start the live stack / real Brain — mocks only (AGENT_RULES §5).
