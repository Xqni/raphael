# infra — status

Updated: 2026-10-06 (Wave 2 COMPLETE — handoff below, AGENT_RULES §11)

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

## Blocked

- Nothing. Four cross-lane requests are OPEN (they don't block this lane):
  `docs/requests/infra__to__integrator__protocol-loopback-bind.md`,
  `infra__to__integrator__pidfile-location.md`,
  `infra__to__brain-core__pidfile-location.md`,
  `infra__to__qa-security__ci-supervisor-tests.md`.

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

## Next

- **STOP at the wave gate** (AGENT_RULES §11): Wave 3+ starts only when
  the integrator bumps `docs/WAVES.md current_wave`. Wave 3 note for the
  handoff: supervisor log rotation (5 MB × 3) already exists and is
  selfcheck-verified — Wave 3 extends rotation to brain/body/orb logs and
  adds crash reports with last-known state (`/status` snapshot +
  supervisor's `procs`/backoff state at the moment of death).
- Merge-order position: infra merges after `orb`, before `qa-security`
  (WAVES.md). Rebase on latest main at merge time; no conflicts expected
  (only my own paths + docs/requests/* + docs/{lanes,status}/infra.md edited).
