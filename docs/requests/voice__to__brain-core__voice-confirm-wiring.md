# voice → brain-core: voice answers for LOW-risk confirmations (yes/no/modify)
Status: OPEN

## What
The voice-side parser ships in `brain/voice/confirmation.py` (voice lane,
already tested):

```python
from brain.voice import parse_voice_answer, to_confirm_answer, \
    voice_confirmation_answer

answer = voice_confirmation_answer(transcript, low_risk=True)
# -> 'yes' | 'no' | None   (None = not a usable answer: keep waiting)
```

Semantics (PROTOCOL §9.2 + addendum §7):
- `"yes"` / `"sure"` / `"uh huh"` → `'yes'`; `"no"` / `"stop"` → `'no'`;
- conditional speech (`"yes, but only the PDFs"`, `"change it to five files"`)
  → parses as `modify`, mapped to `'no'` (abort + re-ask, never a silent
  approval);
- unclear speech → `None` (fail closed; the confirmation timeout still ABORTS);
- **`low_risk=False` always returns `None`, even for a clear "yes"** — voice
  must never resolve a high-risk confirmation (the non-voice channels —
  typed `confirm_resp` / orb menu — are the only accepted path there).

Proposed wiring (2 small pieces, different owners — flagged here so the
decision lives in one place):

1. **brain-core** (`brain/confirm.py`): expose the risk split as a predicate,
   e.g. `voice_safe(rowid) -> bool`, backed by the RiskDecision already
   computed when `needs_confirm` is emitted (store `risk_reason` on the
   pending confirm if it is not retrievable). Voice answers are accepted only
   when that returns True. Rationale: the low/high classification is Core
   Guard semantics (AGENT_RULES §8) and must not be re-derived by the voice
   lane.
2. **integrator** (`brain/ws.py` `_on_audio_end`, unlisted file → integrator
   by the OWNERSHIP default rule): when `engine.confirmer` has a pending job
   and the transcript is a usable answer, resolve it instead of submitting a
   new job:

   ```python
   pending = self.engine.confirmer.pending_ids()
   if pending:
       reply = voice_confirmation_answer(
           res.text, low_risk=confirm_mod.voice_safe(pending[0]))
       if reply is not None:
           self.engine.confirmer.resolve(pending[0], reply)
           await self._send(s, {'type': 'ack', 'v': 1, 'audio': 'end'})
           return
   # else: existing behavior (wake gate -> engine.submit)
   ```

## Why
Wave 2 task 4 (voice confirmation parsing). PROTOCOL §9 says the user answers
speech questions by speech; today a spoken "yes" becomes a NEW JOB with the
text "yes" and the confirmation waits for a `confirm_resp` frame that only the
orb/CLI sends — so spoken confirmations time out and abort (safe, but the
voice-first loop of addendum §7 does not work).

## Impact
No shared-contract change (no PROTOCOL frame changes), no Core Guard
weakening: fail-closed defaults are preserved in the parser itself
(`None` on anything unclear; `None` for high risk). If only piece 1 lands and
piece 2 does not, nothing changes at runtime. If only piece 2 lands without 1,
the proposed snippet must treat "risk unknown" as high-risk (voice refused).
