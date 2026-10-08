# infra — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

**VERIFY-FIRST RULE (non-negotiable):** every finding is a HYPOTHESIS from a docs-only
audit. Before changing ANY code: quote the exact `file:line` (verbatim), then report
one of **CONFIRMED / NOT-APPLICABLE / ALREADY-DONE** in your task_done event, with the
quote inline. Unverified findings are never applied. Scope = ONLY the IDs below.
**QA-4 (new rule):** every wave_done you post MUST link a green CI run
(`gh run list --workflow=ci.yml` → run id) — without it the wave_done is bounced.
Run heavy suites in the CLOUD (`gh workflow run tests-heavy.yml`), one local suite at
a time (Rule 14). Stack stays DOWN — spawn it only for your own live test, tear down
after (user policy 2026-10-07). Speed binds (Rule 15); cost is not a factor.


| ID | Sev | Finding + first-look hints |
|----|-----|------------------------------|
| **SEC-2** | HIGH | systemd raphael-wslg-shadow.service allegedly runs a script from a user-writable home path AS ROOT at boot and replaces the WSLg Weston binary => local privilege escalation. START: grep -rn 'shadow' across repo units + `systemctl cat raphael-wslg-shadow` (if absent on disk/system => NOT-APPLICABLE with that evidence). |
| **SEC-1** | HIGH | SCAN TOOLING part (integrator scrubs docs, human handles visibility): build a value-blind personal-data scanner (usernames <win-user>/<wsl-user>, C:\\Users paths, private IPs, hostnames, serials) over git-ls-files; prints file:line only, never values for secret-shaped patterns; wire as a tests-heavy step (coordinate ci.yml with qa-security). |
| **SEC-5** | MED | .env symlinked into lane worktrees: quote `ls -la ~/raphael-wt/*/.env` results; propose unsharing (per-worktree env or presence-only read-through). |
| **SEC-6** | MED | relay settimeout(None) + Hyper-V blanket Allow + brain loopback bind: quote the settimeout line (grep -rn settimeout scripts/ brain/), quote config.yaml server.host, list any firewall rule sources in repo; mark runtime checks pending-live-check (stack down). |
| **SEC-7** | MED | BOOT/ROOT scripts you own: list every root/boot script (bring-up, WSL entrypoints) for the Core Guard manifest expansion (evolution files the request; you supply the file list). |
| **ARCH-2** | P2 | brain process-mode vs systemd unit: quote supervisor/main.py launch lines AND brain/raphael-brain.service; report which is authoritative / double-management exists. |
| **ARCH-4** | P1 | hardcoded user/paths/IPs in YOUR files: grep supervisor/ scripts/ for <wsl-user>|<win-user>|C:\\Users|IPs → env/config for runtime, placeholders (<wsl-user>) for docs; config.yaml supervisor block = propose, integrator applies (config is integrator-owned). |
| **ARCH-6** | P1 | CO-SHARE: 'raphael doctor' subcommand (value-blind: keys/token 'present/absent' only) + structured-log/timestamp audit for supervisor logs. |
| **ARCH-7** | P2 | backup/restore for ~/.raphael (token, memory DB, config) with a TESTED restore on a temp dir. |
| **F-7** | P1 | always-on readiness checklist (with integrator) gating scheduled-task re-enable; task stays Disabled until the human acts. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.
