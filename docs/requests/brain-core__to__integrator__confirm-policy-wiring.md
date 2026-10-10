# brain-core → integrator: confirm-policy-wiring (P3 re-pin)
Status: APPROVED-BY-ASSIGNMENT — Wave 5P P3 packet + design-review findings 1-2 (coord decisions 2026-10-10); this file is the recorded approval trail for the Core-Guard re-pin of `brain/confirm.py`.

## What changed in brain/confirm.py (P3, findings 1-2)

The design review found `safety.confirm_policy` was DEAD CONFIG (zero reads)
and that the code's real default (allow-on-no-match, old `classify()` line
141-142) contradicted the config's declared `default: confirm`. P3 wires the
policy in, per the coordinator's sharpened decision ("the P3 wiring must make
unclassified tools follow the policy's declared default (decide:
confirm-by-default per config, regex as classifier) and pin it with tests"):

- `confirm_policy()` — reads `safety.confirm_policy` (default + classes,
  verdicts auto|confirm|never); invalid/missing values FAIL CLOSED to
  'confirm'; `voice_ok` excluded (channel policy, not a class).
- `classify()` gains the ladder: policy classes (ToolSpec confirm category
  first, then regex/risky-tool action ids) -> regex classifier -> declared
  default — the default applies ONLY to MODEL-PICKED tools (loop passes
  `model_picked=True` on the LLM dispatch path), so fastpath acts and plain
  chat stay act-first (autonomy-split law 1).
- `RiskDecision` + `refused` (policy 'never' = refuse outright, spoken
  honest cancel — never silent) and `by_policy` (an explicit verdict
  outranks the loop's legacy force-gate).
- `policy_summary()` — the spoken answer to "what requires your confirmation?"
  (fastpath intent, deterministic).

Security direction: gates STRONGER, never weaker — the declared default
turns previously-ungated model-picked tools into confirm-first; 'auto' can
only open classes the USER names in their own config; the regex fallback,
AUD-09 non-voice rule, high-risk list, and voice_ok review channel are all
unchanged. Tests: `brain/tests/test_confirm_policy.py` 17 (policy matrix,
fallback, chat-safety, fail-closed, summary) + qa's pinned confirm/act tests
must stay green (full-suite run recorded with the batch).

## Action

`python tests/core_guard.py --update --approval docs/requests/brain-core__to__integrator__confirm-policy-wiring.md`
— re-pins `brain/confirm.py` for this approved change.
