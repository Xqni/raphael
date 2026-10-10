# Wave 5U Wave A — mutation checks (qa-security)

**Date:** 2026-10-10 · **Lane:** qa-security · **Packet:** USEFUL-NOW §5.5 (Wave A)
**Acceptance rule:** every gate test must FAIL on a deliberately weakened build.

Each row = the gate, the deliberate weakening applied to the build, and the
observed red test (then the build was restored via `git checkout`/backup; zero
residual diff).

## Batch A — confirm gates (`tests/regression/test_wave5u_confirm_gates.py`)

| Gate | Deliberate weakening | Result |
|---|---|---|
| voice `yes` on high-risk rejected (acoustic-injection guard) | `confirm.py::resolve_ex`: `if via == CHANNEL_VOICE and is_yes and risk=='high':` → `if False:` | **RED** `test_voice_yes_on_high_risk_is_rejected_and_pending_stays` (1 failed) |
| policy not loosenable by config.d fragment (AUTHORITY_KEYS) | `config.py`: `AUTHORITY_KEYS = ('safety','privacy','providers')` → `()` | **RED** `test_policy_cannot_be_loosened_by_config_d_fragment` + `test_authority_keys_enforced_in_loader` (2 failed) |

Untestable-by-mutation (xfail tripwire, gate not landed): `unclassified tool → confirm`
— `classify()` still returns `needs=False` for an unknown tool; the tripwire
`test_unclassified_tool_defaults_to_confirm` flips to pass when brain-core's P3
confirm_policy lookup lands (lane line 72). Once landed it joins the mutation
regimen.
