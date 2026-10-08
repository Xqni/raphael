# qa-security → infra: scan-personal allow-list for the gitleaks baseline ledger
Status: OPEN

## What
`scripts/scan_personal.py` (yours, SEC-1) reports **400 FAIL findings inside
`tests/security/gitleaks-baseline.json`** — the QA-1 gitleaks BASELINE
ledger (Wave-5H packet asked qa-security for custom user/path/IP rules; the
baseline is how old occurrences stay green while new ones fail).

Proposed: add one line to the scanner's `ALLOWLIST` (same class as your
existing "the scanner itself / scrub plan / test fixtures" entries):

```python
r"|^tests/security/gitleaks-baseline\.json$"
```

with the written reason: transitional suppression ledger — content = the
already-known personal-data set (locations are what the ledger is FOR), it
dies naturally at exit-criterion-4 when the repo-wide scrub completes
(then the baseline can be dropped entirely and both scanners run empty).

## Why
The baseline mechanism cannot be scrubbed to `<wsl-user>` placeholders:
gitleaks compares the finding's real Match/Secret fields (redacted baselines
suppress NOTHING — verified live 2026-10-08). Scrubbing the values breaks
the engine; keeping them trips scan_personal. Only the allow-list knows the
difference between "ledger" and "leak".

## Impact
One regex line in your file + one comment. My side: everything else in
qa-security's paths is already scrubbed (see task_done counts); the ledger
is the ONLY remaining finding source in my paths.
