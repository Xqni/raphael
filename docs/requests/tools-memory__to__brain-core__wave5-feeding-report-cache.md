# tools-memory → brain-core: wave-5 memory feeding + report-cache hooks
Status: OPEN

## What
Two one-line-class call sites in brain-core-owned code, using APIs that are
built, tested and on `agent/tools-memory`:

**1. Kind-aware memory feeding** (extends/supersedes the injection part of
`tools-memory__to__brain-core__loop-memory-skills-injection.md`, still OPEN):

```python
from brain.memory.retrieval import build_context
# per LLM turn, where you assemble messages (non-private, personal gate as configured):
ctx = build_context(user_text, kind=job_kind,          # chat|analysis|simulation|act
                    include_personal=<your privacy decision>)
if ctx:
    # append as ONE untrusted-context message (block already framed + marker-neutralized)
    ...
```

Budgets (config `memory.kind_budgets`, built-in defaults): `analysis` k=10 /
8000 chars, `simulation` k=4 / 3000, everything else k=5 / 4000 — Analysis
gets the fuller recall it needs for a Report, Simulation stays lean. `''`
means inject nothing; the call itself is fail-silent.

**2. Report cache hook** (new): when `formats.py` emits a `report` frame
(or right after), cache it:

```python
from brain.memory import reports
reports.save_report(title=..., summary=..., sections=..., job=job_id,
                    kind='analysis')   # fail-silent: returns None on any error
```

Caps (summary<=500, sections<=10, text<=2000) are re-enforced inside
`save_report` (defense in depth — a malformed frame truncates, never raises),
so the emit path cannot break on cache input. Recall side (`find_reports`,
`recent_reports`, owner-scoped, fail-silent) is ready for cross-session
report recall / future prompt assembly.

## Why
Wave-5 lane checklist ("Memory-context feeding for Analysis/Simulation
(retrieval budgets per kind) + Report caching"); formats/Simulation kinds
landed in your wave-5 batch (`brain/formats.py`, engine `kind` validation),
the store side is mine. Without call sites, Analysis turns run with no
memory context and Reports are unrecallable after the UI scrolls away.

## Impact
- No PROTOCOL frame change, no Core Guard touch: internal store + one message
  append; every failure path returns `''`/`None` (a memory hiccup never fails
  a turn or an emit — same contract as the landed `conversation.on_turn`);
- prompt growth strictly budgeted per kind (≤8000 chars worst case, config);
- personal categories stay under YOUR privacy-gate decision via
  `include_personal=`.
