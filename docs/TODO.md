# TODO — deferred work (logged per user 2026-10-05, "worry about at the end")

Priority order after Phase 3 completes. Do not let these silently vanish.

## 1. Boot auto-start (logon registration) — DONE 2026-10-05 (user: "move ahead")
- Token generated (file-only; WSL+Windows hash-verified; token-gen.sh fixed: value now travels via STDIN — WSL->Win32 interop passes NO arbitrary env vars).
- Task "Raphael" REGISTERED (AtLogOn, State=Ready, restart-on-failure 1m x10, battery-safe, no 72h kill).
- LIVE SMOKE PASSED: Start-ScheduledTask -> supervisor -> "orb launched cmd=npm start" -> WSL bring-up + keepalive -> body/brain gracefully tolerated while missing.
- Bug found ONLY by the live smoke (review missed it): ctypes.wintypes.HCURSOR doesn't exist on py3.10 -> power hook crash -> FIXED (ctypes.c_void_p), restart verified clean.
- VERIFIED ON REAL REBOOT (2026-10-05): no console/tabs, supervisor pythonw at boot+23s, orb up ~10-15s after logon, zero manual steps. DONE. Uninstall path = scripts/uninstall.ps1.
- 2026-10-05 follow-up (4 mystery tabs + errors): task host -> pythonw.exe, all spawns -> CREATE_NO_WINDOW, orb launches WSL-side, brain unit soft-skips while not-found (Wave 2). When the brain unit is INSTALLED later: grant NOPASSWD for systemctl to dami (sudoers.d, exact argv match of supervisor's `sudo -n systemctl ...` usage) AND set `paths.wsl_sudo: true` in config.yaml — needed only then, not now.

## 2. Performance tuning + measurement (spec §5) — DONE 2026-10-05
- ✅ GPU acceleration (dev): MESA/d3d12 → ANGLE/D3D12 on Iris Xe, dpr 1.0, CPU 136→15.7%.
- ✅ Windows-native idle numbers: GPU ≤0.5%, electron 0.0–0.1% CPU, msrdc 0.52%, system 3.65% — all in PERFORMANCE.md with methods + caveats (targets MET).
- ✅ Frame-time governor shipped + runtime-validated (acted:0 through 33 morphs; apply path code-reviewed) — PERFORMANCE.md "Frame-time governor".
- ✅ WSLg bridge breakdown: msrdc (streaming) + vmwp attribution documented.
- ✅ Quality tiers exercised live via governor ladder (auto rung snap + ceiling verified).

## 3. Deliverables debt (original spec §7) — DONE 2026-10-05
- ✅ Screenshot matrix: 33 shots (11 states × dark/light/busy) in `docs/orb/matrix/` via reusable harness `body/orb/test/orb-matrix.cjs` (CDP, port 9333, `npm run orb:demo`). Vision-QC + size sanity: no blanks.
- ✅ Performance report: `docs/orb/PERFORMANCE.md` extended with Windows-native numbers + governor + bridge breakdown.

## 3b. USER ACTION (when awake — non-blocking, relay already works around it)
- Hyper-V firewall blocks WSL's built-in localhost relay on this machine. The supervisor's user-space relay (paths.brain_relay) covers everything meanwhile.
- Optional one-liner (elevated PowerShell), then set `paths.brain_relay: false` in config.yaml and restart the Raphael task:
  Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow

## 3c. Supervisor: _ExternalBody staleness (found live 2026-10-05)
- After a single-instance rc=0 handoff procs['body'] becomes _ExternalBody whose poll() hardcodes None — if that external body later DIES the supervisor never notices (observed: old body crashed on binary TTS, no respawn until a task restart).
- Fix direction: periodic re-verify of external bodies, or treat externals as unmanaged-with-notice.

## 4. Minor known items
- NOACTIVATE exstyle bit doesn't stick (msrdc rewrites it) — cosmetic, TOOLWINDOW covers the ask.
- ✅ `docs/ORB_REBUILD_TASK.md` §8 checklist TICKED 2026-10-05 during the screenshot matrix pass (sanctioned by this item; evidence note added under §8).
- Band/torus experiment shaders dormant in `shaders/sage.glsl.js` (user rejected rings; kept for possible reuse).
- Reference JPGs: untracked + history-purged; keep it that way (checklist #9).
