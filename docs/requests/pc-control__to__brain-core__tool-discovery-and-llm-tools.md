# pc-control → brain-core: tool-discovery-and-llm-tools
Status: OPEN

## What
Four brain-core changes (all in brain-core-owned files) that INTERFACES §b
already promises / that Wave 2 tool-calling needs:

1. **Auto-discovery of `brain.tools.*` subpackages** (INTERFACES §b: "brain-
   core's loader auto-discovers every `brain.tools.*` subpackage at import
   (pkgutil walk) — new tools appear without touching shared files"). Today
   `brain/app.py` only does `from . import tools`, so `brain/tools/pc/`
   (17 pc tools) never registers on a live Brain. Additive sketch:

   ```python
   # brain/tools/__init__.py (or app.py lifespan) — brain-core-owned
   import pkgutil, importlib
   for _m in pkgutil.iter_modules(__path__):
       if _m.name not in ('tests',):
           importlib.import_module(f'{__name__}.{_m.name}')
   ```

2. **Feed tool specs to the model.** `brain/llm.plan()` currently sends only
   the user text (`router.complete(prompt=…)`), so `loop._extract_tool_call`
   can never fire — the model never sees any tool. Add an optional tools
   argument, e.g. build it once from the registry:

   ```python
   # preferred: native tool-calling where the provider supports it
   from brain.tools.pc import openai_tools      # OpenAI function-tool list
   router.chat(messages, tools=openai_tools(), purpose='tool')
   # fallback (providers without tools): append pc.prompt_block() to the prompt
   # (format matches {"tool": name, "args": {...}} that _extract_tool_call parses)
   ```

   `brain/tools/pc/__init__.py` exports `openai_tools()` and `prompt_block()`;
   both are validated at import.

3. **Enforce tool metadata at dispatch.** `loop.py` gates on `needs_lock`
   but never consults `risky` / confirm metadata: `confirm_mod.classify(text)`
   is called WITHOUT the tool name, so `RISKY_TOOLS` (which lists
   `powershell`) never matches. After fastpath/plan resolves `tool_name`,
   call `confirm_mod.classify(text, tool=tool_name)` (the parameter already
   exists), or check `tool_reg.describe(tool_name)['risky']` before section 4.

4. **Strict spec validation at load** (INTERFACES §b: "The registry rejects
   non-conforming specs at load time (loudly, in tests)"). `register()`
   currently accepts anything. Minimum: reject entries where `category=='gui'`
   but the name is not a string, `description` is empty, or (for specs with
   schemas) `parameters.additionalProperties is not False`. `brain/tools/pc`
   self-validates already (raises `SpecError` at import) — the registry-level
   check is defense in depth for the other namespaces.

## Why
- Wave 2 exit criterion 1 ("Open YouTube and search lo-fi" by voice AND text)
  beyond the fastpath requires the LLM to call `search_youtube` — impossible
  while tools are invisible to the model.
- `docs/lanes/pc-control.md` task 1 ("brain/tools/pc namespace + self-
  registered tools per INTERFACES §b") is only half-effective without (1).
- (3) is a Core Guard conformance item (AGENT_RULES §8: risky tools must be
  confirm-gated in code, never by model judgment).

## Impact
- All edits are brain-core-owned (`brain/tools/__init__.py`, `brain/app.py`,
  `brain/loop.py`, `brain/llm.py`); pc-control touches none of them.
- (1)+(2) are additive; existing built-ins (`shell`, the 5 gui stubs) keep
  their semantics — `brain/tools/pc` re-registers the same 5 gui names with
  identical `category`/`needs_lock` (parity asserted in
  `brain/tools/pc/tests/test_pc_tool_specs.py`).
- (3) adds confirm prompts for risky TOOLS on top of today's text-pattern
  prompts (stricter, never weaker — Core Guard direction is one-way).
