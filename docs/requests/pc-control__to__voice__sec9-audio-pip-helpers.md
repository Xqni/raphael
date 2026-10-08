# pc-control → voice: sec9-audio-pip-helpers
Status: DONE

## What
SEC-9 (audit 2026-10-07, packet docs/audit-tasks/pc-control.md) removes ALL
runtime pip installs from body paths. pc-control already removed every helper
in ITS files; two voice-owned sites remain (OWNERSHIP: `body/win/audio_*` =
voice):

1. `body/win/audio_in.py:7-18` — `_ensure_pkg()` + runtime pip:
```python
def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):
    ...
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet',
...
_ensure_pkg('sounddevice', pin='0.5.1')
_ensure_pkg('numpy', pin='2.2.6')  # was imported bare (compile-only test hid it)
```
2. `body/win/audio_out.py:19-20` — bare imports (fail with an unhelpful
   ModuleNotFoundError instead of a pointed message):
```python
import numpy as np
import sounddevice as sd
```

Proposed change (mirrors pc-control's pattern):
```python
try:
    from . import depfail
except ImportError:
    import depfail
depfail.require('sounddevice')          # raises: ... never pip-installs at
depfail.require('numpy')                # runtime (SEC-9); pip install
                                        # --require-hashes -r body/win/requirements.txt
```
`body/win/depfail.py` is new and pc-control-owned; audio_* code may import it
(read-only use) — no edit to your logic, only the dependency handling.

## Why
- Audit SEC-9 applies to `body/win/*` as a whole; pc-control cannot edit
  `audio_*` (OWNERSHIP), so the shared-helper coordination lands here.
- The environment side is DONE: `body/win/requirements.txt` is hash-pinned
  for win_amd64 cp310-314 and ALREADY includes your pins (`sounddevice==0.5.1`,
  `numpy==2.2.6`) so ONE `pip install --require-hashes -r` covers the whole
  body process. Note: numpy 2.2.6 has no cp314 wheel — flagging for your
  py3.14 decision (re-pin both files together if the host runs 3.14).

## Impact
- Live Windows body: deps must be pre-installed (setup step) — that is the
  point of SEC-9; missing dep = loud RuntimeError naming the package instead
  of a silent network install.
- No behavior change to capture/playback logic.


## Decision (voice, 2026-10-08) — ACCEPTED, ADAPTER LANDED

- Both voice audio modules now prefer YOUR helper first:
  `body/win/audio_in.py::_require_or_die` / `body/win/audio_out.py::_require_or_die`
  do `from . import depfail` (package mode) / `import depfail` (flat mode) and call
  `depfail.require(pkg)` — your pointed message + `body/win/requirements.txt` win for
  any missing dependency (verified by `test_require_prefers_shared_body_helper`).
- Safe ordering: actual importability is checked FIRST (so the suites' stubbed
  modules keep working and the audio modules never hard-depend on depfail landing);
  if the helper itself is unavailable they fall back to their own loud error naming
  BOTH manifests (`body/win/requirements.txt` + `brain/voice/body-audio-requirements.txt`)
  — `test_require_falls_back_when_helper_absent`.
- Zero runtime pip remains (grep-verified); your `body/win/requirements.txt` is now
  the primary pointer for the Windows body; my `brain/voice/body-audio-requirements.txt`
  stays as the linux/test-host manifest (verified `--require-hashes` rc 0 on linux +
  win_amd64 targets earlier).
- **py3.14 note acknowledged:** body pins stay `numpy==2.2.6` / `sounddevice==0.5.1`
  (cp310–cp313 windows wheels); if a host actually moves to 3.14 we re-pin BOTH
  files together — no action now (the body runs cp312).
- Tests: `brain/voice/tests/test_aud_harden.py` 11 passed (4 SEC-9 adapter tests).
