# orb — lane task list (owner: orb lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/orb.md (hand-off). Requests to you: `ls docs/requests/*__to__orb__*.md`.

Merge-order position: see docs/WAVES.md

Base spec: `docs/ORB_REBUILD_TASK.md`, refined by the fidelity pass below.
Run everything with `RAPHAEL_INSTANCE=orb`. Evidence & numbers: `docs/status/orb.md`.

## Wave 2 (finished)

- [x] **W2.0 instance isolation** — WS/CDP/token/userData derive from `RAPHAEL_INSTANCE` (`src/main/instance.js`).
- [x] **W2.1 "orb graphics don't change between states"** — `npm run orb:trace`
      harness built, 6 root causes fixed, frame-trace evidence in
      `docs/orb/trace/trace.jsonl`, gate `npm run orb:diff` **PASS (104 pairs,
      noise 0.0000043)**; request filed to brain-core for emission.
- [x] **W2.2 full state mapping (PROTOCOL §8)** — mode overlays (private teal /
      paused steel), jobs dots, server `shape_hint`, TTS amplitude cleared,
      listening amplitude channel, subtitle, provider/model to the menu.
- [x] **Demo/CDP runs use instance-derived userData + CDP port.**
- [x] **State-machine unit tests green.**

## Fidelity pass (current — see docs/status/orb.md for every number)

- [x] **§1 startup spin-down** — physical `angle += omega*dt`, exponential
      omega relax with `orb.startup.spin_tau_ms`, C1 hand-off, dt clamped 50 ms,
      ease-in-out build, governor frozen during startup.
      **PASS 7/7 assertions** (baseline was FAIL 4/7: +6.13 rad/s jump,
      R² 0.89, 6.9% left at 1.5τ). Evidence: `docs/orb/startup-curve.png`,
      `docs/orb/startup-filmstrip.png`, `docs/orb/STARTUP.md`.
- [x] **§2 cheap motion blur** — velocity-gated low-res (½) 4-tap angular
      smear, one extra pass, mixed in by the existing mask pass.
      **idle: pass skipped, 0% cost · active: 16.678 → 16.676 ms (−0.01%)**
      against a ≤25% budget. Transparency with blur forced: **border alpha 0**
      in every state. Report in `docs/orb/PERFORMANCE.md`.
- [x] **§3 fidelity** — core bloom/spikes; idle less starburst; thinking de-yarned;
      speaking saturated gold (#FFB000/#FF9A1F/#FFE08A, 3450/4227 saturated px);
      private = base brightness + teal ring; fewer/larger panes; line weights;
      85–90% fill; `orb.vibrance` 1.15; every state verified.
      **EXCEPT** the wireframe line-weight item (WebGL clamps lineWidth to 1px —
      fat-line geometry is the open item, see status §2.1).
- [x] **§4 quality gates** — per-state screenshots dark/light/busy replaced in
      `docs/orb/`, filmstrips for speaking (amp low/high) + thinking,
      transparency check with blur on, performance report, governor not
      regressed (0 actions across startup, dpr held at 1.0).
      `npm run orb:size` **PASS** at 160/200/280 px × 100%/150% scale.
- [x] **§5 theme hook** — `orb.theme: raphael|ciel|custom` + palette tokens +
      `orb.vibrance`, `evolve_stage` reserved/forwarded/inert,
      `docs/orb/THEMES.md`.
- [x] **§6 hand-off** — `docs/status/orb.md`.

## Deferred (was W2.3 — not part of the fidelity pass)

- [ ] Typed input: double-click → text box → `command` frame (`source: orb`);
      menu = pause/resume, private on/off, restart, open logs, job list/cancel.
      IPC plumbing already exists (`sendCommand` / `requestJobList` /
      `cancelJob` / `sendControl` in preload and the same three on
      `ws-status.js`) — remaining work is the renderer UI, the native menu and
      mouse hit-testing through `setIgnoreMouseEvents`.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

## Never
- No performance optimization beyond what §2 measures (WAVES global constraint).
- Never commit reference imagery; `assets/orb-reference/` stays gitignored.
- Never start the live stack / real Brain — mocks only (AGENT_RULES §5).
