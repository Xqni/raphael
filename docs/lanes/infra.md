# infra — lane task list (owner: infra lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/infra.md. Requests to you: `ls docs/requests/*__to__infra__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2)) — COMPLETE 2026-10-06

- [x] Supervisor profile cloud_temp: skip Ollama/systemd bring-up, process-mode brain spawn (unit not installed), health/backoff unchanged.
      → `active_profile()` gate: non-`local` profiles issue ZERO Ollama calls (no probe, no start, no pulls/warm); brain bring-up untouched (unit LoadState probe → process mode); health/backoff code untouched. Tests assert the call surface.
- [x] Spawn honors RAPHAEL_INSTANCE-derived port/pidfile (INTERFACES §d); main defaults unchanged.
      → `supervisor/instance.py` single derivation (port/mutex/pidfiles/body lock/supervisor pidfile/log names); `RAPHAEL_INSTANCE`/`RAPHAEL_PORT`/`RAPHAEL_PIDFILE` exported to children; main values byte-identical to historical defaults (tests enforce); EXCEPTION: brain pidfile moved `/tmp` → `~/.raphael[/inst]/brain.pid` (session brief task 3; legacy kept as fallback, requests filed).
- [x] raphael CLI: bash+cmd wrappers + thin role=cli client (jobs list/get/cancel, control, typed command) — no new protocol frames.
      → `scripts/raphael` + `scripts/raphael.cmd` + `scripts/raphael_cli.py`: status/start/stop/restart/pause/resume/private on|off/logs/jobs/cancel/say/selftest; REST only (`/health /status /jobs /control`); exit codes 0/1/2; token value never printed; 20 mock-server tests.
- [x] Task "Raphael" stays Disabled: no Task Scheduler changes; uninstall/setup scripts untouched except instance awareness.
      → zero changes to `setup*.ps1`/`uninstall.ps1`/Task Scheduler/`.wslconfig`; instance awareness needs no setup edit (task env unset = `main` = current behavior).
- [x] Synthetic tests only (existing supervisor test patterns); no live stack starts.
      → `supervisor/tests/` (55 tests): derivation table, config overrides, profile/ollama call-surface, relay bind audit, kill-shell (never executes a real kill), CLI against a stdlib mock brain, selfcheck.

### Session-brief extras (same wave, all done)

- [x] Network security: Brain binds 127.0.0.1 (both modes, `RAPHAEL_BIND` escape hatch); relay audited — Windows leg 127.0.0.1 ONLY, helper leg = one specific NAT address (wildcard fallback removed, refuses to start otherwise); OPTIONAL narrow Hyper-V rule script `scripts/win/allow-brain-localhost.ps1` (TCP 8765 only — blanket `DefaultInboundAction Allow` explicitly rejected); audit + verify/rollback in `scripts/NETWORK-SECURITY.md`.
- [x] Pidfile relocation + OPTIONAL installers: `brain/raphael-brain.service` updated (no Ollama dep; `systemd-analyze verify` 0), `scripts/install-brain-unit.sh` (user+sudo, no enable/start without opt-in), `scripts/brain-sudoers.snippet` (start/stop/restart of raphael-brain only, visudo-validated) — documented, never run by agents.
- [x] Secrets hygiene: `scripts/gitleaks.toml`, `scripts/secret-scan.sh` (real run PASS: .env 600 + gitignored, 111 revisions clean), `scripts/SECRETS.md` (repo-private steps + username/hardware/schedule scrub list).
- [x] Body pinned venv: `scripts/body-requirements.txt` (8 deps pinned vs PyPI), `scripts/install-body-venv.ps1` (py -3.13/-3.12, no admin, import verifier), supervisor `body_script` prefers the venv (config `paths.body_venv` override), selfcheck `body venv` row.
- [x] Requests filed (AGENT_RULES §2): integrator ×2 (PROTOCOL §1 loopback bind sync; INTERFACES §d pidfile column), brain-core ×1 (`RAPHAEL_PIDFILE` in `brain/app.py`), qa-security ×1 (CI include of `supervisor/tests`).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  - Wave 3 (after integrator bumps `current_wave`): log rotation audit + crash reports with last-known state. NOTE: `supervisor/main.py` already ships size-cap rotation (5 MB × 3, selfcheck-verified); Wave 3 extends it to the other stack logs + adds last-known-state crash reports.
  - Wave 4: resilience scripts (kill brain/body, `wsl --shutdown`, sleep/resume) with qa-security; automatic Creative Mode (suspend heavy components when heavy apps run).
  - Wave 5: out-of-band rollback in the supervisor (not modifiable by Raphael) for the evolution pipeline.
