# brain-core → integrator: confirmation hardening changes (Core Guard §8 — for review)

From: brain-core lane. Date: 2026-10-06. Kind: heads-up/review of `brain/confirm.py` + confirm plumbing changes made under my Wave-2 brief item 3 ("Confirmation hardening"). These STRENGTHEN enforcement — nothing is weakened — but §8 says Core Guard changes need integrator awareness, so: please review on merge.

## What changed

1. **Risk tiers**: `RiskDecision` gained `action` (normalized id) + `risk` (`high`/`low`). HIGH = the action maps onto `config.yaml → safety.confirm_actions` (the config list is the authority; read at call time). All pattern hits are now collected (previously first-hit-only) and the question prefers the high-risk hit.
2. **Pattern order**: the delete pattern moved ABOVE the generic privileged-command pattern and gained `rm|del|unlink`, so `rm -rf` classifies as `delete_files` (HIGH) instead of a generic system command (low).
3. **Channel gate**: `Confirmer.request(..., risk=...)`; answers carry a channel (`voice`/`click`/`text`, role-derived when the client doesn't declare one: body=voice, ui=click, cli=typed). A voice **affirmative** on a HIGH-risk confirmation returns `rejected_channel` — the pending future survives (user can still confirm from the orb/keyboard; timeout still aborts, never auto-approves). Voice **denial** always works (denying is safe).
4. **Voice answer paths**: `confirm_resp` with `via`/role=body, voice-source `command` frames with a clear yes/no, and `audio_end` STT transcripts (clear yes/no only — anything else falls through to the wake gate) all resolve the OLDEST pending confirmation.
5. **Orb click path**: `orb_input {kind:'menu'|'click', value:'yes'|'no'}` resolves as the non-voice channel; `orb_input {kind:'submit_text', value}` is the typed channel (Wave-2 lane task).
6. **Dispatch-time gate** (strengthening): a model-picked `risky` tool now triggers confirmation even when the user's text was benign (previously only text patterns could trigger).

## API notes for other lanes

- `Confirmer.resolve() -> bool` unchanged (back-compat); new `resolve_ex() -> 'ok'|'rejected_channel'|'none'` and `resolve_oldest_pending(text, via)`.
- `needs_confirm` frames now carry `risk: high|low` (additive field).
- Confirm `ack`s carry `accepted: true|false` (+ `hint` on rejection) — additive.

## Side fix (same files)

Jobs now really transition to store status `awaiting_confirm` (and back to `running` on grant). Before, only the *event* said `awaiting_confirm` while the store stayed `running` — so `stats.jobs_pending_confirm` was always 0 and the orb could never derive INTERFACES §e `confirm`. Tests: `brain/tests/test_agent_loop.py` + `test_confirm_hardening.py`.
