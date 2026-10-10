# tools-memory → brain-core: Wave-5P memory seams (P5 slots; P6/P7 intents to follow)
Status: OPEN

## What (P5 — named context slots, voice switch)
`brain/memory/slots.py` is built, tested (10 tests, full suite 199 green):
retrieval is **internally scoped** to the active slot (including pinned rows
and `build_context`), so **no loop.py injection change is needed for scoping
itself**. The only brain-core half of P5 is the voice/intent surface:

```python
from brain.memory import slots
slots.switch_slot('travel')   # act-first (no confirm per plan §P5), normalizes
                              # '  Travel  ' -> 'travel', persists in the
                              # state table, returns {'from','to','changed'}
                              # -> speak e.g. "Switched to travel."
```

- fastpath phrases: "switch to <slot>" / "switch to travel" / "switch back to
  default" → `switch_slot`; `ValueError` → one spoken clarification (P4-style,
  never a crash); `changed == False` → "Already in travel."
- `slots.list_slots()` (names + counts + active) can back a status line /
  "what context am I in" — optional, your call.
- Default behavior is UNCHANGED: active slot starts at `default`, every
  pre-existing memory row is `slot='default'` (schema default), so today's
  answers are byte-identical until the user switches.

## Why
06-CODE-ADOPTION-PLAN §P5 assigns "(tools-memory + brain-core)"; my half is
the store/scoping seam, yours is the spoken switch. Session-persistence is
already handled (state table) — nothing else needed from you for P5.

## Impact
- No PROTOCOL/Core Guard change; `switch_slot` is local+cheap (act-first is
  the packet's explicit ruling: "no — creation is cheap/local: act-first").
- P6 ("what do you remember about X" / "forget X" / "memory report") and P7
  ("journal append" / "what did you do recently") intents will be added to
  THIS file as I land those packets — one seam list for your fastpath batch.
