# Scanner wiring + suppression rationale — qa-security (Wave 5H QA-1)
#
# CI job: `.github/workflows/ci.yml` → `security-scanners` (ubuntu).
# Local equivalents (run from repo root):
#
#   gitleaks:  gitleaks git --log-opts=HEAD --config .gitleaks.toml \
#                    --baseline-path tests/security/gitleaks-baseline.json
#     (--log-opts=HEAD scopes the scan to THIS branch's history — the same
#      single-branch view CI's checkout has; without it gitleaks walks every
#      local ref and unmerged sibling-lane commits redden the job (seen
#      live 2026-10-08 with agent/infra's then-unmerged SEC-1 files).)
#   pip-audit: pip-audit -r tests/requirements.txt
#   bandit:    bandit -r brain supervisor scripts tests body \
#                    -c tests/security/bandit.yaml --severity-level high
#   npm audit: (cd body/orb && npm audit --audit-level=critical)
#              # local machines behind the safetycli npm mirror need
#              # --registry=https://registry.npmjs.org (CI uses npmjs).
#
# ## gitleaks baseline (the documented allow-list for pre-existing hits)
#
# File: tests/security/gitleaks-baseline.json — 117 PRE-EXISTING findings
# (90 local-username, 9 private-IP, 8 home/drive-path, 10 generic-api-key
# from test fixtures) across 53 tracked files. They are ALLOWED, not
# forgotten: any NEW occurrence (new fingerprint) fails the job — proven by
# a live negative test (new `<wsl-user>/...` path → exit 1, 2026-10-08).
#
# The baseline MUST be generated WITHOUT --redact (gitleaks matches the
# finding's Match/Secret fields as well as the fingerprint — a redacted
# baseline suppresses nothing). Fingerprints embed COMMIT SHAs — REGENERATE
# AFTER EVERY REBASE of this branch (rewritten commits invalidate the whole
# baseline; observed live 2026-10-08: post-rebase scan went 0 -> 41) and
# before each push, with the reason in the commit message.
# The file itself is a TRANSITIONAL suppression ledger (400 scan_personal
# findings): infra allow-list requested (scan_personal allowlist entry) —
# it disappears when wave-5H exit criterion 4 (zero personal data in tracked
# files) completes repo-wide. Regenerate when a finding is fixed or
# consciously accepted:
#
#   gitleaks git --config .gitleaks.toml --report-format json \
#                --report-path tests/security/gitleaks-baseline.json
#
# ## bandit
#
# HIGH-only gate; B602 + B324 skipped with written reasons in
# tests/security/bandit.yaml (shell-behind-Confirm-Guard is the execution
# model; sha1 hits are cache keys, not security). Medium findings (B108
# /tmp bindings in tests, B310 localhost urlopen probes, B608, B104
# test-only bind) are reported, not gating.
#
# ## pip-audit
#
# Scope: tests/requirements.txt (the only committed requirements file).
# Status 2026-10-08: no known vulnerabilities. No suppressions.
#
# ## npm audit
#
# Scope: body/orb (package-lock.json). Status 2026-10-08: 6 vulns
# (4 moderate, 2 HIGH) — the highs are `electron 30.5.1` (ASAR integrity
# bypass) and its transitive `extract-zip`; the fix is a MAJOR Electron
# upgrade (>= 41.10.6 / 42.3.4) in the ORB LANE's package.json — breaking
# change not qa-security's to make. Suppression: CI gates at
# `--audit-level=critical` (fails on new criticals; the 2 highs are
# documented here + request `qa-security__to__orb__electron-audit-highs.md`)
# plus a non-gating full audit for visibility. When orb bumps Electron,
# tighten the step back to `--audit-level=high` (delete this note then).
#
# ## Dependabot
#
# .github/dependabot.yml — pip (/tests), npm (/body/orb), github-actions (/),
# weekly, auto-merge left OFF (lanes review via the coord bus).
