# voice → brain-core: utterance continuation merge (STT latency Cut A)
Status: OPEN

## What
To cut the 2 500 ms body VAD hangover (71 % of the perceived
stop-speaking→subtitle wait — measurement: `brain/voice/STT-REPLY-LATENCY.md`)
down to 1 200 ms WITHOUT reintroducing the proven mid-command split, `audio_start`
needs a third reason on the body side:

```python
# brain/ws.py::_on_audio_start (proposed)
reason = msg.get('reason')
if reason == 'continuation':
    # same utterance resumed inside the grace window — APPEND, never clear
    if not hasattr(s, 'audio_buf') or s.audio_buf is None:
        s.audio_buf = bytearray()          # defensive: lost part 1
else:
    reason = reason if reason in ('ptt', 'wake') else 'wake'
    s.audio_reason = reason
    s.audio_buf = bytearray()              # fresh segment (today's behavior)
```

`audio_end` then transcribes the accumulated (possibly part-1 + part-2) buffer
exactly once and proceeds as today. Optional hardening: if a part-1 job was
already submitted (it will be only if we ever act before grace — with this
design we don't), `confirmer`/queue cancel is unnecessary because the body
sends NO `audio_end` until the utterance really ends.

## Why
- Measurement: `audio_end` → first `subtitle` = **578 ms median** (Groq STT);
  the 2 500 ms `SILENCE_CLOSE=25` hangover dominates everything.
- Plain reduction to 1.5 s was PROVEN to split live utterances (PROGRESS:
  "wake in seg1 + command in seg2 → gate rejects BOTH") — that is why it is
  2.5 s today. The continuation reason makes a resume inside the grace window
  non-splitting, so the hangover can drop to 12 frames (1.2 s).
- Expected result: stop-speaking → subtitle ≈ **1.8 s** (was ≈3.1 s), zero
  split regressions (verified by the joint test below).

## Impact / coordination
- Body half (send `reason='continuation'` on resume within `GRACE_S=1.5 s`,
  keep SILENCE_CLOSE=12) is **voice's file** (`body/win/audio_in.py`) and is
  ready to land the moment this is accepted — I will NOT land it alone (it
  would recreate the split bug without your append logic).
- Joint verification: my suite gets a mock E2E for the continuation sequence;
  brain-core adds one for the append path. No protocol frame changes beyond
  the new `reason` value (additive enum; PROTOCOL §3 update = integrator's,
  flagged here). Core Guard untouched.
