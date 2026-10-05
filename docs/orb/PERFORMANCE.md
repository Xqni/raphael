# Raphael Orb — Performance Report (Phase 7)

**Date:** 2026-10-05 · **Build:** `main` (Answer Mode final form) · **Window:** 280×280 (content 200), dpr per tier

## Environment (read this before comparing to targets)

Dev environment = **WSL2 + SwiftShader (software GL, `--disable-gpu`)** — the WSLg GPU
compositor path is broken on this box (viz errors documented in PROGRESS), so all
rasterization runs on the CPU. **GPU% targets from the spec are not measurable here**;
formal on-hardware measurement is tracked in `docs/TODO.md` (item 2, Windows-native).

## Method (reproducible)

- **FPS**: `window.__orbStats().frame` = `renderer.info.render.frame`. The pipeline
  renders twice per animation frame (scene→offscreen RT, edge-mask→canvas), so
  `FPS = Δframe / (2 × seconds)`. Samples: 1.6 s settle + 3 s window.
- **CPU%**: sum of `utime+stime` across all `electron` processes from `/proc/<pid>/stat`
  (100 ticks/s), delta over 3 s → % of one core. Includes SwiftShader raster work.
- **Draw budget**: scene-pass `renderer.info.render.calls/triangles` cached after the
  scene render (the mask pass resets `renderer.info`).

## Results (quality = auto)

| State | FPS | CPU (% of one core) | Notes |
|---|---|---|---|
| idle | ~25–30 | ~136% | FPS is **limiter-bound** (spec: 30 idle; 16.7 ms vsync grid jitter) |
| thinking | ~46 | ~261% | measured pre-auto-detect (dpr 1.0) |
| speaking (amp 0.5) | ~47 | ~437% | peak layers + Answer Mode, measured at dpr 1.0 |
| idle @ quality=low | ~25–30 | ~123% | dpr 0.5 — CPU −13%, FPS unchanged (limiter-bound) |

**Draw budget (scene pass):** idle **46 calls / 3,572 tris** · peak speaking **78 calls / 22,052 tris** @ 280².

## Quality tiers (spec §5)

- `orb.quality: auto|low|medium|high` → dpr `auto|0.5|1|2`.
- **Auto now detects software GL** (`WEBGL_debug_renderer_info` → SwiftShader/llvmpipe → dpr 0.75,
  verified live: `dpr 0.75, canvas 210×210`), so dev machines don't overfill raster.
- Runtime *frame-time-based* downshift: **not implemented** — see TODO item 2.

## Targets vs actual

| Spec target | Status |
|---|---|
| idle < 2% GPU / < 1% CPU (typical iGPU) | **Gap: not measurable in this environment** (software GL folds raster into CPU). Draw budget (≤78 calls / ≤22k tris) is far inside any iGPU envelope; formal measurement deferred to Windows-native per TODO. |
| 60fps active / 30fps idle | Limiter configured exactly so; idle measured ≈25–30 (vsync-grid-bound); active ~46–47 under SwiftShader — expected to hit 60 on hardware GL. |
| Pause when hidden | Implemented (`document.hidden` early-return). |
| No per-frame allocation / textures once | Held (zero-alloc update paths; atlas/canvas textures created at init). |

**Honest verdict:** performance *architecture* meets the spec; raw numbers await on-hardware measurement (TODO item 2), and a frame-time auto-downshift governor is the remaining tuning gap (also TODO item 2).
