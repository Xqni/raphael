# scripts/ — Raphael operational scripts (owner: infra lane)

Three tiers — which ones *you* run, and which ones an agent may never run.

## Tier 1 — normal user commands (no elevation)

| script | what |
|---|---|
| `raphael` (WSL bash) / `raphael.cmd` (Windows) | stack CLI: status, start, stop, restart, pause, resume, private on\|off, logs, jobs, cancel, say, selftest — thin client over brain-core's REST API (`raphael_cli.py`) |
| `install-body-venv.ps1` | build the Body's **pinned** Python venv (system 3.10 is EOL ~2026-10); no admin; verifier built in |
| `secret-scan.sh` | secrets history/worktree scan + `.env` permission check (`--fix-perms`) — see `SECRETS.md` |
| `token-gen.sh` | generate the local auth token (value never printed) |
| `setup.sh` / `setup.ps1` / `setup-startup.ps1` / `verify.ps1` / `uninstall.ps1` | existing installer/verification family — **the scheduled task "Raphael" stays Disabled unless *you* run these** (AGENT_RULES §12) |

## Tier 2 — manual, WITH elevation (agents NEVER run these)

Elevated scripts exist to be run by the user, by hand, on purpose:

| script | what | why optional |
|---|---|---|
| `win/allow-brain-localhost.ps1` | ONE narrow Hyper-V firewall rule: Inbound, TCP **8765**, WSL VM creator only | replaces the blanket `DefaultInboundAction Allow` (rejected); enables the pure-127.0.0.1 end state — see `NETWORK-SECURITY.md` for verify/rollback |
| `install-brain-unit.sh [--enable\|--now] [--sudoers]` | install `brain/raphael-brain.service` with paths templated to your checkout; **never enables/starts without opt-in** | process mode (root-less) is the default; `--sudoers` also installs `brain-sudoers.snippet` (NOPASSWD for exactly start/stop/restart of `raphael-brain`, `visudo -cf` validated) |
| `brain-sudoers.snippet` | the scoped sudoers template itself | only needed for `paths.wsl_sudo: true` |

Nothing here touches Task Scheduler or `.wslconfig` — any such change is a
tell-the-user event (AGENT_RULES §12).

## Tier 3 — runtime components (spawned by the supervisor, not by hand)

`wsl-relay.py` (WSL helper leg of the Brain relay — binds exactly one
address, refuses wildcard), `topmost.ps1` / `topmost-watcher.ps1`,
`win/mute.ps1`, `win/make-ref-voice.ps1`, `wslg-shadow/*` — see their own
headers.

## Support files

- `NETWORK-SECURITY.md` — bind audit, relay chain, loopback-only end state.
- `SECRETS.md` — repo privacy + personal-detail scrubbing.
- `gitleaks.toml` — gitleaks rules for `secret-scan.sh` / CI.
- `body-requirements.txt` — pinned Body dependencies (installer input).

Profile `cloud_temp` applies to all of it: **no script here starts Ollama,
pulls models, or warms local models** (WAVES.md).
