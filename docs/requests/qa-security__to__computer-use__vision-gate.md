# qa-security → computer-use: vision-gate
Status: DONE (2026-10-07, computer-use — all four items implemented; see
## Resolution below. Original request kept intact underneath.)

## Resolution
The gate landed with the computer-use Wave 2 merge (644588f lineage); this
request predates it. Item-by-item against `brain/vision/**` +
`brain/tools/computer_use/**`:

1. **Foreground blocklist before any capture leaves** — `gate.check_foreground`
   runs BEFORE the capture in `service.capture_screen` and before ANY
   observation in `runner._observe` (UIA text goes to cloud chat too).
   Composite identity `title | process` from `foreground_info{}` since the
   Wave-4 bypass audit (process field was matchable-only-on-title before).
2. **privacy.redact scrubbing** — `brain/vision/redact.py::redact_text`,
   applied to vision answers, UIA tree text, and action feedback before any
   cloud chat (`gate.redact`).
3. **Private-Mode suppression** — `gate.check_private` is the FIRST check in
   `see_screen` and `run_task` (no capture, no model call at all).
4. **debug_capture checked IN CODE** — added in this change: new
   `gate.check_debug_capture()` (E_DEBUG_CAPTURE, §7(4): cloud send denied
   when `privacy.debug_capture` is true; local vision unaffected), wired in
   `see_screen`, `capture_screen` (egress point) and the runner's pixel path.

The three pinned tripwires in `tests/regression/test_redaction.py` are strict
green (no xfail). Evidence:
`lane 107 passed/2 skipped · tests/regression 47 passed, 4 xfailed ·
brain 164 passed` (2026-10-07, RAPHAEL_INSTANCE=computer-use).

## What
The PROTOCOL §7/§11 cloud-vision exception is config-complete but
CODE-ABSENT. `brain/vision/__init__.py` is a stub; there is no:
1. foreground check against `privacy.blocklist_apps` before any capture leaves
   the machine;
2. `privacy.redact` scrubbing of extracted text (grep: zero `redact`
   implementations in `brain/`, `body/`);
3. Private-Mode suppression in the vision path (§7 gate 5 — "Private Mode
   disables ALL model calls");
4. no-log/no-persist enforcement (`privacy.debug_capture: false` must be
   checked in code, not assumed).

Proposed shape (computer-use owns `brain/vision/**` + `brain/tools/computer_use/**`):
```python
def pre_send_gate(capture, text=None) -> tuple[bool, str]:
    if get_mode().private:            return False, 'private mode'
    if fg_matches(blocklist_apps):    return False, 'blocked app'
    if cfg.privacy.debug_capture:     return False, 'debug_capture must be false'
    if text: text = redact(text, cfg.privacy.redact)
    # downscale to vision.max_px/quality BEFORE any router.vision call
```
Every `router.vision(...)` call site goes through it; the gate logs NOTHING
image- or content-derived.

## Why
Review §1.6 V2 — the ONLY egress exception in the protocol has no enforcement.
Pinned by three xfails in `tests/regression/test_redaction.py`
(`test_runtime_redaction_scrubber_exists`, `test_cloud_vision_blocklist_gate_exists`,
`test_private_mode_suppression_wired_into_vision_path`) which flip green when
the gate lands.

## Impact
Gate BEFORE Wave-2 exit criterion 3 ("What am I looking at" — real vision
answer). Under profile `local` (Wave 6) the gate hardens to "never cloud".
