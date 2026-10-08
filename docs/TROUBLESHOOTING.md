# Troubleshooting Guide

This guide covers common failure modes for the Raphael stack, based on Wave 2 integration findings.

## 🌐 Connectivity & Networking

### Brain Unreachable (Connection Refused)
**Symptoms:** Orb shows `reconnecting` or `offline`; Supervisor logs "brain healthy" check fails.
- **The Hyper-V Firewall Trap:** By default, Windows often blocks the built-in WSL localhost relay. If `127.0.0.1:8765` is refused but the WSL IP (e.g., `172.x.x.x:8765`) connects, this is the cause.
- **Workaround:** The Supervisor implements a user-space relay (`paths.brain_relay: true` in `config.yaml`). This splices traffic from Windows `127.0.0.1:8765` $\rightarrow$ WSL `0.0.0.0:8766` $\rightarrow$ Brain `127.0.0.1:8765`.
- **Permanent Fix (narrow, SEC-6):** run `scripts/win/allow-brain-localhost.ps1`
  (elevated once) — creates a scoped inbound rule for TCP 8765 from the WSL/Hyper-V
  creator only — OR switch `networkingMode=mirrored` in .wslconfig and restart WSL.
  Then set `paths.brain_relay: false` in `config.yaml`.
  **Rejected:** `Set-NetFirewallHyperVVMSetting … -DefaultInboundAction Allow` — it
  opens ALL inbound traffic to the VM (blanket Allow). Kept here only as the explicit
  non-recommendation (see `scripts/NETWORK-SECURITY.md`).

## 🖥️ Process & Windowing

### Mystery Terminal Tabs
**Symptoms:** Windows Terminal opens several tabs (Supervisor, Keepalive, etc.) on startup.
- **Cause:** Standard `python.exe` and `cmd.exe` spawns often trigger a visible console window in Windows 11.
- **Fix:** Ensure the Supervisor is running via `pythonw.exe` and all child processes are spawned with the `CREATE_NO_WINDOW` flag. If tabs appear, restart the "Raphael" task.

### Orb Not Visible / Not Topmost
**Symptoms:** The Orb is hidden behind other windows or doesn't appear.
- **WSLg Shadows:** Some WSLg versions bake a 32px shadow margin into the frame, which can confuse "topmost" scripts. This is fixed via the `WESTON_RDP_WINDOW_SHADOW_REMOTING=0` environment variable (applied via the `/usr/bin/weston` wrapper).
- **Topmost Re-assertion:** The Orb re-asserts its `HWND_TOPMOST` status every 30 seconds. If it's missing, check if the `msrdc` process is running.

### Brain Not Listening
**Symptoms:** `logs/supervisor.log` shows "brain unit NOT active" or "health check failed".
- **Check PID:** Run `ls /tmp/raphael-brain.pid` in WSL. If missing, the brain isn't running.
- **Logs:** Check `logs/brain.log` for Python tracebacks.
- **Process-Mode:** Until the systemd unit is fully installed, the supervisor spawns the brain in process-mode. If it fails to start, check if port 8765 is already bound.

## 🔊 Audio & Voice

### Body Silent / No Audio
**Symptoms:** Brain sends `speak` events, but no sound is heard.
- **Stale Locks:** If the Body was force-killed, a stale `.lock` file might prevent it from restarting. The Body is designed to reclaim locks if the PID inside is dead, but check `logs/body.log` for "single-instance" errors.
- **TTS Path:** Raphael uses a Fish-Speech server on port `:8777`. Verify the server is reachable from the Body.
- **Mute Helper:** For automated tests, the `scripts/win/mute.ps1` script is used to protect the user. Verify your system volume isn't muted if you're testing manually.

## 🔑 Tokens & Secrets

### Token Mismatch
**Symptoms:** 401 Unauthorized errors in `logs/supervisor.log` or `logs/body.log`.
- **Paths:** 
  - WSL: `~/.raphael/token`
  - Windows: `%APPDATA%\Raphael\token`
- **Verification:** The `token-gen.sh` script ensures both files are identical hashes. If you suspect a mismatch, re-run the token generation process.
- **Security:** Tokens are never logged in plain text.

## 🛠️ Recovery Commands

| Problem | Command |
| :--- | :--- |
| Restart everything | `Stop-ScheduledTask -TaskName 'Raphael'` $\rightarrow$ `Start-ScheduledTask -TaskHame 'Raphael'` |
| Kill Brain | `kill $(cat /tmp/raphael-brain.pid)` (in WSL) |
| Force Body restart | Kill `python.exe` (Body process) and restart the Task |
| Reset WSLg Fix | `wsl --shutdown` (resets the system distro overlay) |
