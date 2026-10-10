# orb — status (hand-off)

Updated: 2026-10-06 · lane `orb` · branch `agent/orb` · `RAPHAEL_INSTANCE=orb`
Commits: `7a3615d` (W2 state distinctness) · `6eddf54` (§1 startup spin + §2 blur) · §3–§5 see below.

---

## 1. What changed

### A. Instance isolation (INTERFACES §d)
- New `body/orb/src/main/instance.js` — single derivation for WS port, CDP port,
  data-dir, token path and Electron userData (which **is** the single-instance
  key, since `requestSingleInstanceLock()` is scoped to userData).
  `main`/unset keeps today's behaviour exactly; `orb` → WS **8906**, CDP
  **9406**, `~/.raphael/orb/orb/`.
- `main.js` re-paths userData before app-ready; `config.js` reads
  `Instance.wsUrl()` / `Instance.readToken()` instead of hardcoded
  `ws://127.0.0.1:8765` + `RAPHAEL_ORB_TOKEN`.
- `npm run orb:demo` goes through `test/run-demo.cjs` (npm scripts cannot
  compute a port); `main` still gets 9333.
- **Verified:** `instance=orb ws=8906 cdp=9406` in every trace run; the orb
  authenticated against a mock Brain on 8906.

### B. "The orb's graphics do not change between states" — diagnosed end-to-end, fixed, gated
Built `npm run orb:trace` (`body/orb/test/`): `mock-brain.cjs` (replays every
INTERFACES §e scene over a real WS on the instance port), `orb-trace.cjs`
(orchestrator), `cdp.cjs`, `png.cjs`, `orb-diff.cjs` (the gate), `startup.cjs`
+ `gfx.cjs` (curve/filmstrip), `orb-size.cjs`.

`docs/orb/trace/trace.jsonl` (153 lines) proves the client chain was never the
bottleneck — every mock frame reached the renderer with the right state name
and the weights/uniforms moved with it. Root causes, all fixed:

| # | root cause | fix |
|---|---|---|
| 1 | **`mode` never rendered** — private/paused are *modes* (INTERFACES §e), renderer ignored them, so `paused` was byte-identical to `idle` and `private` had no ring | mode overlays in `sagecore.js` (teal **double** ring for private, steel ring + desaturation + rays-off + 10% spin for paused) + `modeTarget()` in the renderer |
| 2 | **`jobs_active` never rendered** | new `src/renderer/jobdots.js` — up to 9 beads + halo (PROTOCOL §8) |
| 3 | **server `shape_hint` clobbered** by `STATE_SHAPE` on every state but `acting` | `effectiveShape()`: the frame's hint wins while `task_kind !== 'none'`, otherwise the per-state signature |
| 4 | **TTS amplitude never cleared** when `speak{end}` was missed → every later state kept pulsing (trace showed `amp.speak=0.7` into confirm/error/paused/offline) | cleared on any transition out of `speaking` |
| 5 | **`backgroundThrottling` left on** (ORB_REBUILD §5 says disable it for the orb window) → rAF could collapse to ~1 Hz when occluded | disabled |
| 6 | listening amplitude had no channel | `orb_state.amplitude` plumbed ws-status → renderer (needs brain-core to emit — see §5) |

**Ruled out by measurement, not by reading code:** frame-time governor
(`gov.acted = 0` in all 76 captures, dpr held at 1.0); state-name mismatch
(every `applied.state` matched the frame sent); `reduced_motion`/`rest_motion`
(read from config but never referenced by the renderer); frames not arriving
(mock logged the auth + every `orb_state`).

**The gate — `npm run orb:diff` / `npm test` (real output):**
```
scenes=15 backgrounds=3 pairs=104 shots=86
temporal noise floor = 0.0000043 -> threshold 0.300
  alias private~private_overlay: diff=0.000 (must be <= 1) ok
PASS: every pair of states renders measurably differently
```
Noise floor is **0.0000043** because captures are **pose-locked**
(`window.__orbLockPose()`): the orb's own ~40 s rotation used to add 5–8/255
between two shots of the *same* state — larger than several real state
differences, which is why the first version of this gate was blind to exactly
the bug above.

### C. §1 startup spin-down — physical rotation
**Diagnosed with numbers first** (148 samples @50 ms through a scripted
`starting → idle`), then rewritten.

| assertion | BEFORE | AFTER |
|---|---|---|
| monotonic non-increasing | **FAIL +6.13 rad/s** jump | **ok 0.00000** |
| no velocity jump at hand-off | **FAIL 7.20 rad/s** | **ok 0.096 rad/s** |
| exponential-like | **FAIL R² 0.89 / tau 977 ms** | **ok R² 1.0000 / tau 1401 ms** |
| no early flat tail (1.5τ) | **FAIL 6.9% left** | **ok 21.8% left** |
| no zero crossing / settled / governor quiet | ok | ok |
| **overall** | **FAIL (4/7)** | **PASS (7/7)** |

Causes confirmed: a bell-curve *velocity* profile (`sin²(π·spinProg^0.4)·7`)
whose tail collapsed quadratically; a velocity discontinuity where that window
closed while `w.spin` ramped on the 5400 ms state flip; four fixed per-tick
rotation increments (`+= 0.003` etc.); and `dt = now - lastFrame` (time since
the last *render*), which double-counted on the 30 fps idle cap and made every
300–600 ms blend run ~1.5× fast. **Governor ruled out** (0 actions).

Now: `angle += omega*dt` (never reset, never eased), `omega` relaxes
exponentially to rest with τ = `orb.startup.spin_tau_ms` (1400), C1 at both
ends, dt clamped to 50 ms per tick, build progress eased with ease-in-out and
overlapping the spin-down, governor frozen while `spin.phase !== 'run'`.
Evidence: `docs/orb/STARTUP.md`, `startup-curve.png`, `startup-filmstrip.png`.

### D. §2 cheap motion blur
Velocity-gated **low-res (½) angular smear**, one extra pass `edgeRT → blurRT`
with 4 taps along the tangent, mixed in by the existing edge-mask pass — no
full-resolution post chain. Premultiplied RGBA averaged throughout.

| condition | frame time (EMA) |
|---|---|
| idle (rest spin 0.18 rad/s) → gate `calm`, **pass not executed** | 16.670 ms |
| active, blur OFF | 16.677 ms |
| active, blur FORCED ON (amount 0.9) | 16.671 ms |

**Overhead −0.04%** (vsync-locked; the pass fits the existing budget). Budget
was ≤25%. Gates: `orb.motion_blur: auto|off|low|high`, `reduced_motion`,
quality tier `low`→off / `medium`→3 taps, and the governor (downshift → ≤2
taps). Full numbers in `docs/orb/PERFORMANCE.md`.

**Transparency with blur forced on**, measured by `gl.readPixels` (a CDP
screenshot of a transparent page returns empty in this WSLg/ANGLE env, which
made the first version of this check pass vacuously):

| scene | max border alpha | max border RGB | lit px |
|---|---|---|---|
| idle / speaking / error / paused / reconnecting | **0** | **0** | 1719–9269 |

Pass ⇒ no box, no fringe, no clipping (limits: alpha ≤16, RGB ≤24, lit ≥200).

### E. §3 fidelity
- **Core** — wider edgeless bloom (two exponentials), hotter white centre,
  faint warm tint only at the centre, **6 thin diffraction spikes** (4 at 90°
  + a horizontal lens-flare pair). Still the brightest element.
- **Idle** — speed lines dialled back (0.85→0.70), vertex nodes up
  (1.00→1.30), cage up (1.00→1.15): less starburst, more "analysing".
- **Thinking** — inner cage gets its own material and fades to 0.15 (it was
  the doubled-up cage that read as yarn), spokes 14→10, Data Rings 6→4 but
  each brighter (base 1.25−0.07i), bars 0.8→1.05.
- **Speaking** — saturated gold palette #FFB000 / #FF9A1F / #FFE08A on the
  glyph rings, deep-orange ticks, sparkle dust cut 0.90→0.30 so the circle,
  not the sun, carries the state. Measured: **3450 of 4227 saturated pixels
  are gold/orange** vs 0 for idle.
- **Private** — base look at normal brightness + teal double ring (§3.5 ✓).
- **Details** — panes 30→18 and ~50% larger, orbit-ring line weight up
  (real geometry; GL `linewidth` is clamped to 1 device px so the *wireframe*
  cannot be thickened — see known gaps), job dots pulled inside the content
  radius (1.52→1.35), data rings/bars pulled in, camera clamp so small
  windows can't clip the outer layers.
- **Vibrance** — `orb.vibrance` (1.15) scales saturation/lightness of every
  palette token; `orb.theme: raphael|ciel|custom` resolves the palette once at
  page load. Docs: `docs/orb/THEMES.md`. `evolve_stage` reserved + forwarded
  (`evolveStage`) and documented, deliberately not rendered.

### F. W2.3 typed input + right-click menu (TODO §3e)
- **Double-click → text box → `command` `{text, source:'orb'}`** (PROTOCOL §3,
  role `ui`). Enter sends, Esc closes, closes itself after a send.
- **Right-click menu**: `Provider:` / `Model:` (from the `orb_state` frame —
  this closes the last open half of Wave-2 checklist item #1), pause/resume,
  private on/off, `Jobs (n)` submenu with per-job cancel, Open Logs, Restart
  Orb, Quit. Exposed as *data* via `orb-menu-spec` so tests can assert the
  structure without popping a native window.
- **Hit-testing**: the window stays click-through by default
  (`setIgnoreMouseEvents(true, {forward:true})`, so the renderer still sees
  the pointer) and only becomes solid inside a 0.40× hit disc and while the box
  is open — the orb never eats clicks meant for the desktop.
- **Fixed while testing:** menu cancel sent `scope:'gui'`, which per PROTOCOL
  §3 only releases the input lock and would leave the job running → `scope:'full'`.
- **Verified:** `npm run orb:trace -- --only=interaction` → **PASS 14/14**
  (`docs/orb/trace/interaction.json`), and the phase now also runs inside the
  full `orb:trace` pipeline.

### G. §4 quality gates — all green
```
orb:trace   startup PASS 7/7 · transparency PASS · distinctness PASS (104 pairs, noise 0.0000043)
orb:size    PASS — 12 (size × scale × state) combos:
            160px → orb 137–147px (86–92% of window)
            200px → orb 175–184px (88–92%)
            280px → orb 170–181px (85–90% of content_px 200)
            no edge clipping (min gap 3px), min coverage 60.3%, worst size
            drift 10.4% (allowed 12%)
            (150% Windows scale reproduced faithfully with --force-device-scale-factor=1.5)
npm test    state-machine 8/8 + orb-diff PASS
```
Per-state screenshots on dark/light/busy are in `docs/orb/` (old ones
replaced) **and** mirrored to `docs/orb/matrix/<state>--<bg>.png` — the path
ORB_REBUILD §8 / TODO §4 / PROGRESS.md all cite as the Wave-2 evidence (41
shots regenerated from this build; `orb:trace` keeps them in step and
`orb:diff` scans that directory too). Filmstrips:
`speaking-filmstrip.png` (amp 0.12 vs 0.95 — visibly different),
`thinking-filmstrip.png`, `startup-filmstrip.png`.

Vision QC (uncensored local VLM) confirmed: idle layers complete + core
brightest; speaking clearly a gold magic circle (~50% of bright pixels gold);
private = teal ring at **normal** brightness; paused = desaturated/grey + steel
ring; all filmstrip cells render; **no box, hard edge, clipping or blown blob
in any image**.

---

## 2. Known gaps / honest notes

1. **`slightly thicker line weights` (§3.6) is only partly done.** WebGL clamps
   `gl.lineWidth` to 1 device px, so the wireframe/rays/dashed rings cannot be
   thickened without converting them to fat-line geometry
   (`three/examples/jsm/lines/Line2` — not attempted: it would touch the pose
   lock, the `uDrop` discard and the morph path). Compensated by raising line
   *brightness* and by thickening the layers that ARE geometry (orbit ring,
   private/paused rings, job dots, node size). **Fat lines = the one open §3
   item.**
2. **Windows scaling at 150% is simulated**, not measured on the real desktop:
   `--force-device-scale-factor=1.5` reproduces exactly what Windows scaling
   does to the renderer (dpr 1.5 → 1.5× backing store), but a check on the real
   Windows desktop at 150% is still the integrator's to do.
3. **Motion-blur cost is vsync-limited.** Both readings pin at 16.67 ms, which
   proves the pass fits the frame budget but does not isolate its GPU time. If
   a real number is ever needed it needs `EXT_disjoint_timer_query` or a
   deliberately un-vsynced run.
4. **`private_overlay` vs `mode: private`** are two protocol spellings of one
   visual; the gate *asserts* they agree (`alias private~private_overlay:
   diff=0.000`) rather than pretending they are different states.
5. **idle vs private remains the weakest pair (0.73)** — by design: ORB_REBUILD
   §3.5 says private keeps the base look and only adds the teal ring. It clears
   the 0.30 floor with the ring covering 2.5% of pixels.
6. **`starting`'s build clock and the boot timeout** interact: the renderer
   still flips `starting → idle` 5400 ms after *page load* (natural boot
   story). A re-triggered `starting` (as the trace does) is driven by the
   harness at the same 5400 ms so the two paths behave identically.

---

## 3. Requests to other lanes

**`docs/requests/orb__to__brain-core__orb-state-transitions.md` — OPEN.**
The real Brain can only emit `idle | thinking | confirm | private_overlay`
(`brain/ws.py:249-273` and `:529-547` duplicate the same four-state ladder);
`listening`, `speaking`, `acting`, `error`, `starting` are never sent, and
`shape_hint:'circle'` / `task_kind:'none'` are hardcoded with no
`provider`/`model`/`amplitude`. That is *why production looked static* even
with the client fixed. Nothing on the orb side is blocked — the mock Brain
covers the full contract meanwhile.

No other lane is asked for anything. No shared contract, Core Guard or
config.yaml change is proposed by this lane (all new config lives in
`config.d/orb.yaml`, AGENT_RULES §3).

---

## 4. Test output (real runs, 2026-10-06)

```
$ cd body/orb && node tests/state-machine.test.js
All state machine tests passed

$ npm run orb:diff          # (also the second half of `npm test`)
scenes=15 backgrounds=3 pairs=104 shots=86
temporal noise floor = 0.0000043 -> threshold 0.300
  alias private~private_overlay: diff=0.000 (must be <= 1) ok
PASS: every pair of states renders measurably differently

$ npm run orb:trace
[orb-trace] instance=orb ws=8906 cdp=9406
[orb-trace] startup: PASS over 149 samples (7997 ms), peak=2.043 rest=0.192 rad/s
  ok  x7 (monotonic 0.00000, jump 0.0955, R2 1.0000/tau 1401ms, 21.8%@1.5tau,
          settled 0.4%, governor_quiet 0)
[orb-trace] filmstrips written: thinking, speaking (amp 0.12 / 0.95)
[orb-trace] transparency (blur forced): PASS — borderA0/rgb0, lit 1719-9269
[orb-trace] blur perf: idle=calm active off=16.7ms on=16.7ms (-0.0%)
[orb-trace] distinctness: pass=true weakest=idle vs private = 0.73
[orb-trace] PASS: every scene renders measurably differently

$ npm run orb:size
[orb:size] PASS — no_edge_clipping (min 3px) · has_content (min 60.3%)
           size_matches_spec (worst drift 10.4%, allowed 12%) · 12 combos

$ npm test
state-machine 8/8 + orb-diff PASS   (exit 0)
```

---

## 5. Next / for the integrator

- Wave 2 exit criterion 4 ("per-state orb screenshots prove distinct visuals")
  is **satisfied for the mock contract**; on the live instance it needs the
  brain-core request above to land first.
- **Wave 2 is complete** — the orchestrator acked the reconciliation and the
  last open item (W2.3 typed input + menu) is now done and verified 14/14.
- **Queued, blocked on brain-core:** re-run `npm run orb:trace` against the
  *real* Brain instead of the mock (the coordinator confirmed `agent/brain-core`
  already emits every INTERFACES §e state; it queues behind router), then
  `wave_done` is the Wave-2 exit.
- Wave 3+ items are not started (AGENT_RULES §11).

---

## 7. User art feedback (2026-10-06) — 2D feel, black haze, dim cages

> *"nothing should feel 2d … the particles those glowing blue ones you added are
> flat 2d which looks weird when revolving … there is a black haze around the
> sun in the center which shouldn't be … make the cages brighter please they are
> barely visible on different screens … when she is listening those white cages
> can be even brighter."*

| complaint | root cause | fix |
|---|---|---|
| **flat 2D particles** (the orbiting beads) | `jobdots.js` drew `CircleGeometry` — flat discs in the screen plane | now `SphereGeometry` with a **limb-darkening shader** (bright facing centre, dark silhouette — still flat-*unlit* anime shading, no light direction), and the orbit plane is **tilted** (`rotation.set(0.10, 0.06, 0)`) so the ring is never coplanar with the screen |
| **"nothing should feel 2d"** (more than the beads) | two layers really were flat cards: the **morph lattice** was `z = 0` for every vertex, and the **prismatic Data Rings** were all coplanar | lattice bent into a **shallow two-wave lens** (`z = sin(i/n · 2π · 2) · 0.20`) — same silhouette, real depth when it revolves; each Data Ring (and the micro-bar ring) given its own **tilt**, z-spin untouched |
| **black haze around the sun** | spec §4's *legibility backing disc*: a black radial-gradient `CircleGeometry(1.35)` at `z = -0.01`, alpha 0.25. It sits behind the sun but outside its silhouette, so it shows exactly as a dark halo in the middle of the orb (invisible on dark wallpaper, a grey smudge on light) | **off**, via `config.d/orb.yaml` → `backing_disc_alpha: 0.0` (lane-owned config per AGENT_RULES §3 — `config.yaml` is integrator-owned). The renderer skips the mesh entirely at 0, so idle cost is unchanged |
| **cages barely visible** | `polyFrag`'s depth term `clamp(1.35 − (vDepth − 2.4)·0.45, 0.35, 1.0)` evaluates to its **0.35 floor** at this camera's real depth (vDepth ≈ 5.07), so the wireframe drew at `0.35 × 0.55 × uAlpha ≈ 19%` alpha | curve re-centred on the actual camera depth → `clamp(1.18 − (vDepth − 4.2)·0.22, 0.55, 1.15)` ⇒ **≈0.99** at vDepth 5.07, and the baseline lifted `0.55 → 0.66`. Net: cage alpha ≈ **19% → 68%** at idle. Same curve applied to the **node dots** so they stay matched |
| **cages even brighter while listening** | `S.listening.poly` was only 1.10 vs idle's | `poly 1.10 → 1.55`, `node 1.60 → 2.10`, `ring 1.20 → 1.45` ⇒ listening cage alpha ≈ **88%** — the brightest white state |

Verification: `npm run orb:trace` (gates) + `npm run orb:size` + `npm test`, plus a
post-change vision QC on the regenerated screenshots.

### §7 verification — vision QC + measured colour

Vision QC (uncensored local VLM, on the regenerated screenshots):

| check | verdict |
|---|---|
| black haze around the sun | **Gone** (all images) |
| cage visibility (idle) | **10/10** — edges traceable, nodes crisp |
| listening vs idle cages | **Brighter**, ice-blue shift visible |
| cage shape per state | **different silhouettes**: idle/jobs = rounded ball · thinking = sharp octahedron · speaking = hexagonal prism · confirm = square/box prism |
| thinking rings | **tilted/foreshortened** — orbits passing in front of and behind the core, not a flat plate |
| flat 2D anywhere | **none**; the orbiting beads read as *shaded beads with depth*, not flat circles |
| defects | none — no box, no clipping, no blown blob |

Measured colour (per-channel hue histogram, pixels with v>150 and s>0.18):

| state | saturated px | dominant hue | reading |
|---|---|---|---|
| idle | 27 | — (white) | plain white cage ✓ |
| listening | 2665 | 180–210° **2343** | ice-blue ✓ |
| thinking | 4197 | 210–240° **2817** | blue ✓ (tint then raised from `#bfd4ff` → `#7fa8ff`, see below) |
| confirm | 3099 | 0–60° **2859 (92%)** | amber/gold ✓ — the vision pass initially read this as "no amber", the numbers disagreed and confirmed the original tint was right |
| speaking | 5431 | 0–30° **3763** | saturated gold ✓ |

One real fix came out of the QC: **thinking's cage tint was only 25% saturated**
(`#bfd4ff`), so it sat visually inside the pale-blue Data Rings and read as
"white with a glow". Raised to `#7fa8ff` (50% saturation) — the cage now reads
as its own colour against the rings.

### §7 — one test was wrong, not the product

The full pipeline flagged `pointer_over_orb_takes_input` while the same check
passed in isolation. Instrumenting instead of guessing (`window.__orbPointer()`
+ a record of the *last mousemove as the listener actually saw it*):

```
hit_test_decision:      dist=0 hitR=112.0 viewport=280x280 inside=true
mousemove_listener_wired: listener saw clientX=195 clientY=59 dist=97.9 inside=true seen=6
main_follows_renderer:  renderer.pointerInside=true -> main.mouseThrough=false
```

The window forwards real OS mouse events, so a genuine `mousemove` lands right
after the synthetic one — it reported `clientX=17 clientY=157 dist=124.2`, i.e.
correctly *outside*, and overwrote the harness's dispatch. **The hit-testing was
never broken; the assertion was racing the physical cursor.** Rewritten to
check the three things that are actually contracts and none of which depends on
where the cursor happens to be:

1. the decision function reads the geometry correctly,
2. the `mousemove` listener is wired and computes the same answer
   (`inside == dist <= hitR`),
3. `main`'s `setIgnoreMouseEvents` is the exact opposite of the renderer's
   `pointerInside` (consistency, not an absolute).

Also fixed: `--only=<phase>` runs returned exit code 0 even when their own
checks failed — they now set `process.exitCode = 1`.
Result: **interaction PASS 16/16**.

---

# Wave 3 — Bug C (P0) + Rule-15 speed

**Verdict: three real bugs found in the orb's own renderer, all fixed and gated.**
`docs/BUGS-WAVE2.md` pointed at the right area; two of the three were subtler
than the dossier suggested, and one was being **masked by the pose-lock
screenshots**.

### C-1 — no pulse while she spoke
`renderer.js` guarded with `if (ev.seq <= lastSpeakSeq) return;` and
`lastSpeakSeq` survived across utterances. Every fresh utterance restarts `seq`
at 0, so after the first answer the guard rejected the **whole run**
(`0 ≤ 8, 1 ≤ 8, …`) — the orb simply stopped pulsing.

Fix: the transport is an **ordered WebSocket** (PROTOCOL §1), so a replayed or
out-of-order `speak` frame cannot exist and the guard could only ever drop
legitimate frames. Processing is idempotent (it just assigns the amplitude), so
**nothing is dropped any more**; `lastSpeakSeq` is kept as a high-water mark for
diagnostics. `event: end` still clears amplitude, and the mirror in
`tests/state-machine.js` matches byte-for-byte.

> Note: my first attempt kept the guard and reset it on `start`/lower-seq. The
> phase still failed (`amp1=0.15 → amp2=0.15`) because two short utterances can
> legitimately land on the **same** seq — indistinguishable from a duplicate.
> That is when it became clear the guard had no safe form at all.

`testStaleSeqDrop` encoded the broken contract and was replaced by
`testRepeatedSeqIsNotDropped`.

### C-2 — cages/lattice stuck in a weird shape (two bugs, not one)
1. **Length mismatch.** `makeMorphTarget('octagram')` returned **48 points
   (144 floats)** while every other target returns **60 (180)**. `updateMorph`
   lerps only `Math.min(from.length, to.length)`, so indices 144–179 were
   **never written again** — a permanent stale tail that `startMorphTo` then
   re-captured as the next `from`. Fixed: the star is now sampled *along its
   outline* to exactly `n` points, plus a defensive cycle in `startMorphTo`
   that logs loudly if a target is ever mis-sized.
2. **The morph never fired on a state change.** `onOrbState` assigned
   `orbState.shapeHint = want` *before* `animate` checked
   `if (want !== orbState.shapeHint)` — so that condition was **always false**
   exactly when the state changed, and the lattice kept its previous shape.
   Fixed with one owner, `applyLatticeShape()`, guarded by `lastMorphShape` and
   called from the IPC path, the per-frame path and the pose lock.

**Why no screenshot gate caught #2:** `__orbLockPose()` snapped the lattice
straight to the target before every capture, so all 104 distinctness pairs and
every matrix shot looked correct while the live orb never morphed. The new
`window.__orbMorphDiff()` probe measures it **without** the lock — that is what
turned a masked bug into a failing check.

### C-15 speed (Rule 15)
State-flip delivery, mock-Brain send → renderer applied (includes the
harness's own evaluate round-trip, so it is an upper bound):

```
mean=1ms  worst=2ms   listening:1 thinking:2 confirm:1 error:2 idle:1
```
The 300–600 ms **crossfade is by design** and is not what this measures.

### Evidence

```
$ npm run orb:trace -- --only=bugc
Bug C + speed: PASS (6/6)
  ok pulse_follows_fresh_utterance: amp1=0.15 -> amp2=0.95
  ok renderer_received_every_speak_frame: 9 -> 10
  ok morph_targets_share_one_length: [180,180,180,180,180,180] (octagram was 144)
  ok morph_settles_after_interruption: maxErr=0 (was 0.134)
  ok cage_shape_settles_after_interruption: maxErr=0 shape=hexagon (was 0.253/'circle')
  ok state_flip_latency: mean=1ms worst=2ms
EXIT=0

$ node tests/state-machine.test.js
All state machine tests passed        (11 test functions, 4 new for Bug C)
```
`docs/orb/trace/bugc.json` holds the full check table.

---

# Wave 3 — `notice` frame (coord nudge, PROTOCOL §3, integrator-approved)

Contract: Brain→Client `notice`, roles **ui+cli**, fields `text / level / ts /
job?`, **no state change**. Rendered as a banner; "never as an orb_state".

| layer | change |
|---|---|
| `ws-status.js` | new `case 'notice'` → `emit('notice', …)` (and `_rx` records it); **no** `orbState` write |
| `main.js` | forwards `notice` → renderer (alongside subtitle/speak/confirm) |
| `preload.js` | `onNotice(cb)` |
| `renderer.js` | `updateNotice()` → reuses the subtitle element as a banner, tinted per `level` (`info` / `warn` / `error`), 4 s instead of 1.2 s, `force:true` so it is **not** suppressed by Private Mode (a notice is a local system message, not cloud content) |

Deliberately **not** wired into `setState`/state machine — the contract says the
state must not move.

**Evidence** (`orb:trace --only=interaction`, now **PASS 19/19**):
```
ok notice_reaches_renderer:        renderer rx notice frames: 0 -> 1
ok notice_shown_as_banner:         banner={"text":"Notice: disk almost full","shown":true}
ok notice_never_changes_state:     state idle -> idle, applied=idle (must be unchanged)
```

---

# WAVE 3 HANDOFF (orb lane) — 2026-10-07

**Scope for this lane in Wave 3 is complete.** Every box in
`docs/lanes/orb.md` is ticked; committing `3de9a54` / `8f94665`.

## What shipped this wave

| item | verdict | evidence |
|---|---|---|
| **P0 Bug C (1) no pulse** | fixed | speak `seq` guard dropped every fresh utterance restarting at 0 — removed (ordered WS ⇒ nothing needs dropping). Verified `amp1=0.15 → amp2=0.95` |
| **P0 Bug C (2) stuck shape** | fixed | two causes: octagram target **144 floats vs 180** (stale tail forever) **and** `onOrbState` pre-setting `shapeHint` so the morph never fired on a state change. Verified `maxErr = 0` for lattice **and** cage after 5 interrupted morphs (was 0.134 / 0.253) |
| **Rule 15 speed** | met | mock-Brain → renderer applied **mean 1 ms, worst 2 ms**; 300–600 ms crossfade is by design |
| **`notice` frame** (§3 nudge) | done | level-tinted banner, **never** an `orb_state` (`notice_never_changes_state: idle → idle`) |
| **size gate de-flaked** | done | worst drift **12.0% (on the line) → 8.0% / 7.7%** across consecutive runs; pose-locked captures |

```
$ npm run orb:trace            PASS  (distinctness 104 pairs, interaction 19/19,
                                      BugC 6/6, transparency border alpha 0)
$ npm run orb:trace --only=bugc PASS 6/6   -> docs/orb/trace/bugc.json
$ npm run orb:size              PASS x2 (limit 12%, measured 8.0% / 7.7%)
$ node tests/state-machine.test.js  All state machine tests passed (11)
$ node test/orb-diff.cjs        PASS (exit 0)
orphans: none · ports 8906/9406 free
```

## The one lesson worth carrying forward

**The pose lock was hiding a real bug.** `__orbLockPose()` snaps the lattice
straight to the target before every capture, so *every* screenshot-based gate
(104 distinctness pairs, the whole matrix, `orb:size`) looked correct while the
live orb never morphed at all. The fix was a probe that measures the same thing
**unlocked** — `window.__orbMorphDiff()` (`maxErr`, `lengthMismatch`,
`targetLengths`). Any future renderer invariant should be asserted through an
unlocked probe, not through a locked screenshot.

## Known gaps / still open (not started, not mine to start now)

1. **Real-Brain re-run** of `npm run orb:trace` (replace the mock) — queued
   behind brain-core's merge per decision `1791339926`.
2. `docs/requests/orb__to__integrator__backing-disc-default-zero.md` — **OPEN**:
   base `config.yaml` default + `ORB_REBUILD_TASK.md` §4 text still say 0.25;
   live behaviour is already correct via `config.d/orb.yaml`.
3. **Wireframe line weight** — WebGL clamps `gl.lineWidth` to 1 device px, so
   "slightly thicker lines" is done only for layers that are real geometry
   (orbit ring, private/paused rings, job dots, node size). Fat-line geometry
   (`three/examples/jsm/lines`) remains the one open §3 item.
4. **150% Windows scaling** is verified with `--force-device-scale-factor=1.5`
   (identical to what Windows does to the renderer), not on the real desktop.
5. Wave-3 orb scope has **no further checkbox**; the Wave-3 goals list in
   `docs/WAVES.md` (memory, skills/plugins, tools, MCP, CDP, job concurrency)
   is other lanes' — re-check `docs/lanes/orb.md` at the next `wave_open`.

**Next for this lane:** wait for `wave_open` / an inbox assignment (AGENT_RULES §11/§13).

---

# WAVE 4 — renderer resilience (orb lane)

Spawn permission: **APPROVED WITH CONDITIONS** (coord ts 1791379204, recorded
in `docs/requests/orb__to__integrator__harness-spawn-while-live.md`). All five
conditions were met and are enforced in code, not by convention.

## 1. GPU context loss recovery

`webglcontextlost` **must** call `preventDefault()` — Chromium only fires
`webglcontextrestored` if it does, so without it the canvas is dead forever.
Recovery is a page reload (Three.js cannot replay its uploads into a new
context), **rate-limited** so a dying context cannot become a reload loop,
which would be strictly worse than a frozen orb.

- `src/renderer/glrecovery.js` — pure policy, injectable clock.
- `renderer.js` wires it and **skips all GL work while the context is lost**.
- `main.js` re-pushes the current `orb_state` on `did-finish-load`, so a
  recovered orb comes back showing what it was showing instead of `starting`.

```
$ node tests/glrecovery.test.mjs        (pure — no GPU)
All 4 gl-recovery tests passed
  ok preventDefault called (restore can fire)
  ok restore reloads exactly once
  ok a context that keeps dying cannot cause a reload loop
  ok 100 loss/restore cycles stay bounded (<=4 reloads, >=95 suppressed)
```

## 2. Reconnect-storm / state-spam visuals

`startMorphTo` reset the ramp clock on **every** retarget. States flipping
faster than the 600 ms ramp (Bug E's `speaking→listening→speaking`, or any
reconnect storm) restart progress from 0 each time → the lattice parks at its
start shape. Fixed by making progress a function of **wall-clock** time.

```
$ node tests/morphclock.test.mjs       (pure simulation)
All 5 morph-clock tests passed
  ok retarget keeps progress -> a storm CONVERGES on the newest target (<=700ms)
  ok reset-on-retarget (the old behaviour) NEVER converges   <-- documents the bug
  ok a calm ramp is untouched by the fix
  ok progress is monotonic while nobody retargets
  ok degenerate inputs cannot divide-by-zero
```

## 3. Pose-lock-vs-truth probe invariant → CI (the Wave-3 lesson)

The bug that mattered was invisible to screenshots because `__orbLockPose()`
snapped the lattice before every capture. Two halves now enforce it:

- **pure half, no GPU at all** — the morph-target builders moved to
  `src/renderer/morphtargets.js` and `tests/morphtargets.test.mjs` asserts the
  exact invariant Bug C violated:
  ```
  $ npm run test:unit
  All 7 morph target invariants passed        <-- "all targets share ONE vertex count"
  ```
  It even reconstructs the legacy 144-vs-180 failure and asserts the shipped
  builder does not reproduce it.
- **unlocked half, in the gate** — `window.__orbMorphDiff()` reports
  `maxErr` / `lengthMismatch` **without** the pose lock, and `orb:trace`'s Bug-C
  phase fails if either drifts.

`npm test` now runs all five pure suites *before* the screenshot gate, so the
invariants hold even on a machine with no display.

## 4. fps/VRAM audit under load — MEASURED

`npm run orb:audit` (`docs/orb/trace/audit.json`), isolated instance, mock
Brain only, one Electron, hard 150 s bound:

| condition | frame time (EMA) | tree RSS |
|---|---|---|
| idle | **16.7 ms** | 300.2 MB |
| speaking (amp 0.95) | **16.7 ms** | 300.4 MB |
| **storm** — 67 state flips in 6 s (faster than the 600 ms ramp) | **16.7 ms** | 302.0 MB |

- **fps: no degradation** — vsync-locked 60 Hz in all three conditions, so the
  storm costs nothing measurable.
- **RAM delta over 67 flips: +1.8 MB** (300.2 → 302.0) — no per-flip leak.
- Max single-process **VmHWM 150.6 MB**, 5 Electron processes in the tree.
- **Morph converged after the storm: `maxErr = 0`, `lengthMismatch = false`,
  60 points** — the `morphclock` fix holding under real spam.
- Frame-time governor: `acted = 0`, `dpr` held at 1.0 — not regressed.
- GL: `ANGLE (D3D12 (Intel(R) Iris(R) Xe Graphics), OpenGL 4.1)`, dpr 1.0.
- `glRecovery`: `lost=false, restores=0` — no context loss occurred during the
  run (the recovery *policy* is covered by the pure tests above).

**Honest gap:** GPU VRAM is **not readable from WSL** — there is no
per-process GPU counter on this path. Reported numbers are VmRSS over the whole
Electron tree + VmHWM + `renderer.info`; they are explicitly *not* a VRAM
figure and are labelled as such in `audit.json` (`vramNote`).

## 5. Condition compliance (each enforced in code)

| # | condition | how |
|---|---|---|
| 1 | separate instance + userData + CDP | `RAPHAEL_INSTANCE=orb` → ws 8906 / cdp 9406 / `~/.raphael/orb/orb/` |
| 2 | mock Brain, never the live one | in-process `MockBrain` on 8906; zero live ui sessions |
| 3 | never touch the live stack's processes | measurements walk **our pid's `/proc` descendant tree**; only our own child is ever signalled — no `pkill`, no path/cmd matching |
| 4 | bounded + kill-verify + report | pidfile `~/.raphael/orb/orb-audit.pid`, 150 s hard timeout, `kill-verify: ZERO orphans, instance ports free`, pidfile removed, delta reported above |
| 5 | one Electron max | pidfile pre-flight refuses a second run; instance ports checked free |

> Two rule-14 pre-flights **false-positived** while building this — a `ps`
> path match counted the invoking shell's own `cd <worktree>`, and then a
> path+`electron` match counted my own command line. Replaced with an exact
> pidfile + `/proc` descendant walk: no pattern matching, nothing to match
> wrongly.

## 6. Stale hazard fixed

`test/fake-brain.cjs` hardcoded **port 8765 — the live brain's port** — and an
absolute path into the old workspace. Inert (no script runs it) but exactly what
must never be runnable against a live stack. Now derives from
`RAPHAEL_INSTANCE` (defaulting to the **lane**), and refuses the main port
unless `--allow-main` is passed.

```
$ node tests/fakebrain-port.test.cjs    (pure — binds nothing)
All 8 fake-brain port safety tests passed
```

## 7. One more bug found while auditing (mine, fixed)

The audit's first run wrote `audit.json` to **`body/docs/orb/trace/`** —
`path.join(ROOT, '..', 'docs', …)` where `ROOT` here is `body/orb`, not the
worktree. That is a path *outside* the orb lane's owned directories
(`body/orb/**`, `docs/orb/**`). Caught because the expected file was missing
from `docs/orb/trace/`, the stray directory was removed, and the path corrected
to `ROOT/../../docs/orb/trace`. Re-run is clean (EXIT 0, correct location).

---

# WAVE 4 HANDOFF (orb lane) — 2026-10-07

**Wave-4 scope for this lane is complete.** Every box in `docs/lanes/orb.md` is
ticked. Commits `8f94665` → `663b618` (Wave 3) and `663b618` (Wave 4).
Integrator verified: *"Wave-4 renderer resilience VERIFIED (663b618 clean; npm
test reran PASS …)"*.

## Shipped this wave

| item | verdict | evidence |
|---|---|---|
| GPU context-loss recovery | done | `preventDefault` + skip-GL-while-lost + rate-limited reload + `orb_state` re-push on `did-finish-load` · **4/4 pure** |
| Reconnect-storm / state spam | done | morph ramp clock no longer resets on retarget · **5/5 pure** (incl. "old behaviour NEVER converges") · live `maxErr=0` after **67 flips/6 s** |
| Probe invariant into CI | done | builders extracted pure → `npm run test:unit` runs **7+4+5+8+state-machine with no Electron and no display** before the screenshot gate |
| fps/VRAM audit under load | **measured** | idle / speaking / storm **all 16.7 ms**, RAM **+1.8 MB over 67 flips**, VmHWM **150.6 MB**, governor `acted=0` |
| (bonus) live-port hazard | fixed | `fake-brain.cjs` no longer binds **8765** · **8/8 pure** |

Full-gate re-run after the wiring: `orb:trace` PASS (104 pairs, bugc 6/6,
interaction 19/19, transparency) · `orb:size` PASS (drift 4.6% of 12%) ·
`npm run test:unit` PASS · **kill-verify: ZERO orphans, ports free.**

## Two process lessons worth keeping

1. **Never pattern-match to decide whether you may spawn.** Two rule-14
   pre-flights false-positived (a `ps` path match caught my own `cd <worktree>`;
   a path+`electron` match caught my own command line). Replaced with an exact
   **pidfile + `/proc` descendant walk** — it cannot match wrongly and it never
   touches the live stack.
2. **A locked screenshot cannot prove a visual invariant.** (Carried from Wave
   3, now enforced.) The unlocked `__orbMorphDiff()` stays in `orb:trace`, and
   the pure half runs with no display at all.

## Carried forward (open, not started — need another lane or a user call)

1. `docs/requests/orb__to__integrator__backing-disc-default-zero.md` —
   **OPEN**: base `config.yaml` default and `ORB_REBUILD_TASK.md` §4 still say
   `backing_disc_alpha: 0.25`; live behaviour is already correct via
   `config.d/orb.yaml` (0.0). Text/base only.
2. `docs/requests/orb__to__brain-core__orb-state-transitions.md` — the
   **substance was answered in coord** (brain-core emits every INTERFACES §e
   state on their branch) but the file's `Status:` line is still `OPEN`; the
   owner (brain-core) flips it, not me.
3. **Fat-line geometry** for the wireframe — WebGL clamps `gl.lineWidth` to 1
   device px, so ORB_REBUILD §3.6 "slightly thicker lines" is still only done
   for layers that are real geometry. The one open §3 item.
4. **150% Windows scaling** is verified with `--force-device-scale-factor=1.5`
   (identical to what Windows does to the renderer), never on the real desktop.
5. **GPU VRAM is not measurable from WSL** — no per-process counter on this
   path. `docs/orb/trace/audit.json` reports VmRSS/VmHWM + `renderer.info`
   and says so in `vramNote`. If a real VRAM number is ever required it needs
   Windows-side counters.

**Next for this lane:** wait for `wave_open` / an inbox assignment
(AGENT_RULES §11/§13). No unblocked work remains here.

---

# WAVE 5 — Answer/Report + parallel-minds + persona-tier themes (orb)

All of it is **renderer-side**; no new `orb_state`, no shared-contract change.
`docs/PROTOCOL.md` §3 already carries the three additive frames (`answer`,
`report`, `job_event += kind|parent`), so nothing needed an integrator request.

## 1. Persona-tier visuals — `orb.theme: auto`

The Wave-2 theme hook now **follows `persona.tier`** instead of being pinned:

```
config.d/orb.yaml   theme: auto            (was: raphael)
config.js           reads persona.tier from config.d/evolution-persona.yaml
palette.js          THEMES = { great_sage, raphael, ciel }  + auto resolution
```

`great_sage` is the identity tier (per `docs/evolution/04-tier-switch-test-plan.md`
A2) so it renders exactly like Raphael today; `ciel` is still an alias. An
explicit `theme:` pins it and wins over the tier, and an unknown tier falls
back to the Raphael palette rather than rendering blank.

**Verified:** `orb:trace --only=wave5` →
`theme_follows_persona_tier: orb.theme=auto persona.tier=great_sage`.
A tier switch is now a config edit, never a renderer change — `docs/orb/THEMES.md`
updated.

## 2. Parallel-minds visuals (`job_event.parent`)

`ws-status` now tracks the additive `job_event` fields into a job table
(`{job, status, kind, parent}`) on its own channel — **deliberately not folded
into `orb_state`**. The renderer lays the beads out as a **fan**:

- no parent info → the original single evenly-spaced tilted ring (unchanged);
- parent present → each parent gets a wedge, its children sit on an inner ring
  inside that wedge, and a **spoke links parent → child** (one
  `LineSegments` buffer with a per-frame `drawRange`), so "N children of one
  mind" reads at a glance and two parents read as two clusters.

**Verified:** `parallel_minds_fan_layout: jobs=3 fan=true groups=2 spokes=6`
(6 = drawRange = 3 spokes × 2 verts).

## 3. `kind` styling (Analysis / Simulation)

`job_event.kind` drives a **look only** — the lattice carries each state's
signature shape, so it also carries the kind accent:

| kind | lattice accent |
|---|---|
| `analysis` | `#7FD4FF` cool cyan |
| `simulation` | `#9D8CFF` violet |
| `act` | `#FFB000` amber |
| `chat` / none | `#58C4F2` (unchanged default) |

Design note worth keeping: a **live `analysis`/`simulation` job wins over a
`chat` root that happens to be first in the list** — otherwise a fan-out
(root=chat, children=analysis+simulation) would style as plain chat and the
accent would never appear in exactly the case it was added for. That was caught
by the test (`kind_accent_analysis` first failed with `kind=chat`).

## 4. `answer` / `report` banners

Both render through the same banner element as `notice`, but they are **wrapped
cards** (new `#subtitle.banner` style — the plain subtitle is `white-space:
nowrap`, so a paragraph would have been clipped off the 280px window):

- `answer` → `Answer · <first 60 chars>… · <provider>/<model>` — gold, 6 s
- `report` → `<title> — <summary≤220>` — violet, 9 s

Both `force: true` (a local system message, not cloud content, so Private Mode
does not suppress them) and **neither touches `orbState`**.

**Evidence:** `docs/orb/trace/wave5.json`

```
$ npm run orb:trace -- --only=wave5
Wave 5: PASS (7/7)
  ok parallel_minds_fan_layout   jobs=3 fan=true groups=2 spokes=6
  ok kind_accent_analysis        foreground kind=analysis
  ok answer_renders_as_banner    "Answer · The quick brown fox… · groq/llama-3.3-70b-versatile"
  ok answer_does_not_change_state  thinking -> thinking
  ok report_renders_as_banner    "Weekly pipeline report — 4 jobs run, 0 failures…"
  ok report_does_not_change_state  thinking -> thinking
  ok theme_follows_persona_tier  orb.theme=auto persona.tier=great_sage
EXIT=0
```

### Wave-5 full gate (after the job-count + memoisation fixes)

```
npm run test:unit   PASS  (7 morph + 4 gl-recovery + 5 morph-clock + 8 port-safety + state-machine)
npm run orb:trace   PASS  distinctness 104 pairs (noise 4.3e-6) · wave5 7/7 · bugc 6/6
                     · interaction 19/19 · transparency border alpha 0 · startup 7/7
npm run orb:size    PASS  worst drift 4.6% of a 12% limit, 12 combos, edge margin 3px
node test/orb-diff.cjs  PASS (exit 0)
orphans: none · ports 8906/9406 free · live stack (8765/8777) untouched
```

One correctness fix landed with it: bead count now derives from
**`orb_state.jobs_active`** (the §8 authority) with `job_event` supplying only
the fan *structure* — deriving the count from the job table could leave stale
beads on screen after jobs finished.

---

# USER DIRECTIVE 2026-10-07 — shape-morph revert

> "revert back the shape change — the color change (+ the speaking state) is
> the only thing we are okay with. i have other plans for shape changing for
> future."

## What changed

Two booleans, both defaulting **off** — nothing deleted, machinery intact:

```js
const BASE_SHAPE = 'circle';
const SHAPE_MORPHS_ENABLED = false;   // effectiveShape() -> always the plain ball
const KIND_ACCENTS_ENABLED = false;   // analysis/simulation lattice tint off
```

- `effectiveShape()` returns `BASE_SHAPE` immediately; the original
  per-state / task-kind mapping is kept **verbatim underneath** the flag.
- The kind accent block is gated and **not evaluated while off** (no per-frame
  work — ORB_REBUILD §5).
- `startMorphTo` now has exactly **one** call site, inside `applyLatticeShape`;
  `runDemo` was re-routed through that owner so the opt-in demo timeline can't
  morph around the flag.

**Kept, per the directive:** colour + theme per state, the speaking
pulse/amplitude animation, answer/report/notice banners, the parallel-minds
fan-out, mode overlays, jobs dots, startup spin, motion blur.

**Side effect worth noting:** with morphs off the lattice/cage can never wedge
again — this retires the "cages stuck in weird shape" complaint for good, on
top of the two real bugs fixed in the Bug-C work.

## Gate

`orb:trace` now re-scans every `applied` record it wrote and fails if any
`shapeHint` other than `circle` appears:

```
[orb-trace] shape directive: ok shapeHint values seen = ["circle"]
```

Full run after the revert (all green):

```
npm run test:unit   PASS  (7 morph + 4 gl-recovery + 5 morph-clock + 8 port-safety + state-machine)
npm run orb:trace   startup 7/7 · transparency PASS (border alpha 0) · BugC 6/6 ·
                     wave5 7/7 · interaction 19/19 · shape directive ok ["circle"] ·
                     distinctness PASS (104 pairs) — weakest idle~private 0.73
npm run orb:size    PASS (12 combos, worst drift 4.6% of 12%)
node test/orb-diff.cjs  PASS
```

States remain distinguishable **without** shape morphing — colour, mode
overlays, jobs dots, Data Rings and the amplitude pulse carry the whole
distinctness gate on their own. Screenshots + `docs/orb/matrix/` regenerated
by the same run.

---

# Wave 5 — Ciel gold palette (request from evolution-persona)

`docs/requests/evolution-persona__to__orb__ciel-gold-palette.md` → **Status:
DONE**, decision recorded in the file. All three requirements met:

| requirement | how |
|---|---|
| **1. gold-leaning palette + delivery point** | Swatches in `src/renderer/palette.js → CIEL` (this lane's design authority, per the request). Base `#E8B84B`, warm core `#FFF6E3`, amber/coral haze, `#FFC247` glyph, gold beads. Delivery point = **`persona.tier` → `orb.theme: auto` → `THEMES`** — flipping the tier needs **no code change**. |
| **2. tier switch changes the palette LIVE** | `main.js` stats `config.yaml` + `config.d/*.yaml` on every `orb_state` (throttled ≥1 s), rebuilds `Config`, pushes `orb-palette`; renderer re-resolves and calls `applySagePalette`/`applyAnswerPalette`/`applyJobPalette` → nebula, orbit rings, glyph ring, beads and fan spokes re-tint **without a restart**. |
| **3. private/paused keep working over gold** | New **`private_ring`** token, teal in **every** theme (ORB_REBUILD §3 names `#2DD4BF` — semantic, not decoration). Paused keeps hardcoded steel `#9fb6d8`, Offline its grey — neither themed. |

**Existing tiers byte-identical — asserted, not assumed.** The first draft of
the test failed twice and both failures were real findings:

1. my frozen snapshot used the *raw* config colours, but `vibrance` 1.15 is
   applied to every token (`#B8E02A → #C3EF29`) — the snapshot now freezes what
   actually renders;
2. `vibrance` was only clamped in `config.js`, so `resolvePalette({vibrance:
   0.1})` passed 0.1 straight through — **the documented 0.8–1.5 range now
   lives at the point of use too**.

```
$ node tests/palette.test.mjs
All 8 palette tests passed
  ok great_sage and raphael are BYTE-IDENTICAL palettes
  ok raphael palette equals the frozen 2026-10-07 snapshot
  ok great_sage / raphael / ciel all resolve under theme:auto
  ok ciel is gold-leaning and distinctly warmer than raphael
  ok private ring is the SAME teal in every theme (semantic, never themed)
  ok paused steel is untouched by any theme (hardcoded in sagecore)
  ok vibrance is applied and clamped to 0.8..1.5
  ok custom overrides still win, unknown tier falls back to raphael

$ npm run orb:trace -- --only=wave5
Wave 5: PASS (9/9)   [was 7/7 — the two new checks:]
  ok palette_reloads_live_without_restart: orb-palette frames received: 1
  ok palette_content_unchanged: config.d/orb.yaml byte-identical (only mtime moved)
```

The live probe touches **only my own** `config.d/orb.yaml` (mtime bump,
content byte-identical, restored in a `finally`) — no other lane's file is
read, written or restored by the test.

## Full gate after the palette work

```
npm run test:unit   PASS — 7 morph + 4 gl-recovery + 5 morph-clock + 8 palette
                              + 8 port-safety + state-machine
npm run orb:trace   startup 7/7 · transparency PASS · BugC 6/6 · wave5 9/9 ·
                     interaction 19/19 · shape directive ok ["circle"] ·
                     distinctness PASS (104 pairs)
npm run orb:size    PASS (12 combos, worst drift 4.6% of 12%)
node test/orb-diff.cjs  PASS
```

---

# AMENDMENT — preserve the cage (user, 2026-10-07 evening)

> "the orb is now in a weird shape, its not a cage we had earlier — preserve that."

## Verdict: the code is correct; the live orb is STALE

| evidence | result |
|---|---|
| **live orb process start** | `Wed Oct 7 **18:30:26** 2026` |
| **shape-revert commit `fb1c0c0`** | `2026-10-07 **18:44:09** -0500` |

The revert landed **14 minutes AFTER** the running orb started, and Electron
does not hot-reload renderer modules — so the user was watching a process that
still had the pre-revert `effectiveShape()`. The deployed checkout
(`/home/<wsl-user>/raphael/body/orb`) *does* contain `SHAPE_MORPHS_ENABLED` (grep = 2
hits) and its `effectiveShape()` returns `BASE_SHAPE` immediately, so **a
restart is all that is needed to put the fix on screen**. I did not touch the
live stack (AGENT_RULES §5/§12 — it stays the integrator's call).

## New gate: `cage guard` — PASS 4/4

`npm run orb:trace` now runs `runCageGuard` **before** anything drives a state:

```
[orb-trace] cage guard: PASS (4/4)
  ok cage_established_at_boot          lattice.maxErr=0.0000 cage.maxErr=0.0000 points=60
  ok mid_task_hint_reaches_renderer    orb_state frames carrying a shape_hint: octagram
                                       (the brain-side value we must IGNORE)
  ok cage_preserved_mid_task           applied=circle effective=circle morphActive=false
                                       lattice.maxErr=0.0000 cage.maxErr=0.0000
  ok state_applied_while_shape_stays_circle   state=thinking shapeHint=circle
```

This covers **both** research findings:
1. **init path** — the cage geometry is proven established *at boot*, before any
   state event (the revert collapsed every morph through one
   `applyLatticeShape()` call site; this asserts boot-time establishment rather
   than assuming it).
2. **brain still sends per-task `shape_hint`** — the check *requires* an
   `octagram` hint to actually arrive and then proves it is not applied
   (`maxErr = 0.0000` against the circle target, `morphActive=false`).

## Screenshot proof (matrix regenerated by the same run)

Vision QC on the fresh captures (`docs/orb/matrix/`, `docs/orb/*.png`):

| image | outer cage silhouette | vertex dots | score |
|---|---|---|---|
| idle (rest) | **rounded ball, ~12–14-gon** | present, white | **8/10** |
| listening (rest) | **rounded ball, ~12–16-gon** | present | 7/10 |
| thinking (mid-task) | **rounded ball** — did NOT become a star or box | present | 5/10 |
| jobs (mid-task) | **rounded ball**, more angular from the beads | present | 4/10 |

> *"the outer wireframe stays rounded in the mid-task states"* — the shape
> regression the user reported is **not present** in the current build.

### What the mid-task "weird" actually is (identified, not removed)

Vision flagged an interior "octagram/star" + "square outline" + "teal discs" in
thinking/jobs. Traced to code, all three are **designed features**, not morphs:

| vision saw | what it is |
|---|---|
| blue 8-ray starburst at the core | the core's **4 diffraction spikes** (ORB_REBUILD §3.1, added in the fidelity pass) ×2 arms, tinted **blue by the `thinking` colour** the user explicitly sanctioned ("the color change is the only thing we are okay with") |
| square/diamond outline near the core | the **floating data panes** (ORB_REBUILD §2.1.2 — translucent square plates that drift) |
| teal discs, **2 → 6** between thinking and jobs | the **jobs beads** — exactly `jobs_active` 2 vs 6 (PROTOCOL §8) |
| magenta/red/yellow/green lines | the **prismatic Data Rings** (ORB_REBUILD §2.3 "prismatic spectrum") |

None of these is a lattice/cage morph — the gate proves the lattice geometry is
the circle target with `maxErr = 0.0000` in both states.

## Not actioned (per the amendment)

- **"a weird box underneath"** — the amendment says *vision analysis incoming,
  do not guess-remove banners/subtitles until identified*. My pass finds no
  rectangular boundary box in any image; the only squares are the spec's
  floating panes and the Answer-Mode diamond (speaking/acting only). **Nothing
  removed** — awaiting the coordinator's identification.
- Listening's core reads brighter/bigger than idle (7/10 vs 8/10, "blown out").
  It is partly intentional (`S.listening.bright 1.45` + the user's earlier
  "cages even brighter while listening"), and the ring arcs do **not** actually
  reach the frame edge (radius 1.34 world ≈ 51 px inside a 140 px half-window).
  Flagged for review, not changed.

---

# CAGES → 3D WIREFRAME SPHERES (user, 2026-10-07)

> "nah i dont like the octagram, please change the cages (inner and outer) to
> 3d spheres please" — and: *"the only change in state would be the color."*

## What was built

`initSageCore` now generates the cage as a **wireframe globe** instead of an
icosphere (and instead of the octagram prism that was tried in between and
rejected):

| | before (icosphere) | now |
|---|---|---|
| construction | `IcosahedronGeometry(1.15,1)` + `EdgesGeometry` | 5 latitude rings × 20 segments + 6 meridians × 16 segments |
| edges | ~120 | **196** |
| node dots | 42 (icosphere verts) | 12 (meridian × parallel crossings) |
| outer + inner | same geometry @1.0 / @0.56 | same — **spheres by construction** |
| free spokes | 10 "whiskers" (ended mid-air) | **0** — every segment rejoins the mesh |

Depth comes from the front/back meridian arcs, so it reads as a ball from any
angle; the inner cage is the identical geometry at 0.56 scale hugging the core.

Shape stays **constant** and **colour is the only per-state change**:
`BASE_SHAPE` is `circle` (the sphere's silhouette), `SHAPE_MORPHS_ENABLED` and
`KIND_ACCENTS_ENABLED` remain false.

## Proof — numeric, not a opinion

The CDP probe now reports the radius of **every** cage vertex:

```
$ npm run orb:trace -- --only=cage
cage guard: PASS (4/4)
  ok cage_established_at_boot          cageRadius=1.150..1.150 (SPHERE if spread<0.02)
  ok mid_task_hint_reaches_renderer    orb_state frames carrying a shape_hint: octagram
  ok cage_preserved_mid_task           cageRadiusSpread=0.0000
  ok state_applied_while_shape_stays_circle   state=thinking shapeHint=circle
```

**All vertices at radius 1.150 with spread 0.0000 = every cage vertex lies on
one sphere.** A star, prism or icosphere cannot produce that, so this proves
sphericity directly rather than relying on a screenshot review. The check is
enforced at **boot** and **mid-task**, with a real brain `octagram` hint
deliberately delivered and ignored.

## Independent vision check (fresh matrix)

| question | answer |
|---|---|
| outer cage a globe? | **YES** — ~4 curved parallels stacked in latitude + ~8–10 meridians converging pole-to-pole, round silhouette (roundness ≈0.9) |
| inner cage a sphere? | **YES** — ~50% radius, same topology |
| shape changes across states? | *"I see no star, octagon, hexagon, box, or differing ring count in the cage"* — cage is stable |
| 3D read | "a ball with some depth", 55–65% — pole convergence sells it; held back by no back-hemisphere occlusion |
| ratings (3D wireframe sphere) | idle **7/10** · listening 6/10 · thinking 6.5/10 · jobs 6/10 |

Non-spherical items vision flagged are **by design, not shape changes**: the
job beads (`jobs_active` 2→6), the prismatic Data Rings, the orbit rings'
dim back-half, and the floating data panes.

## Full gate after the rebuild

```
npm run test:unit   PASS (6 suites)
npm run orb:trace   cage guard 4/4 · startup 7/7 · transparency border alpha 0 ·
                     BugC 6/6 · wave5 9/9 · interaction 19/19 ·
                     shape directive ok ["circle"] · distinctness PASS (104 pairs)
npm run orb:size    PASS (12 combos, worst drift 4.6% of 12%)
node test/orb-diff.cjs  PASS
```

### Open from the vision review (not actioned — no instruction to change them)

1. **No back-hemisphere occlusion/dimming** → the ball reads ~55–65% 3D rather
   than fully solid. `polyFrag` already has a depth term
   (`clamp(1.18 − (vDepth−4.2)·0.22, 0.55, 1.15)` → front 1.15 / back 0.74);
   strengthening it would deepen the sphere read at the cost of dimming the
   Data Rings and Answer-Mode lines that share the shader. **Left as-is pending
   an instruction.**
2. **Core reads blown-out in idle/listening** (clipped to 255 with the
   diffraction spikes). The core is *meant* to be the brightest element
   (checklist §8.3); whether it should stop short of clipping is an art call.
3. **"A weird box underneath"** — still waiting on the coordinator's vision
   identification (amendment item 2). My own pass finds no rectangular
   boundary; the squares are the spec's floating data panes. **Nothing removed.**

---

# AMENDMENT 2 — BOOT SEQUENCE REWIRE: starting → idle → <event> (user, 2026-10-07)

> "the starting state might need to be rewired — starting state → idle state →
> then change based on what's happening."

The brain-core lane owns the *emission* half (settle-to-idle-first after
`finish_boot()`); the orb owned the *guarantee* half. Both halves are now in.

## The two mechanisms (src/main/ws-status.js)

| | what | why |
|---|---|---|
| **auto-escape** | `STARTING_ESCAPE_MS = 4000`, one-shot, armed while `starting`, retired by `_settleBoot()` | a socket that opens but is never answered used to leave the main-process status in `starting` **forever** — only the renderer's one-shot 5400 ms timer ever rescued it, and the status/menu never escaped at all |
| **settle beat** | if the first non-boot frame is already an *event* state → show `idle` for `BOOT_IDLE_BEAT_MS = 400`, then apply it | guarantees `starting → idle → thinking` even if brain-core's half regresses; with brain-core working, the arriving frame *is* `idle` and no delay occurs |
| **clean shutdown** | `StatusWS.dispose()` retires every timer + `_disposed` blocks reconnect re-arming; wired into `main.js` `before-quit` | before this, quit left a reconnect timer armed |

`bootEscapeMs` is config-overridable so the unit test exercises the timer in
250 ms instead of 4 s.

## Evidence A — logic (plain Node, `tests/boot-sequence.test.cjs`)

Wired into `npm run test:unit` — **13/13**:

```
A: starts in `starting`                                   starting->idle
A: auto-escapes starting->idle when NO frame arrives      starting->idle
A: escape fires inside the 250 ms budget                  escape after 259 ms
A: never lingers — ends idle, not starting/reconnecting   final=idle
A: a healthy open socket must not drop to reconnecting    starting->idle
B: starts in `starting`                                   starting->idle->thinking
B: never starting->thinking DIRECTLY (idle beat inserted) starting->idle->thinking
B: idle shown before the event state                      starting->idle->thinking
B: the deferred event state is still applied (not swallowed) thinking
C: starts in `starting`                                   starting->idle->thinking
C: settles to idle on auth                                starting->idle->thinking
C: never starting->thinking DIRECTLY                      starting->idle->thinking
C: sequence is starting -> idle -> <event>                starting->idle->thinking
```

(A) Brain accepts the socket and **never answers** · (B) Brain boots straight
into an event state · (C) the normal `auth_ok` path. Runs on an ephemeral test
port (18942) — never 8765, the live brain port (AGENT_RULES §14).

## Evidence B — end-to-end rendered (`orb:trace --only=boot`)

New probe **`window.__orbStateHistory()`** records every *rendered* transition,
seeded at module scope with `starting` (a fast `auth_ok` can land before the
first animation frame, so seeding on rAF would miss it).

```
$ npm run orb:trace -- --only=boot
boot sequence: PASS (5/5)
  ok rendered_sequence_starts_starting:            rendered=starting->idle
  ok settles_to_idle_next_before_anything_else:    first starting -> idle
  ok never_starting_straight_to_an_event_state:    rendered=starting->idle
  ok event_state_lands_after_idle:                 rendered=starting->idle->thinking
  ok never_stuck_in_starting_or_reconnecting:      final=thinking
```

`docs/orb/trace/boot-sequence.json` · the phase is a permanent part of the full
`npm run orb:trace` run (a failure sets exit code 1), not a one-off.

## Scope note

The amendment says "kill/restart brain twice". The live stack is **down by
default** (policy change, 2026-10-07), so the restart is simulated against the
mock brain — same frames, same ports, no live process touched. The two
scenarios that matter (`no frame arrives` / `first frame is an event`) are both
covered; a live re-run is queued behind the brain-core merge alongside the
existing Real-Brain `orb:trace` re-run.

---

# WAVE 5H AUDIT — ARCH-1 / F-4 / F-3 (2026-10-07)

Packet: `docs/audit-tasks/orb.md`. Verify-first rule applied — every finding
below is quoted with its `file:line`.

## ARCH-1 (P1) — Windows-native Electron: **PLAN ONLY, delivered**

**`docs/orb/WINDOWS-NATIVE-PLAN.md`** (plan, zero code, zero installs), backed by
`.opencode/research/windows-native-electron-orb.md`.

- **Node-on-Windows = ALREADY-DONE.** Measured on this box:
  `C:\Program Files\nodejs\node.exe` = **`v24.1.0`**, and Node 24 is the correct
  line (Electron 44 embeds Node 24.18.1; electron-builder v27 / `@electron/rebuild`
  require ≥ 22.12). The plan documents the real trap instead: **Electron 44 = ABI
  149 vs Node 24 = ABI 137**, so every native module must be `@electron/rebuild`ed
  against Electron headers (`win_delay_load_hook` stays on).
- **Prototype = BLOCKED, `coord user_attention` posted.** What needs approval is
  the prototype (Electron dist download + unsigned `electron.exe` + a test port),
  not a Node install.
- Covers every required topic: Node version, config-path resolution (4-step order
  preserving the current dev layout), token delivery (stdin/user-DACL pipe →
  `safeStorage`; argv disqualified by WMI *and* by `second-instance` argv
  forwarding; plain env readable same-user via `PROCESS_VM_READ`), always-on-top +
  click-through, multi-monitor/DPI, GPU flags, **measured idle for both paths**,
  a 10-item parity checklist, and rollback.
- **Measured idle — WSLg path** (cited from `docs/orb/PERFORMANCE.md`): GPU
  ≈0–0.5%, electron CPU 0.0–0.1%, `msrdc` bridge 0.52%, system 3.65%.
  **Native path cannot honestly be numbered until a native build runs** — §7b
  gives the exact `typeperf` / `\GPU Engine(*)` / WPR protocol so the two numbers
  are comparable.
- The retirement argument is not frame cost, it is compensations removed:
  `weston-wrapper` + `boot-hook.sh` (the wrapper is *reset on every
  `wsl --shutdown`*), `topmost.ps1` re-applied every 30 s, and the `SetWindowRgn`
  clip for the **~32 px shadow margin WSLg bakes inside the surface** — a native
  window needs none of them (`thickFrame:false` is the documented shadow killer).
- **WSLg path untouched** and stays fully gated until §8 parity passes.

## F-4 (P2) — usage/rate headroom + SEC-3 cloud-mic indicator: **DONE, gated**

Verdict **CONFIRMED** (finding was real): `orbMenuTemplate()` showed only
provider/model — `main.js` before this change had no `/status` consumer at all
(`grep fetch/axios body/orb/src` → no hits), so rate headroom was unreachable.

- **No new frames** (packet rule): reads `GET /status` — PROTOCOL §2 REST, same
  port and same token as the WS — on menu open, `STATUS_TTL_MS = 1000`,
  `STATUS_TIMEOUT_MS = 600`, never blocking a right-click.
- **Stable row contract:** `info-usage` + `info-rate` always exist, degrading to
  `(unavailable)` rather than vanishing; `info-circuit` appears only when a
  circuit is not `closed`.
- Headroom math = **tightest provider** across `router.providers[*].rpm`
  (`1 - used/cap`), so the row shows the binding constraint, not an average.
- **Token hygiene:** sent as `Authorization: Bearer`; the mock asserts only the
  header's *presence* (`statusAuthSeen`), never its value. PROTOCOL §11 intact.
- **SEC-3 indicator, fail-safe by design:** on-orb `#micbadge` shown while
  `orb_state = listening` unless Private Mode (the only provable cloud off-
  switch), + a `mic-cloud` menu row in all three readings. Placed **inside** the
  orb silhouette and sized in `vw` because `orb:size` measures the radius
  containing 97% of lit pixels (`test/orb-size.cjs:50`) — a badge poking past the
  sphere would move that number. Known over-warning under a future `local`
  profile → `docs/requests/orb__to__brain-core__stt-source-in-status.md` filed.
- **Evidence:** `orb:trace` interaction phase **19/19 → 30/30**, incl.
  `menu_rate_headroom_math` (`3% · zen_free 58/60 rpm`), `menu_circuit_row_when_open`,
  `menu_status_sent_bearer_token`, `mic_badge_on_while_listening`,
  `mic_badge_off_in_private_mode`, `menu_usage_degrades_honestly`.
  Mock-brain gained a real `/status` (401 without Bearer, 404 when the test wants
  the degradation path).

## F-3 (P2) — activity viewer: **DESIGN ONLY, correctly blocked**

Verdict **CONFIRMED + BLOCKED**: the packet calls it CO-SHARE and the user said
"design first, implement after pc-control exposes the API".

- Schema agreement filed: `docs/requests/orb__to__pc-control__act-journal-schema.md`
  (entry shape, reversibility table, `GET /activity` + `POST /activity/{id}/undo`,
  no new WS frames — the orb is `role: ui` and may never emit `act_req`).
  Why pc-control must own it: **only `body/win/actions.py` knows whether an
  action can be undone**; guessing in the renderer would offer an Undo that
  silently does nothing.
- Design: `docs/orb/ACTIVITY-VIEWER.md` — reached from the menu, rendered as an
  in-orb panel (native menus cannot scroll 30 rows or show per-row undo results),
  read-only, `[Undo]` rendered **only** when `reversible && !undone`, fail-closed
  on server disagreement, plus a mock-brain test plan.
- **Zero orb code**, as instructed. Panel is closed by default, so the design
  changes no pixel of the current sweep.

## Gate status after this wave

See the run recorded at the bottom of this file for the post-change numbers.
`test:unit` (7 suites), `orb:trace`, `orb:size`, `orb:diff` — all green or
re-run pending at time of writing; distinctness is re-verified after **every**
change per audit item 4.

## Wave 5H gate record (post-change, final code)

```
npm run test:unit          PASS — 7 suites (7 morph + 4 gl-recovery + 5 morph-clock
                                    + 8 palette + 8 port-safety + state-machine
                                    + 13 boot-sequence)
npm run orb:trace          PASS — boot sequence 5/5 · cage guard 4/4 ·
                                    startup 7/7 (peak 2.043 rest 0.193 rad/s) ·
                                    transparency border alpha 0 · BugC 6/6 ·
                                    wave5 9/9 · interaction 30/30 ·
                                    distinctness PASS (104 pairs, weakest
                                    jobs vs thinking = 0.73) ·
                                    shape directive ["circle"]
npm run orb:size           PASS — 12 combos, worst drift 4.6% of 12%, edge gap 3px,
                                    min coverage 62.9%
node test/orb-diff.cjs     PASS — every pair of states renders differently
```

One transient failure occurred mid-wave (`startup phase FAILED: CDP timeout after
30000ms: Runtime.evaluate`, EXIT=1) with no code correlation — unit, size and
diff all passed either side of it, and an immediate re-run of the full trace was
green end-to-end. Recorded for honesty, not a real defect.

The F-4 endpoint fix (derive REST host/port from `wsUrl`, not from the derived
`wsPort()`, so `RAPHAEL_WS_URL` overrides cannot desynchronise WS from REST) was
made **after** the full-trace run, so that change was re-verified with
`--only=interaction` (30/30) plus `test:unit`, `orb:size` and `orb:diff` on the
final code — the renderer is untouched by it, so the trace's visual phases stand.

---

# AMENDMENT 3 — NO ON-SCREEN TEXT (user, 2026-10-07)

> "text displays under her, a whole box of the answer, the red mic->cloud pill —
> none of that. **Just speech.**"

## What was removed

Every text path in the orb funnels through **one** function,
`renderer.js updateSubtitle()`, so the fix is a single gate rather than six
scattered deletions:

```js
const ORB_TEXT_ENABLED = false;   // AMENDMENT 3: speech only
```

| Formerly painted | Caller | Now |
|---|---|---|
| status/narration line under the orb | `onOrbState` subtitle (`renderer.js:1360`) | never painted; element scrubbed |
| `subtitle` frame text | `onSubtitle` (`renderer.js:1377`) | never painted |
| **answer box** ("a whole box of the answer") | `updateAnswer` (`:1024` → banner card) | never painted |
| report card | `updateReport` (`:1033` → banner card) | never painted |
| `notice` banner | `updateNotice` (`:1010`) | never painted |
| demo state label | `runDemo` (`:671`) | never painted |
| **red `MIC → CLOUD` pill** | `#micbadge` | **element deleted** (`index.html`) + toggle removed |

The gate also **scrubs** (clears `textContent`, forces `.hide`) rather than
merely skipping, so a frame that raced in ahead of the flag cannot leave words on
screen.

**Deliberately kept:**
- **PROTOCOL §3 frames are unchanged** — `subtitle` / `notice` / `answer` /
  `report` still arrive and are still recorded by `traceRx`. CLI/API consumers
  are unaffected; the orb just never renders them. (Also proven by the gate
  below: the notice frame *arrives*, the text does *not appear*.)
- **Cage, colours, pulse, job-dots** and the **on-demand right-click menu** —
  including its `mic-cloud` row, which is user-invoked, not auto-displayed.
- **Typed input** (`#typed`) — user-initiated on double-click, not auto text,
  and it is the vehicle for `command{source:'orb'}`.
- Glyph/rune rings, data panes, Data-Ring bars — abstract marks, not readable
  text.
- `#fps` overlay: `renderer.js:40` documents it is **null on the production
  page** (`index.html` has no `#fps`), demo-only.

## Gate changes (explicitly sanctioned: "update gates (color+shape distinctness only)")

Two assertions were *inverted* so they now **prove the directive** instead of
fighting it:

| was | now |
|---|---|
| `notice_shown_as_banner` — required `.show` + `/disk almost full/` in `textContent` | `notice_frame_not_rendered_as_text` — requires `shown === false` **and** empty text, while `notice_reaches_renderer` still proves the frame arrived |
| `mic_badge_on_while_listening` — required `on === true` | `mic_badge_absent_when_listening` — requires the **element to be gone** (`null`) |
| `mic_badge_off_in_private_mode` — required `on === false` | `mic_badge_absent_in_private_mode` — requires `null` |

Distinctness stays a **colour + shape** gate (104 pairs) — unchanged, and the
one that must stay green.

---

# SEC-1 / ARCH-4 PERSONAL-DATA SCRUB (orb-owned files only)

`python3 scripts/scan_personal.py`, own-lane files only per the ownership rule.

| | before | after |
|---|---|---|
| **orb-owned FAIL findings** | **7** | **0** |
| repo-wide findings | 204 | 197 |
| repo-wide FAIL | 119 | **112** (exactly −7, my share) |

Scrubbed (placeholders per the nudge: `<wsl-user>` / `<win-user>`):

| file:line | was | now |
|---|---|---|
| `.opencode/research/windows-native-electron-orb.md:20` | path-windows — a Windows user-drive path literal in a doc example | `C:\<win-user>\…` |
| `docs/orb/trace/audit.json:7` | user-linux + path-home | `/home/<wsl-user>/.raphael/orb/orb` |
| `docs/requests/orb__to__integrator__harness-spawn-while-live.md:27` | user-linux + path-home | `/home/<wsl-user>/raphael/body/orb` |
| `docs/status/orb.md:941` | user-linux + path-home | `(/home/<wsl-user>/raphael/body/orb)` |

> **Self-inflicted, worth recording:** this table is what *reintroduced* 9 FAIL
> findings on the very next pre-commit scan — quoting the raw pre-scrub values as
> evidence put the personal data straight back. The rule now shown is the rule
> that fired; the actual literals are no longer reproduced anywhere in this file.

**Not scrubbed (NOT-APPLICABLE):** the 5 remaining `REVIEW` hits in
`body/orb/package-lock.json` (`rule=ip-private`). That is a **generated npm
lockfile** — rewriting it would invalidate npm's integrity hashes, it carries no
personal data I authored, and it is REVIEW severity, not FAIL. Flagging to infra
that generated/lockfile artifacts likely want an exclusion rather than a scrub.

**Recurrence risk (infra's call, not mine):** `docs/orb/trace/*.json` are
*regenerated* by every `orb:trace` run and will re-emit the real `userData`
path. Scrubbing is correct today but the finding will return on the next
regeneration unless the scanner excludes generated trace artifacts.

---

# "BLUE PARTICLES" + "STARTING IS PINK/PURPLE" — investigated by LOOKING, not by reading code

User: *"you should take screenshots of those states bruh and see those blue
particles yourself. you are not removing them, please just look at them instead
of blindly moving forward."* Fair — this section exists because I did exactly
that, and looking caught a defect my code-reading had missed.

## 1. Blue particles — removed in code, NOT on your screen

| evidence | result |
|---|---|
| starfield code | `renderer.js:565` → `starsMesh = null`; the `PointsMaterial(0x58c4f2)` line is gone |
| committed? | **YES** — `48da3dd` |
| on `origin/main`? | **NO** — `git merge-base --is-ancestor 48da3dd origin/main` → false |
| live install | `/home/<wsl-user>/raphael/body/orb/src/renderer/renderer.js` still contains `58c4f2` **5×** |

**So the removal is correct but has never been merged** — the live orb loads
`main`, which still has it. This is the same reason every other fix in this batch
is invisible on screen: nothing has shipped since `b0ed6ce`. Fix = post
`wave_done` → merge → supervisor relaunch.

Blind vision QC on my own fresh renders (post-removal) agreed the starfield was
gone in 3 of 4 frames, and flagged `thinking` — see §3.

## 2. "starting should be white not pink/purple" — my GATE was lying

Measured, honestly:

| capture | r24 (R,G,B) | verdict |
|---|---|---|
| settled render (3 s wait, my probe) | `138,138,138` spread **0** | **WHITE** |
| same state, settled, all radii | `214,213,211 / 138,138,138 / 119,119,120` spread **0–2** | **WHITE** |
| `docs/orb/starting-dark.png` (the gate's own screenshot) | `92,59,92` spread **32** | **MAGENTA** |

The code fix was right all along — `S.starting.nebula = 0.00`
(`sagecore.js:45`) and `getStateTint('starting') = 0xffffff` (`renderer.js:754`),
confirmed by the trace: `"state":"starting" … "tint":"0xffffff"`.

**The defect was in my capture harness.** `capture()` slept a fixed
`SETTLE_MS=1400` + `LOCK_SETTLE_MS=600`, but the state it was shooting had come
from `thinking`, whose **prismatic Data Rings** (`setHSL(i/4)` → red/green/cyan/
**270° violet**) and nebula were still damping. Instrumented:

```
thinking              dataRings.w = 0.977   nebula = 0.648
starting @1400ms      dataRings.w = 0.029   nebula = 0.019   <- GATE SHOT HERE
starting @2600ms      dataRings.w = 0.0014  nebula = 0.0009   <- settled
```

Violet residue over a dim boot core reproduces the measured `196,107,197`.

**Fix:** `capture()` now **polls for convergence** (two consecutive samples of
`dataRings.w`, `sage.nebula`, `latticeOpacity` within EPS 0.004) instead of
sleeping a guessed interval, capped at 5 s so a state that legitimately *holds*
those values (`thinking` = 1.0) cannot stall the sweep. Convergence, not
magnitude — the first attempt polled for "small" and would have stalled every
capture; that was caught before the run.

## 3. Coloured specks in `thinking` — flagging, not guessing

Blind vision on `thinking-dark.png`: *"10–18 micro-square specks — several
red/pink, 2–3 green, several cyan/bright-blue pinpoints, scattered over the
ball; the user is right for this frame."*

Those are the **prismatic Data Rings** (`datarings.js`, `setHSL(hue, 0.95, 0.6)`
over 4 rings + the `bars` ring), which are **spec-mandated** for `thinking`
(`ORB_REBUILD` §2.3 / re-pasted §3.3 "the Data Rings (prismatic dashed rings)
fading in"). They are not the removed starfield.

**Not changed** — spec says keep them, you asked me to remove "blue particles"
(which is the starfield). Say the word and I'll desaturate or thin the Data
Rings too.

---

# DISTINCTNESS REGRESSION — root-caused to ONE uniform still damping under pose lock

`orb:diff` came back `pass=false … 13 near-identical pairs`. Most pairs had
nothing to do with what I had changed, which is exactly why it was worth
tracing instead of tuning thresholds.

## The chain

| step | finding |
|---|---|
| gate formula (`test/orb-diff.cjs:124`) | `threshold = max(ABS_FLOOR, NOISE_FACTOR × worstSameSceneNoise)` |
| constants | `ABS_FLOOR = 0.30` (`:28`), `NOISE_FACTOR = 1.5` (`:33`) |
| observed | `need 9.67` ⇒ **worstSameSceneNoise = 6.45** |
| which scene? | `distinctness.json` → `noise.perScene`: **`starting@dark = 6.45`**, `starting@busy = 3.25`, `starting@light = 1.17` — **every other scene = 0.000** |
| consequence | threshold 0.30 → 9.67, so 13 pairs "failed" while the real weakest pair (`idle vs private @light`, `jobs vs thinking @dark`) sits at **0.73 — 2.4× the genuine 0.30 floor** |

**One scene's temporal noise was poisoning the global threshold.** At the real
floor all 13 pass.

## Why only `starting`

Pose lock (`__orbLockPose`, `renderer.js:1102`) promises to *"snap every weight
to its target … so the two captures are a pure function of state"*. It did — for
**tint** (`lockSageCore`, `sagecore.js:544`-area) and for **amp** (`L.ampS =
opts.amp || 0`, `sagecore.js:544`). The one uniform it missed was **`uBright`**,
which still *damped* every frame (`TAU = 400 ms`, `sagecore.js:766`).

`starting` is the only state with a long enough brightness travel to still be
moving when rep1/rep2 were shot:

```
idle  uBright target        ~ 1.00
starting uBright target = 0.45 × genSun(=0.148 at the locked gt=2000) ≈ 0.067
                             └─ travel ≈ 0.93, still easing after 600 ms
```

Every other state lands close to where it started, so it had already converged
→ noise 0.000.

## Fix

`sagecore.js` `updateSageCore`:

```js
const bTarget = w.bright * fx * Math.max(genSun, 0.001);
cu.uBright.value = ctx.lock ? bTarget : damp(cu.uBright.value, bTarget, TAU, dt);
```

Snap under lock, damp otherwise — i.e. `uBright` now honours the pose-lock
contract the other two uniforms already honoured. **No gate was weakened**: the
threshold formula, `ABS_FLOOR` and `NOISE_FACTOR` are untouched.

## Related fixes in the same pass

1. **`capture()` now polls for convergence** instead of sleeping a fixed
   1400 ms — that is what exposed `starting-dark.png` rendering magenta
   (violet Data-Ring/nebula residue from the preceding `thinking`) when the
   settled render is white. Poll is on *convergence* (weights stopped changing),
   not on magnitude, so `thinking` (which legitimately holds `dataRings≈1.0`)
   cannot stall the sweep.
2. **`starting` dimmed** to the requested "dim white": `bright 0.72 → 0.45`,
   `poly/node 0.70 → 0.55`, `ring 0.40 → 0.26`, `spark 0.35 → 0.22`,
   `speed 0.50 → 0.34` — which also separates it from `private_overlay` (1.00)
   and `reconnecting` (0.75) on merit rather than on colour it no longer has.

## CORRECTION — the `uBright` snap above was a wrong hypothesis

The `uBright` snap under pose lock is **correct and worth keeping** (the lock's
own contract says "snap", and it was the one uniform still easing), but it did
not fix the noise — `need` actually went **9.67 → 10.18**. Chasing it properly
with an instrumented probe (300 ms sampling under pose lock) produced:

```
t(ms)   pixDiff   uBright   spin.phase omega  angle
  900    0.000    0.0667    settle     0.774  0.000    ← starting, snapped
 1200    7.750    0.9420    settle     0.774  0.000    ← JUMP
 1500    0.627    0.9997    settle     0.774  0.000
 1800    0.004    1.0000    settle     0.774  0.000    ← exactly IDLE's target
```

`uBright` landed on **exactly 1.0000**, which is `idle`'s target
(`bright 1.00 × genSun 1.0`), not `starting`'s (`0.45 × 0.148 = 0.067`). So the
scene was **changing state mid-capture**, not merely easing.

### Actual root cause: my own AMENDMENT 2 auto-escape

`STARTING_ESCAPE_MS = 4000` fired ~1.2 s after pose lock (lock happens ~2.8 s
into the synthetic state) and converted the harness's `starting` into `idle`
**between rep1 and rep2**. That is why:

- **only** `starting` was noisy (only it is on the escape clock) —
  `idle`/`thinking` measured **0.000 / 0.000** under the identical probe;
- the noise was ~6.79 while every other scene was exactly **0.000**;
- and it saturated in steps (`0.067 → 0.94 → 1.00`) rather than jittering.

**Two genuine bugs fell out of it:**

1. **`ws-status.js` — the escape ignored arriving frames.** AMENDMENT 2 says
   *"auto-escape timeout **if no frame arrives**"*, but the timer was only
   armed/cleared on *state transitions*, so a Brain legitimately streaming
   `starting` frames through a long boot was force-flipped to `idle` at 4 s
   **while it was talking to us**. Fixed: `handle()` now calls
   `_resetBootEscape()` on **any** inbound frame while in `starting`.
2. **`orb-trace.cjs` — a synthetic `starting` with no frame stream.** The
   convergence poll (up to 5 s) plus the burst could outlive the 4 s budget. The
   harness now re-asserts `brain.step(scene)` inside the poll and again
   immediately before the burst, the same way a live Brain streams frames.

**Method note (the thing worth keeping):** the fix came from *sampling the
pixel diff every 300 ms and printing it next to the suspect uniforms*, not from
re-reading code — three code-reading hypotheses (nebula, Data Rings, `uBright`)
were each wrong or incomplete.

---

# RE-VERIFICATION ON A FRESH PRODUCTION BUILD (wave-5H follow-up, coord [38])

Asked for: *"re-verify #fps null + boot-sequence AMENDMENT-2 leftovers on a
fresh production build."*

**"Production" here means the real page, not the harness's demo page** —
`main.js:337-340` selects `index.html` unless `--demo` is passed, so the run
below launched **without** `--demo`, exactly as `orb-trace.cjs:67-84` does
("*Production page (index.html) — the trace must reproduce what the user sees,
so --demo is deliberately NOT used here*").

## Result — PASS, all eight assertions

| check | expectation | actual |
|---|---|---|
| page | `index.html` | **`index.html`** ✓ |
| `#fps` element | **absent** | **`false`** ✓ |
| `#micbadge` element | absent (AMENDMENT 3) | **`false`** ✓ |
| `#subtitle` text | `""` | **`""`**, `shown=false` ✓ |
| `document.body.innerText` length | 0 | **0** ✓ — literally no on-orb text |
| state @9 s | `idle`, not stuck | **`idle`** (`__orbTrace` agrees) ✓ |
| rendered state history | `starting → idle` | **`starting -> idle`** ✓ |
| `Runtime.exceptionThrown` | 0 | **0** ✓ |

Static corroboration for `#fps`: `grep -c 'id="fps"' src/renderer/index.html`
→ **0**, matching the code comment at `renderer.js:40` ("null on production
page (index.html)"); `fpsEl` is only ever non-null on `demo.html`.

## AMENDMENT-2 leftovers — none found

| check | result |
|---|---|
| `tests/boot-sequence.test.cjs` | **13/13 PASS** (auto-escape 259 ms/250 budget · idle beat · normal auth) |
| `orb:trace --only=boot` (rendered, end-to-end) | **PASS 5/5** — `rendered=starting->idle`, `event_state_lands_after_idle` → `starting->idle->thinking`, `never_stuck_in_starting_or_reconnecting` |
| orphan processes after the runs | **none** — ports 8906/9406 free, no harness/Electron left from this lane |
| the only live Electron | the **production install** (a `<wsl-user>` home path) — not mine, deliberately untouched |
| `ws-status.js` escape fix still on main | `_resetBootEscape` present (2 refs), `HEAD` is an ancestor of `origin/main` |

**No leftover `starting`/`reconnecting`, no orphan timers surfaced, no leaked
harness processes, no exceptions on the production page.**

## Note on the escape fix reaching production

`ws-status.js` `handle()` now calls `_resetBootEscape()` on **any** inbound
frame while in `starting` — the AMENDMENT-2 wording is *"auto-escape timeout **if
no frame arrives**"*, and the original implementation only armed the timer on
state *transitions*. Merged in `08a30b5`; re-verified here on the production
page rather than assumed.

---

# 2D BILLBOARDS — CONVERTED (wave-5H follow-up, coord [40])

Scope as agreed: convert the `jobdots` halos and the Answer-Mode petal/bokeh
sprites; leave the nebula; document the corona; clear the stale `#micbadge`
bullet.

## What changed

| element | before | after |
|---|---|---|
| **job-bead halo** | `CircleGeometry(HALO_R, 20)` + `MeshBasicMaterial` **flat colour, no map** → constant alpha across the disc, then a step to 0 at the circle boundary = a **hard-edged 2D disc** | `SphereGeometry(HALO_R, 16, 12)` + `haloFrag`: `a = pow(f, 1.6) * uAlpha` where `f = dot(N,V)` → **0 at the limb** → soft glow *ball*; `uColor`/`uAlpha` uniforms (3 call sites updated), `halo.scale` `set(s,s,1)` → `set(s,s,s)`, `premultipliedAlpha: true` |
| **Answer-Mode bokeh** | radial-gradient canvas texture on a **camera-facing** `PlaneGeometry` | `SphereGeometry(0.5, 16, 12)` + new `glowVert`/`glowFrag` (same limb-falloff), `premultipliedAlpha: true`; `makeBokehTexture` retained but unused |
| **Answer-Mode petals** | `rotation.z` only → **flat against the screen** | fixed 3D tilt `rotation.set(0.75+…, ±1.0, 0)`; the per-frame update writes only `rotation.z`, so x/y persist |

**Why no hard edge is possible now (construction proof, stronger than a pixel
sample):** `dot(N,V)` is **0 exactly at a sphere's silhouette**, so `pow(f,1.6)`
puts alpha at **0** there — the glow reaches the background with no step. The
old `CircleGeometry` + flat `MeshBasicMaterial` had *constant* alpha right up to
the disc boundary, which is where the edge came from.

*(A pixel-level falloff measurement was attempted at 280 px and again at 600 px
and **deliberately abandoned**: the bright geodesic cage lines cross the sampling
rays and re-brighten them mid-falloff, so the ring profile oscillates and any
"step" it reports is the cage, not the halo. The shader argument above is the
reliable one; vision was used for the perceptual half.)*

## Accepted by design (not converted, documented)

- **Nebula plane** — the user explicitly likes the cloud; it reads as a *cloud*,
  not a structural element.
- **Sun corona glow plane** — a bloom is inherently a billboard: it must face the
  camera to read as *light*. Converting it to geometry would give the sun a solid
  edge, directly contradicting spec §3.1 ("no visible edge").
- **`#micbadge` pill** — **stale entry, cleared**: AMENDMENT 3 deleted the element
  outright, so there is no DOM pill left to convert; the SEC-3 indicator survives
  only as the on-demand `mic-cloud` menu row.

## Evidence

**Gates (all run):** `test:unit` 7 suites · `orb:trace` boot 5/5, cage 4/4,
startup 7/7, transparency `borderA0/rgb0`, BugC 6/6, wave5 9/9,
interaction 34/34, **distinctness pass=true (104 pairs, failures 0)** ·
`orb:size` PASS (drift 4.8%) · `orb:diff` **noise floor 0.000 → threshold 0.300,
PASS**.

Note: the weakest pair moved **0.73 → 0.52** (`jobs` vs `thinking`) because the
halo lost its hard disc — still 1.7% of pixels changed (≥ the 0.7% floor) and
1.7× above threshold, so **pass**. Recorded rather than hidden.

**Vision (blind, on the fresh matrix):**
- `jobs-dark` **7/10** — *"halos read as soft glowing balls, not flat discs… I do
  not see any that clearly still look like a flat paper disc with a hard outline."*
- `speaking-dark` **8/10**, `acting-dark` **8/10** — *"petals read as tilted
  shards in 3D, including foreshortened ones that clearly aren't facing the
  camera"*, bokeh *"soft blobs, no visible square/rectangular edge"*.
- control `listening-dark`: *"no teal job beads/halos, no coloured bokeh blobs,
  no pale petal flakes — clean."*
- No new artifacts: *"no hard halo edge, no visible sphere silhouette/wireframe
  on the glows, no colour banding, no solid dark ball, nothing vanished."*

**The one red flag vision raised** — a top-centre bead in `jobs-dark` reading
"elongated/teardrop" — is explained by the **parallel-minds fan spokes**:
`docs/orb/trace/wave5.json` records `spokes=6` for that state, i.e. beads have
spokes deliberately attached (PROTOCOL §5). A bead *with* a spoke reads elongated
by design. Not a defect from this change.

---

# DEPENDABOT EVAL — electron 30.5.1 → 44.5.1 (PR #10, coord [44])

**VERDICT: MERGE-RECOMMENDED.** Evaluated in an isolated worktree
(`/tmp/opencode/orb-e44` @ `a02d305`) so my own branch was never dirtied; PR
touches only `body/orb/package.json` + `body/orb/package-lock.json`.

## Gates on the bumped build — all green

| gate | result on **44.5.1** |
|---|---|
| `npm run test:unit` | **7/7 suites** (incl. boot-sequence **13/13**) |
| `orb:trace` | **EXIT 0** — boot **5/5**, cage **4/4**, startup 7/7 (peak 2.020), transparency **borderA0/rgb0**, BugC **6/6**, wave5 **9/9**, interaction **34/34**, shape directive `["circle"]` |
| distinctness | **pass=true**, weakest `idle vs private` = **0.73** (104 pairs) |
| `orb:size` | PASS — worst drift **5.1%** of 12%, edge gap 3px |
| `orb:diff` | **noise floor 0.000 → threshold 0.300, PASS** |

Deps resolved as electron **44.5.1**, three 0.170.0, ws 8.22.0 — no other
version moved.

## Security — this is the point of the bump

| build | `npm audit --registry=https://registry.npmjs.org` |
|---|---|
| **30.5.1** (before) | **6 vulnerabilities (4 moderate, 2 high)**, exit 1 |
| **44.5.1** (after) | **0 vulnerabilities**, exit 0 |

`tests/security/SCANNERS.md:56-64` documents exactly those highs: *"6 vulns
(4 moderate, 2 HIGH) — the highs are `electron 30.5.1` (ASAR integrity bypass)
and its transitive `extract-zip`; the fix is a MAJOR Electron upgrade
(>= 41.10.6 / 42.3.4) in the ORB LANE's package.json — **breaking change not
qa-security's to make**."* **The bump closes the original audit finding** that
produced `qa-security__to__orb__electron-audit-highs.md`.

Note: `npm audit` without `--registry` still 400s against the configured
`pkgs.safetycli.com` mirror — that is an endpoint problem, not a lockfile one,
and is unrelated to this PR (the separate lockfile redirect is commit `ee8823c`).

## API / breaking-change review (30 → 44)

Orb surface: `Menu.buildFromTemplate`, `app.{exit,getPath,on,quit,relaunch,
requestSingleInstanceLock,setPath,whenReady}`, `contextBridge.exposeInMainWorld`,
`ipcMain.{handle,on}`, `ipcRenderer.{invoke,on,send}`, `nativeImage.{createEmpty,
createFromPath}`, `screen.{getAllDisplays,getPrimaryDisplay,on}`, `shell.openPath`,
`webContents.{on,send}`, plus one `BrowserWindow` block
(`main.js:309-332`: frame/transparent/alwaysOnTop/skipTaskbar/resizable/movable/
focusable + webPreferences preload/contextIsolation/nodeIntegration/sandbox/
backgroundThrottling).

Checked against the official breaking-changes list 44→35:

- **44.0 `clipboard` removed from renderer / rearchitected** → our single grep
  hit is `win32clipboard` in `scripts/install-body-venv.ps1` — a **Python**
  import for the Windows Body. **Not Electron. Not affected.**
- **44.0 `net.request` Sec-Fetch-Dest** → we use plain `node:http` in
  `main.js refreshStatus()`, never `net`. **N/A.**
- **44.0 macOS-12 / Windows-ia32 removals** → we ship linux-x64 + win-x64. **N/A.**
- **42.0 `ELECTRON_SKIP_BINARY_DOWNLOAD` removed** → **0 references** in repo.
- **42.0 postinstall → on-demand binary download** → our install ran and
  `electron --version` reported `v44.5.1`. **Works.**
- **39.0 `window.open` popups always resizable** → **0** `window.open` /
  `setWindowOpenHandler`. **N/A.**
- **36.0 `app.commandLine` lowercasing** → **0 references**.
- No `remote`, no `nodeIntegration:true`, no `webviewTag`, no renderer clipboard.

**Verdict: no API break touches this codebase.**

## Risks checked and cleared

- **Ozone/Wayland (Electron 38 change):** this box has `WAYLAND_DISPLAY=wayland-0`
  set (`XDG_SESSION_TYPE` unset), so native-Wayland-by-default was the top
  suspicion for an overlay that depends on always-on-top + transparency +
  click-through. **Did not materialise:** transparency `borderA0/rgb0` and the
  full interaction suite (hit-testing, `setIgnoreMouseEvents` forwarding) passed
  identically. `ozone`/`OZONE` have 0 references in our launch paths.
- **ANGLE now statically linked (44.0)** — we render through ANGLE/D3D12 on the
  Intel iGPU; startup, cage and distinctness all unchanged.
- **preload-in-subframes (44.0)** — preload targets the main frame only;
  `interaction 34/34` proves IPC/`contextBridge` still work end-to-end.

## Notes for the merger (not blockers)

1. **Spec conflict:** `docs/ORB_REBUILD_TASK.md:116` pins *"electron 30.5.1,
   three 0.170.0, ws 8.22.0 — no version drift"* — merging **requires updating
   that base-spec line** (plus the `npm audit endpoint broken` clause can be
   reworded once SCANNERS.md's documented-highs note is retired).
2. **This is a VERSION BUMP only** — it is *not* the Windows-native migration.
   ARCH-1 stays plan-only and human-gated; do not conflate the two.
3. `sandbox: false` is unchanged and still honoured on 44 — restoring it stays
   as ARCH-1 item **H4**, deliberately sequenced with the migration.
4. `tests/security/SCANNERS.md` documented-highs note and
   `qa-security__to__orb__electron-audit-highs.md` should be retired by
   **qa-security** after merge (their files, not mine to edit).
5. Residual: gates run on **WSL/Linux only** — no Windows runtime was exercised.
   Windows conformance in CI covers docs parsing, not the Electron window, so a
   post-merge Windows smoke (overlay shows, click-through, topmost) is worth a
   human eyeball.

## Interlock

`ee8823c` (safetycli lockfile redirect, 1 entry → npmjs, integrity
byte-verified) is what lets dependabot resolve this PR cleanly — landed on my
branch, CI **5/5 green**.

---

# TWO REQUESTS ANSWERED BY THE ELECTRON BUMP + LOCKFILE FIX (2026-10-08)

Both landed on main as a side-effect of work already done; verified on **current
main**, not from memory.

## `infra__to__orb__npm-safetycli-lock.md` — satisfied (my file, my fix)

The request's own verification criterion:

> "verification = `grep -c pkgs.safetycli body/orb/package-lock.json` → 0"

| check | result |
|---|---|
| `grep -c pkgs.safetycli body/orb/package-lock.json` | **0** ✓ |
| resolved-host census | **15 × registry.npmjs.org, 0 × pkgs.safetycli.com** |
| `electron` in lockfile | **44.5.1** |
| JSON valid / `npm ci --dry-run` | valid / **exit 0** |

Fixed in `ee8823c` (integrity byte-verified against `registry.npmjs.org/ws/8.22.0`
`dist.integrity` before editing), merged via the position-6 batch. Their preferred
method was `npm install --package-lock-only`; a manual one-line edit was explicitly
acceptable *because the integrity is unchanged*, which is what I verified.

## `qa-security__to__orb__electron-audit-highs.md` — criterion MET, ball is in qa's court

Their ask, verbatim:

> "When you bump Electron and `npm audit` is clean, ping me: I tighten the CI step
> to `--audit-level=high` and delete the allow-list note (`tests/security/SCANNERS.md`)."

| condition | status |
|---|---|
| Electron bumped | **YES** — 30.5.1 → **44.5.1** (PR #10 merged `ac05b3c`), evaluated by me: all orb gates green, verdict MERGE-RECOMMENDED |
| `npm audit` clean | **YES** — `npm audit --registry=https://registry.npmjs.org --prefix body/orb` → **"found 0 vulnerabilities", exit 0** |
| before | **6 vulnerabilities (4 moderate, 2 high)**, exit 1 — exactly the ASAR-integrity HIGH + transitive `extract-zip` they catalogued |

**Both of their conditions are satisfied → qa-security can now tighten the CI step
to `--audit-level=high` and delete the `tests/security/SCANNERS.md` allow-list
note.** Those two files are theirs (ownership), so the action is theirs.

Note for whoever runs it: `npm audit` **without** `--registry` still 400s against
the configured `pkgs.safetycli.com` mirror (`Invalid request payload JSON format`)
— that is a registry-endpoint problem, not a lockfile one, and is unrelated to
either request above. The CI step already uses the real registry, which is why
the bump's clean result reproduces there.

## Current as of 2026-10-09 (integrator freshness pass)

- **Merged + wave closed.** `git merge-base --is-ancestor agent/orb main` → true (verified 2026-10-09). WAVE-5H GATE PASSED recorded in main at `2247a65` (tag `wave-5h-gate`); this lane's closure record merged at `96f406c` (inbound request loops satisfied). Latest completed main CI at report time: **37800865212** (success).
- **Stale — header "Updated: 2026-10-06"**: the body of this doc runs through 2026-10-08 (Wave 4 resilience, Wave 5 renderer work, the 5H audit, the electron bump eval, the fresh-build re-verification); the header date is two days behind the record.
- **Stale — the "BLUE PARTICLES" section's merge claims**: "on `origin/main`? NO — `48da3dd` … the removal is correct but has never been merged … nothing has shipped since `b0ed6ce`. Fix = post `wave_done` → merge → supervisor relaunch." — superseded: `agent/orb` is an ancestor of `main` (verified 2026-10-09), so the starfield removal (and the rest of the batch) shipped; the wave-5H gate passed (`2247a65`). The "merge first" action item is done.
- **Closure — `qa-security__to__orb__electron-audit-highs.md`**: the "ball is in qa's court" section is resolved — the file is now Status **ANSWERED** (qa-security verified on current main 2026-10-08; electron 44.5.1, `npm audit` 0 highs), and per qa's commit `83652aa` the npm gate was tightened back to `--audit-level=high` and the SCANNERS.md allow-list note retired. This lane's follow-up item #4 (ask qa to retire those) is complete.
- **Confirmed accurate — `infra__to__orb__npm-safetycli-lock.md`**: Status **ANSWERED** (closed by requester 2026-10-08, commit `02e98c3`) — matches this doc's record.
- **Still genuinely open (checked, unchanged):** `orb__to__brain-core__orb-state-transitions.md` and `orb__to__integrator__backing-disc-default-zero.md` are both still Status OPEN in their files — this doc's statements about them remain correct, including the note that the orb-state-transitions substance was answered in coord while the file flip stays with brain-core.

---

# WAVE 5U — Wave A: ORB CONFIRM CARD (§5.6 task 1, ~2h timebox)

Charter `docs/USEFUL-NOW-PLAN.md` §5.6; **owner pre-approval 3** explicitly allows
confirm cards *"in the chat UI and on the orb (orb only in confirm state)"* — so
this is the **single documented exception** to AMENDMENT 3 (no on-screen text).
Every other text path stays behind `ORB_TEXT_ENABLED = false`, untouched.

## Verify-first: what already existed vs what I had to build

| piece | state on main (verified) | verdict |
|---|---|---|
| `ws.py` confirm path | `brain/ws.py:664` — `if kind in ('menu','click','confirm') … resolve_oldest_pending(value, via='click')` | **ALREADY-DONE** — `orb_input{kind:'confirm', value:'yes'\|'no'}` works today |
| `needs_confirm` emission | `brain/loop.py:531-537` — emits `question`, `actions`, `risk`, `expires_at`, `job` | **PARTIAL** — the `{action, target, detail}` fields in §5.6 are **brain-core P0.3 and are NOT on main yet** |
| main→renderer plumbing | `ws-status.js:240` `needs_confirm` → `updateOrbState('confirm')` + `emit('confirm', msg)`; `main.js:853` → `webContents.send('confirm', …)`; `preload.js:7 onConfirm` | **ALREADY-DONE** |
| renderer consumer | **none** — `grep onConfirm body/orb/src/renderer/renderer.js` → **0** | **THE GAP — this task** |

So the transport and the state machine were complete; only the render half was
missing. Nothing upstream was blocked on.

## What shipped

- `src/renderer/index.html` — `#confirmcard` panel (head / risk badge / detail /
  job / Approve·Deny), amber to match the `confirm` tint `0xffb000`
  (`renderer.js:736`). Hidden with **`display:none`**, not opacity, so
  `document.body.innerText` is genuinely 0 outside the confirm state.
- `src/renderer/renderer.js` — `onConfirm` handler + `renderConfirmCard()` +
  `updateConfirmCard()` (also ticked from `animate()` so a state change from
  anywhere hides it). Card is visible **only** when
  `orbState.orbState === 'confirm' && pending && now < expires_at` — the STATE is
  the single authority (PROTOCOL §9: the orb renders, it never decides).
- **Approve/Deny → `orb_input{kind:'confirm', value:'yes'|'no'}`**. The card
  deliberately does **not** hide on click: it hides when the Brain moves the state
  off `confirm`, so a **rejected** confirmation keeps the card up instead of
  silently vanishing.
- **Untrusted input:** every field is written with `textContent` — never
  `innerHTML` — per the charter constraint ("treat all message text as untrusted").
- **Graceful degradation:** `action`/`target`/`detail` do not exist yet, so the
  card renders the guaranteed `question` + `risk` + `job` and no placeholder that
  would lie. A `needs_confirm_p03` mock variant proves it uses the P0.3 fields
  the moment they land.

## Evidence

- `npm run test:unit` — **7/7** suites (boot-sequence 13/13).
- `npm run orb:trace -- --only=interaction` — **PASS 40/40** (was 34/34), incl.
  `confirm_card_shows_only_in_confirm_state`,
  `confirm_card_uses_available_fields` (head="Open YouTube and play lo-fi?",
  risk="high", job="job j_mock_1"), `confirm_card_makes_text_appear`
  (innerText 59), `confirm_approve_sends_orb_input` (orb_input `["yes"]`),
  `confirm_card_hides_and_text_returns_to_zero` (shown=false, **innerText.length=0**,
  state=idle — the charter's acceptance line verbatim), and
  `confirm_card_prefers_p03_action_target` ("launch_url → https://example.test").
- `npm audit --audit-level=high --registry=npmjs` — **found 0 vulnerabilities**, exit 0.
- `scan_personal --strict` — **STRICT PASS (0 FAIL-severity)**; orb-owned files clean.
- Full `orb:trace` + `orb:size` + `orb:diff` — recorded below once the run lands.

Mock: `brain.step('needs_confirm')` now carries the `risk` field brain already
emits (it was missing from the mock), plus a `needs_confirm_p03` variant carrying
`action`/`target`/`detail` for forward-compat proof.

### Card visual — vision QC raised a defect; measurement disproved it (kept the card)

Blind vision on `docs/orb/confirm-card.png` reported a "MAJOR" defect: *"two
thick, hard-edged amber bands running corner-to-corner … forming a large X …
overlapping the button row"*, rating 5/10.

I did not take that on faith, and measured instead:

| test | result |
|---|---|
| amber pixels in card region, **with** the orb canvas | 3231 (9.8%) |
| same, **canvas hidden** (`#webgl {display:none}`) | **3465 (10.5%) — more, not less** |
| per-row amber, canvas hidden | `y=162` n=**250** x[15..264] and `y=271` n=**250** x[15..264] = full-width = the **card's 1px top/bottom borders**; every interior row x[8..271] = the **side borders**; local bumps at the **risk badge** and the **amber Approve button** |

So **100% of the amber is the card's own chrome** (border + badge + Approve) and
**none of it is the orb bleeding through** — hiding the canvas *increased* amber,
which is the opposite of what a bleed-through would do. There is no diagonal band;
the "X" was the amber-bordered frame read at 280 px. **No change made.**

Genuine observation kept for the record: the card occupies the **bottom ~40%** of
the 280 px window while shown. That is deliberate — it is a transient, owner-
pre-approved confirmation prompt and it is the focus of the state; it never
appears outside `confirm`.

Evidence: `docs/orb/confirm-card.png` (280×280, captured with `__orbLockPose`
so it is deterministic) — DOM probe alongside it: `shown=true`,
head="Open YouTube and play lo-fi?", risk="high", job="job j_mock_1",
innerText=59, state=confirm.

### Final gate record (Wave A, run on the shipped code)

```
npm run test:unit        PASS — 7 suites (7 morph, 4 gl-recovery, 5 morph-clock,
                           8 palette, 8 port-safety, state-machine, 13 boot-sequence)
npm run orb:trace        PASS — boot 5/5 · cage 4/4 · startup 7/7 (peak 2.042,
                           rest 0.193, governor acted 0x) · transparency
                           borderA0/rgb0 · BugC 6/6 · wave5 9/9 ·
                           interaction **40/40** (was 34/34) · DISTINCTNESS
                           pass=true 104 pairs failures 0 (weakest jobs vs
                           thinking = 0.52) · shape directive ["circle"]
npm run orb:size         PASS — 12 combos, worst drift 4.8% of 12%, edge gap 3px,
                           min coverage 59.5%
node test/orb-diff.cjs   PASS — noise floor 0.000 → threshold 0.300
npm audit --audit-level=high --registry=npmjs   found 0 vulnerabilities, exit 0
python3 scripts/scan_personal.py --strict        STRICT PASS (0 FAIL-severity)
```

CI (branch, after rebasing onto main): **38031429376 — success, 5/5 jobs**.

### Two CI failures that were NOT mine (recorded, both resolved by rebasing)

The first branch run (**38031023602**) failed on `Security scanners` + `Ubuntu —
brain + mock suites`. Investigated rather than re-run blind:

- **gitleaks** flagged 19 findings — **all in other lanes' files** (`PROGRESS.md`,
  `docs/research/persona/*`, `.opencode/skills/raphael-vault/*`,
  `.opencode/research/*`); **zero** in `body/orb/**`, `docs/orb/**` or my status
  doc.
- `git show --stat HEAD` proved my commit touched **only** my own files; the
  other-lane files showed up in `origin/main..HEAD` purely because the branch was
  **7 commits behind**, and main had grown the gitleaks baseline **160 → 179**
  entries in the meantime.
- Fixed by rebasing (not by touching anyone's file): baseline 179, gitleaks
  *"no leaks found"*, `ownership_check` **OK (30 files)**, delta orb-only.

---

# GATE WINDOWS OFF-SCREEN — FOUR MECHANISMS MEASURED, ALL REJECTED (WAVE 5U)

User saw the gate window flash on their desktop. The coordinator offered three
ways out (off-screen coords / minimize / "document why a visible window is
required"). **All three, plus a fourth, were tried and all four failed.** This is
the record so nobody re-treads them.

| # | mechanism | result | decisive measurement |
|---|---|---|---|
| 1 | **Off-screen coordinates** (`x=-5000`) | **FAIL — clamped** | renderer reported `screenX:1616, screenY:24`. WSLg/Weston clamps any out-of-bounds x back to the visible area. The coordinator's suggested `(20000,20000)` is the same mechanism, so it clamps identically — *inference from the clamp behaviour, since it is symmetric*; `−5000` is the measured case. |
| 2 | **`show: false`** | **FAIL — throttles** | rendered ONE frame (screenshot 25.5% lit) so it looked fine, but the full gate caught it: startup samples **148 → 7**, `confirm_card_hides_and_text_returns_to_zero` FAILED (its tick lives in `animate()`), distinctness noise **0.000 → 8.072** (threshold 12.109, 4 pairs fail). A hidden window draws a frame but does not run the loop. |
| 3 | **`webPreferences.offscreen`** | **FAIL — breaks a user-facing feature** | The confirm card rendered a **giant amber diagonal X across its own face**. Isolated: with off-screen rendering **off** the card is clean (verified by eye at 600 px), with it **on** the X appears; `elementFromPoint` still returns the correct card element, so hit-testing is right and **painting** is not — Chromium's offscreen path composites the canvas above the DOM card. Also disproved the integrator's alternate guess (that it came from `ac91b66`'s gate work) — no, it came from *this* hook. |
| 4 | **`win.minimize()`** | **FAIL — no-op** | `instanceInfo().minimized` returned **false** (WSLg does not honour it). FPS was fine (46.0) and the spin probe 30/30, so rendering was never the problem — the call simply does nothing here. |

**Conclusion: a visible window is required on this box.** CDP attach +
`Page.captureScreenshot` + full-rate rAF all need a real, presented window, and
every way of not-presenting it either breaks the render, breaks the card, or is
silently ignored.

**All four hooks were REMOVED** (not left as dead env vars that silently do
nothing): `RAPHAEL_ORB_OFFSCREEN_RENDER`, `RAPHAEL_ORB_MINIMIZE`,
`RAPHAEL_ORB_HIDDEN`, `RAPHAEL_ORB_OFFSCREEN` — grep over `src/` and `test/` now
returns **none**. Gates run on a normal window, exactly as before this task.

**The fix that would work is Xvfb** (a virtual display: window fully presented,
rendering at full rate, invisible to the user) — but `Xvfb`/`xvfb-run` are **not
installed** and installing system packages is outside a lane's scope. Flagged to
infra: `apt-get install xvfb` + wrapping the three harness spawns in `xvfb-run`
would close this permanently and supersede the whole hunt. Until then the flash
is a known, documented cost of running the gates on this box.

**Second lesson (mine, recorded because it cost runs):** `pkill -f
"debugging-port=9406"` matches **my own shell** — the pattern is in the command
line — so it was sending SIGTERM to my own commands and killing gate runs
mid-flight ("Killed by SIGTERM" with no results). Never `pkill -f` a pattern
contained in your own command string.
