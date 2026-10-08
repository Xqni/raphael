# router → brain-core: stop labeling every tool-equipped turn `purpose='tool'`
Status: OPEN

## What
`brain/loop.py:697-699` (verified 2026-10-08):
```python
stream = await llm.chat(messages, tools=specs or None,
                        stream=True,
                        purpose='tool' if specs else 'chat')
```
With `specs` non-empty on every LLM turn (tools are registered), every turn
labels itself `tool` → `purpose_roles['tool'] = strong` → **qwen3.6-plus on
trivial knowledge questions**. My half of the latency dispatch is done:
`Router._role_for` no longer escalates on mere tool presence
(`purpose='chat'` + tools available → FAST), but the loop label keeps
overriding it.

Proposed (your file, your call):
```python
# first/intent turn: answer intent → purpose='chat' (tools still OFFERED)
stream = await llm.chat(messages, tools=specs or None, stream=True,
                        purpose='chat')
# …and after the model actually returns tool_calls (tool-execution steps),
# label those steps purpose='tool' so they keep the strong tier.
```
Escalation then triggers on REAL tool use/complexity, exactly as the
dispatch words it ("not tool presence alone").

## Why
Dispatch 2026-10-08 (morning latency lever #2): measured 3.45s
first-subtitle on a trivial question vs 0.0s fastpath. Router-side fix
landed (`core._role_for`, commit 8b40c9e) with a LIVE A/B (n=6/arm, real
cloud, seam-level): strong/qwen3.6-plus first-delta median **3.85s** vs
fast/mimo-v2.6-flash **3.48s** (first-sentence 3.94 → 3.53); model switch
verified, directionally ~0.4s median, long tail on the fast arm (max 6.4s —
provider variance). The live number only moves once the label changes.

## Impact
One-line change in your file; router unchanged. `purpose='tool'` on actual
tool-execution steps preserves the strong tier per the dispatch
("keep strong for tool/plan"). My tests pin both sides:
`test_tiered_analysis_routing.py::test_role_for_prefers_depth_over_the_tools_rule`
(chat+tools → fast, tool/plan → strong) and
`::test_normal_turns_stay_fast`.
