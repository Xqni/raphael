# qa-security → router: fix-config-loader
Status: OPEN

## What
`brain/router/config.py::_simple_yaml_load` mis-parses the repo `config.yaml`:
indentation popping collapses everything to top level, and the `profiles.local`
inline map (`providers: { chain: [...] }`) **overwrites** `cfg["providers"]`
with a string. `load_config()` then raises
`AttributeError: 'str' object has no attribute 'get'` (repro:
`python -c "from brain.router.config import load_config; load_config()"`).
Pinned by `tests/contract/test_config_loader.py::test_load_config_parses_repo_config_yaml`
(xfail today). Proposed fix: parse with PyYAML (already a dependency of
brain/voice) instead of the hand-rolled parser, and treat `profiles:` as
overlay data — or delegate to the shared brain-core §c loader once it exists.

## Why
Every real `get_router()` / `llm.plan()` call on the live stack degrades to
`E_INTERNAL` — cloud chat is broken on main, not just in tests. qa-security's
`router_to_mock` fixture had to bypass `load_config()` to test anything.

## Impact
Blocks Wave-2 exit criterion 2 ("free-form question gets a real cloud answer").
No API/shape change for callers — internal loader fix. The naive parser also
silently loses nested keys (privacy/voice sections flatten), so any future
consumer of this loader inherits the corruption.
