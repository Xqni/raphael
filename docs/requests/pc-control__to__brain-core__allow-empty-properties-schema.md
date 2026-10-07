# pc-control → brain-core: allow-empty-properties-schema
Status: DONE

## Decision
APPROVED — empty `properties` is valid JSON Schema for no-arg tools and unblocks
`foreground_info` in the Wave-2 privacy flow. This is spec-shape validation, NOT
Core Guard security semantics (`additionalProperties: false` remains enforced), so
AGENT_RULES §8 is untouched. brain-core implements `validate_schema` relaxation on
their branch; pc-control flips the three zero-arg tools to `schema=s.schema()`
after it merges. Decision mirrored to both inboxes.

## Implemented (2026-10-07, pc-control)
brain-core's relaxation is merged (`validate_schema` now explicitly allows an
empty mapping); pc-control flipped ALL 17 tools — including `list_windows`,
`foreground_info`, `list_running_apps` — to `schema=s.schema()` in
`brain/tools/pc/__init__.py`, so `registry.tool_specs()` offers every pc tool
to the model. Parity test updated:
`test_registry_receives_schemas_so_tools_are_offered` asserts the strict
empty shape for the zero-arg three and presence in `tool_specs()`.

## What
Relax `brain/tools/__init__.py::validate_schema` to ACCEPT an empty
`properties` mapping for no-argument tools (today it raises
`BadToolSpec: schema.properties must be a non-empty mapping`):

```python
props = schema.get('properties')
if not isinstance(props, dict):          # <- drop `or not props`
    raise BadToolSpec(...)
```

`required: []` + `additionalProperties: false` with empty `properties` is
valid JSON Schema and is how no-param functions are described (OpenAI/
Groq-compatible: `{"type":"object","properties":{},"required":[],
"additionalProperties":false}`).

## Why
- Three pc tools take NO arguments and are currently not offered to the
  model: `list_windows`, `foreground_info`, `list_running_apps`
  (`registry.tool_specs()` skips schema-less tools). `foreground_info` in
  particular is part of the Wave-2 privacy flow (blocklist check before a
  screenshot leaves the machine) — the model should be able to call it
  directly instead of learning it only via `prompt_block()` fallback.
- Interim behavior is recorded + tested in
  `brain/tools/pc/tests/test_pc_tool_specs.py::
  test_registry_receives_schemas_so_tools_are_offered`; once this lands I
  flip those three to `schema=s.schema()` (one-line change on my branch).

## Impact
- brain-core-owned file; loosening a validation strictness (never tightening
  Core Guard — this is spec shape, not security semantics). Existing tools
  with non-empty properties are unaffected; no consumer can pass a bogus
  schema through it (`additionalProperties: false` still enforced).
