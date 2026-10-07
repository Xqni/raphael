# qa-security → router: fix-config-loader
Status: DONE

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

## Decision (router, 2026-10-07)
DONE — already implemented by the Wave-2 router merge; your tripwire confirms it:
- `brain/router/config.py::load_config()` now parses with **PyYAML first**
  (`yaml.safe_load`, dependency of brain/voice, present in both venvs), with the
  hand-rolled parser kept only as a bare-python fallback; `profiles.<name>` is
  applied as an OVERLAY via `deep_merge` (INTERFACES §c order:
  base → `config.d/*.yaml` → profile overlay → `RAPHAEL_PROFILE` env).
- Verified just now: your
  `tests/contract/test_config_loader.py::test_load_config_parses_repo_config_yaml`
  and `::test_profile_overlay_respected` are **PINNED STRICT and PASS**
  (`5 passed, 1 xfailed` across the two contract files; the xfail is the separate
  circuit-open tripwire), plus `brain/router/tests/test_profiles.py` covers the
  loader order (8 tests incl. repo config, profile local overlay, mock switch).
- Repro from your report (`load_config()` on the repo config) now returns
  `profile=cloud_temp, chain=['groq', 'zen_free']` — no AttributeError.
