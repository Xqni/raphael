# SECRETS.md — repo privacy + personal-detail scrubbing (infra lane)

Wave-2 secrets task. Scanner: `scripts/secret-scan.sh` (this doc's commands
never print a secret value — locations only, AGENT_RULES §7).

## Status (verified 2026-10-06)

- `scripts/secret-scan.sh` → **PASS**: `.env` mode `600`, `.env`
  gitignored, 111 revisions + worktree clean for high-confidence token
  formats (AWS/GitHub/Slack/sk-/PEM/webhook patterns).
- Engine today = built-in fallback (gitleaks not installed locally);
  `scripts/gitleaks.toml` ships the config for when it is (CI, qa-security).
- Known personal-detail footprint: **usernames, hardware, schedule** — see
  the scrub list below. No secrets, no public IPs, no webhooks found.

## Run it

```bash
scripts/secret-scan.sh              # history + worktree + .env perms
scripts/secret-scan.sh --fix-perms  # chmod 600 .env if too open
gitleaks detect --config scripts/gitleaks.toml --redact   # full engine
```

## Making the repo private (user/integrator step — no agent does this)

1. GitHub → repo **Settings → General → Danger Zone → Change repository
   visibility → Private** (owner account only; confirm any org prompt).
2. Afterwards check: **Settings → Collaborators** (only intended accounts),
   **Settings → Deploy keys / Webhooks / Actions secrets** (nothing stale),
   and the fork list (forks keep their own visibility — detach if needed).
3. Local remotes keep working over HTTPS; per-lane worktrees/branches need
   no change. The GitHub *handle in the remote URL* is itself an identifier
   (see scrub list) — decide whether the org/handle should be renamed
   (GitHub rename redirect exists until the old name is taken).
4. Re-run `scripts/secret-scan.sh` after the flip (cheap, and it becomes a
   pre-publish gate: run before ANY future public push).

## Scrubbing personal details (username / hardware / schedule)

Find first, decide after — locations only:

```bash
# usernames: home dir, Windows login, GitHub handle (use YOUR values):
grep -rlI --exclude-dir=.git --exclude-dir=node_modules -e "home/<user>" -e "<win-login>" .
grep -rlI --exclude-dir=.git "github.com/<handle>"
# hardware + schedule:
grep -rlIE --exclude-dir=.git -e "RTX|4060|3090|[0-9]+ ?GB" -e "Premiere" .
grep -rlIE --exclude-dir=.git -e "20[0-9]{2}-[0-9]{2}-[0-9]{2}.*(UTC|EST|cron)" .
# network identifiers:
grep -rlIE --exclude-dir=.git -e "[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}" .
```

Where it lives today (filename-level, contents not reproduced here):
`SYSTEM_REPORT.md`, `PROGRESS.md`, `docs/REQUIREMENTS_ADDENDUM.md`,
`docs/TODO.md`, `docs/LAUNCH.md`, `.opencode/research/*.md`,
`.opencode/agents/*.md`, `brain/raphael-brain.service` (`User=` /
`WorkingDirectory=`), `scripts/wslg-shadow/*`, `.env.example` (path hints),
plus lane code/test fixtures with fake home paths.

Fix strategy, in order of preference:

1. **Make it private first** — that lowers the urgency of everything below.
2. Scrub the **top of the tree** (current files) in normal commits —
   rewrites anyone's docs only with their lane's agreement (ownership!).
3. **History rewrite is LAST resort and integrator-only**: rewriting main
   invalidates every open lane branch (10 worktrees need rebase) —
   `git filter-repo` runbook belongs to the integrator, never a lane.
   Rule of thumb: private repo → top-of-tree scrub is enough; going
   *public* again → full history rewrite first.

## If a real key ever lands in history

1. **Rotate it at the provider immediately** (revoke + regenerate; paste
   the new one only into `.env` at runtime — never into chat, notes, logs).
2. `scripts/secret-scan.sh` again → confirm the *location* is gone from the
   worktree.
3. Decide with the integrator whether history must be rewritten (public
   repos: yes, always).

## CI

Requested: qa-security wires `scripts/secret-scan.sh --no-history` (fast)
plus a scheduled history scan — see
`docs/requests/infra__to__qa-security__ci-supervisor-tests.md` for the
suite include this rides along with.
