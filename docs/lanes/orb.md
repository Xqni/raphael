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

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

## Never
- No performance optimization beyond what §2 measures (WAVES global constraint).
- Never commit reference imagery; `assets/orb-reference/` stays gitignored.
- Never start the live stack / real Brain — mocks only (AGENT_RULES §5).
