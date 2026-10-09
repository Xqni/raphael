# Raphael

Raphael is a local-first, voice-operated AI desktop orchestrator. She lives as a **3D Electron Orb** on your Windows desktop, powered by a **Brain** in WSL2 and a **Body** on Windows.

## 📌 Status (as of 2026-10-09)

- **Development through Wave 5 is complete.** The Wave-5H audit-hardening sprint passed its gate on 2026-10-08 (tag `wave-5h-gate`); the full record with all five exit-criteria evidence is in [docs/WAVES.md](docs/WAVES.md). All 10 lanes are merged to `main`.
- **CI is green** on both OSes including the security scanners (gitleaks / pip-audit / bandit / npm audit), and the scheduled `tests-heavy` sweep is green — see the latest runs for this repo on GitHub.
- **Electron is on 44.5.1** (bumped from 30.5.1) with **0 `npm audit` vulnerabilities** in the body/orb packages.
- **Personal-data hygiene is gated:** `python3 scripts/scan_personal.py --strict` runs in CI and in the tests-heavy workflow (FAIL-severity findings block; REVIEW-class hits are advisory).
- **The live stack is intentionally STOPPED** as of 2026-10-09 (user-directed shutdown before a laptop restart). Nothing auto-starts — the "Raphael" scheduled task is disabled and the keepalive cron was removed. Bring-up instructions: [docs/HANDOFF-2026-10-09.md](docs/HANDOFF-2026-10-09.md) §1.
- **Wave 6 is human-gated** — it does not start until the user opens it. The standing human-only items (repo visibility, PAT rotation, history-rewrite approval, branch protection, cloud-vs-RAM decision, Node-on-Windows for the orb) live in the ATTENTION register mirrored in [docs/HANDOFF-2026-10-09.md](docs/HANDOFF-2026-10-09.md) §2.

## 🌌 System Overview

Raphael is designed to be a silent, high-performance assistant that manages your computer without intrusive consoles or tabs.

- **The Orb (UI):** A 3D WebGL interface that morphs its shape and color based on Raphael's state (Idle, Speaking, Thinking, Acting).
- **The Brain (WSL2):** A FastAPI-powered core handling the agent loop, tool orchestration, and the "Fast Path" decision engine (deterministic keyword rules today; the Laya decision tier is benchmarked but **not yet wired** — see [TODO §5](docs/TODO.md)).
- **The Body (Windows):** A native Python layer handling the "physical" interaction: microphone capture, audio playback, screenshots, and UI automation.
- **The Supervisor (Windows):** A silent watchdog that ensures the entire stack starts automatically at logon and recovers from crashes.

## 🚀 Quick Start & Installation

### First Run
Raphael is configured for **zero-touch startup**. Once installed via `scripts/setup.ps1`:
1. **Logon:** Raphael starts automatically via a Windows Scheduled Task.
2. **Boot Sequence:** The Supervisor launches the Orb $\rightarrow$ wakes WSL2 $\rightarrow$ starts the Brain $\rightarrow$ launches the Body.
3. **Ready:** The Orb will transition from `starting` to `idle` within 15-30 seconds of logon.

### Dev Loop & Management
- **Restart Stack:** Stop/Start the "Raphael" Scheduled Task via Task Scheduler or PowerShell:
  ```powershell
  Stop-ScheduledTask -TaskName 'Raphael'
  Start-ScheduledTask -TaskName 'Raphael'
  ```
- **Brain Respawn:** To force-restart the brain without a full task cycle:
  ```bash
  kill $(cat /tmp/raphael-brain.pid)
  ```

## ⌨️ Hotkeys

| Action | Key Combo | Behavior |
| :--- | :--- | :--- |
| **Kill GUI** | `Ctrl+Alt+Shift+K` | Momentary; closes the Orb immediately |
| **Pause** | `Ctrl+Alt+P` | Persistent; stops Raphael from listening/acting |
| **Private Mode** | `Ctrl+Alt+Shift+P` | Persistent; disables all cloud-based LLM calls |
| **Push-to-Talk** | `Ctrl+Alt+Space` | Fallback mic input — always-listen is the default (`voice.always_listen: true`); hold to talk when it is off |

## 🧪 Verification & Testing

Entry points from their respective environments (Wave-5H-era state; the full
pre-push battery lives in [docs/HANDOFF-2026-10-09.md](docs/HANDOFF-2026-10-09.md) §5):

- **Brain Logic:** `cd brain && ./.venv/bin/pytest`
- **Integration Tests:** `cd tests && ./.venv/bin/python -m pytest -q .` (conftest puts the repo root on `sys.path`)
- **Body Control E2E:** `python body/win/e2e_control.py`
- **Full Wave-2 E2E:** `python tests/e2e_wave2.py` (Requires running stack + muted audio — the stack is currently stopped, see Status above)
- **Personal-data gate:** `python3 scripts/scan_personal.py --strict` (must print STRICT PASS; FAIL-severity findings block, REVIEW is advisory)
- **Core Guard:** `python3 tests/core_guard.py` (must print Core Guard OK)
- **CI:** every push re-runs the suites on both OSes plus the security scanners; `tests-heavy` also runs the strict personal-data gate and a cloud mock sweep.

## 🗺️ Documentation Map

- **[HANDOFF-2026-10-09.md](docs/HANDOFF-2026-10-09.md):** where things stand right now — stack state, human-only ATTENTION list, open threads, verify-before-you-push battery.
- **[WAVES.md](docs/WAVES.md):** wave state machine + gate records (`wave-3-gate` … `wave-5h-gate`).
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md):** Process topology, directory ownership, and the "Fast Path" logic.
- **[PROTOCOL.md](docs/PROTOCOL.md):** The binary and JSON wire-spec for Brain $\leftrightarrow$ Body $\leftrightarrow$ Orb communication.
- **[PERFORMANCE.md](docs/orb/PERFORMANCE.md):** Verified GPU/CPU footprints and frame-time governor data.
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md):** Common failure modes (Firewalls, WSLg, Process locks).
- **[TODO.md](docs/TODO.md):** Current gaps and pending user actions.

## ⚠️ Known Gaps
- **Firewall:** Hyper-V may block the built-in WSL localhost relay (see Troubleshooting).
- **Brain Unit:** The systemd unit is not yet installed; the supervisor currently uses process-mode spawning.
- **Laya decision tier:** researched + benchmarked + installed, but not yet wired into the fast path (TODO §5).
- **Voice latency:** Fish TTS generates ≈13 s/reply → ask-to-audio ≈15–20 s (acceleration queued, TODO §6).
- **Typed input:** no text entry yet — orb menu affordance / `raphael` CLI not built (TODO §3e).
- **Run state:** the whole stack is intentionally STOPPED as of 2026-10-09 (user-directed, before a laptop restart); nothing auto-starts — task "Raphael" Disabled, root WSLg service disabled, keepalive cron removed (backup outside git at `~/.raphael-coord/crontab.keepalive.bak`). Revival steps: [docs/HANDOFF-2026-10-09.md](docs/HANDOFF-2026-10-09.md) §1 — TODO §0.
