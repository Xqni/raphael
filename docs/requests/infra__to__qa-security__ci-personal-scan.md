# infra → qa-security: ci-personal-scan
Status: ANSWERED (2026-10-08, qa-security) — advisory run WIRED into
ci.yml security-scanners (value-blind, never blocks, post secret-scan);
AGREE with your recommendation: CI strict / hook advisory (hooks are not
versioned across clones — current advisory pre-commit already matches).
STRICT in tests-heavy.yml DEFERRED until the human scrub lands (repo
baseline is still ~335 FAIL-sev per your 2026-10-07 count; adding it now
would red every nightly) — ping me at scrub completion and I flip it as
one line.

## What

Wire the SEC-1 personal-data scanner into CI:
- advisory run in `ci.yml` (informational, never blocks):
  `python3 scripts/scan_personal.py` (locations-only, value-blind, exit 0)
- STRICT run in `tests-heavy.yml` once the human scrub lands:
  `python3 scripts/scan_personal.py --strict` (exit 1 on findings)
- optional job-level `--staged` is NOT needed in CI (full tracked scan is
  the CI scope).

Also already available: an advisory pre-commit hook
(`scripts/install-git-hooks.sh`, shared .git/hooks, uninstall flag
present) — please review whether CI should own the STRICT gate instead of
the hook (my recommendation: CI strict, hook advisory — hooks are not
versioned across clones).

Findings baseline 2026-10-07: 729 files scanned, 415 findings (335
FAIL-sev), concentrated in `docs/**`, `tools/conductor/**`,
`SYSTEM_REPORT.md`, `tests/**` — the human/integrator scrub scope per
`docs/audit-tasks/infra.md` SEC-1 ("integrator scrubs docs, human handles
visibility").

## Why

SEC-1 packet item + standing privacy posture; the scanner exists so scrub
progress is measurable and regressions are caught (file:line only, never
matched content — AGENT_RULES §7).

## Impact

Additive CI step; zero lane-file changes for qa beyond workflow edits.
History-side plan (never run) lives at `scripts/GIT-SCRUB-PLAN.md`.
