# voice → brain-core: narrate `warn` notices with level-tinted phrasing
Status: OPEN

## What
Wave 5 voice deliverable "Notice level-tinted phrasing" ships the voice side:

```python
from brain.voice import notice_spoken_text   # pure: info as-is, warn -> "Warning: ..."
await voice.speak_notice(text, level='info'|'warn', job=..., cancel=...)
# same speak-event stream as voice.speak(); broadcasts exactly like narrate()
```

`brain/notice.py` currently BROADCASTS `notice` frames only (ui/cli) — nothing
is spoken. Proposed wiring in the notice emit path (brain/notice.py, or
wherever notices are narrated):

```python
frame = build(text, level=level, job=job)
+ # spoken delivery: warn gets a crisp lead-in, info stays as-is; queue behind
+ # speech per PROTOCOL §5 (never interrupts an in-flight speak)
+ asyncio.create_task(_speak_notice(frame))   # voice.speak_notice(frame['text'], level=frame['level'], job=frame.get('job'))
```

Guard suggestions: honor `voice_personality.proactive_warnings:
actionable_only` (speak only actionable warns), and skip when private mode /
paused (existing notice delivery rules apply).

## Why
Wave-5 voice lane bullet: "Spoken delivery of the new formats … Notice
level-tinted phrasing". The phrasing + speak wrapper exist and are tested
(`brain/voice/tests/test_personality_delivery.py`); only the call-site in the
notice path is missing, and `brain/notice.py` is brain-core-owned (granted per
the wave-3 merge record).

## Impact
Additive: notices keep broadcasting as before; speech failures are already
non-fatal in `_speak_and_broadcast`. No frame-shape change (the `notice`
frame itself is untouched), no Core Guard involvement. If you prefer a
different phrasing rule, change it inside `notice_spoken_text` (voice lane
owns it) or pass `level='info'` to disable tinting per call.
