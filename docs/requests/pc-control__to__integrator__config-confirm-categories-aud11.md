# pc-control → integrator: config-confirm-categories-aud11
Status: OPEN

## What
Add two confirm ids to `config.yaml → safety.confirm_actions` (Core Guard
authority key — lanes may NOT touch `safety.*` in config.d, `brain/config.py:129
AUTHORITY_KEYS`, so this needs the integrator):

```yaml
safety:
  confirm_actions:
    # …existing 8…
    - open_arbitrary_file   # AUD-11: open_path — arbitrary exe/document/handler-open
    - gui_submission        # AUD-11: uia click/type — high-impact GUI submissions
```

Companion (brain-core): extend `brain/confirm.py::TOOL_ACTION` with
`'open_path': 'open_arbitrary_file'`, `'uia': 'gui_submission'` so
`tool_decision()` classifies these as HIGH risk with the normalized id
(today it falls back to the raw tool name, which is not in the config list
→ risk labeled 'low').

## Why
- AUD-11 (register PART 2): open_path/uia are now registered `risky=True`
  — the dispatch-time gate in `brain/loop.py:521-523`
  (`if not decision.needs and meta.get('risky'): decision =
  confirm_mod.tool_decision(...)`) ALREADY fires the confirmation without
  the config change; what's missing is the HIGH-risk classification and the
  canonical action ids (confirm.py maps reason→id against this list).
- `safety` is an authority key: config.d fragments are stripped
  (brain/config.py:129-131), and AGENT_RULES §8 wants integrator sign-off
  for Core Guard list changes anyway.

## Impact
- Additive list extension (strengthening, never weakening §8); question
  text unchanged (`About to run tool \`open_path\`: … Confirm?`).
- Until approved the gate still fires (risky metadata); only the risk
  label/id mapping await this change.
