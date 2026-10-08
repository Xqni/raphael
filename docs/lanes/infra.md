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

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [x] [P0-BugG] Bring-up/teardown pid hygiene (docs/BUGS-WAVE2.md Bug G): stale pid files made `kill $(cat /tmp/raphael-brain.pid)` silently no-op and `raphael stop` call a LIVE supervisor "dead" (WSL cannot see Windows pids) — resolve real pids via `ss -tlnp` / PowerShell side; supervisor must track the ACTUAL orb pid (integrator relaunched orb manually during E2E — next bring-up is supervisor-only). Ensure stop() leaves ZERO processes on both sides.
      → kill shell now layers pidfile → **`ss -tlnp` port resolution** (cmdline-verified) → guarded pgrep (relative AND absolute venv paths); `_pid_exists` probes **both namespaces** on WSL (`os.kill` + `tasklist.exe`); supervisor pidfile carries a `side=windows|linux` marker (legacy single-line files: a Windows pid is taskkill-verified via PowerShell CommandLine first — **refuses** unverified pids); `stop_wsl_side()` tears down orb (cwd-verified to this repo), the instance-scoped relay helper and keepalive loops, and self-reports survivors (exit 1) — `raphael stop` fails unless the endpoint is down AND wsl-side is clean; `launch_orb` **adopts** an already-running orb (no double-spawn) + writes `~/.raphael[/inst]/orb.pid`; heartbeat resolves the REAL electron pid (one wsl round-trip per heartbeat, never per tick). Tests: `supervisor/tests/test_bug_g_pid_hygiene.py` (16) + updated lifecycle/CLI tests.
- [x] [SPEED] Supervisor restart/reconnect loops stay tight — no long backoffs in normal operation (Rule 15).
      → `backoff_cap` 300 s → **60 s**, PERMANENT_ERROR `slow_interval` 60 s → **15 s** (base 5 s / health tick 5 s / heartbeat 300 s unchanged; contracts pin no numbers — verified against PROTOCOL/ARCHITECTURE); recovery PROBES stay at 5 s, only restart issuance/backoff changed. Pinned by `test_speed_defaults_no_long_backoffs`.

### Wave 3 follow-ups (2026-10-07)

- [x] Answered qa-security's two OPEN requests with post-merge evidence (both tripwires now XPASS): `qa-security__to__infra__ollama-profile-gate` (DONE), `qa-security__to__infra__instance-derivation` (DONE — infra slice; residual xfail = `brain/app.py` literal, brain-core's split).

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Supervisor resilience drills per WAVES wave-4: kill storms (brain/body/orb rapid-kill loops), WSL churn + network-change recovery, crash-recovery (supervisor self-restart), zero-orphan invariant under repeated bring-up/teardown cycles.
      → **All four drills + mechanism fixes, synthetic only** (live stack untouched per wake directive — no servers spawned, no request needed):
      • **crash recovery**: default `main.py` run = watchdog parent spawning the real bring-up as child (`RAPHAEL_SUPERVISOR_CHILD`), respawns on unexpected exit, crash-loop guard gives up loudly after 5 rapid crashes, SIGTERM forwarded; **Task Scheduler wiring unchanged** (Rule 12); `RAPHAEL_WATCHDOG=0` opt-out. Child writes the PARENT pid (tree-kill root) into `run/supervisor.pid` so `raphael stop` kills watchdog+child together; parent self-crash needs external relaunch (documented boundary). **Active from the next supervisor start after merge** (live stack still runs pre-Watchdog code — no restart forced).
      • **kill storm**: threaded run_health_loop with mocked probes/launchers — restarts cap exactly at `max_attempts`, PERMANENT_ERROR latch holds under continued failure, network hook recovers, auto-resume issues fresh restarts, loop stops on demand.
      • **churn**: `resume` hook lifts PERMANENT_ERROR + immediate re-verify even with 999 s poll interval (Rule 15).
      • **zero-orphan**: 5 spawn/teardown cycles → ZERO marker-scoped leftovers each cycle, while an untagged control process survives every cycle (teardown scoping proven; bracket-pattern self-match guard; full cleanup in `finally`).
      → `supervisor/tests/test_resilience_drills.py` (6 tests, 4.1 s).

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Tier/simulation rollout plumbing: config.d tier switching at runtime (safe restart semantics), simulation job scheduling/supervision, shadow-instance row support WHEN brain-core lands it (port 8911).
      → **CLI `raphael tier` (safe runtime switch):** show current `persona.tier` + whether the running brain has it; set = fail-closed validation (only `great_sage|raphael|ciel`, mirrors the loader's C1/C2 — unknown/`GOD`/empty never written), surgical single-line edit of `config.d/evolution-persona.yaml` (refuses unless EXACTLY one `tier:` line; `max_tokens_tier` and comments untouched; atomic tmp+replace), **active-jobs guard** (REFUSED with the job list; `--force` = explicit informed override), then a **single-spawner recycle**: supervisor alive → verified kill only (its health loop respawns — never a double-spawn race); supervisor absent → local respawn; waits healthy (~24 s headroom for a latched backoff, Rule 15) and reports old→new. Brain-down switch = write + "applies at next start" (no pointless recycle). No new protocol frames (pure config + existing REST).
      → **Simulation supervision:** `raphael jobs <id> --wait [--timeout N]` polls to a terminal state at 0.4 s (prints status/stage/progress transitions + a confirm-hint while `awaiting_confirm`); exit 0 only on `done` (prints a truncated result), non-zero on failed/cancelled/interrupted + `error_code`, EXIT_DOWN if the brain vanishes mid-wait.
      → **Shadow readiness (8911, carried item):** an instance WITHOUT a §d row now **fails closed** in `load_config` unless `RAPHAEL_PORT` is explicit (old behavior silently fell back to 8765 = collision with live main; aligned with brain-core's `port()` and qa's "never guess a port"). `main()` exits 1 with the actionable message; with `RAPHAEL_PORT=8911` everything derives collision-free (mutex `Raphael_Supervisor_shadow`, lock, pidfile, relay backend 9911) — asserted by tests. When brain-core lands the §d row, adding the name to `INSTANCE_ORDER` is the only change.
      → tests: `supervisor/tests/test_tier_and_jobs_cli.py` (11) + fail-closed config test update.

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [x] Read `docs/audit-tasks/infra.md` → your IDs: **SEC-2, SEC-1, SEC-5, SEC-6, SEC-7, ARCH-2, ARCH-4, ARCH-6, ARCH-7, F-7** — VERIFY-FIRST (verbatim file:line, then CONFIRMED / NOT-APPLICABLE / ALREADY-DONE), QA-4: link a green CI run with your wave_done. Source register + dedupe: `docs/AUDIT-2026-10-07.md`. Rules: stack down (spawn only for your test), one suite at a time, heavy suites in cloud (`gh workflow run tests-heavy.yml`), Rule 15 speed, cost not a factor.
      → 10/10 verified-first + delivered (full table: `docs/status/infra.md`
      "Wave 5H audit packet"); wave_done queued at merge position 7 with
      CI ids (tests-heavy 37714440504, CI 37714381234). Stragglers
      re-verified 2026-10-08: ARCH-7 present + 8/8 tests green; F-7
      co-sign formalized as `docs/requests/infra__to__integrator__f7-readiness-cosign.md`
      (OPEN — integrator); hook whisper fix confirmed at
      `scripts/install-git-hooks.sh:6-7`.

### Wave 5 follow-ups (2026-10-07)

- [x] Audit packet Wave 5H (docs/audit-tasks/infra.md) — all IDs verified-first
  and delivered: SEC-2 (priv-esc CONFIRMED → root-owned sha chain, disabled
  default, rollback; live unit disabled by human), SEC-1 (value-blind
  scanner + advisory hook + prepared-never-run scrub plan + CI request),
  SEC-5 (.env.dev valueless template/installer + integrator request),
  SEC-6 (keepalive+90s idle cap both relay legs, 480s real proof, ss
  loopback proof with teardown, docs request), SEC-7 (root/boot script
  inventory), ARCH-2 (process-mode report), ARCH-4 (identity via env/config,
  tests), ARCH-6 (`raphael doctor`), ARCH-7 (backup/restore + round-trip
  test), F-7 (ALWAYS-ON-READINESS draft for co-sign). Full quotes + test
  output in docs/status/infra.md.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  - Wave 3 (after integrator bumps `current_wave`): log rotation audit + crash reports with last-known state. NOTE: `supervisor/main.py` already ships size-cap rotation (5 MB × 3, selfcheck-verified); Wave 3 extends it to the other stack logs + adds last-known-state crash reports.
  - Wave 4: resilience scripts (kill brain/body, `wsl --shutdown`, sleep/resume) with qa-security; automatic Creative Mode (suspend heavy components when heavy apps run).
  - Wave 5: out-of-band rollback in the supervisor (not modifiable by Raphael) for the evolution pipeline.
