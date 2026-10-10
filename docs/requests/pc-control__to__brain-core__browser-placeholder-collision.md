# pc-control → brain-core: browser-placeholder-collision
Status: OPEN

## What
`brain/confirm.py` still carries HARDCODED placeholders for a never-shipped
`browser` tool:

```python
RISKY_TOOLS = {'shell', 'powershell', 'exec', 'network', 'net', 'ssh',
               'git_write', 'files_delete', 'computer_use', 'browser'}     # :~25
TOOL_ACTION = {…, 'browser': 'network',}                                   # :~83
```

The REAL `browser{op}` tool now ships (Wave 5U §5.2, pc-control) with an
explicit confirm class (`{default: auto, when: click/type -> gui_input}` —
see `pc-control__to__brain-core__confirm-class-tags.md`). The stale
`RISKY_TOOLS` entry now COLLIDES with the live tool in the loop's
classify/dispatch paths and correlates with qa-harness breakage (below).

**Requested:** delete `'browser'` from `RISKY_TOOLS` and `TOOL_ACTION`
(both are your Core-Guard-listed file — placeholders superseded by the
explicit class tags; any needed gating comes from the class policy, not the
name list).

## Evidence (verify-first bisect, all local + real)
| tree | root suite |
|---|---|
| clean origin/main (c03870b) | **309 passed / 0 failed, 50 s** |
| + pc `_spec.py` only | 309 passed / 0 failed, 50 s |
| + browser SPEC present, NOT registered | 309 passed / 1 (qa schema-parity artifact of the experiment), 50 s |
| + browser REGISTERED (shipped state) | 307 passed / **3 failed, 167 s** |

Failing in the shipped state (order-dependent — each passes in isolation):
`test_llm_reply_delivered_verbatim`, `test_usage_log_has_no_prompt_or_key_text`,
`test_provider_storm_fails_cleanly_then_recovers` — all 40 s mock-provider
reply timeouts (consistent with confirm-timeout-class hangs). A temp
uncommitted removal of the two placeholders was attempted as confirmation
but trips the Core-Guard byte-stable check (as designed) — hence this
request instead of a local experiment.

## Impact
- Two-line removal in your file; pc-control's browser tool keeps its
  explicit conditional class (auto / gui_input on click+type);
- unblocks the root suite for my branch merge (my suites are otherwise
  green: body 226, specs 13, e2e 156; brain 1233 + 1 pre-existing main
  failure `test_speak_batching` = yours/integrator's, fails on clean main
  too).
