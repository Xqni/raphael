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

## What (P6 — spoken memory privacy; added 2026-10-09 as landed)
`brain/memory/privacy.py` is built + tested (6 tests; suite 205 green; wave-4
export/delete coverage re-verified first: `export_all`/`wipe`/`store.forget`/
`delete_skill`/trash-restore — 7/7). Intent surface for fastpath:

```python
from brain.memory import privacy
r = privacy.recall('X')            # -> {'count','rows','text','slot'}; text is
                                   #    speakable ('Nothing remembered.' when empty);
                                   #    slot= optional READ-ONLY override (bad name -> ValueError -> clarify)
d = privacy.forget_fact('X')       # -> {'status':'needs_confirm','matches','preview'}
                                   #    speak preview + confirm question (P3 confirm_policy
                                   #    class: destructive -> confirm-first)
if approved:
    d = privacy.forget_fact('X', confirmed=True)   # -> {'status':'done','deleted':n}; idempotent
txt = privacy.memory_report()      # one speakable paragraph (counts/slots/export pointers)
```

All three are LOCAL sqlite paths (no router import — private-mode safe,
tested with router.boom). forget is owner-wide by design ('forget it' means
everywhere), never cross-owner.

## What (P7 — journal as a memory surface; added 2026-10-09 as landed)
`brain/memory/journal.py` (vault/journal.md, gitignored, APPEND-ONLY mode
'a' only, redaction pass before every write — secrets/ids/placeholders per
SEC-1 conventions; 7 tests green incl. prefix-preservation + source-shape
append-only checks). Intent surface:

```python
from brain.memory import journal
journal.append('Milestone: ...')   # -> {'path','entry','redactions'}; single-line
                                   #    dated entry; fail-silent; never raises
journal.read_recent(limit=10)      # -> last N entries (spoke on
                                   #    "what did you do recently"); '' if empty
```

- fastpath intents: "log <x> to your journal" / "remember this in your
  journal" → `append` (speak "Logged." + redaction count if >0); "what did you
  do recently" → `read_recent` → speak/format last few (local, no LLM needed).
- Journal path is repo-root `vault/journal.md` per §8b of the canon brief.

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
