# pc-control → voice: sec9-audio-pip-helpers
Status: OPEN

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
