# Raphael Orb — Performance Report (Phase 7, GPU path)

**Date:** 2026-10-05 · **Build:** `main` (Answer Mode final) · **Window:** 280×280 (content 200) · **dpr:** 1.0 (full quality)

## GPU acceleration (the fix for dev-env pixelation)

The original WSLg GPU path crashed Chromium's GPU process (viz_main_impl), forcing
`--disable-gpu` + SwiftShader (software raster, dpr cut to 0.75 = visible pixelation).
**Resolved** by three combined changes, now baked into every npm script:

```
MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 electron . \
  --no-sandbox --disable-gpu-sandbox --ignore-gpu-blocklist
```

- sandbox flags → GPU process no longer crashes (0 crashes across runs)
- Mesa d3d12 driver override → ANGLE lands on the hardware GPU
- **Verified GL:** `ANGLE (Microsoft Corporation, D3D12 (Intel(R) Iris(R) Xe Graphics), OpenGL 4.1)` — hardware accelerated; quality auto-detect no longer matches software → **dpr 1.0, full resolution**

## Results (GPU path, quality=auto, dpr 1.0)

| State | FPS | CPU (% of one core) |
|---|---|---|
| idle | ~25 (limiter target 30) | **15.7%** |
| thinking | ~49 | **22.7%** |
| speaking (amp 0.5) | ~47 | **27.3%** |

**Before (SwiftShader, dpr 0.75):** idle 136% · thinking 261% · speaking 437% CPU.
→ **10–17× CPU reduction**, full resolution restored.

**Draw budget (scene pass):** idle 46 calls / 3,572 tris · peak speaking 78 calls / 22,052 tris @ 280².

## Method

- FPS = `Δwindow.__orbStats().frame / (2 × seconds)` (two renders per frame: scene→RT, mask→canvas).
- CPU = `/proc/<pid>/stat` utime+stime delta across electron processes (100 Hz), % of one core.

## Targets vs actual (honest)

| Spec target | Status |
|---|---|
| idle < 2% GPU / < 1% CPU (typical iGPU) | CPU now **15.7% one-core in dev** (includes WSLg bridge + Electron main + driver overhead; raster offloaded). Full on-hardware Windows-native measurement + WSLg overhead breakdown deferred to `docs/TODO.md` item 2. |
| 60fps active / 30fps idle | Idle = limiter-bound (~25–30, vsync-grid); active ~47–49 under WSLg streaming. Windows-native expected to cap at display refresh (unverified — TODO item 2). |
| Pause when hidden | ✅ implemented. |
| Quality tiers | ✅ auto/low/medium/high = dpr auto/0.5/1/2; **auto now hardware-aware** (software GL → 0.75 fallback kept for broken environments). |
| Runtime frame-time downshift | Not implemented (TODO item 2). |

## Windows-native idle numbers (2026-10-05, production orb via supervisor)
Measured on the logon-boot production instance (WSLg/msrdc presentation, quality=auto):

| Metric | Method | Result | Target | Verdict |
|---|---|---|---|---|
| GPU (all engines, Windows counters) | 10×3s samples | max ≈0–0.5% (idle only) | <2% idle | **MET** |
| electron CPU (WSL `/proc` deltas) | 2×5s | **0.0–0.1%** idle (≈6% during boot animation) | <1% idle | **MET** |
| WSLg bridge `msrdc` CPU | 6×2s avg | 0.52% | — (new number) | — |
| supervisor `pythonw` CPU | 6×2s | ~0% | ~0 | **MET** |
| Total system CPU | 6×2s avg | 3.65% (incl. dwm 4.6% desktop baseline) | — | — |
| Render path | `__orbStats` | ANGLE/**D3D12** Intel Iris Xe, dpr 1.0, 280², 46 calls / 3572 tris | hardware GL | **MET** |

Caveats: `vmmemwsl` (whole-WSL VM) read 24% during sampling because the orchestration
session (OpenCode + build agents) runs inside the same WSL instance — at true logon-idle
the orb-only VM cost is ~1–3%. WSL d3d12 work is attributed by Windows to `vmwp` (VM
worker), not to electron (no Windows PID); bridge = `msrdc` (RDP streaming) + vmwp copy.

## Frame-time governor (spec §5: automatic downgrade if frames are slow)
Implemented in `renderer.js`, active only for `quality=auto`: EMA of achieved frame
intervals vs the current target interval (60fps active / 30fps idle). Sustained >1.6×
target for ~1.5s → downshift one pixel-ratio rung (0.5 < 0.75 < 1 < 1.5 < 2) with a 4s
cooldown; sustained <1.15× for ~6s → climb back, **capped at the startup rung** (never
above what the GPU was trusted with). The edge render target follows every tier change
(`resizeEdgeRT` captured in a closure — it is function-scoped inside `initScene`).
Observability: `__orbStats().gov` = `{on, dpr, ceiling, ema, acted, slow, fast}`.

Runtime validation (2026-10-05, demo instance): `{"on":true,"dpr":1,"ceiling":1,"ema":43,"acted":0}`
through the full 33-shot state-morph matrix — correct ladder snap, **zero spurious shifts**.
The downshift *apply* path is code-reviewed but not artificially forced (no load generator on
this GPU); if it ever triggers in the wild it shows as `acted>0` + a lower `dpr`.

---

# §2 Motion blur — cost report (fidelity pass, 2026-10-06)

Build: `agent/orb` · instance `orb` · window 280×280 (content 200) · dpr 1.0 ·
quality `auto` · `orb.motion_blur: auto` · measured by `npm run orb:trace`
(`docs/orb/trace/blur-perf.json`), rolling EMA of real animation-tick
intervals, 2.5 s per condition after a 1.6 s settle.

## Design (why it is cheap)

- **Velocity gated.** `amount = clamp((speed − 0.35) / (1.60 − 0.35), 0, 1)`
  where `speed` = the physical assembly spin (`spin.omega`, rad/s), raised to
  0.55 while Answer Mode is on and 0.45 while the Data Rings are on. Below
  0.35 rad/s — i.e. the idle rest spin of 0.18 rad/s — the gate returns *calm*
  and **the pass is not executed at all**.
- **One LOW-RES pass.** `edgeRT → blurRT` at **half resolution**, 4 taps
  (2/3/6 for low/medium/high tiers, 0 on quality `low`), sampling the already
  rendered scene at tangential offsets around the window centre — an angular
  blur, which is what a spinning overlay actually needs. There is **no**
  full-resolution post chain: the existing edge-mask pass just mixes
  `tScene` with `tBlur` when `uBlur > 0`.
- **Premultiplied alpha throughout**: the shader only averages premultiplied
  RGBA, so rgb and alpha decay together and a smear over a transparent region
  stays transparent.
- **Gates that turn it off:** `orb.motion_blur: off`, `reduced_motion: true`,
  quality tier `low`, and the frame-time governor (if it has already
  downshifted the pixel ratio, the tap budget drops to 2).

## Measured

| condition | frame time (EMA) | notes |
|---|---|---|
| **idle** (rest spin 0.18 rad/s) | 16.670 ms | gate = **`calm`** → pass skipped, `uBlur = 0` → **idle cost unchanged** |
| active (speaking), blur **OFF** | 16.677 ms | baseline |
| active (speaking), blur **FORCED ON** | 16.671 ms | worst case (`amount = 0.9`, 4 taps) |

**Overhead: −0.04% (no measurable change).** The display is vsync-locked at
60 Hz, so this reads as "the blur fits inside the existing frame budget" — if
it did not, the tick interval would stretch past 16.67 ms. It does not.

Against the budget in the brief (**≤ 25% added to active-state frame time**):
**−0.04% measured, 25% = ~4.2 ms of headroom unused.** No taps or resolution
were reduced to fit.

`__orbMotionBlur()` reports `{amount, angle, taps, skipped, reason, speed}` per
frame; reasons seen: `calm`, `on`, `reduced_motion`, `motion_blur-off`,
`quality-tier`, `override-off`.

## Quality tiers / controls (not re-measured — they only ever reduce work)

| setting | taps | blur RT |
|---|---|---|
| `orb.motion_blur: auto` + `quality: auto` | 4 | ½ resolution |
| `motion_blur: low` | 2 | ½ |
| `motion_blur: high` | 6 | ½ |
| `quality: low` | **0 (off)** | not rendered |
| `quality: medium` | 3 | ½ |
| `quality: high` | 6 | ½ |
| governor has downshifted | ≤ 2 | ½ |
| `reduced_motion: true` / `motion_blur: off` | **0 (off)** | not rendered |

## Transparency with blur on (§4)

`gl.readPixels` on the drawing buffer (a CDP screenshot of a transparent page
comes back empty in this WSLg/ANGLE environment, so screenshots are useless
for alpha) — blur **forced on**, outermost 2 px of the canvas:

| scene | max border alpha | max border RGB | lit px |
|---|---|---|---|
| idle | 0 | 0 | 4830 |
| speaking | 0 | 0 | 9269 |
| error | 0 | 0 | 3935 |
| paused | 0 | 0 | 1719 |
| reconnecting | 0 | 0 | 2028 |

Budget: border alpha ≤ 16, border RGB ≤ 24, lit px ≥ 200 (so the check cannot
pass vacuously). **PASS** — no box, no fringe, no clipping at the window edge
in any state with the blur on.

## Frame-time governor — not regressed

Still active for `quality: auto`, unchanged ladder (0.5 < 0.75 < 1 < 1.5 < 2),
EMA vs target interval, 90 slow frames → downshift with a 4 s cooldown, 360
fast frames → climb, capped at the startup rung. Two additions:

1. it is **frozen while the startup spin-down is in progress** (`spin.phase !==
   'run'` or state `starting`) — a mid-startup dpr change is exactly the
   "animation visibly hitches" cause from §1, and the startup assertions
   include `governor_quiet: 0 actions`;
2. when it *has* downshifted, it also cuts the motion-blur tap budget.

Runtime validation: `gov.acted = 0` across the whole 8 s startup window and
`dpr` held at 1.0 through every one of the 86 per-state captures.
