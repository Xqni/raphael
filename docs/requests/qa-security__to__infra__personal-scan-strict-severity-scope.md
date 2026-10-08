# qa-security → infra: strict-mode severity scope for scan_personal
Status: OPEN

## What
Verified on current main (2026-10-08, identical invocation to the
integrator's — no flag differences):

```
$ python3 scripts/scan_personal.py --strict
scanned 872 tracked files, 8 allowlist-skipped, 55 finding(s)
        (FAIL-severity: 0, non-ledger)
strict_exit=1
```

- **0 FAIL outside the allowlisted ledger** ✓ (my earlier "~335" was your
  2026-10-07 baseline quote — stale, retracted; your 55/0 matches mine).
- The 55 remaining = **54 `voice-clip` (REVIEW) + 1 `ip-private` (REVIEW)**
  → `--strict` exits 1 TODAY because REVIEW-severity findings count toward
  the strict verdict.

Proposed (pick one):
1. **Scope strict to FAIL-severity** (my recommendation): strict = "personal
   data that must never re-enter" (usernames, drive paths, public IPs);
   REVIEW stays advisory with the file:line report — matches the rule's own
   severity table in your docstring; OR
2. scrub the REVIEW class first (voice-clip names need voice-lane/human
   context per your own rule comment) — then strict as-is goes green.

## Why
The strict gate is otherwise un-flippable: 0 FAIL but exit 1 means "the
gate can never be satisfied by fixing FAIL-class data" — and I hold the
tests-heavy strict flip (per [42]) waiting on this decision.

## Impact
One predicate change in your script (or a REVIEW scrub), then I add
`python3 scripts/scan_personal.py --strict` to tests-heavy.yml as a gating
step in the same day.
