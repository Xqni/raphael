# pc-control → brain-core: aud11-open-path-mappings
Status: OPEN

## What
Two small brain-core-side mappings that complete AUD-11 (companion to
`pc-control__to__integrator__config-confirm-categories-aud11.md`):

1. `brain/confirm.py::TOOL_ACTION` additions:
```python
'open_path': 'open_arbitrary_file',
'uia': 'gui_submission',
```
Without them `tool_decision()` defaults the action id to the raw tool name,
which is not in `config.safety.confirm_actions` → the confirm still FIRES
(`needs=True`, registry `risky` drives it) but risk is labeled 'low'.

2. `brain/fastpath.py` `_open()`: a path-like argument (contains a path
separator or an existing-file shape) must route to **open_path**, not
open_app. pc-control's `open_app` now refuses literal paths at the trusted
boundary (AUD-11: "separate trusted app launch from arbitrary exe/document/
handler-open"), so today's `"open C:\notes\a.pdf"` fastpath intent lands on
open_app and fails with a steering error instead of opening the file.
Suggested: `if os.path.sep in arg or arg.startswith('~') → tool='open_path',
tool_args={'path': arg}` before the current URL/name split.

## Why
- AUD-11 boundary only becomes end-to-end usable for the fastpath with (2);
  the model path already steers correctly via tool descriptions.
- Both are brain-core-owned files (pc-control never edits them).

## Impact
- Additive mappings; `open_path` is `risky=True` so every fastpath file
  open now passes the dispatch-time confirmation gate (AUD-11 intent —
  folders included; noted tradeoff, fail-closed).
