# computer-use → pc-control: focused-password-flag
Status: OPEN

## What
Additive Body fields so the Wave-5H audit item 2 ("focused password fields,
UIA IsPassword") can be DETECTED at capture time. Two small shapes:

1. **`foreground_info{}` result** — add a boolean alongside the window entry:
   ```json
   {"window": {...}, "focused_is_password": true|false}
   ```
   (`_run_foreground_info` / winlayer: whether the focused element of the
   foreground window reports UIA IsPassword=true; False when unknown.)
2. **`uia{op:"tree"}` nodes** — add optional booleans per node in `_describe`
   (or only when true): `is_password` and `focused`:
   ```json
   {"name": "...", "control_type": "Edit", "is_password": true, "focused": true, ...}
   ```
   Absent = False (my parser treats missing keys as clean — backward
   compatible in BOTH directions).

## Why
My gate refuses capture when a password field has focus (short spoken reason:
"A password field is focused — I won't capture the screen.") — but today the
Body exposes neither IsPassword nor focus (`winlayer._describe` returns
name/control_type/automation_id/class_name/rect only; `_describe_window`
returns hwnd/title/pid/process/rect/visible). My consumption code is ALREADY
landed and tested against both result shapes (`brain/tools/computer_use/
gateway.py::password_focus`, tests in `brain/vision/tests/
test_sensitive_contexts.py`) — it simply stays False until these fields exist.
Without them the only working detection layer is title/process patterns.

## Impact
- Additive result keys only — no new action, no frame change (both shapes are
  already inside the PROTOCOL §7 `foreground_info{}`/`uia{}` contracts).
- `password focus` currently has NO fallback on the pixel path when UIA can't
  see the focus state; this closes that hole at the source.
