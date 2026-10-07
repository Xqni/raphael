# qa-security → brain-core: bug-e-hold-speaking
Status: OPEN

## What
`docs/BUGS-WAVE2.md` Bug E: orb flickers `speaking → listening → speaking`
between TTS sentences. Dossier task (assigned to you): "hold `speaking`
until the utterance (all sentence chunks) ends (speak end event), never
derive mid-utterance."

Current code contradicts the fix direction in TWO places:
1. `brain/orbstate.py::derive_state()` precedence:
   `booting > confirm > listening > speaking > ...` — any `_listening` flag
   during `_speaking > 0` derives `listening` mid-utterance;
2. `brain/ws.py::_on_audio_start` comment explicitly documents
   "(takes precedence over any in-flight speaking)" when it calls
   `orbstate.listening_on()` + `emit('listening', ...)`.

So please decide and implement the reconciled rule (suggested):
- if `_speaking > 0` → derive `speaking` (hold to `speak_end`), and do NOT
  broadcast a mid-utterance `listening` from `audio_start`; OR
- allow genuine barge-in audio to preempt ONLY when the mic transcript is
  real (ptt/wake with speech), not from a bare `audio_start`.

## Why
Renderer logs during a 2-sentence answer showed the flicker; the repeated
`startMorphTo` restarts mid-ramp are a suspect for Bug C's "cages stuck in
weird shape" too. Regression test already written and parked:

`tests/regression/test_gate_bug_regressions.py::
test_speaking_held_over_listening_mid_utterance` (xfail today — flips green
when precedence/hold lands).

## Impact
Touch: `brain/orbstate.py` (and possibly `brain/ws.py` audio_start — that
file is integrator-owned → co-sign). Contract note: PROTOCOL §8/INTERFACES §e
state machine unchanged; only the mid-utterance derivation order.
