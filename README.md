# Raphael

Raphael is a local-first, voice-operated AI desktop orchestrator. She lives as a **3D Electron Orb** on your Windows desktop, powered by a **Brain** in WSL2 and a **Body** on Windows.

## 🌌 System Overview

Raphael is designed to be a silent, high-performance assistant that manages your computer without intrusive consoles or tabs.

- **The Orb (UI):** A 3D WebGL interface that morphs its shape and color based on Raphael's state (Idle, Speaking, Thinking, Acting).
- **The Brain (WSL2):** A FastAPI-powered core handling the agent loop, tool orchestration, and the "Fast Path" decision engine (Laya).
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
| **Push-to-Talk** | `Ctrl+Alt+Space` | Reserved for Voice Phase 3 |

## 🧪 Verification & Testing

Run these from their respective environments to verify the current Wave 2 state:

- **Brain Logic:** `cd brain && ./.venv/bin/pytest`
- **Integration Tests:** `cd tests && ./.venv/bin/pytest`
- **Body Control E2E:** `python body/win/e2e_control.py`
- **Full Wave-2 E2E:** `python tests/e2e_wave2.py` (Requires running stack + muted audio)

## 🗺️ Documentation Map

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md):** Process topology, directory ownership, and the "Fast Path" logic.
- **[PROTOCOL.md](docs/PROTOCOL.md):** The binary and JSON wire-spec for Brain $\leftrightarrow$ Body $\leftrightarrow$ Orb communication.
- **[PERFORMANCE.md](docs/orb/PERFORMANCE.md):** Verified GPU/CPU footprints and frame-time governor data.
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md):** Common failure modes (Firewalls, WSLg, Process locks).
- **[TODO.md](docs/TODO.md):** Current gaps and pending user actions.

## ⚠️ Known Gaps (Wave 2)
- **Firewall:** Hyper-V may block the built-in WSL localhost relay (see Troubleshooting).
- **Assets:** `assets/raphael_reference.wav` is pending user delivery.
- **Brain Unit:** The systemd unit is not yet installed; the supervisor currently uses process-mode spawning.
