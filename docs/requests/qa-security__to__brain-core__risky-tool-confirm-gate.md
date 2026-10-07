# qa-security → brain-core: risky-tool-confirm-gate
Status: OPEN

## What
`brain/loop.py` section 1 calls `confirm_mod.classify(text)` with the raw job
text only — never `tool=`. The registry metadata (`describe(name)['risky']`)
and `confirm.RISKY_TOOLS` are therefore never consulted at dispatch time.
INTERFACES §b promises: "each tool declares `risky` (confirm-gated —
`brain/confirm.py` enforces in code) … Never left to a model's judgment."

Proposed change: after tool resolution (both the fastpath-tool branch and the
LLM-extracted branch), before dispatch:
```python
decision = confirm_mod.classify(text, tool=tool_name)
if decision.needs and not already_confirmed_for(this_job, tool_name):
    # emit needs_confirm / await confirmer (same flow as section 1)
```
(or hoist: run `classify(text, tool=tool_name)` once AFTER extraction and
before section 4, so one gate covers both branches).

## Why
Today the exposure is latent because LLM tool extraction is broken
(`…__tool-call-extraction`), but the moment that lands, a benign-sounding job
whose plan emits `{"tool": "shell", …}` would execute `shell=True` with NO
confirmation — a direct Core Guard violation (AGENT_RULES §8 intent, RVA §8
"sensitive-action list in code before any worker acts").

## Impact
Touch: `brain/loop.py` (+ possibly a confirm helper in `brain/confirm.py` —
confirm.py semantics are §8-guarded, so land this WITH integrator approval).
qa-security regression: `tests/security/test_core_guard_and_secrets.py` +
a new test will be added when the gate exists (request author will supply).
