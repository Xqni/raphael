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

## User art feedback (2026-10-06) — 3D + anime vibe  ✅ all verified

- [x] **Nothing should feel 2D / "3d + anime vibe":**
      - orbiting beads were flat `CircleGeometry` → now shaded **spheres** with
        the orbit plane tilted;
      - morph lattice was `z = 0` everywhere → bent into a **two-wave lens**;
      - Data Rings were coplanar ("a disk around the sun and inner cage") →
        tilted hard enough to pass **in front of and behind** the core, the way
        Speaking's Answer Mode glyph bands do;
      - **cages change shape per state** — icosphere topology preserved,
        vertices projected onto cube / triangular-pentagonal-hexagonal prism /
        octahedron per `shape_hint`, lerped over 600 ms;
      - **cages change colour per state** — every state now has a tint
        (listening ice-blue, thinking lilac-blue added on top of the existing
        gold/red/amber/grey family).
- [x] **No black haze around the sun** — spec §4's legibility backing disc was
      the cause; off via `config.d/orb.yaml` (`backing_disc_alpha: 0.0`), with
      `docs/requests/orb__to__integrator__backing-disc-default-zero.md` open to
      reconcile the base default + spec text.
- [x] **Cages barely visible → brighter; listening even brighter** — the depth
      term was pinned at its 0.35 floor (≈19% alpha) at this camera; re-centred
      to ≈0.99 with a higher baseline (≈68% at idle), `S.listening.poly`
      1.10 → 1.55 (≈88%).
- [x] **Verified (2026-10-06, all green):** `orb:trace` PASS (interaction
      16/16, distinctness 104 pairs noise 8.5e-6, startup 7/7, transparency
      border alpha 0), `orb:size` PASS (12 combos, min coverage 63.7%, drift
      5.2%), `npm test` PASS. Vision QC: haze **gone**, cage visibility
      **10/10**, listening brighter + ice-blue, cage silhouettes differ per
      state (ball / octahedron / hex-prism / box), rings **tilted** so they
      pass in front of and behind the core, beads read as **shaded beads**,
      no flat stickers, no defects.
- Measured: thinking saturated px 4197→**5278** with blue (210-240°) = **3326
      (63%)** and whiteish 2153→**1070** after raising the tint
      `#bfd4ff → #7fa8ff`; confirm keeps **2858 px in the 0-60° gold band**.
- Evidence: `docs/status/orb.md` §7.

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [x] **[P0-BugC] Speaking visuals** — fixed and gated (`orb:trace --only=bugc`
      **PASS 6/6**, `docs/orb/trace/bugc.json`; also runs inside the full pipeline):
  - **(1) no pulse** — `renderer.js` dropped any `speak` frame whose `seq` was
        `<= lastSpeakSeq`, which survives across utterances; a fresh utterance
        restarting at 0 was rejected wholesale (`0 ≤ 8`), so the orb stopped
        pulsing after the first answer. The transport is an **ordered WS**, so
        nothing needs dropping — the guard is gone, `lastSpeakSeq` is a
        high-water mark. Mirror updated in `tests/state-machine.js`
        (`testStaleSeqDrop` → `testRepeatedSeqIsNotDropped`).
        **Verified: `amp1=0.15 → amp2=0.95` across a seq reset.**
  - **(2) stuck shape** — two causes: `makeMorphTarget('octagram')` returned 48
        points vs 60 for everything else, so `updateMorph` (which lerps
        `min(from,to)`) never touched indices 144–179 and that stale tail was
        re-captured as the next `from`; **and** `onOrbState` assigned
        `orbState.shapeHint` before `animate`'s `want !== shapeHint` check, so
        the morph never fired on a state change at all.
        The pose lock snapped the lattice for every screenshot, which is why
        all 104 distinctness pairs passed while the live orb never morphed.
        Fixed with a single owner (`applyLatticeShape`) + equal-length targets.
        **Verified: `maxErr = 0` for both lattice and cage after 5 interrupted
        morphs (was 0.134 / 0.253).**
  - Delivery chain was **not** re-debugged, per BUGS-WAVE2.md.
- [x] **[SPEED] Orb flips states with no perceptible lag (Rule 15)**
      — `mean=1ms worst=2ms` from mock-Brain send to renderer applied
      (`listening:1 thinking:2 confirm:1 error:2 idle:1`), harness round-trip
      included so it is an upper bound. The 300–600 ms crossfade is by design.

- [x] **`notice` frame (coord nudge, PROTOCOL §3)** — accepted on ui, rendered
      as a level-tinted banner (info/warn/error, 4 s), never as an `orb_state`.
      **interaction PASS 19/19** incl. `notice_reaches_renderer`,
      `notice_shown_as_banner`, `notice_never_changes_state`.

## WAVE 5H AUDIT TASKS (packet `docs/audit-tasks/orb.md`)

Verify-first: every finding quoted with `file:line`, reported CONFIRMED /
NOT-APPLICABLE / ALREADY-DONE in `task_done`. QA-4: `wave_done` must link a
green CI run.

- [x] **ARCH-1 (P1) — Windows-native Electron: PLAN ONLY.**
      `docs/orb/WINDOWS-NATIVE-PLAN.md` + `.opencode/research/windows-native-electron-orb.md`.
      No code, no installs. Node on Windows already present (`v24.1.0`, right
      line). Prototype BLOCKED on human approval — `coord user_attention` posted.
      WSLg path untouched.
- [x] **F-4 (P2) — usage/rate headroom rows in the right-click menu (no new frames)
      + SEC-3 cloud-mic indicator.** CONFIRMED and shipped: `GET /status` on menu
      open → `info-usage` / `info-rate` / `info-circuit` (stable ids, honest
      `(unavailable)` degradation) from the router's `usage_status()` accessor;
      `#micbadge` + `mic-cloud` menu row, fail-safe (warns unless Private Mode).
      Interaction phase 19/19 → **30/30**.
- [x] **F-3 (P2) — activity viewer: DESIGN ONLY (CO-SHARE, correctly blocked).**
      Schema request `docs/requests/orb__to__pc-control__act-journal-schema.md`,
      design `docs/orb/ACTIVITY-VIEWER.md`. **No orb code** until pc-control
      exposes `reversible`/`undo`.
- [ ] **Item 4 — state-distinctness green after every change** (all 104 pairs).
      Re-verified on every commit in this wave.

### AMENDMENT 2 (user): BOOT STATE SEQUENCE REWIRE

- [x] **User directive: "the starting state might need to be rewired — starting state →
  idle state → then change based on what's happening."** Desired flow: on ANY launch or
  reconnect the orb shows `starting` BRIEFLY, always settles into `idle` next (even if
  jobs/journals exist — the boot Notice already carries that info), and only THEN moves
  to thinking/speaking/etc as events actually happen. Research findings: brain holds
  `starting` until `finish_boot()` (brain/app.py:92); orb initializes `orbState='starting'`
  until the first brain frame (ws-status.js:41) with `reconnecting` on drops. Your half:
  starting must AUTO-ESCAPE (timeout fallback to idle if no frame arrives; no lingering
  starting/reconnecting on a healthy stack); brain-core is assigned the emission half
  (settle-to-idle-first after finish_boot). Test: kill/restart brain twice — sequence must
  be starting→idle→(event states), never starting→thinking directly, never stuck.
  - **ORB HALF — DONE + gated (both halves of the evidence).**
    1. **Auto-escape** (`ws-status.js`): `starting` now carries a one-shot
       `STARTING_ESCAPE_MS = 4000` timer. If no frame arrives — socket open but
       the Brain never answers — it falls back to `idle` instead of lingering.
       Previously only the renderer's one-shot 5400 ms timer covered this, and
       the main-process status never escaped at all. Re-armed only when the orb
       re-enters `starting`; retired the moment it leaves (`_settleBoot`).
    2. **Settle beat** (`ws-status.js`): if the Brain's very first non-boot
       frame is already an event state (jobs exist the moment boot finishes),
       show `idle` for `BOOT_IDLE_BEAT_MS = 400` first, then apply the frame —
       so the sequence is `starting -> idle -> thinking`, never
       `starting -> thinking`. Normally brain-core sends `idle` first and no
       delay happens at all; this is the belt-and-braces half.
    3. **Clean shutdown**: `StatusWS.dispose()` retires every timer including
       the escape and blocks reconnect re-arming (`_disposed`); wired into
       `main.js` `before-quit`.
    4. **Evidence A — logic, plain Node, no Electron**
       (`tests/boot-sequence.test.cjs`, wired into `npm run test:unit`):
       **13/13** across three scenarios — (A) Brain accepts the socket and
       *never* answers → escapes in **259 ms** against a 250 ms budget, ends
       `idle`, never drops to `reconnecting`; (B) first frame is already
       `thinking` → **idle beat inserted**, `starting->idle->thinking`; (C)
       normal `auth_ok` → `starting->idle->thinking`.
    5. **Evidence B — end-to-end rendered** (`orb:trace --only=boot`, phase
       `boot_sequence`, written to `docs/orb/trace/boot-sequence.json`):
       **PASS 5/5** — `rendered=starting->idle->thinking`, i.e. the sequence
       survives the IPC path from `StatusWS` to the pixels:
       `starts_starting` · `settles_to_idle_next_before_anything_else` ·
       `never_starting_straight_to_an_event_state` ·
       `event_state_lands_after_idle` · `never_stuck_in_starting_or_reconnecting`.
    6. New probe **`window.__orbStateHistory()`** records every *rendered*
       transition, seeded at module scope with `starting` (not on the first
       animation frame — a fast `auth_ok` can land before rAF ticks).


### AMENDMENT (user, 2026-10-07 evening): PRESERVE THE CAGE + kill the box

- [x] **"the orb is now in a weird shape, its not a cage we had earlier — preserve that."**
      DONE + gated — **the code was already correct; the live orb was stale**
      (process start 18:30:26 vs revert commit 18:44:09 — Electron does not
      hot-reload, so the fix had never reached the screen; the deployed checkout
      *does* contain the flag). **Restart = integrator's call, not mine.**
      New `cage guard` **PASS 4/4**: cage geometry established **at boot**
      (`maxErr=0.0000` both lattice and cage), and mid-task a real `octagram`
      hint **arrives and is ignored** (`applied=circle effective=circle
      morphActive=false`). Vision on the regenerated matrix: outer cage is a
      **rounded ball in all four** images (rest 8/10,7/10 · mid-task 5/10,4/10).
      ORIGINAL TEXT: *"the orb is now in a weird shape, its not a cage we had earlier — preserve that."
  RESTORE THE CAGE as the always-on look.** Research findings: (1) the revert was
  renderer-side only — brain/orbstate.py:187 still emits per-task `shape_hint` from
  orb.shape_map (llm->octagram etc.), so during any task the lattice morphs away from the
  cage; brain-core is getting a decision to emit `circle` only for now (field kept for your
  future plans). (2) verify the renderer INIT path: the revert collapsed to a single
  `applyLatticeShape()` call site — confirm the cage geometry is established at BOOT (not
  only on the first state event), otherwise the lattice sits at build-time default = the
  weird look the user saw. ACCEPTANCE: at rest AND mid-task, the orb is the familiar cage
  ball; screenshot proof before/after (matrix render), gates green.
- [ ] (VISION PENDING) "a weird box underneath" the orb — user screenshot taken, vision
  analysis incoming; will be appended here with the element's identity. Do not guess-remove
  banners/subtitles until identified.

### CAGES -> 3D WIREFRAME SPHERES (user, 2026-10-07 — supersedes the octagram call)

- [x] **"nah i dont like the octagram, please change the cages (inner and outer)
      to 3d spheres please"** — DONE + gated.
  - `initSageCore` now builds the cage from **latitude rings + meridians** (a
        wireframe globe): 5 parallels × 20 segments + 6 meridians × 16
        segments = 196 edges (the icosphere it replaced had ~120, so the
        "tangled yarn" risk did not grow). The **inner cage is the same
        geometry at 0.56 scale** — outer and inner are spheres *by
        construction*, which is literally what was asked.
  - An octagram prism was built first and rejected by the user; it is gone.
  - Free "whisker" spokes removed — every segment now rejoins the mesh (they
        were the "lines that terminate mid-air" in the vision review).
  - Constant shape + colour-only state change preserved: `BASE_SHAPE` is back
        to `circle` (the sphere's silhouette), no per-state/task-kind morph.
  - **Numeric proof, not an opinion:** the probe now reports the radius of
        every cage vertex — `cageRadius=1.150..1.150`, **spread 0.0000**.
        All vertices on one sphere = it *is* a sphere; a star, prism or
        icosphere would fail that instantly.
  - **Gate:** `cage guard` requires `radiusSpread < 0.02` at boot AND mid-task,
        plus `morphActive=false` and `maxErr=0` for both lattice and cage.
        **PASS 4/4.**
  - Vision on the regenerated matrix (independent): *"the outer cage in image 1
        is a recognisable wireframe sphere/globe … a second, smaller sphere
        (~50% radius) around the core … I see no star, octagon, hexagon, box,
        or differing ring count in the cage"* — ratings 6–7/10 as a 3D sphere.

## USER DIRECTIVE 2026-10-07 — shape-morph revert (do this FIRST)

- [x] **Revert ALL automatic shape morphing.** DONE + gated — implementation:
      `effectiveShape()` now returns a constant `BASE_SHAPE = 'circle'` behind
      `SHAPE_MORPHS_ENABLED = false`, and the kind accent behind
      `KIND_ACCENTS_ENABLED = false`. **Nothing was deleted** — `STATE_SHAPE`,
      `MORPH_SHAPES`, `orb.shape_map`, the morph engine and the kind map are all
      still in the code; flipping the two booleans re-enables them.
      `startMorphTo` now has exactly **one** call site (`applyLatticeShape`),
      and `runDemo` was routed through it so the demo timeline cannot bypass
      the flag. Colour/theme per state, the speaking pulse, banners and the
      fan-out all untouched.
      **Gate added:** `orb:trace` asserts `shapeHint values seen = ["circle"]`
      across every captured scene — `shape directive: ok`.

  User:  *"revert back the shape change — the
  color change (+ the speaking state) is the only thing we are okay with. i have other
  plans for shape changing for future."* The lattice/cage must hold ONE stable base shape
  (circle — the plain ball) always: NO per-state morph (STATE_SHAPE) and NO kind accents
  (analysis/simulation). KEEP: color/theme per state, the speaking pulse/amplitude
  animation, banners, fan-out visuals, everything else. Machinery stays in code untouched
  (morph engine, MORPH_SHAPES, shape_map config — future plans re-enable it); just stop
  APPLYING it: effectiveShape() → constant 'circle', kind accent off. Update gates/matrix
  expectations accordingly. Also: the user's "cage stuck in weird shape" complaint = this
  scope (morphs off means the cage can never wedge again). Research pointers:
  renderer.js effectiveShape() (line ~151), STATE_SHAPE map, startMorphTo call sites
  (state-change block ~718, shapeHint ~594, kind accent ~792), config.yaml orb.shape_map.

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] **Renderer resilience** — all four, verified (Wave-4):
  - **GPU context loss recovery** — `webglcontextlost` cancels the event
        (mandatory or `restored` never fires), skips GL work while lost,
        rate-limited reload (no reload loop), and `main.js` re-pushes
        `orb_state` on `did-finish-load`. Pure tests **4/4**.
  - **Reconnect-storm / state spam** — the morph ramp clock no longer resets on
        retarget, so states flipping faster than 600 ms converge instead of
        parking. Pure simulation **5/5** (incl. "the old behaviour NEVER
        converges"); confirmed live: `maxErr=0` after 67 flips/6 s.
  - **fps/VRAM audit under load** — `npm run orb:audit`, all 5 spawn
        conditions enforced. idle/speaking/storm all **16.7 ms** (no
        degradation), RAM delta **+1.8 MB over 67 flips**, VmHWM peak
        **150.6 MB**, governor `acted=0`. GPU VRAM is not readable from WSL —
        reported as an explicit gap, not invented. `docs/orb/trace/audit.json`.
  - **Pose-lock-vs-truth probe into CI** — morph-target builders extracted to a
        pure module; `npm test:unit` now runs **7 morph invariants + 4
        gl-recovery + 5 morph-clock + 8 port-safety + state-machine**, all with
        **no Electron and no display**, before the screenshot gate. The unlocked
        `__orbMorphDiff()` probe stays in `orb:trace`.
  - Full gate re-run after the wiring: `orb:trace` PASS, `orb:size` PASS
        (drift 4.6%), `npm run test:unit` PASS, zero orphans, ports free.
- [x] **Safety:** `test/fake-brain.cjs` no longer binds the **live brain port
      8765** (now lane-derived, refuses `main` without `--allow-main`) — 8/8
      pure tests.

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] **Parallel-minds visuals + persona-tier visuals** — renderer only, no new
      `orb_state`, no integrator request needed (`docs/PROTOCOL.md` §3 already
      carries `answer`/`report`/`job_event += kind|parent`):
  - **Persona tiers** — `orb.theme: auto` (new default) follows
        `persona.tier`, so `great_sage → raphael → ciel` is a **config edit,
        never a renderer change**; `great_sage` = identity tier, unknown tier
        falls back to the Raphael palette. `docs/orb/THEMES.md` updated.
        Verified `theme_follows_persona_tier: orb.theme=auto persona.tier=great_sage`.
  - **Parallel minds** — `job_event.parent` tracked in ws-status on its own
        channel; beads lay out as a **fan**: one wedge per parent, children on
        an inner ring, a spoke linking parent→child (single `LineSegments` with
        a per-frame `drawRange`). Verified `jobs=3 fan=true groups=2 spokes=6`.
        Count stays authoritative from `orb_state.jobs_active` (§8) so a stale
        job table can never leave beads on screen.
  - **`kind` styling** — lattice accent per `job_event.kind`
        (analysis `#7FD4FF`, simulation `#9D8CFF`, act `#FFB000`). A live
        analysis/simulation job wins over a `chat` root — caught by the test
        (`kind_accent_analysis` first failed with `kind=chat`).
  - **`answer` / `report` banners** — wrapped `#subtitle.banner` cards (the
        plain subtitle is `nowrap` and would have clipped a paragraph off a
        280px window): answer gold 6 s with provider/model, report violet 9 s
        with title+summary. **Neither moves the orb state** — asserted.
  - **Per-frame allocation** — layout memoised on `(jobList identity,
        jobs_active)` per ORB_REBUILD §5 "Do not allocate per frame".
- [x] **Full gate:** `npm run test:unit` PASS · `orb:trace` PASS (distinctness
      104 pairs + wave5 7/7 + bugc 6/6 + interaction 19/19 + transparency) ·
      `orb:size` PASS (drift 4.6% of 12%) · `orb-diff` PASS · zero orphans,
      ports free.

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [ ] Read `docs/audit-tasks/orb.md` → your IDs: **ARCH-1, F-3, F-4** — VERIFY-FIRST (verbatim file:line, then CONFIRMED / NOT-APPLICABLE / ALREADY-DONE), QA-4: link a green CI run with your wave_done. Source register + dedupe: `docs/AUDIT-2026-10-07.md`. Rules: stack down (spawn only for your test), one suite at a time, heavy suites in cloud (`gh workflow run tests-heavy.yml`), Rule 15 speed, cost not a factor.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

## Never
- No performance optimization beyond what §2 measures (WAVES global constraint).
- Never commit reference imagery; `assets/orb-reference/` stays gitignored.
- Never start the live stack / real Brain — mocks only (AGENT_RULES §5).
