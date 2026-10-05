# Wave 2 Phase 3 - Windows Body: Mic Lane + Act Pipeline
# Verification Report

## 1. Compilation
- Ran `python3 -m py_compile` on all modified files: SUCCESS.

## 2. Implementation Details
- **Mic Capture (`audio_in.py`)**: Implemented using `sounddevice`. 
  - Sample rate: 16000 Hz, Mono, Float32 -> PCM s16le.
  - Binary frame format: `b'RAPH' + u8 kind=1 + u32 seq (Big Endian) + payload`.
  - PTT Gating: integrated with `keyboard` on_press/on_release.
- **Act Pipeline (`ws_client.py`)**:
  - Added `handle_message` logic for `act_req`.
  - Implemented routing for `launch_url`, `open_app`, `screenshot`, `uia`, `clipboard`.
  - Lock Etiquette: uses `automation.acquire_input_lock` with `E_LOCK_BUSY` response if unavailable.
- **Audio Output (`audio_out.py`)**:
  - Minimal `sounddevice` playback for `kind=2` (24kHz mono).

## 3. Frame Specifications (Emitted)
- **audio_start**: `{"type": "audio_start", "v": 1, "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le", "reason": "ptt"}`
- **audio_frame**: `[b'RAPH'][1][u32 seq BE][PCM s16le]`
- **audio_end**: `{"type": "audio_end", "v": 1}`
- **act_res**: `{"type": "act_res", "v": 1, "job": "...", "ok": bool, "result": "...", "error": "..."}`

## 4. Open Issues
- PTT Hotkey simplification: current implementation assumes `ptt_hotkey` is a single key name (e.g., 'space'). Complex chords (ctrl+alt+space) require `keyboard.add_hotkey` with a custom trigger or a listener for the specific chord.
