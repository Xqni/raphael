# ALWAYS-ON-READINESS.md — gates before the scheduled task is re-enabled (F-7)

Status: **DRAFT for integrator co-sign** (packet F-7: "with integrator").
The scheduled task "Raphael" stays **Disabled** until the HUMAN acts
(AGENT_RULES §12, user policy 2026-10-07: stack DOWN by default, spawn
only for a lane's own live test, tear down after). This checklist is the
standing definition of "ready for always-on"; every box must be true and
verifiable by `raphael doctor` where possible.

## Gates (all must hold)

1. **Identity/secrets**
   - [ ] `.env` mode 600, owner-only, gitignored; `.env.dev` exists per
     worktree and holds NO keys (`scripts/install-env-dev.sh`).
   - [ ] `scripts/secret-scan.sh` PASS + `scripts/scan_personal.py --strict`
     PASS after the human scrub.
2. **Bring-up safety**
   - [ ] `raphael doctor` → FAIL=0 on the target machine (token, bind
     loopback, relay, disk ≥5 GB, WSL mem ≥400 MB).
   - [ ] Supervisor watchdog active (crash respawn) — verified by one
     intentional child-kill drill, respawn within ~2 s, then leave it up.
   - [ ] Unit installs stay OPTIONAL: brain unit `LoadState` documented
     (today: `not-found` = process mode, ARCH-2) — exactly ONE manager
     (never unit + process double-start; `brain_run_mode` enforces).
3. **Privilege surface**
   - [ ] `raphael-wslg-shadow` chain: root-owned install
     (`scripts/wslg-shadow/install-rooted.sh`) **only if still wanted**
     (ARCH-1 retirement pending) — and ENABLED only with fresh human
     approval; old `/home/<user>/scripts/...` payload deleted.
   - [ ] sudoers snippet absent or exactly the 3 scoped verbs
     (`brain-sudoers.snippet`), `visudo -cf` clean.
   - [ ] No other root/boot script executes user-writable content
     (SEC-7 inventory reviewed — evolution files Core Guard manifest).
4. **Cost/speed policy**
   - [ ] Paid caps recorded in `docs/PAID_USAGE.md` match runtime config
     (vision slot + broad paid-fast); doctor/console show no cap drift.
   - [ ] Rule 15 speed defaults confirmed: backoff cap 60 s, slow poll 15 s.
5. **Live E2E gate (human GO)**
   - [ ] Full gate re-run (WAVES exit criteria) with the task enabled BY
     THE HUMAN: `Enable-ScheduledTask -TaskName 'Raphael'` is a human
     step; rollback: `Disable-ScheduledTask -TaskName 'Raphael'` +
     `raphael stop` + fish kill (one-fish rule).
   - [ ] First boot watched: doctor PASS, heartbeat lines in
     `logs/supervisor.log` show real orb pid, zero orphans after one
     `raphael stop` cycle.
6. **Recovery**
   - [ ] A fresh `scripts/backup-raphael.sh` archive exists AND a restore
     was proven (`supervisor/tests/test_backup_restore.py` green + one
     manual `--dry-run` review of the archive listing).
7. **Coordination**
   - [ ] Conductor `attention` queue clear for infra; QA-4 CI run linked
     on the wave_done that accompanies the re-enable.

## Explicit non-goals

- Never re-enable automatically from a lane (AGENT_RULES §12).
- Never edit `.wslconfig` / Task Scheduler as part of this checklist —
  every box is either a script the human runs or a read-only verification.
- `cloud_temp` constraints stay until Wave 6 (no Ollama; Fish = only local
  model).

## Sign-off (integrator, 2026-10-08)

**CO-SIGNED with one amendment** — the checklist is the correct standing definition of
"ready for always-on"; every box is verifiable and the human-GO gate in §5 is preserved
(my co-sign is NOT enablement — the scheduled task stays Disabled until the user acts).

Amendment (mine, becomes gate 8):
8. **Coord automation healthy**
   - [ ] conductor running (tmux `raphael-conductor`), no STOP armed;
   - [ ] keepalive cron installed: `*/10 dispatch` + `*/20 usage`
       (`tools/conductor/keepalive.py`; never rewrites state.json — regression-tested);
   - [ ] usage watcher state sane (`~/.raphael-coord/usage-watch.json`) and its
        limit-reset auto-wake path exercised once (probe → attention → integrator ping);
   - [ ] both CI workflows green on main (QA-4 run id recorded on the re-enable wave_done).

Verdict: checklist APPROVED as the gate. Nothing here executes; enablement remains
100% human (AGENT_RULES §12).
