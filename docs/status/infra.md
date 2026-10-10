# infra — status

Updated: 2026-10-10 (Wave 5U §5.7 complete — see section below; coord rule §13)

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

## Wave 5 (current_wave=5 — open 2026-10-07, wave-4 GATE PASSED)

### Done (2026-10-07, branch rebased onto origin/main `ccee742`)

17. **Tier runtime switch — safe restart semantics.** `raphael tier`
    [name] [--force]: show/set `persona.tier` in
    `config.d/evolution-persona.yaml` with fail-closed validation (only
    the three tier names, loader-C1 parity), surgical exactly-one-line
    edit (atomic; `max_tokens_tier` + comments provably untouched),
    active-jobs REFUSAL (job list shown; `--force` = informed override),
    then a **single-spawner recycle** — supervisor alive ⇒ verified kill
    only (its health loop is the sole respawner; no double-spawn race),
    supervisor absent ⇒ local respawn; waits healthy and reports
    old→new. Brain-down ⇒ write + defer to next start. No new frames.
18. **Simulation supervision.** `raphael jobs <id> --wait [--timeout N]`:
    0.4 s polls to a terminal state, transition lines,
    `awaiting_confirm` hint, result snippet on done, exit codes
    0/1/2 (done / terminal-failure / brain unreachable).
19. **Shadow-instance readiness (8911, carried).** Unknown
    `RAPHAEL_INSTANCE` **without** `RAPHAEL_PORT` now fails CLOSED in
    `load_config` (ValueError → supervisor main exits 1, CLI reports) —
    the old silent 8765 fallback could collide with the live main
    instance; aligns with brain-core `port()` + qa "never guess".
    With `RAPHAEL_PORT=8911`: full derivation collision-free (mutex,
    lock, supervisor pidfile, relay backend 9911) — test-asserted.
    When brain-core's §d row lands: one line in `INSTANCE_ORDER`.

### Wave 5 test output (real runs, sequential — Rule 14, 2026-10-07)

- `pytest supervisor/tests -q` → **99 passed** (+11 tier/jobs/shadow)
- `pytest tests -q` → **204 passed, 7 xfailed**
- `pytest body -q` → **139 passed**
- brain suite: not rerun this wave — diff is supervisor/scripts/docs-only
  and brain tests have zero `supervisor` imports (proven last wave);
  integrator reruns at review. (Known cross-lane memory/tests order flake
  from wave 4 still reported in the error log.)
- selfcheck exit 0 · secret-scan exit 0.

## Wave 5H audit packet (docs/audit-tasks/infra.md — VERIFY-FIRST honored)

### Verification table (quotes verbatim; status per packet format)

- **SEC-2: CONFIRMED (live) → FIXED repo-side / NEUTRALIZED by human** —
  `scripts/wslg-shadow/raphael-wslg-shadow.service:7`
  `ExecStart=/home/<wsl-user>/scripts/raphael-wslg-shadow.sh` (redacted) (live:
  `systemctl cat` → `/etc/systemd/system/...`, is-enabled=enabled,
  is-active=active, payload `755 <wsl-user>:<wsl-user>` == repo boot-hook.sh (redacted));
  `boot-hook.sh:11` `BACKUP=/mnt/wslg/raphael-shadow-fix` (root exec via
  `wsl --system`); `install.sh:11` `WRAPPER_SRC=/mnt/wslg/...` → `:22-23`
  `mv "$REAL" "$WRAPPED"` / `cp "$WRAPPER_SRC" "$REAL"`. Human ran
  `systemctl disable --now` (neutralized). Repo half: root-owned
  `/usr/local/lib/raphael` chain, unit pins `@BOOT_SHA@` pre-exec,
  tar-pipe transfer, pin-verified wrapper, install-rooted.sh
  **disabled-by-default** + fail-loud path audits, uninstall rollback,
  README retirement trigger (ARCH-1). Never re-enabled without fresh
  approval.
- **SEC-1: CONFIRMED (no tooling) → DONE** — scanner
  `scripts/scan_personal.py` (locations only, value-blind), hook
  `scripts/install-git-hooks.sh` (advisory, refuses foreign hooks),
  `scripts/GIT-SCRUB-PLAN.md` (prepared, never run), qa CI request OPEN.
  Baseline: 741 files / 200 findings (120 FAIL) = scrub inventory.
- **SEC-5: CONFIRMED → PROPOSED (integrator lines pending)** —
  `ls -la ~/raphael-wt/*/.env` → all 10 lanes `-> /home/<wsl-user>/raphael/.env` (redacted)
  (real file `-rw------- 1 <wsl-user> <wsl-user>` = 600 (redacted)). Shipped:
  `scripts/env.dev.template` (valueless, zero GROQ/GITHUB) +
  `scripts/install-env-dev.sh` (600, idempotent, redacted value guard,
  gitignore loud-warn). Request:
  `infra__to__integrator__sec5-env-dev-and-docs.md` (.gitignore, LAUNCH).
- **SEC-6: CONFIRMED → FIXED (docs request OPEN)** —
  `scripts/wsl-relay.py:66` + `supervisor/main.py:1426`
  `backend.settimeout(None)` (deliberate — recv timeout kills WS);
  `config.yaml:21` `host: 127.0.0.1` (ALREADY-DONE); blanket-allow sources:
  `docs/TROUBLESHOOTING.md:13` + `docs/TODO.md:35` (integrator files →
  request bundled in sec5-env-dev-and-docs). FIXED: TCP keepalive + select
  idle cap ≥3×ping (default90s, `RAPHAEL_RELAY_IDLE_CAP`) on BOTH legs,
  semaphore kept; **real-duration proof: 2 passed in480s** (silent reaped
  ~90s, pinger survived5min; `/tmp/opencode/sec6_long_proof.log`).
  **Runtime ss proof (own live test, torn down):**
  `LISTEN 0 2048 127.0.0.1:8907 0.0.0.0:* users:(("python",pid=83607,fd=15))`
  — loopback ONLY; teardown verified (graceful drain, port free, temp
  files removed).
- **SEC-7: DONE (file list for Core Guard manifest)** — root/boot scripts
  owned by infra: `brain/raphael-brain.service`,
  `scripts/install-brain-unit.sh`, `scripts/brain-sudoers.snippet`,
  `scripts/setup.ps1`, `scripts/setup-startup.ps1`, `scripts/setup.sh`,
  `scripts/uninstall.ps1`, `scripts/win/allow-brain-localhost.ps1`
  (admin), `scripts/wslg-shadow/{raphael-wslg-shadow.service, boot-hook.sh,
  install.sh, install-rooted.sh, uninstall-rooted.sh}`.
- **ARCH-2: REPORTED (process mode authoritative)** —
  `supervisor/main.py:1294` `"brain/.venv/bin/python -m uvicorn brain.app:app "`
  + `:1245` `def brain_run_mode` ("auto: systemd unit when installed, else
  'process'") vs `brain/raphael-brain.service:34` `ExecStart=... -m brain.run`;
  live `systemctl show -p LoadState raphael-brain` → `LoadState=not-found`
  ⇒ **process mode**; double-management prevented by the auto probe
  (unit installed ⇒ supervisor stops spawning).
- **ARCH-4: DONE (code + tests)** — `supervisor/main.py` DEFAULT
  `wsl_user` now `os.environ.get("USER") or os.environ.get("USERNAME") or ...`
  and `_normalize` honors `RAPHAEL_WSL_USER` (env > config > derived);
  wslg payloads all `RAPHAEL_*`-parameterized; no hardcoded IPs (WSL IP
  discovered at runtime); config.yaml comment proposal in the request.
- **ARCH-6: DONE** — `raphael doctor` (11 checks, value-blind, actionable
  fixes, structured-log timestamp audit). Live: PASS=6 WARN=4 FAIL=0
  SKIP=1 exit0. Tests plant a secret and assert it never appears.
- **ARCH-7: DONE** — `scripts/backup-raphael.sh` + `restore-raphael.sh`
  (`--root` test mode, pre-restore safety copy, token 600) with an
  automated temp-dir round-trip test.
- **F-7: DRAFT (co-sign pending)** — `scripts/ALWAYS-ON-READINESS.md`
  (7 gate groups; task stays Disabled until the human acts).

### Wave 5H test output (real, sequential — Rule 14)

- `pytest supervisor/tests -q` → **127 passed, 2 skipped** (skips =
  env-gated SEC-6 long proof, which RAN separately: **2 passed in480s**)
- `pytest tests -q` → **214 passed, 7 xfailed**
- `pytest body -q` → **150 passed**
- `pytest supervisor/tests/test_doctor.py` → 6 passed; audit tooling → 8;
  sec2 → 7; keepalive fast →5; config →7
- selfcheck exit0 · secret-scan exit0 · personal scan advisory exit0
  (741 files/200 findings — inventory, not a gate until scrub)
- live doctor smoke (stack down): PASS=6 WARN=4 FAIL=0 exit0
- no elevated commands run by this lane; stack spawned once for the ss
  proof and torn down (policy 2026-10-07).


## Wave 5U §5.7 (complete — 2026-10-10, head c4d1aa8 on top of origin/main 0684b3e)

16. **Finding 3 + watchdog** (decision [49]/charter): helper accept loop
    now has the Windows leg's guard (transient OSError -> continue;
    `fileno()==-1` -> exit) — commit `9062703`; supervisor watchdog:
    `_spawn_relay_helper` + `_helper_alive` (exact-argv, watchdog cadence
    only) + `_relay_watchdog_loop` (sleep-first, 60 s default,
    `RAPHAEL_RELAY_WATCHDOG_INTERVAL`, exceptions logged never fatal).
17. **Finding 12**: `bind_watch_loop` re-resolves `hostname -I`
    (`RAPHAEL_RELAY_BIND_CHECK`, 300 s) and closes the listener when the
    address vanished -> zombie guard exits -> watchdog respawns fresh
    (the review's required ordering).
18. **One-command start (DoU line 1)**: `raphael start --dry-run` lists
    supervisor/brain/body/orb/relay/TTS + chat URL, exit 0, spawns nothing
    (live-verified); `start`/`status` print `chat: http://127.0.0.1:PORT/chat`.
19. **CLI verbs**: `confirm <job> yes|no` (WS confirm_resp role=cli ->
    ack, token value never printed on auth failure), `tasks [id] [--cancel]`,
    `chat` (interactive; prints answer/report/notice/job_event frames;
    `--web` opens /chat), `latency` (/status.latency p50/p95/max table,
    value-blind). New `scripts/raphael_ws.py` — minimal stdlib WS client
    (handshake+Sec-WebSocket verify, masked frames, auto-pong, auth role cli).
20. **P3 docs**: `scripts/NETWORK-SECURITY.md` "Mini-PC / LAN move" table
    (loopback default, TLS required off-box, token unchanged, narrow
    firewall) + `brain.url` key request to integrator. **Task 4**
    (conductor ensure-running hook in setup-startup.ps1) = request only:
    tools/conductor semantics are integrator-owned (routed in task_done).
21. **Guard**: re-pin from a CLEAN tree per charter (commit `c4d1aa8`,
    approval = `infra__to__integrator__5u-supervisor-relay-watchdog.md`,
    1-line diff, byte-stable after).

### Wave 5U test output (sequential battery, Rule 14)

- `pytest supervisor/tests -q` → **153 passed, 2 skipped** (+19 this batch:
  10 finding-12/accept-loop, 9 wave5u CLI incl. mock-WS handshake)
- `pytest tests -q` → 270 passed + 1 FAILED —
  `test_cloud_temp_chain_has_no_local_providers` (chain[0]=='go' vs config
  zen_free): **reproduced on pristine origin/main 0684b3e** (worktree run)
  → pre-existing, routed to qa/integrator, NOT mine
- `pytest body -q` → **194 passed**
- `brain suite` → 7 errors, **identical on pristine origin/main 0684b3e**
  (`brain/evolution/tests`: `No module named 'brain'` — missing path setup)
  → pre-existing, routed to evolution-persona, NOT mine
- guard byte-stable; personal-scan advisory clean for FAIL class
  (REVIEW-only: 7 synthetic test-IP fixtures, advisory by design)

## Next

- Wave 5 lane list complete (tier plumbing + job supervision + shadow
  readiness). Post `task_done` + `test_result`; await review — `wave_done`
  on the conductor's call (exit criteria are the human's, §11).
- Blockers: none. The §d shadow row itself is brain-core's (assigned);
  infra is ready the moment it lands (one-line table entry).

## Current as of 2026-10-09 (integrator freshness pass)

- **Merged + wave closed.** `git merge-base --is-ancestor agent/infra main` → true (verified 2026-10-09). WAVE-5H GATE PASSED recorded in main at `2247a65` (tag `wave-5h-gate`); this lane's post-gate doc record merged at `ccf4a86`. Latest completed main CI at report time: **37800865212** (success).
- **Stale — SEC-1 row "qa CI request OPEN"**: superseded by this lane's post-gate work — OPTION 1 implemented on this lane (commit `8f941d2`: `scan_personal --strict` gates on FAIL-severity only, REVIEW advisory with counts) and wired into tests-heavy the same day by qa-security (commit `4620775`; branch CI **37799170764** success; merged to main at `48f74f3`; SCANNERS.md strict semantics + npm `--audit-level=high`). Request files confirm: `qa-security__to__infra__personal-scan-strict-severity-scope.md` Status **DONE** ("infra implemented OPTION 1, 2026-10-08"); `infra__to__qa-security__ci-personal-scan.md` Status **ANSWERED**.
- **Stale — "F-7: DRAFT (co-sign pending)"**: `infra__to__integrator__f7-readiness-cosign.md` is now Status **CO-SIGNED** (integrator, 2026-10-08) with a gate-8 amendment; enablement remains human per rule 12.
- **Request closure:** `infra__to__orb__npm-safetycli-lock.md` is Status **ANSWERED** (closed by requester 2026-10-08, commit `02e98c3`) — the doc's Blocked bullet claiming it pending predates that closure.
- **Still genuinely open (checked, unchanged):** `infra__to__integrator__sec5-env-dev-and-docs.md` remains Status OPEN — the SEC-5 "PROPOSED (integrator lines pending)" row is still accurate.
- **Stale — "## Next: … await review — `wave_done` on the conductor's call"**: the conductor's call happened — the 5H gate passed and this lane merged; nothing awaits review here as of 2026-10-09.
