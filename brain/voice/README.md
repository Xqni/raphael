# brain/voice — Raphael voice stack (voice-dev handoff)

STT (profile `cloud_temp`, current): utterances are segmented body-side by the
lightweight VAD (`body/win/audio_in.py`) and transcribed through
`router.transcribe()` → Groq Whisper (INTERFACES §a) — one segment = one
call, silence never leaves the machine, and profile cloud_temp FORCES the
cloud engine. Local faster-whisper `small` (config `voice.stt_model`, device
`auto`) stays in the repo but is reachable only with `profile local`
(`voice.stt_engine: local`).
TTS: Fish-Speech v1.5.0 (`fishaudio/fish-speech-1.5` checkpoint, 1.4 GB,
Apache code @ tag v1.5.0 cloned to `brain/voice/vendor/fish-speech`) served
from an ISOLATED venv `brain/voice/.venv-fish` (fish-speech pins
numpy≤1.26.4 / pydantic==2.9.2 / torch≤2.4.1 — installing it into
`brain/.venv` would downgrade the live brain stack; the two venvs coexist).
Wake word `raphael`, PTT gating, barge-in interrupts: `wake.py` (pure, tested)
+ `activation.py` (pre-STT cloud gate + playback-echo rejection); live mic
lane is wired in ws.py audio handlers. Fish port and voice log dir derive
from `RAPHAEL_INSTANCE` (INTERFACES §d — main keeps 8777 and
`brain/voice/logs/`).

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
    res = await asyncio.to_thread(voice.transcribe_result, buf,
                                  reason=reason)      # pre-STT gate + VAD-era
                                                      # silence short-circuit
    hub.broadcast(stt_final_frame(res.text, res.lang, res.rtf), roles={'body','ui'})
    match = voice.wake.gate(res.text, reason=reason)   # ActivationGate: wake
        # gate + playback-echo rejection (her own words -> kind='none')
    if match.kind != 'none':
        # match.command = transcript with wake word stripped ('wake' kind)
        engine.submit(text=match.command, priority='user_facing', source='voice')
except VoiceSTTError as e:
    hub.broadcast(error_frame(e.code, e.detail), roles={'body','ui'})
```

- `transcribe(pcm_bytes) -> str` — blocking; ALWAYS `asyncio.to_thread`
  (ARCHITECTURE §4: no blocking calls on the loop).
- Silence/empty PCM returns `''` gracefully (no exception) and never calls a
  provider. Passing `reason` lets the pre-gate drop wake segments when
  `voice.always_listen: false` (omitted = fail open; see
  `docs/requests/voice__to__integrator__audio-end-pass-reason.md`).
- Engine unavailable → `VoiceSTTError(code, detail)` with PROTOCOL §10 codes
  (`E_PROVIDER_429`/`E_OFFLINE`/`E_PROVIDER_AUTH`/`E_TIMEOUT`/`E_INTERNAL`) —
  broadcast `error_frame(...)`, never crash.
- Voice confirmations: `brain.voice.voice_confirmation_answer(text,
  low_risk=...)` → `'yes'|'no'|None` for LOW-risk confirmations only
  (high-risk always None — see `docs/requests/
  voice__to__brain-core__voice-confirm-wiring.md`).

### 2) Barge-in (interrupt) — BEFORE submitting the new command

```python
if voice.interrupts.any_active():
    voice.interrupts.interrupt()          # cancels ALL in-flight speak streams
```
The `speak()` iterator checks its cancel event between chunks and ends with
`{"event":"end","interrupted":true}` — stale chunks are dropped; control
returns to the listener immediately (PROTOCOL §5: user voice interrupts,
job announcements queue behind speech).

Self-trigger protection (while she speaks): `body/win/audio_in.py` raises the
VAD open threshold to speech level while `audio_out.PLAYER.active()` (her
measured bleed 40-225 can't open a segment, real speech 2000+ still can — so
wake-word barge-in keeps working), and `activation.PlaybackEchoRegistry`
drops any transcript that matches what she just said (her "Raphael online."
greeting can never become a job).

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

### Reference voice (USER DIRECTIVE 2026-10-07 — Bug D)

`config voice.tts_voice = assets/raphael_reference_jp.wav` — the great-sage
(JP slime) reference, **user-approved and PERMANENT** (Zira retired). Every
synthesis sends it as an in-context reference (base64 JSON per fish
`ServeReferenceAudio`) and logs the proof line:

```
[tts] ref sent: path=.../assets/raphael_reference_jp.wav bytes=751686 sha1=f64bd512ea1e sentence='Task ...'
```

- **`voice.tts_reference_required: true` (default):** a missing/empty
  reference FAILS LOUD — `TTSError` → subtitle notice ("Voice reference
  unavailable …") + `[tts] BLOCKED (reference)` log, ZERO audio. No silent
  default voice, ever. Only `VoiceConfig(tts_reference_required=False)`
  opts out (tests/tooling).
- **Cache namespacing:** the phrase cache lives in
  `assets/acks/<sha1(ref)[:12]>/` (e.g. `…/f64bd512ea1e/`), so a reference
  change can never replay another voice's wavs; `TTSEngine.refresh_reference()`
  re-namespaces automatically when the file changes. fish's own
  `use_memory_cache` is `"off"` (its key is text-only — Bug D suspect #3).
- **Live proof:** `brain/.venv/bin/python brain/voice/scripts/prove_reference.py`
  (never spawns fish; exit 3 when the server is unreachable).

### Fallback (degraded) path — honest behavior

If the fish server cannot start/synthesize (venv missing, checkpoint gone,
OOM):
1. cached wav for the phrase if present → played normally (`engine:"cache"`);
2. else **SUBTITLE-ONLY**: no audio chunks at all, plus a **ONE-TIME**
   `notice` on the `end` frame ("TTS engine unavailable — replies are shown
   as subtitles until Fish-Speech is back.") which loop.py MUST subtitle
   together with the reply text. Later degraded replies stay quiet — no
   repeated apology, no placeholder tone (`engine:"fallback"`).

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

- `brain/voice/tests/` — the whole lane suite (pytest, runs in `brain/.venv`):
  - `test_voice.py` — core units + fish-dependent integration tests
    (self-skip when the server is down; run with `-m "not integration"` for
    the pure mock run);
  - `test_instance.py` — RAPHAEL_INSTANCE port/path derivation;
  - `test_stt_cloud.py` — cloud STT seam (stubbed `router.transcribe`),
    PROTOCOL error mapping, "no local model under cloud_temp" assertions;
  - `test_activation.py` — pre-STT gate, playback-echo registry, body echo
    guard (sounddevice stubbed — no mic, no pip);
  - `test_confirmation.py` — yes/no/modify parsing + high-risk = non-voice;
  - `test_voice_path.py` — whole path: fake mic PCM → VAD → stub STT → wake
    gate → command, and fake Fish → speak JSON + binary frames (amplitude,
    §6 wrapper, 500 ms cap) → barge-in → degraded mode.
- `brain/voice/smoke_test.py` — REAL end-to-end (integrator only): silence/
  sine PCM → STT graceful empty; real fish synthesis speak frames; real
  TTS→STT round-trip; binary frame encode check.

```bash
brain/.venv/bin/python -m pytest brain/voice/tests -q -m "not integration"
brain/.venv/bin/python -m pytest brain/voice/tests -q          # + integration
brain/.venv/bin/python brain/voice/smoke_test.py               # needs fish
```

## Phase-2 TODOs (explicit, not hidden)

1. ~~Live mic wiring~~ DONE — ws.py `_on_audio_start/_on_audio_end` +
   binary kind=1 buffering → `transcribe_result` (audio_end should pass
   `reason=`; request OPEN to integrator).
2. **Real amplitude from playback** — current amplitude = RMS of synthesized
   chunk (real audio, honest); orb-side sync (amplitude → actual speaker
   output level) needs the Body playback ack loop.
3. **pitch_hz quality** — ZCR estimate is rough; replace with crepe/torchcrepe
   when VRAM budget allows (optional field; orb degrades gracefully).
4. **Endianness alignment** with body-dev for §6 u32 seq (I used big-endian).
5. **assets/raphael_reference.wav** — user must provide; adapter auto-wires.
6. **Voice-confirm wiring** — parser ships (`brain/voice/confirmation.py`);
   needs brain-core's `voice_safe(rowid)` + integrator's ws.py resolve branch
   (request OPEN).
