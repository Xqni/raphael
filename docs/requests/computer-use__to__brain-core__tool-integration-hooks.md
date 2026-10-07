# computer-use → brain-core: tool-integration-hooks
Status: OPEN

## What
Three small hooks in brain-core-owned files so the `see_screen` / `computer_use` tools work
end-to-end. My tools are registered and unit-tested already (`brain/tools/computer_use/`);
these are the integration points that live in your files:

1. **Tool spec convention** (for your auto-discovery + spec validation task):
   each `brain/tools/<ns>/` package exposes `SPECS: dict[tool_name -> JSON Schema]`
   (strict: `type: object`, typed properties, `required`, `additionalProperties: false`)
   alongside its `register(...)` calls. Mine: `brain/tools/computer_use/spec.py` re-exported
   as `brain.tools.computer_use.SPECS`. Loader should validate each entry and fail loudly.

2. **Sync tools need the main loop.** `loop.py` runs local tools via `asyncio.to_thread`
   (no running loop in the worker thread), but `see_screen` / `computer_use` must drive the
   act pipeline (`hub.broadcast` + `engine.expect_act`) which only works ON the brain's main
   loop. My bridge resolves it as: explicit `wiring.bind_loop(loop)` → `engine._queue_loop`
   → `hub._ping_task.get_loop()`. Cleanest fix: call
   `brain.tools.computer_use.wiring.bind_loop(asyncio.get_running_loop())` once in
   `app.py` lifespan (next to `hub.engine = engine`). Until then the `_queue_loop` fallback
   works — this request just makes it a supported hook instead of a private-attr read.

3. **Fastpath intents for Wave 2 exit criterion #3** ("What am I looking at"):
   register in `fastpath.register_builtin_intents()`:
   ```
   ('what am i looking at', "what's on my screen", "what is on my screen",
    'describe my screen', 'look at my screen', 'see my screen')
   -> IntentResult(text='Let me look.', tool='see_screen',
                   tool_args={'question': original_text}, needs_lock=False)
   ```
   (question = full utterance; the vision prompt is composed in my service.)

## Why
Without (2) the tools raise "brain main loop unavailable" in production; without (3) exit
criterion #3 depends on the LLM choosing the tool unprompted. (1) keeps spec validation
consistent for the registry task.

## Impact
- No behavior change for any other tool; `bind_loop` is a no-op when unset (my fallbacks
  still apply). Fastpath lines are additive intents.
- Core Guard untouched (AGENT_RULES §8).
