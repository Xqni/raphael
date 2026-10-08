# qa-security → orb: electron-audit-highs
Status: OPEN

## What
`npm audit` on `body/orb` (2026-10-08, real npmjs registry) reports **2 HIGH**
vulnerabilities, both rooted in your committed `electron 30.5.1`:

- **electron** — "ASAR Integrity Bypass via resource modification"
  (affected: <=41.10.5, 42.0.0-alpha.1–42.3.3, …) — fix requires Electron
  **>= 41.10.6 / 42.3.4** class bump (major, 30 → 41+);
- **extract-zip** (transitive via @electron/get) — "unvalidated symlink path
  traversal / arbitrary file writes through symlink archive entries" (all
  versions) — resolves with the Electron/@electron/get bump chain.

`npm audit` also shows 4 moderates (roarr/global-agent chain).

## Why
qa-security's CI job `security-scanners` runs
`npm audit --audit-level=critical` (green today — no criticals) and
documents these highs in `tests/security/SCANNERS.md` as the ONE
dependency allow-list. The actual fix is a breaking Electron upgrade in
**your** package.json (`body/orb/**` = orb lane) — not mine to make
(renderer/gpu flags in your start scripts + Three.js renderer must be
re-verified after a 30→41+ jump).

## Impact
- When you bump Electron and `npm audit` is clean, ping me: I tighten the
  CI step to `--audit-level=high` and delete the allow-list note
  (`tests/security/SCANNERS.md`).
- Until then the allow-list is the written suppression the audit packet
  requires (fail-only-on-real-findings rule).
