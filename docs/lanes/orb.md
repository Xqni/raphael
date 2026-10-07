# orb — lane task list (owner: orb lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/orb.md (hand-off). Requests to you: `ls docs/requests/*__to__orb__*.md`.

Merge-order position: see docs/WAVES.md

Base spec: `docs/ORB_REBUILD_TASK.md`, refined by the fidelity pass below.
Run everything with `RAPHAEL_INSTANCE=orb`. Evidence & numbers: `docs/status/orb.md`.

## Wave 2 — reconciliation against the original checklist (2026-10-06)

Re-ticked against the item text as originally written, with real evidence
(never ticked on claim alone):

| # | original item | status | evidence |
|---|---|---|---|
| 1 | Renderer coverage: every INTERFACES §e state renders distinctly (incl. mode overlays private/paused, jobs_active dots, **provider/model**) | **DONE** | distinctness **PASS 104 pairs, noise 4.3e-6** covers every state; mode overlays + jobs dots shipped; **`provider`/`model` now surfaced** in the right-click menu (`Provider: groq | Model: llama-3.3-70b-versatile`, asserted by `orb:trace --only=interaction`) |
| 2 | Fake-brain harness drives full transition sequences (starting→idle→listening→thinking→acting→speaking→confirm→error + reconnecting/offline) | **DONE** | `npm run orb:trace` + `body/orb/test/mock-brain.cjs`; every frame logged in `docs/orb/trace/trace.jsonl`; reconnecting/offline driven by a real WS drop + rejected auth |
| 3 | Refresh per-state screenshot matrix (`docs/orb/matrix`) = Wave 2 exit evidence | **DONE** (was genuinely open — I had deleted `matrix/`, which ORB_REBUILD §8 / TODO §4 / PROGRESS.md still cite) | **41 shots regenerated** from the current build (13 states × dark/light/busy + reconnecting/offline on dark); `orb:trace` now keeps it in step automatically; `orb:diff` scans it |
| 4 | Demo/CDP runs use instance-derived userData + CDP port (INTERFACES §d) | **DONE** | `src/main/instance.js` + `test/run-demo.cjs`; every harness logs `instance=orb ws=8906 cdp=9406` |
| 5 | State-machine unit tests green | **DONE** | `node body/orb/tests/state-machine.test.js` → `All state machine tests passed` (re-run 2026-10-06) |

**First truly-open item = #1's `provider/model` remainder**, i.e. W2.3 below.

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

## W2.3 typed input + menu (was deferred — DONE)

- [x] **Typed input (TODO §3e):** double-click over the orb opens a text box →
      `command` frame `{text, source:'orb'}` (PROTOCOL §3, role `ui`).
      Enter sends, Esc closes, box closes itself after a send.
- [x] **Menu:** pause/resume, private on/off, restart, open logs, job
      list/cancel — plus `Provider:` / `Model:` from the `orb_state` frame.
- [x] **Mouse hit-testing:** the window stays click-through by default
      (`setIgnoreMouseEvents(true, {forward:true})` so the renderer still sees
      the pointer) and only becomes solid while the cursor is inside a 0.40×
      hit disc (and while the text box is open) — no click trap over the host
      desktop.
- [x] **Verified** `npm run orb:trace -- --only=interaction` → **PASS 14/14**,
      asserted against a live orb over CDP + the mock Brain:
      menu structure/values, pointer over→solid and away→click-through
      (renderer decision **and** what main actually applied), text box
      open→send→close, `command.source=='orb'` with the text round-tripping,
      `control{action:'pause'}` leaving the process, `Jobs (2)` populated from
      a `job_list` frame, and `cancel{job, scope:'full'}` reaching the Brain.
      The phase now also runs inside the full `orb:trace` pipeline.
- Fixed while testing: menu cancel was sending `scope:'gui'`, which per
  PROTOCOL §3 only releases the input lock and would have left the job running
  — now `scope:'full'`.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

## Never
- No performance optimization beyond what §2 measures (WAVES global constraint).
- Never commit reference imagery; `assets/orb-reference/` stays gitignored.
- Never start the live stack / real Brain — mocks only (AGENT_RULES §5).
