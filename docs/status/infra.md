# infra — status

Updated: 2026-10-07 (Wave 4 open — resilience drills complete, queued for review; coord rule §13)

## Done (Wave 2 — all tasks, commits `0451dba..737e216` on `agent/infra`)

1. **Instance isolation** — `supervisor/instance.py` derives EVERYTHING from
   `RAPHAEL_INSTANCE` (port table 8765/8901..8910, mutex
   `Raphael_Supervisor[_lane]`, brain pidfiles, body lock
   `raphael_body[_lane].lock`, supervisor pidfile `run/supervisor[_lane].pid`,
   log names `logs/<n>[_lane].log`, relay helper port main 8766 / lane
   port+1000). Unset = main = historical values byte-identical (test-enforced).
   Names are sanitized before they reach shell strings/paths.
2. **Profile awareness** — `cloud_temp` (and any non-`local` profile): ZERO
   Ollama interaction (no `is-active`, no start, no pulls, no warm) with an
   explanatory log line; Orb/Body/Brain still start; Fish TTS is spawned by
   the Brain's voice layer (supervisor never spawns it — INTERFACES §d).
   `local` profile keeps the original Ollama bring-up (Wave 6).
3. **Network security** — Brain default bind `127.0.0.1` in both WSL modes
   (`brain/run.py`; `RAPHAEL_BIND` escape hatch); supervisor Windows relay
   leg hard-127.0.0.1 (extracted `_relay_listener`, not configurable);
   `scripts/wsl-relay.py` binds exactly the VM NAT address and EXITS rather
   than fall back to wildcard; relay skipped automatically in mirrored mode;
   helper leg gated (`paths.brain_relay_helper`). OPTIONAL narrow firewall
   script `scripts/win/allow-brain-localhost.ps1` (Inbound/TCP/8765/WSL
   creator — Microsoft-documented cmdlet + GUID; blanket
   `DefaultInboundAction Allow` rejected and recorded as such). Full audit,
   verify + rollback steps: `scripts/NETWORK-SECURITY.md`.
4. **Pidfile relocation + optional systemd** — new primary
   `~/.raphael[/lane]/brain.pid` (written at spawn; `RAPHAEL_PIDFILE`
   exported for brain-core), legacy `/tmp/raphael-brain[_lane].pid` always
   read/removed as fallback (recycle kill is pidfile + `/proc` cmdline
   verified, never blind `pkill -f`). `brain/raphael-brain.service` dropped
   its Ollama `Wants/After` + bind comment synced (`systemd-analyze verify`
   exit 0). OPTIONAL installers: `scripts/install-brain-unit.sh`
   (templates paths, installs + daemon-reload only — `--enable/--now`
   opt-in; `--sudoers` installs `scripts/brain-sudoers.snippet` =
   NOPASSWD for exactly start/stop/restart of `raphael-brain`, `visudo -cf`
   validated). Nothing elevated was run by this lane.
5. **`raphael` CLI** — `scripts/raphael` (WSL bash) + `scripts/raphael.cmd`
   (Windows) + `scripts/raphael_cli.py` (stdlib thin client):
   status/start/stop/restart/pause/resume/private on|off/logs[-n/-f]/jobs
   [id]/cancel [--gui]/say [--gui]/selftest. REST-only against brain-core
   (`/health /status /jobs /jobs/{id} /jobs/{id}/cancel /control`), no new
   protocol frames. stop = supervisor pidfile tree-kill first (watchdog can
   not respawn) → cmdline-verified brain SIGTERM → orphan body → verify
   endpoint down; idempotent. Exit codes 0/1/2; token path shown, value
   never printed. Supervisor gained a SIGTERM→clean-exit handler so stop
   runs the finally path.
6. **Secrets hygiene** — `scripts/gitleaks.toml` (default ruleset + tight
   allowlist), `scripts/secret-scan.sh` (gitleaks `--redact` when present,
   built-in per-rev `git grep -l` fallback otherwise → LOCATION only, never
   a value; `.env` mode + gitignored checks, `--fix-perms`),
   `scripts/SECRETS.md` (make-private steps, personal-detail scrub list for
   username/hardware/schedule with filename-level inventory, rotate-first
   leak response), `scripts/README.md` (three-tier script index).
7. **Body pinned venv** — `scripts/body-requirements.txt` (pywinauto
   0.6.9 / comtypes 1.4.17 / keyboard 0.13.5 / mss 10.2.0 / pillow 12.3.0 /
   numpy 2.5.3 / sounddevice 0.5.6 / pywin32 312 — verified vs PyPI
   2026-10-06, all install on Python 3.13 which is already present as
   `py -3.13`), `scripts/install-body-venv.ps1` (no admin, never downloads
   Python itself, import verifier, `-Force`, refuses <3.12), supervisor
   `body_script` remaps plain `python` → venv (config `paths.body_venv`
   override; explicit python path in `body_cmd` respected), selfcheck row
   `body venv` (WARN until installed).

## Coord-bus follow-ups (2026-10-06, after wave_done verification)

8. **Approved pc-control request implemented** (bus msg 5): supervisor
   mutex REUSES `body/win/instance.py::supervisor_mutex()` (mirror fallback
   keeps the logon entry point alive); `_child_env()` merge guarantees
   `RAPHAEL_INSTANCE` is never unset; `launch_body`/`launch_brain`/
   `launch_orb` all carry the `RAPHAEL_INSTANCE + RAPHAEL_PORT +
   RAPHAEL_TOKEN_PATH` triple (WSL side existence-picked, instance token
   first).
9. **Pidfile source adopted** (bus msg 2): `wsl_pidfiles()` now mirrors
   `brain/config.py::pidfile()` as the §d single source — structural
   parity test-bound vs `bcfg.pidfile()/legacy_pidfile()`; **lane instances
   dropped the legacy `/tmp` path entirely** ("lanes never touch /tmp",
   main keeps its dual-read fallback).
10. **Rebased onto merged main twice** (rule 4) — router/brain-core/
    pc-control/voice landed clean, zero conflicts; brain-suite tool-registry
    flake from the pre-follow-up tree resolved by main's dfcc5a8
    follow-up merge (227 green).
11. **All 4 request files recorded** with their bus decisions (Status:
    DONE ×3, ACCEPTED ×1).

## Blocked

- Nothing. Requests resolved: `protocol-loopback-bind` DONE,
  `pidfile-location` (integrator) DONE, `pidfile-location` (brain-core)
  DONE/SUPERSEDED, `ci-supervisor-tests` ACCEPTED (qa-security implements).
- Waiting only for the merge slot (merge order: … → orb → **infra** →
  qa-security; voice merged, computer-use + orb ahead) / `wave_open`.

## Wave 3 (current_wave=3 — open 2026-10-07 via coord `wave_open`)

### Done (2026-10-07, branch rebased onto origin/main `66679c8`)

12. **[P0-BugG] pid hygiene / zero-process teardown** —
    (a) kill shell layered: pidfile → `ss -tlnp` real-listener resolution
    (cmdline-verified) → guarded pgrep accepting relative AND absolute venv
    paths; stale pidfiles can no longer make a kill silently no-op.
    (b) cross-namespace liveness: `_pid_exists` on WSL probes `os.kill`
    AND `tasklist.exe` (a Windows supervisor is no longer reported "dead"
    from the WSL CLI); `_verify_windows_supervisor` gates legacy pidfiles
    (PowerShell CommandLine must match our supervisor or taskkill is
    REFUSED).
    (c) supervisor pidfile side marker `side=windows|linux` (legacy
    single-line still parses).
    (d) `stop_wsl_side()`: one sh teardown of orb (cwd pinned to this
    repo's `body/orb`), this instance's relay helper (exact port argv) and
    keepalive loops + self-verifying survivor report; `raphael stop` now
    fails unless endpoint-down AND wsl-side clean.
    (e) orb truth: `launch_orb` adopts an already-running orb (no
    double-spawn after a manual relaunch) and writes
    `~/.raphael[/inst]/orb.pid`; the heartbeat resolves the REAL electron
    pid once per heartbeat (never per tick — Rule 14).
13. **[SPEED] tight restart loops (Rule 15)** — `backoff_cap` 300 s → 60 s,
    PERMANENT_ERROR `slow_interval` 60 s → 15 s; probe tick (5 s), backoff
    base (5 s) and heartbeat (300 s) unchanged. No shared contract pins
    these numbers (checked PROTOCOL/ARCHITECTURE). Pinned by test.
14. **qa-security requests answered** — `ollama-profile-gate` DONE (both
    tripwires XPASS on the rebased tree), `instance-derivation` DONE for
    the infra slice (residual xfail = `brain/app.py` literal → brain-core).

**Live observation (reported, not touched):** a parent-less WSL keepalive
loop (`sh -c while :; do sleep 3600; done`, pid 6079/6088, ~59 min,
no supervisor process) — real-world evidence of Bug G's keepalive leak;
left in place (another session's process; `stop_wsl_side` now removes this
class on the next `raphael stop`). No orphans from this session (Rule 14).

### Wave 3 test output (real runs, sequential — Rule 14, 2026-10-07)

- `tests/.venv/bin/python -m pytest supervisor/tests -q` → **82 passed**
  (Bug G file adds 16: kill-shell layering, cleanup-shell targets, side
  marker roundtrip, dual-namespace probes, tasklist parsing, side-aware
  stop incl. refusal path, orb adoption/heartbeat, SPEED defaults)
- `cd tests && ./.venv/bin/python -m pytest -q .` → **187 passed,
  9 xfailed, 2 xpassed** (the 2 xpass = qa's ollama tripwires; no failures)
- `python -m pytest body -q` → **78 passed**
- `cd brain && ./.venv/bin/pytest -q` → **393 passed, 4 skipped**
- `python3 supervisor/main.py --selfcheck` → exit 0 ·
  `scripts/secret-scan.sh` → exit 0 · `bash -n`/`py_compile` → OK

## Test output (real runs only — 2026-10-06)

- `tests/.venv/bin/python -m pytest tests supervisor/tests -q` → **65 passed**
  (10 pre-existing baseline + 55 new lane tests, ~9.7 s)
- `cd tests && ./.venv/bin/python -m pytest -q .` (documented command) → **10 passed**
- `python3 supervisor/main.py --selfcheck` → **exit 0**
  (`PASS=6 WARN=2 FAIL=0 SKIP=2` — WARNs are expected here: brain down
  (stack intentionally stopped) and no pinned Body venv on this Linux host)
- `scripts/secret-scan.sh` → **exit 0** (`PERMS PASS .env mode=600`,
  gitignored, `HISTORY PASS 111 revision(s)`, `WORKTREE PASS`)
- `scripts/secret-scan.sh --perms` → exit 0
- `bash -n` on `scripts/raphael`, `scripts/secret-scan.sh`,
  `scripts/install-brain-unit.sh` + `py_compile` on all touched Python → OK
- `systemd-analyze verify brain/raphael-brain.service` → exit 0
- CLI against the intentionally-stopped stack: `raphael status` → exit 2 +
  "unreachable … raphael start"; `raphael selftest` → exit 0;
  `raphael logs supervisor -n 3` → exit 0
- NOT run (by design): no live stack start, no elevated command, no
  Task Scheduler / `.wslconfig` change, no scheduled-task re-enable.

### Post-follow-up re-runs (2026-10-06, branch rebased onto merged main)

- `tests/.venv/bin/python -m pytest tests supervisor/tests body -q` → **154 passed**
  (10 root + 66 supervisor/CLI + 78 pc body; mutex + pidfile parity vs
  `brain/config.py` and `body/win/instance.py` ACTIVE and green)
- `cd brain && ./.venv/bin/pytest -q` → **227 passed** (brain-core suite
  on the rebased tree; the transient 2-fail window pre-dated main's
  dfcc5a8 tool-discovery follow-up)
- `python3 supervisor/main.py --selfcheck` → exit 0 · `scripts/secret-scan.sh` → exit 0

## Wave 4 (current_wave=4 — open 2026-10-07, wave-3 GATE PASSED)

### Done (2026-10-07, branch rebased onto origin/main `e56b9c4`, commit `4e833a2`)

15. **[Resilience] crash recovery — supervisor watchdog.** Default run
    entry spawns the real bring-up as a child and respawns it on
    unexpected exit; crash-loop guard (5 rapid crashes → loud give-up,
    `RAPHAEL_WATCHDOG=0` opt-out); SIGTERM/SIGINT forwarded for clean
    stops. Child records the PARENT pid in `run/supervisor.pid` (tree-kill
    root) so `raphael stop` takes out watchdog+child together; legacy
    bare runs keep own-pid. Task Scheduler wiring untouched (Rule 12) —
    watchdog engages at the supervisor's next natural start after merge;
    the live stack (pre-Watchdog code) was NOT restarted (wake directive).
    Honest boundary documented: a crash of the watchdog parent itself
    still needs external relaunch (logon task).
16. **[Resilience] drills** — `supervisor/tests/test_resilience_drills.py`
    (6 synthetic tests, no servers, live stack untouched): kill storm
    through the REAL health loop (capped restarts == max_attempts,
    PERMANENT_ERROR latch holds, network-hook recovery, auto-resume,
    clean loop stop); churn (resume hook lifts PERMANENT_ERROR + immediate
    re-verify at 999 s poll interval — Rule 15); watchdog give-up /
    clean-stop / child-env+parent-pidfile; zero-orphan invariant —
    5 bring-up/teardown cycles with ZERO marker-scoped leftovers while an
    untagged control process survives every cycle (scoping proven).

### Wave 4 test output (real runs, sequential — Rule 14, 2026-10-07)

- `pytest supervisor/tests -q` → **88 passed** (82 + 6 drills, 14 s)
- `pytest tests -q` → **197 passed, 9 xfailed** (qa's ollama xfails now
  plain-passed — flipped by qa-security)
- `pytest body -q` → **85 passed**
- `cd brain && pytest -q` → **578 passed, 4 skipped, 2 FAILED** — both
  failures in `brain/memory/tests/` (tools-memory territory) under
  FULL-suite order; isolated `pytest memory/tests` → **116/116 passed**;
  zero `supervisor` imports anywhere in brain tests and this lane's diff
  is supervisor/docs-only → cross-lane registry-order flake, reported to
  the conductor, not infra's.
- selfcheck exit 0 · secret-scan exit 0 · tree clean at `4e833a2`.

## Next

- Wave 4 lane list complete (resilience drills + watchdog, commit
  `4e833a2`). Post `task_done` + `test_result`; await review — `wave_done`
  only on the conductor's call (exit criteria are the human's,
  AGENT_RULES §11).
- For the reviewer: brain-suite 2-failure flake detail above (tools-memory
  order-dependent, passes isolated); watchdog engages at next supervisor
  start — no live restart forced (live_e2e=true).
