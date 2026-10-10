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

## Batch B — background-task gates (`tests/regression/test_wave5u_background_gates.py`)

| Gate | Deliberate weakening | Result |
|---|---|---|
| only one lock holder / FIFO no-steal | `lock.py::acquire`: `if self._owner is None:` → `if True:` (newcomer steals) | **RED** `test_second_lock_job_queues_behind_owner_then_gets_handed_off` + `test_force_release_drops_waiters` (2 failed) |
| workers cannot emit speak/act frames | `ws.py`: `CAN_SEND_AUDIO = {'body'}` → `{'body','worker'}` | **RED** `test_worker_and_chat_cannot_emit_speak_or_act_frames` (1 failed) |

Not duplicated here: `tasks never auto-resume after restart` — already covered
end-to-end by `tests/resilience/test_crash_recovery_interrupted.py` (real
isolated brain reboot; PROTOCOL §5). Deferred to world-state landing (brain-core
Wave B, after P0.6): a mock-clock `chat latency unaffected by a running task`
engine-admission test; the InputLock boundary that keeps chat un-serialized is
pinned now (`test_non_lock_job_is_never_serialized_behind_a_lock_task`).

## Batch C — browser-safety tripwires (`tests/regression/test_wave5u_browser_safety.py`)

| Gate | Deliberate weakening | Result |
|---|---|---|
| PROTOCOL documents password/scheme/loopback refusals | `PROTOCOL.md`: drop "password-field typing … refused" | **RED** `test_browser_contract_documents_safety_refusals` (1 failed) |

Runtime refusal checks (password-field type, javascript:/file:/data: nav, CDP
loopback) are **skip-until-landed** — pc-control's browser worker is Wave 5U P1
and not merged; `test_browser_worker_enforces_refusals` activates on merge and
joins the mutation regimen then.

## Batch D — chat/UI tripwires (`tests/regression/test_wave5u_chat_ui_gates.py`)

| Gate | Deliberate weakening | Result |
|---|---|---|
| no innerHTML sinks in orb renderer | append `el.innerHTML = frame.text;` to renderer.js | **RED** `test_no_innerhtml_sinks_in_orb_renderer` (1 failed) |
| token never in a URL | `instance.js` wsUrl(): append `?token=${readToken()}` | **RED** `test_ws_url_never_carries_the_token` (1 failed) |

Note: the first wsUrl test draft had a `[^}]*` regex blind spot (stopped at the
`}` inside `${wsPort()}`) that let the token mutation through — caught by the
mutation check itself and fixed to scan the whole module for `wss?://…token`
(then re-mutation-verified red). This is why every gate is mutation-checked.

## Batch B/D addendum — fleet + personal-routing gates

| Gate | Deliberate weakening | Result |
|---|---|---|
| worker cannot resolve a confirm | `ws.py`: `CAN_SEND_CONFIRM_RESP` += `'worker'` | **RED** `test_worker_cannot_resolve_a_confirm` (1 failed) |
| personal_ok excludes free providers | `config.yaml`: `personal_ok: [go, ollama]` → `+= zen_free` | **RED** `test_personal_ok_excludes_free_providers` (1 failed) |

Task-6 (move `scan_personal.py --strict` into CI) is already DONE: the FAIL-only
strict gate is wired in `.github/workflows/tests-heavy.yml:57` (SEC-1 criterion-4,
option-1; ci.yml stays Core-Guard-pinned and advisory-only).

Deferred to dependency landing (noted, not skipped silently):
- fleet `allowlist` enforcement ("specialist cannot call a tool outside its
  allowlist") — needs the fleet runtime (brain-core Wave D).
- router mock-spy (assert zen_free is never SELECTED for a personal payload) —
  activates when the router consumes `personal_ok` (router P2); the `_skip_free`
  config boundary it relies on is pinned now.
- golden transcript for the YouTube same-tab flow + Definition-of-Usable script
  (`tests/e2e/usable_checklist.md`) — Wave B demo scope.
