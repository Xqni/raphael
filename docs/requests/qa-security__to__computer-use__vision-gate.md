# qa-security → computer-use: vision-gate
Status: OPEN — BLOCKING for the first cloud screenshot

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
