# TODO — deferred work (logged per user 2026-10-05, "worry about at the end")

Priority order after Phase 3 completes. Do not let these silently vanish.

## 0. ⏸️ RAPHAEL TEMPORARILY SHUT DOWN (user, 2026-10-05 evening) — RAM for Premiere Pro video editing
- Task "Raphael" is **Disabled** (not deleted), all her processes killed (supervisor/body/orb/brain/fish/relay/keepalive + ollama per user). Free RAM ~2.9 -> ~3.3+ GB; WSL kept alive ONLY for OpenCode (this session) + the comics vision stack needs ollama again later.
- DO NOT re-enable before the user says go. (RAM upgrade later SKIPPED — user, 2026-10-05 evening: budget tight — so revival is gated on the user's word ONLY, not on any RAM swap.)
- REVIVAL (one command set, I run it when user says go):
    Enable-ScheduledTask -TaskName 'Raphael'; Start-ScheduledTask -TaskName 'Raphael'
    (ollama auto-restarts at its next boot OR: Start-Process ollama; fish TTS pre-warms at brain startup automatically; body/orb/brain relaunch via the task.)
- RAM upgrade skipped for now → keep .wslconfig `memory=10GB` (a bump to 12GB only if/when RAM actually lands). Note: `experimental.autoMemoryReclaim=discard` is already staged in .wslconfig (backup: `~/.raphael-backups/`) — it arms at the next WSL start/reboot.

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

## 3c. Supervisor: _ExternalBody staleness — FIXED 2026-10-05
- Was: poll() hardcoded None → a crashed external body was never relaunched (observed live: old body died on binary TTS, stayed dead until a task restart).
- Now: poll() verifies the PID the body writes into its single-instance lock (%TMP%\raphael_body.lock — the rc=0 bounce pid was always dead, so the lock is the authoritative source): no lock/dead pid → -1 → body_status relaunches. Synthetic test: dead→-1, alive→None, no-lock→-1 PASS.

## 3d. Router providers: core.complete() fake-text stub — FIXED 2026-10-05 (real /api/chat + OpenAI-style calls, system persona, 400-token budget, 45s plan timeout; original note below)
- brain/router/core.py:297 literally returns `f"[{provider}:{model}] response"` — free-form chat answers are placeholder text (visible as job result "[ollama:gpt-oss:120b-cloud] response").
- config.yaml providers.chain = [zen_free, go, ollama] already configured (allow_go_runtime/allow_paid_runtime false per user directive).
- Needed (router-dev phase): real HTTP calls to zen free-tier + local ollama via the existing discovery/circuit-breaker/rate-limit scaffolding; fastpath commands unaffected (they act for real).

## 3e. Voice phase-2 (post-user-test)
- Wake word "Raphael" always-listening — DONE 2026-10-05 (user made the privacy call: always_listen: true default; VAD segmenter + phonetic wake gate + pre-roll built; PTT remains the fallback when off).
- Typed input channel: orb menu has no text entry (protocol submit_text exists); needs an orb UI affordance or the CLI (raphael/raphael.cmd not built).
- Audio cadence: continuous player verified in==out (exact on every utterance); inter-sentence gaps = fish generation latency — the real fix is §6 (TTS latency).

## 4. Minor known items
- NOACTIVATE exstyle bit doesn't stick (msrdc rewrites it) — cosmetic, TOOLWINDOW covers the ask.
- ✅ `docs/ORB_REBUILD_TASK.md` §8 checklist TICKED 2026-10-05 during the screenshot matrix pass (sanctioned by this item; evidence note added under §8).
- Band/torus experiment shaders dormant in `shaders/sage.glsl.js` (user rejected rings; kept for possible reuse).
- Reference JPGs: untracked + history-purged; keep it that way (checklist #9).

## 5. Laya decision tier — researched + benchmarked, NOT WIRED (doc-audit finding 2026-10-05)
- REALITY: `brain/` has zero `import laya` — a fastpath miss goes straight to the LLM. README/ARCHITECTURE implied the tier was live; corrected in the 2026-10-05 doc-sync pass (this section is the source of truth).
- DONE (2026-10-05): decision (user directive, addendum §12) + install (`brain/.venv`: laya 0.3.27, torch 2.14.0+cu126 — cu130 fails on driver 12.7) + GPU benchmark (44.7 ms single / 21 ms/utt batched; VRAM 1.7–2.5 GB; CPU ~935 ms = fallback only; INT8 ONNX banned for confidence-bearing use) + docs (addendum §12, `.opencode/research/laya-decision-engine.md`, `.opencode/skills/laya/SKILL.md`).
- REMAINING (Phase 1 → 2), laptop-side/free, needs user go-ahead:
  1. Advisory adapter: fastpath miss → Laya typed questions (intent/task_kind/urgency/needs_confirm) → cosmetic hints only (orb `shape_hint`, urgency scoring, pre-check hints); authoritative path unchanged. Measure real-traffic latency.
  2. Zero-shot accuracy blocks gating (delete→confirm 0.09; research/timer→out_of_scope; uncalibrated checkpoint temps) → fine-tune on own traffic labels (upstream Kaggle notebook, free GPU) + recalibrate.
  3. Phase 2 gating (voice-confirm parsing, act_req confirm probability with `min_confidence` abstention) only after 1+2 prove out.
- GPU residency: Laya (1.7–2.5 GB VRAM) must share the 8 GB card with fish-speech + whisper + ollama — load/unload policy not studied yet.

## 6. TTS latency — ask-to-audio ≈15–20 s (live-test finding 2026-10-05; user's queued next task)
- MEASURED: fish generation = 13.4 s/phrase (10.4 tok/s, GPU 1.95 GB) at 24 kHz; body playback itself is exact (in==out). Short answers ("what time is it?") feel this worst — text subtitle shows immediately, voice follows ~15 s later.
- Attack options (not yet tried): fish `--compile`/torch.compile (~2× expected), `speed_factor`, start playback when the FIRST sentence is ready instead of waiting for full generation, phrase-cache expansion.
- Related fix already shipped: brain lifespan pre-warms fish at boot (cold-spawn used to make the first reply silently drop audio — root cause of the user's "she showed text but never spoke" report).
