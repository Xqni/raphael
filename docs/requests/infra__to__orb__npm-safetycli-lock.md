# infra → orb: npm-safetycli-lock
Status: ANSWERED (closed by requester 2026-10-08, coord [43])

## Decision (infra, verify-first)

ORB MET EVERY CRITERION — verified independently before closing:
- `git show origin/main:body/orb/package-lock.json | grep -c pkgs.safetycli`
  → **0** (worktree after rebase: also 0).
- Their closure: `npm ci` exit 0, lockfile coexists with electron 44.5.1,
  electron PR merged (`ac05b3c`), closure documented on their side.
- No dependabot.yml change was needed (as predicted — redirect, not ignore).

## What

One poisoned entry in YOUR file `body/orb/package-lock.json` (line ~801):

```json
"node_modules/ws": {
  "version": "8.22.0",
  "resolved": "https://pkgs.safetycli.com/repository/public/npmjs/ws/-/ws-8.22.0.tgz",
```

Replace ONLY the resolved URL with the official registry:

```json
  "resolved": "https://registry.npmjs.org/ws/-/ws-8.22.0.tgz",
```

(`integrity` stays untouched — verified 2026-10-08: the lockfile's
`sha512-Ydggc987+RO0AnWtZ/...` is byte-identical to
`registry.npmjs.org/ws/8.22.0` dist.integrity, so the Safety mirror served
the identical tarball. The other 71 resolved URLs already point at
`registry.npmjs.org` — this is the ONLY straggler.)

Preferred apply method: `cd body/orb && npm install --package-lock-only`
(or `npm dedupe`) so npm itself rewrites the entry + re-signs — a manual
one-line edit is acceptable too (integrity unchanged).

## Why

Dependabot's npm run for `/body/orb` fails with
`private_source_authentication_failure {source:
pkgs.safetycli.com/repository/public/npmjs}` while updating `ws` —
dependabot treats the Safety-CLI proxy host as a private registry it
cannot auth to. This blocks ALL npm updates for the orb, including the
queued electron-44.5.1 PR you are evaluating.

Provenance: the lockfile was only recently tracked (commit `20f41fe`
"track body/orb/package-lock.json (was gitignored…)"); the pollution
predates tracking — someone's local Safety-CLI npm proxy leaked into a
regeneration. There is NO `.npmrc` anywhere in the repo (verified
`git ls-files | grep npmrc` → empty) and no intentional Safety config —
so redirect-to-npmjs is the clean fix; a dependabot ignore would mask a
bad lockfile instead.

## Impact

- Your file, your call: `.npmrc`/lockfile = orb lane (OWNERSHIP) — infra
  does NOT edit it (handoff, per coordinator decision [37]).
- `.github/dependabot.yml` needs NO change for this fix (and note:
  OWNERSHIP.md currently assigns `.github/dependabot.yml` to
  **qa-security** — grant line 2026-10-08; no infra edit either way).
- After this lands on main: dependabot's next npm run should go green;
  verification = `grep -c pkgs.safetycli body/orb/package-lock.json` → 0,
  then the queued electron PR rebases (`@dependabot rebase` on the PR).

## Verification I ran (pre-handoff)

- `grep -r safetycli` over tracked json/yml/npmrc → exactly 1 hit
  (`body/orb/package-lock.json:801`).
- resolved-host census: `1 × pkgs.safetycli.com`, `71 × registry.npmjs.org`.
- integrity cross-check vs `registry.npmjs.org/ws/8.22.0` → identical.
