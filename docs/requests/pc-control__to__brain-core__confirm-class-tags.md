# pc-control → brain-core: confirm-class-tags (Wave 5U P0.2)
Status: OPEN

## What
Every pc tool spec now carries an explicit confirm class
(`brain/tools/pc/_spec.py`, Wave 5U §5.2 task 1 — done). This is the tag
vocabulary + per-tool table for your P0.2 policy map ("tool calls with no
policy class fail closed to confirm; tools carry an explicit class via
registry `confirm=` metadata").

**Classes (`_spec.py::CONFIRM_CLASSES`):**
| class | meaning |
|---|---|
| `auto` | never confirms — read-only / reversible / launch-class |
| `open_arbitrary_file` | handler-opens an arbitrary exe/document (exists) |
| `system_settings_change` | fixed-registry script run (exists) |
| `gui_input` | **NEW** — keystrokes/form input. Confirms ONLY when the focused element is a password field or a submit control on a non-allowlisted site → escalates to `gui_submission` |
| `gui_submission` | high-impact GUI submission (escalation target; AUD-11 id, requested in config) |

**Per-tool tags (20 tools):**
- `auto`: launch_url, navigate_url, search_youtube, open_app,
  list_running_apps, volume, brightness, media, window, list_windows,
  foreground_info, screenshot, notify, clipboard, report, activity
  (charter list + extrapolations: navigate_url = launch-class;
  notify/report/activity = auto; **clipboard flagged for your review** —
  paste can carry content into a focused field; proposing auto until the
  gui_input condition evaluator exists)
- `open_arbitrary_file`: open_path (risky=True)
- `system_settings_change`: powershell (risky=True)
- `gui_input`: input
- **conditional**: uia = `{default: auto, when: [{args:{op:{in:[click,type]}},
  class: gui_input}]}` — read/find/tree auto, click/type gui_input

**Escalation semantics (gui_input)**: default-approve; escalate to
`gui_submission` when (a) the focused element of the target window is a
password field — Body already exposes this:
`foreground_info.focused_is_password` (pywinauto IUIA CurrentIsPassword) and
uia descriptors' true-only `is_password`; or (b) a submit control on a
non-allowlisted site — (b) needs the Wave-B CDP worker (§5.2 P1); until it
ships, (a) is evaluable today and (b) can fall back to fail-closed confirm.

**Conditional tag shape** (what your loader must read from
`ToolSpec.confirm`):
```jsonc
{"default": "auto",
 "when": [{"args": {"op": {"in": ["click", "type"]}}, "class": "gui_input"}]}
```
(Loudly validated at import: unknown classes, ops outside the tool's enum,
non-op conditions, risky+auto combos all raise `SpecError`.)

**Interim (unchanged behavior)**: registry `risky` stays exactly as today
(open_path/powershell/uia True; input False) so no gate regresses while your
map lands. Once the class evaluator is live: `risky` gating should become
`class != auto` (uia's read ops stop over-confirming; input escalates on the
password condition). I can pass `confirm=` into `register()` the day your
registry grows that parameter.

## Why
Wave 5U charter P0.2 (docs/USEFUL-NOW-PLAN.md:40) — brain-core owns the
policy map, pc-control owns the class tags. Wave A timebox (~2h) done on my
side: tags + validation + charter-table tests, zero behavior change.

## Impact
- Specs-only on my side (+ this contract); registry/loop changes are yours.
- `docs/requests/pc-control__to__integrator__config-confirm-categories-aud11.md`
  (ids `open_arbitrary_file`/`gui_submission` in safety.confirm_actions)
  remains the config-side companion; `gui_input` is a CLASS for your map,
  not a config id — add one only if your policy wants it high-risk-listed.
