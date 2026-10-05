# TODO — deferred work (logged per user 2026-10-05, "worry about at the end")

Priority order after Phase 3 completes. Do not let these silently vanish.

## 1. Boot auto-start (logon registration)
- Raphael should "start on her own" at Windows logon.
- Mechanism exists: `scripts/setup.ps1` Task Scheduler registration (+ `setup-startup.ps1` Startup-folder fallback) — NEVER executed yet (dry-run only).
- Gate: user approval required (registers a real logon task). Include `scripts/uninstall.ps1` in the same session.
- Verify after: orb alive after a fresh reboot without manual launch; single-instance + watcher + dock all come up.

## 2. Performance tuning + measurement (spec §5) — PARTIALLY DONE (GPU achieved 2026-10-05)
- ✅ GPU acceleration in dev: MESA_LOADER_DRIVER_OVERRIDE=d3d12 + sandbox flags → ANGLE/D3D12 on Intel Iris Xe, dpr 1.0, CPU dropped 136→15.7% (idle). Flags persisted in package.json scripts.
- ⬜ Windows-native measurement (orb runs on REAL Windows GPU there): idle <2% GPU / <1% CPU formal numbers.
- ⬜ Frame-time-based runtime auto-downshift governor (spec: "automatic downgrade if frames are slow") — only GPU-type detection exists.
- ⬜ WSLg bridge overhead breakdown (streaming + msrdc sit outside the electron process sum).
- Current status: never measured properly. Method ideas: Windows-side GPU counter (DXGI/Task Manager trace), process CPU via PowerShell sampling, fps/frame-time readout (hidden eval — on-screen FPS was removed per user).
- Quality tiers (orb.quality auto|low|medium|high) wired but untested against real frame-time data.

## 3. Deliverables debt (original spec §7)
- **Screenshot matrix**: every state × {dark, light, busy} backgrounds -> `docs/orb/` (method: DevTools Page.captureScreenshot + demo bg toggle via `window.__orbDemo.setBg`).
- **Performance report**: `docs/orb/PERFORMANCE.md` (measurements + method + WSL caveat).

## 4. Minor known items
- NOACTIVATE exstyle bit doesn't stick (msrdc rewrites it) — cosmetic, TOOLWINDOW covers the ask.
- `docs/ORB_REBUILD_TASK.md` fidelity checklist §8 never formally ticked by reviewer (most items effectively verified through the user review loop — close it during the screenshot matrix pass).
- Band/torus experiment shaders dormant in `shaders/sage.glsl.js` (user rejected rings; kept for possible reuse).
- Reference JPGs: untracked + history-purged; keep it that way (checklist #9).
