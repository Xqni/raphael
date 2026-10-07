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
