# qa-security → brain-core: tool-call-extraction
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: the broken regex is gone — `brain/loop.py:67-100` `_extract_tool_call` is now a balanced-brace scanner with nested-object support (docstring names the old `[^{}]*` failure). The pinned xfail is now a strict pin and passes: `tests/regression/test_act_pipeline.py:101-103` "PINNED STRICT 2026-10-06 (was xfail): LLM tool calls now dispatch through the OpenAI tool_calls response path" — `test_llm_tool_call_with_args_dispatches_to_body` → passed (run 2026-10-09).

## What
`brain/loop.py::_TOOL_CALL_RE = r'\{[^{}]*"tool"[^{}]*\}'` can never match a
realistic tool call — `[^{}]*` stops at the first inner brace, so
`{"tool": "launch_url", "args": {"url": "…"}}` (and even `{"args": {}}`) does
not match. Verified: `_extract_tool_call` returns `(None, {})` for every
nested-args payload (probe in review §1.8 T2).
Pinned by `tests/regression/test_act_pipeline.py::test_llm_tool_call_with_args_dispatches_to_body`
(xfail today).

Proposed change: replace regex extraction with balanced-JSON scanning, e.g.
find `{"tool"` then use `json.JSONDecoder().raw_decode()` from the opening
brace — or (better long-term) move model tool-calling to the OpenAI
`tool_calls` response shape once INTERFACES §a `chat(tools=…)` exists.

## Why
Until this is fixed, tools are unreachable from model plans: the job "succeeds"
by narrating raw JSON as if it were the answer (silent wrong-behavior, not a
crash). The whole act-pipeline/computer-use story from a free-form request
depends on it.

## Impact
Touch: `brain/loop.py` only. Must keep `_extract_tool_call`'s signature
(tool_name, args) for the runner. Regression-tested by the xfail above — it
flips green automatically when fixed. Pairs with `…__risky-tool-confirm-gate`
(fix extraction only WITH the confirm gate, see that request).
