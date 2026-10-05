# PROGRESS – Wave 2 (Windows Body) Phase 1

Implemented core Body modules:
- `main.py` – single‑instance lock, launches async client.
- `ws_client.py` – WS handshake, ping/pong, auto‑reconnect, token handling.
- `capture.py` – screenshot (mss + Pillow), downscale, JPEG output.
- `automation.py` – UI automation helpers using pywinauto, async input‑lock.
- `apps.py` – launch URLs/files/executables.
- `clipboard.py` – get/set clipboard via pywin32.
- `system.py` – set volume (Core Audio) and brightness (PowerShell).
- `hotkeys.py` – register hotkeys from `config.yaml`, queue control actions.
- `audio_in.py` / `audio_out.py` – stubs with logging.

All required third‑party packages are lazily installed on first import.
Manual verification commands ran successfully (see below).

## Verification Commands & Output (truncated)
```
$ python -m body.win.main
Another Raphael body instance is already running – exiting.
```
(first run creates lock, second run exits cleanly)
```
$ python -m body.win.capture
Wrote screenshot_test.jpg 32241 bytes
```
```
$ python -c "import body.win.automation as a; print('automation loaded')"
automation loaded
```
```
$ python - <<PY
from body.win import clipboard
clipboard.set_clipboard_text('hello')
print('got:', clipboard.get_clipboard_text())
PY
got: hello
```
All imports succeeded, no uncaught exceptions.

## Open issues / Next steps
- Wire hotkey control queue to `ws_client` for real `control` frames.
- Implement binary audio streaming for mic capture and TTS playback.
- Expand UIA action support (read element properties, window ops).
- Add graceful shutdown handling for reconnect loop.

*End of report.*
