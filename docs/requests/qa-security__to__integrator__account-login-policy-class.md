# qa-security → integrator: account_login missing from confirm_policy classes (Wave 5U P0.3 drift, live-caught)

Status: RESOLVED (2026-10-10: account_login added to confirm_policy.classes on main; see tests/regression/test_confirm_policy.py — pending ledger cleared)

## What
`config.yaml` Wave-5U P0.3 additions (commit 095068a) added `account_login`
to `safety.confirm_actions` (line 119) and `safety.typed_confirm` (line 126)
but NOT to `safety.confirm_policy.classes` (verified 2026-10-10).

The invariant in `tests/regression/test_confirm_policy.py` ("every action in
confirm_actions must have a policy class — the two config authorities may not
diverge", plan P3 line 29) flagged it the moment the config landed.

## Ask
Add to `config.yaml → safety.confirm_policy.classes`:
```yaml
      account_login: confirm     # Wave 5U P0.3 typed/click class
```
(voice-YES-blocked classes must be confirm-first — `account_login` is in
`typed_confirm`, so `confirm` is the only valid value.)

## Note (same edit, cosmetic)
`safety.confirm_actions` now carries duplicates from the P0.3 append:
`send_email`, `enter_password`, `purchase`, `delete_files` each appear twice
(lines 106-115 vs 116-118). Functionally harmless (set semantics) — worth a
one-line dedupe while touching the block.

## Interim
The divergence test carries a PENDING ledger entry for `account_login`
(commented with this request) so the gate stays active for NEW drift; the
ledger entry is removed once the class lands (its removal is the flip signal).
