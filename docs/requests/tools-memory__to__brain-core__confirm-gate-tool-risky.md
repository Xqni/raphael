# tools-memory → brain-core: confirm-gate-tool-risky
Status: OPEN

## What
`brain/loop.py` step 1 (confirm gate, ~line 113-114) calls `confirm_mod.classify(text)` **without the tool name**, and the registry's `risky` metadata is never consulted (meta is fetched only later, ~line 206, and only `needs_lock`/`category` are used from it).

Proposed change in `brain/loop.py` (brain-core owns the file):

```python
# before (current):
decision = confirm_mod.classify(text)

# after:
decision = confirm_mod.classify(text, tool=tool_name)
if tool_name and tool_reg.describe(tool_name).get('risky'):
    decision.needs = True   # registry metadata is authoritative; text patterns stay as defense in depth
```

`confirm.classify(text, tool=...)` already accepts the `tool` parameter and matches it against `RISKY_TOOLS` — it is simply never passed today. Fetching `tool_reg.describe(tool_name)` at the gate is a dict lookup (it is already imported as `tool_reg`).

## Why
INTERFACES §(b): *"each tool declares `risky` (confirm-gated — `brain/confirm.py` enforces in code) ... Never left to a model's judgment."* The registry docstring says the same. Today the gate relies on **text patterns only**, so confirmation of a risky tool depends on the user's phrasing.

This blocks tools-memory Wave 3: `file_trash` ("trash it" matches no pattern — `RISKY_PATTERNS` has delete/remove but not trash), `github_set_visibility` (private→no pattern hit), `mcp_*` (default-risky, arbitrary phrasing). Without the fix, those confirm-gates are pattern-luck rather than code-enforced.

## Impact
- Fail-closed direction only: more confirmations, never fewer. Non-risky tools unchanged (describe() returns `risky: False` by default). Timeout/deny paths already exist (30 s → abort).
- Touches Core Guard confirm semantics (AGENT_RULES §8: confirm.py semantics need integrator approval even though brain-core owns the file) — **this strengthens the gate, never weakens it**; flagging for integrator review anyway.
- No shared-contract change: INTERFACES §(b) already specifies this behavior; the code just hasn't caught up.
