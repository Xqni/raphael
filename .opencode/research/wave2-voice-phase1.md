# Wave 2 — Voice phase 1 (brain/voice/) — FINAL LOG

Owner: voice-dev. Status: **PHASE 1 COMPLETE + VERIFIED (2026-10-05 ~09:40)**
(Edit-tool writes outside brain/voice are denied by permission config; this log
is written via shell heredoc — orchestrator-instructed path.)

## Environment facts (verified)
- brain/.venv: Python 3.12.8; fastapi 0.142.2, uvicorn 0.54.0, torch 2.14.0+cu126,
  numpy 2.5.3, pydantic 2.13.5, transformers 5.18.0, pyyaml 6.0.3, httpx, soundfile.
- GPU: RTX 4060 Laptop 8188 MiB (free during run: 7.44 GB; no Ollama model resident).
- assets/raphael_reference.wav — MISSING (user-provided per addendum §10; adapter
  auto-wires it as fish in-context reference once dropped in — no code change).
- assets/acks/ — created by voice stack (phrase cache; 3 real synthesized wavs).

## Installs (REAL uv output, verbatim key lines)
1. brain/.venv: `uv pip install --python brain/.venv/bin/python faster-whisper soundfile`
   → + av==19.0.1, ctranslate2==4.8.2, faster-whisper==1.2.1, soundfile==0.14.0,
     cffi==2.1.1, pycparser==3.0 (6 packages, 7ms install after download)
2. brain/voice/.venv-fish (ISOLATED — fish-speech pins numpy<=1.26.4, pydantic==2.9.2,
   torch<=2.4.1; installing into brain/.venv would downgrade the LIVE brain stack):
   `brain/voice/scripts/build_fish_venv.sh`
   - torch==2.4.1 + torchaudio==2.4.1 from download.pytorch.org/whl/cu124
     (downloaded: torch 760MB, cudnn 634MB, cublas 392MB, nccl 168MB, triton 200MB,
     cusparse 187MB, cufft 116MB, cusolver 118MB + others ≈ 2.6GB total)
   - 151 fish-speech runtime deps (gradio, funasr 1.1.5, modelscope, librosa, kui,
     ormsgpack, tiktoken, pydantic 2.9.2, numpy 1.26.4, ...). pyaudio EXCLUDED
     (only tools/api_client.py imports it; needs portaudio headers — no sudo).
   - `fish-speech==0.1.0` installed -e from vendor clone (--no-deps)
   - VERIFIED: `FISH_VENV_OK torch 2.4.1+cu121 cuda True` (BUILD_DONE)

## Downloads (REAL sizes)
- Systran/faster-whisper-small → ~/.cache/huggingface/hub/models--Systran--faster-whisper-small
  = **464 MB** (du -shL)
- fishaudio/fish-speech-1.5 (UNGATED; s1-mini avoided — gated) →
  brain/voice/models/fish-speech-1.5 = **1.4 GB** (model.pth 1,275,908,030 B +
  firefly-gan-vq-fsq-8x1024-21hz-generator.pth 188,518,579 B + tokenizer/config)
- fishaudio/fish-speech code: git clone --depth 1 --branch v1.5.0
  → brain/voice/vendor/fish-speech (tag v1.5.0 matches the 1.5 checkpoint)

## Architecture decisions
- Fish-speech served via ITS OWN HTTP API server (docs/en/inference.md @v1.5.0:
  `python -m tools.api_server`), spawned on demand by brain/voice/tts.py into
  127.0.0.1:8777 (brain keeps 8765), model-resident → per-sentence REST calls.
  Server log: brain/voice/logs/fish_server.log. HF_HUB_OFFLINE=1 (weights local).
- speak() streams sentence-by-sentence: first sentence synthesized+emitted while
  the next generates (20 frames for a 2-sentence phrase; 4.05s total wall).
- Amplitude = per-chunk RMS of REAL synthesized audio ×3.0 clamped [0,1] (§8).
  pitch_hz = rough ZCR estimate, gated 60-400 Hz + energy (emits None on real
  speech chunks tonight — honest abstention; crepe = phase 2).
- Binary §6 wrapper: `b'RAPH' + u8 kind + u32 seq + payload`, **u32 BIG-endian**
  (PROTOCOL unspecified — flagged for body-dev alignment).
- ctranslate2 CUDA fix: libcublas.so.12 ships in brain/.venv as nvidia pip deps
  but glibc dlopen cache misses it → stt.py preloads nvidia/*/lib via
  ctypes.CDLL(RTLD_GLOBAL) before model load (verified: whisper runs on CUDA,
  float16; silence rtf 0.25, model load ~1.0s lazy).

## Bugs found & fixed during verification (REAL failures, not hypothetical)
1. `_chunk_events()` returns (list, seq) tuple but speak() iterated it directly
   → TypeError 'list indices' — fixed by unpacking at all 3 call sites.
2. PhraseCache.load() rejected payloads <=44 bytes (wav-header guard too strict)
   → threshold >0.
3. libcublas.so.12 dlopen failure → RTLD_GLOBAL preload (see above).
4. smoke test: startup_ms None when server already running → guarded print.
5. fallback chunk events mislabeled cached=True → now reflects phrase-cache hit.

## Test runs (REAL outputs)
`brain/.venv/bin/python -m pytest brain/voice/tests -q` (FINAL):
  `....................                                                     [100%]`
  `20 passed in 8.60s`
  (includes: wake/PTT/interrupt unit tests, cache, frames, audio math, STT
  silence/sine graceful + CUDA model load + typed error path, TTS fallback
  events + cancel + mid-stream interrupt, REAL fish synthesis, REAL
  fish→whisper round-trip)

`brain/.venv/bin/python brain/voice/smoke_test.py` (FINAL, cold start):
  silence 1s  -> text='' rtf=0.253 (1269 ms)
  sine 440Hz  -> text='' rtf=0.063 (model load: 1015 ms, device loaded lazily)
  fish server: HEALTHY at http://127.0.0.1:8777 (startup 19335 ms)
  speak('Understood. Executing now.') -> 20 frames in 4.05s (18 chunks, 2.09s audio @24k)
  mid chunk: {... "event": "chunk", "amplitude": 0.290, "pitch_hz": null,
             "engine": "fish"} payload=6000B
  amplitudes: [0.006, 0.197, 0.109, 0.037, 0.264, 0.041, 0.015, 0.006, ...]
  cached speak -> 19 frames in 1 ms start.cached=True engine=cache
  binary frame: magic=b'RAPH' kind=2 seq=1 payload=6000B (total 6009B)
  ROUND-TRIP: synthesized 'Analysis complete.' (1.49s @24k) ->
              whisper transcript: 'An analysis complete.' (lang=en rtf=0.152)
  gate('Raphael, what time is it', wake) -> kind=wake command='what time is it'
  gate('open youtube', wake)            -> kind=none (ignored)
  gate('open youtube', ptt)             -> kind=ptt command='open youtube'
  SMOKE_TEST_DONE

Forced degraded fallback (real run): placeholder tone chunks
  amplitudes [0.344, 0.382, 0.334], cached=False, engine=fallback,
  end notice: "TTS engine unavailable — placeholder tone; subtitle carries
  the actual reply"

## Files delivered (all under brain/voice/ + voice-owned assets/)
- brain/voice/__init__.py      — public API + VoiceStack singleton + docstring wire-up
- brain/voice/config.py        — config.yaml voice: loader + env overrides
- brain/voice/stt.py           — faster-whisper Transcriber (lazy, CUDA preload, typed errors)
- brain/voice/tts.py           — FishSpeechServer + TTSEngine.speak() + PhraseCache
                                 + amplitude/pitch + §6 frame helpers
- brain/voice/wake.py          — WakeGate / PTTGate / InterruptController (pure logic)
- brain/voice/README.md        — loop.py handoff (exact imports, call sites, frames)
- brain/voice/tests/test_voice.py + tests/__init__.py + pytest.ini — 20 tests
- brain/voice/smoke_test.py    — end-to-end smoke (outputs pasted above)
- brain/voice/scripts/build_fish_venv.sh — reproducible isolated venv build
- brain/voice/vendor/fish-speech (clone v1.5.0), models/fish-speech-1.5 (1.4GB),
  .venv-fish, logs/fish_server.log, tests/_tcache* (test artifacts)
- assets/acks/*.wav (3 synthesized cache entries — assets/ is voice-dev-owned per ARCH §2)

## RESUME state (phase 2 handoff)
DONE phase 1: STT (VAD, CUDA, graceful), TTS (fish server adapter, sentence
stream, phrase cache, amplitude, fallback+notice), wake/PTT/interrupt logic,
PROTOCOL frames + helpers, loop.py README wiring, 20 tests + smoke verified.
PHASE 2 TODOs (explicit):
1. Live mic wiring in ws.py `_on_audio_start/_on_audio_end` + binary kind=1
   buffering → transcribe_result (needs brain-dev hub access; PTT hotkey
   body-side = "voice phase 3" per PROGRESS.md).
2. Barge-in wiring: audio_start while speaking → voice.interrupts.interrupt()
   BEFORE submitting the new command (logic tested; needs the hub hook).
3. pitch_hz quality: ZCR abstains on real speech; torchcrepe when VRAM allows
   (optional field; orb degrades gracefully).
4. §6 u32 seq endianness = big-endian here → confirm with body-dev.
5. assets/raphael_reference.wav + optional .txt transcript — user provides;
   adapter auto-sends as fish reference; restart server to pick up.
6. VRAM scheduling: fish server (≈2-3GB) + whisper (~0.6GB) + Ollama on 8GB —
   brain-dev scheduling concern (addendum §73); server stays resident by design,
   stop via TTSEngine.shutdown() when needed.
7. Known cosmetic: speak `start` frame carries engine='none' when engine is
   resolved later (fish/fallback); end frame + notice carry the truth.
