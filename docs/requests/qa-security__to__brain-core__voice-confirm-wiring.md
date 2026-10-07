# qa-security → brain-core: voice-confirm-wiring
Status: OPEN

## What
Spoken confirmation is not wired: `ws._on_audio_end` feeds transcripts only
into `wake.gate()` → a NEW job; nothing ever answers a pending `needs_confirm`.
So the voice-first confirmation loop (RVA §7, PROTOCOL §9.2 "user replies by
speech (Body mic → stt_final)") can never resolve — every risky job
timeout-aborts unless a text client answers.

Proposed change (brain-core owns the loop/hub seam):
1. In `_on_audio_end` (or the loop's voice seam): while
   `engine.confirmer` has pending job(s) AND the gate match is a plain
   yes/no/modify utterance (use `confirm_mod.parse_free_text`), resolve the
   PENDING job via `confirmer.resolve(rowid, text)` instead of submitting a
   new command. Per-job binding stays job-id based (never "latest confirm").
2. **Channel rule (pairs with integrator__voice-confirm-channel):** a
   voice-derived answer may only resolve NON-risky confirms; risky/high-risk
   confirms must be answered from a non-voice channel (typed command, orb
   menu, CLI). Enforce in code where the channel is known.
3. Only ONE pending confirm may exist at a time for voice answers — if two
   are pending, ask the user to use the screen (don't guess which job the
   word "yes" belongs to).

## Why
RVA §7 is a user directive (voice-first), and the current state is both
non-functional AND the moment it is naively wired it becomes the acoustic
injection vector (review §1.4 C1/C2): TTS/speaker replay of "yes" would grant
risky jobs. Wiring and the channel rule must land together.

## Impact
Touch: `brain/ws.py` (integrator-owned — needs integrator co-sign or merge),
`brain/loop.py`, possibly `brain/confirm.py` (§8: integrator approval).
qa-security xfails that flip green: `regression/test_confirm_flow.py::
test_spoken_yes_resolves_pending_confirmation` and
`::test_voice_channel_grant_is_refused_for_risky_job`.
