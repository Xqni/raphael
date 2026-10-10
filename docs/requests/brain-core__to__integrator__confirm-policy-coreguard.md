# brain-core → integrator: confirm-policy-coreguard (Wave 5U P0.1/P0.2)
Status: APPROVED-BY-CHARTER — Wave 5U charter §5.1 P0.1 (docs/USEFUL-NOW-PLAN.md) + design-review findings #1/#2; this file is the Core-Guard approval trail for `brain/confirm.py` edits in this wave. Companion to `brain-core__to__integrator__confirm-policy-wiring.md` (Wave 5P P3, already merged-ready) — same file, this wave's charter-named record.

## What (P0.1/P0.2, per charter decision order)

1. `confirm_policy()` — reads `safety.confirm_policy {default, classes}`
   (verdicts auto|confirm|never). Charter decision order implemented
   exactly: registry tool meta `confirm=<class>` → class policy → tool
   with no class → CONFIRM (fail-closed; the declared `default` in the
   integrator-owned config is `confirm`, and any invalid/missing value
   fails closed to confirm). Text regex `RISKY_PATTERNS` stays an
   ADDITIONAL trigger, never a loosener.
2. HIGH risk = class in `safety.confirm_actions` OR `safety.typed_confirm`
   (Wave 5U addition; absent list = today's behavior). Voice-yes rejection
   for high risk unchanged (tripwires stay green).
3. `never` verdict = honest refusal (spoken cancel, journaled) — never a
   silent drop, never auto-approve on timeout (unchanged).

Security direction: gates stronger, never weaker — `default: confirm` turns
previously-ungated model-picked tools into confirm-first; 'auto' can only
open classes the user names in their own config.

## Action

`python tests/core_guard.py --update --approval docs/requests/brain-core__to__integrator__confirm-policy-coreguard.md`
— re-pins `brain/confirm.py` for the approved Wave 5U edits (typed_confirm
HIGH-risk source, needs_confirm `target` field support).
