# computer-use → pc-control: screen-context-ops
Status: DONE — superseded without owner action. pc-control's merged landing
(`body/win/act_window.py` `foreground_info{}`, `body/win/act_uia.py`
`uia{op:"tree"}`, PROTOCOL §7 enum amended 2026-10-06) shipped equivalent
operations under different shapes; the computer-use gateway now targets the
SHIPPED contract (`foreground_info` result `{'window': {title,...}|None}`;
`uia{op:"tree", element:{control_type:"window"}, args:{depth:1..3}}` rendered
to text Brain-side — see `brain/tools/computer_use/gateway.py` +
`tests/test_gateway.py`). Kept below for the original rationale.

## What
Two read-only body `act_req` operations my cloud-vision gate and computer-use loop depend on
(PROTOCOL §7 allow-list already permits `window{op}` and `uia{op, element, args}`):

1. **Foreground window info** — `act_req{action: "window", args: {"op": "foreground"}}`
   → `act_res{ok: true, result: {"title": str, "process": str | null}}`
   - `title` must be the OS window title of the foreground window (empty string when there is
     no foreground window / desktop). `process` optional (exe name) — my blocklist matches on
     `title` case-insensitively (config `privacy.blocklist_apps`), so a title is mandatory.
   - Unknown/missing result (op unsupported) must surface as `ok:false` with an error string —
     my gate fails CLOSED when the title can't be verified.

2. **Foreground element tree as text** —
   `act_req{action: "uia", args: {"op": "tree", "target": {"scope": "foreground"},
   "args": {"max_depth": 12, "max_chars": 4000}}}`
   → `act_res{ok: true, result: {"text": str}}`
   - Plain-text UIA dump of the foreground window's element tree (indentation + role/name/
     automation-id per line), truncated to `max_chars`. Read-only: send with `lock: false`
     (never moves mouse/keyboard). Missing/empty tree → `result: {"text": ""}` (my loop then
     falls back to gated vision).

## Why
- The foreground title is the PROTOCOL §7 blocklist gate that must run BEFORE any screenshot
  leaves the machine (`see_screen`, computer-use observe step). Without it I must refuse
  screen reads entirely (fail closed).
- The UIA tree is the UIA-FIRST observe step of the `computer_use` loop (vision only when UIA
  is insufficient) — saves cloud vision calls and is the Wave 2 loop design.

## Impact
- No shared-contract change: both ops are inside the existing §7 enum.
- `window{op: "foreground"}` and `uia{op: "tree"}` are additive op values; today's
  `perform_uia` raises NotImplementedError for unknown ops (read-only fallback unchanged).
- My side is already coded against exactly these shapes (mocked in my tests) — see
  `brain/tools/computer_use/gateway.py`.
