# qa-security → integrator: confirm-policy spec-class divergence (Wave 5P P3)

Status: OPEN

## What
`docs/research/persona/06-CODE-ADOPTION-PLAN.md:29` (P3 spec) names the policy
classes `gui_submission`, `open_arbitrary_file`, `files_write`, **`web_publish`**,
`system_*`. The integrator-authored `config.yaml:116-134` carries
`gui_submission`/`open_arbitrary_file`/`files_write` + `system_settings_change`
but **no `web_publish` class** (verified: `web_publish` appears nowhere in
`config.yaml` or `brain/`).

## Why it is a NOTE, not a gate
Behavior is already covered:
- publish-style text (`publish|tweet|post|send message|send email|share`) maps
  to `send_message` via `ACTION_BY_REASON` (brain/confirm.py:67-75) → policy
  `send_message: confirm` ✓
- read-only fetch is `web_fetch: auto` ✓

So nothing is ungated; only the named class diverges from the spec wording.

## Asks
1. Integrator: either add a `web_publish` class (then brain-core maps publish
   targets to it in TOOL_ACTION/ACTION_BY_REASON) **or** amend P3's class list
   to match the shipped config (web_fetch/send_message).
2. If a class is added: `tests/regression/test_confirm_policy.py` matrix test
   only enforces validity + destructive-class strength, so no test change is
   required unless the class is destructive (then it must be `confirm`).

## Note (for brain-core, recorded here while reviewing P3)
`config.yaml:134` states policy edits "must go through a confirmed act
(self-protecting)" — there is no runtime config-write path today
(`brain/config.py` exposes no save/write fn), so this is NOT-APPLICABLE now.
If a policy-edit affordance lands, its write MUST be confirm-gated (and must
not be swallowed by `files_write: auto`).
