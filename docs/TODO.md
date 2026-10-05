# TODO — deferred work (logged per user 2026-10-05, "worry about at the end")

Priority order after Phase 3 completes. Do not let these silently vanish.

## 1. Boot auto-start (logon registration) — DONE 2026-10-05 (user: "move ahead")
- Token generated (file-only; WSL+Windows hash-verified; token-gen.sh fixed: value now travels via STDIN — WSL->Win32 interop passes NO arbitrary env vars).
- Task "Raphael" REGISTERED (AtLogOn, State=Ready, restart-on-failure 1m x10, battery-safe, no 72h kill).
- LIVE SMOKE PASSED: Start-ScheduledTask -> supervisor -> "orb launched cmd=npm start" -> WSL bring-up + keepalive -> body/brain gracefully tolerated while missing.
- Bug found ONLY by the live smoke (review missed it): ctypes.wintypes.HCURSOR doesn't exist on py3.10 -> power hook crash -> FIXED (ctypes.c_void_p), restart verified clean.
- REMAINING: confirm on an actual reboot (next Windows logon) that the chain comes up with zero manual steps; uninstall path = scripts/uninstall.ps1.
- 2026-10-05 follow-up (4 mystery tabs + errors): task host -> pythonw.exe, all spawns -> CREATE_NO_WINDOW, orb launches WSL-side, brain unit soft-skips while not-found (Wave 2). When the brain unit is INSTALLED later: grant NOPASSWD for systemctl to dami (sudoers.d, exact argv match of supervisor's `sudo -n systemctl ...` usage) AND set `paths.wsl_sudo: true` in config.yaml — needed only then, not now.

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
