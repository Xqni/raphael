# brain/voice — Raphael voice stack (voice-dev handoff)

STT: faster-whisper `small` (config `voice.stt_model`), device `auto`
(cuda→float16, cpu→int8), silero VAD filter for clean segment boundaries.
TTS: Fish-Speech v1.5.0 (`fishaudio/fish-speech-1.5` checkpoint, 1.4 GB,
Apache code @ tag v1.5.0 cloned to `brain/voice/vendor/fish-speech`) served
from an ISOLATED venv `brain/voice/.venv-fish` (fish-speech pins
numpy≤1.26.4 / pydantic==2.9.2 / torch≤2.4.1 — installing it into
`brain/.venv` would downgrade the live brain stack; the two venvs coexist).
Wake word `raphael`, PTT gating, barge-in interrupts: logic in `wake.py`
(pure, tested); live mic-lane wiring is phase 2 (ws.py audio handlers).

## Install / model artifacts (already done — 2026-10-05)

| Step | Command | Result |
|---|---|---|
| STT deps | `uv pip install --python brain/.venv/bin/python faster-whisper soundfile` | faster-whisper 1.2.1, ctranslate2 4.8.2, av 19.0.1, soundfile 0.14.0 |
| STT weights | `brain/.venv/bin/hf download Systran/faster-whisper-small` | 464 MB in `~/.cache/huggingface/hub/models--Systran--faster-whisper-small` |
| Fish code | `git clone --depth 1 --branch v1.5.0 https://github.com/fishaudio/fish-speech brain/voice/vendor/fish-speech` | tag v1.5.0 |
| Fish weights | `brain/.venv/bin/hf download fishaudio/fish-speech-1.5 --local-dir brain/voice/models/fish-speech-1.5` | 1.4 GB (model.pth 1.28 GB + firefly-gan VQGAN 188 MB) |
| Fish venv | `brain/voice/scripts/build_fish_venv.sh` | torch 2.4.1+cu121 (cuda OK), 151 pkgs; pyaudio excluded (only api_client imports it; needs portaudio headers) |

## Wiring loop.py (exact imports + signatures)

```python
from brain.voice import (get_voice, transcribe, speak, speak_frame,
                         speak_payload, encode_binary_frame,
                         stt_final_frame, error_frame, VoiceSTTError,
                         TTSError, WakeGate)

voice = get_voice()          # cfg-wired singleton (config.yaml → voice:)
await voice.warmup()         # resume hook: pre-starts fish server (non-fatal)
```

### 1) Mic lane → STT (ws.py `_on_audio_start` / binary kind=1 / `_on_audio_end`)

```python
# audio_start{reason: ptt|wake} -> voice.ptt.open(sid, reason)  (buffers follow)
# binary kind=1 payload (PCM s16le 16k mono, ≤50ms frames)  -> append to buf
# audio_end ->:
try:
    res = await asyncio.to_thread(voice.transcribe_result, buf)   # VAD inside
    hub.broadcast(stt_final_frame(res.text, res.lang, res.rtf), roles={'body','ui'})
    match = voice.wake.gate(res.text, reason=reason)   # reason from audio_start
    if match.kind != 'none':
        # match.command = transcript with wake word stripped ('wake' kind)
        engine.submit(text=match.command, priority='user_facing', source='voice')
except VoiceSTTError as e:
    hub.broadcast(error_frame(e.code, e.detail), roles={'body','ui'})
```

- `transcribe(pcm_bytes) -> str` — blocking; ALWAYS `asyncio.to_thread`
  (ARCHITECTURE §4: no blocking calls on the loop).
- Silence/empty PCM returns `''` gracefully (no exception).
- Model unavailable → `VoiceSTTError(code, detail)` with PROTOCOL §10 codes
  (`E_OFFLINE` weights missing + no network, `E_INTERNAL` otherwise) —
  broadcast `error_frame(...)`, never crash.

### 2) Barge-in (interrupt) — BEFORE submitting the new command

```python
if voice.interrupts.any_active():
    voice.interrupts.interrupt()          # cancels ALL in-flight speak streams
```
The `speak()` iterator checks its cancel event between chunks and ends with
`{"event":"end","interrupted":true}` — stale chunks are dropped; control
returns to the listener immediately (PROTOCOL §5: user voice interrupts,
job announcements queue behind speech).

### 3) Narration → speak frames (replaces `hub.narrate` for spoken text)

```python
cancel = voice.interrupts.register(job_id)     # barge-in target key = job id
try:
    async for ev in voice.speak(text, job=job_id, cancel=cancel):
        hub.broadcast(speak_frame(ev), roles={'body'})        # JSON speak frame
        if ev['event'] == 'chunk':
            hub.send_binary(encode_binary_frame(2, ev['seq'],
                                                speak_payload(ev)))  # §6 kind=2
        if ev.get('notice'):                                  # degraded TTS
            hub.broadcast({'type':'subtitle','v':1,'job':job_id,
                           'text': ev['notice'], 'fade_ms':6000}, roles={'ui'})
finally:
    voice.interrupts.done(job_id)
```

### Frames this module emits (all `{"type":"speak","v":1}`)

| event | extra fields |
|---|---|
| `start` | `sample_rate:24000`, `text`, `cached:bool`, `engine:"fish\|cache\|fallback"` |
| `chunk` | `sample_rate`, `amplitude:0-1` (required §8), `pitch_hz:float?` (rough ZCR estimate; absent when unvoiced/silent), `cached`, `engine`, `payload` (raw s16le — stripped by `speak_frame()`) |
| `end` | `cached`, `engine`, `interrupted?:true` (barge-in), `notice?:str` (degraded mode — ALSO subtitle it) |

Binary wrapper (PROTOCOL §6): `encode_binary_frame(kind=2, seq, payload)` =
`b'RAPH' + u8 kind + u32 seq + payload`, **u32 big-endian** — PROTOCOL does
not specify endianness; body-dev must use the same (flagged to orchestrator).

Also emitted on the STT path: `stt_final_frame(text, lang, rtf)` and
`error_frame(code, detail)` (shapes per PROTOCOL §3).

### Phrase cache

- Dir: `assets/acks/` (config `voice.ack_cache`; voice-dev owns `assets/`).
- Key = `normalize_text(text)`: NFKC + lowercase + punctuation stripped +
  whitespace collapsed (`wake.normalize_text`).
- Lookup order: `assets/acks/<normalized>.wav` (user-droppable canned acks)
  → `assets/acks/<sha1(key)[:16]>.wav` (auto-stored after first synthesis).
- Cache hits stream instantly (`cached:true`, engine `cache`).

### Reference voice

`config voice.tts_voice = assets/raphael_reference.wav` — **asset does not
exist yet** (user-provided; addendum §10). While missing, Fish-Speech picks
its own timbre and the first degraded notice tells the user. When the file
(+ optional `assets/raphael_reference.txt` transcript) appears, the adapter
sends it automatically as an in-context reference (base64 JSON per fish
`ServeReferenceAudio`) — no code change needed. Restart the fish server
(`voice.tts.shutdown()` then warmup) to pick it up.

### Fallback (degraded) path — honest behavior

If the fish server cannot start/synthesize (venv missing, checkpoint gone,
OOM):
1. cached wav for the phrase if present → played normally;
2. else a short 440 Hz placeholder tone (clearly labeled `engine:"fallback"`)
   + `notice` on every frame → loop.py MUST subtitle the notice + the reply
   text. This is NOT presented as Raphael's voice.

Exact blockers if fallback is active at runtime: see OPEN ISSUES in
`.opencode/research/wave2-voice-phase1.md` (reference wav missing; VRAM
sharing with Ollama is a brain-dev scheduling concern — addendum §73).

## Running the fish server manually

```bash
brain/voice/.venv-fish/bin/python -m tools.api_server \
  --listen 127.0.0.1:8777 \
  --llama-checkpoint-path brain/voice/models/fish-speech-1.5 \
  --decoder-checkpoint-path brain/voice/models/fish-speech-1.5/firefly-gan-vq-fsq-8x1024-21hz-generator.pth \
  --decoder-config-name firefly_gan_vq --device cuda --half
# cwd = brain/voice/vendor/fish-speech  (the adapter does this for you)
```
Logs: `brain/voice/logs/fish_server.log`. `POST /v1/health` → `{"status":"ok"}`.
The adapter spawns it on demand (`warmup()`), waits ≤240 s for model load.

## Tests

- `brain/voice/tests/test_voice.py` — unit + integration (pytest, runs in
  `brain/.venv`; fish-dependent tests self-skip when the server is down).
- `brain/voice/smoke_test.py` — end-to-end: silence/sine PCM → STT graceful
  empty; TTS speak-frame dicts (real fish synthesis when server up); real
  TTS→STT round-trip; binary frame encode check.

```bash
brain/.venv/bin/python -m pytest brain/voice/tests -q
brain/.venv/bin/python brain/voice/smoke_test.py
```

## Phase-2 TODOs (explicit, not hidden)

1. **Live mic wiring** — ws.py `_on_audio_start/_on_audio_end` + binary kind=1
   buffering → `transcribe_result` (logic exists; needs brain-dev's hub
   access; PTT hotkey body-side is "voice phase 3" per PROGRESS.md).
2. **Real amplitude from playback** — current amplitude = RMS of synthesized
   chunk (real audio, honest); orb-side sync (amplitude → actual speaker
   output level) needs the Body playback ack loop.
3. **pitch_hz quality** — ZCR estimate is rough; replace with crepe/torchcrepe
   when VRAM budget allows (optional field; orb degrades gracefully).
4. **Endianness alignment** with body-dev for §6 u32 seq (I used big-endian).
5. **assets/raphael_reference.wav** — user must provide; adapter auto-wires.
