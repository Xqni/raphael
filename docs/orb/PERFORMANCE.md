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
