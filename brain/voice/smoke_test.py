#!/usr/bin/env python
"""brain/voice/smoke_test.py — REAL end-to-end smoke test (voice-dev).

Runs in brain/.venv. Exercises: STT graceful paths (silence/sine), fish-speech
server startup + real synthesis, speak-frame emission (amplitude/pitch/cached),
TTS->STT round-trip, phrase cache hit, binary frame encoding, wake gate.

Usage: brain/.venv/bin/python brain/voice/smoke_test.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402

from brain.voice import (VoiceConfig, error_frame, get_voice,  # noqa: E402
                         encode_binary_frame, normalize_text,
                         speak_frame, speak_payload, stt_final_frame)
from brain.voice.stt import Transcriber  # noqa: E402
from brain.voice.tts import TTSEngine, TTSError, resample_s16le  # noqa: E402


def section(title):
    print(f"\n=== {title} ===")


def main():
    cfg = VoiceConfig()
    print(f"python: {sys.version.split()[0]}")
    print(f"repo:   {_REPO}")
    print(f"stt:    faster-whisper '{cfg.stt_model}' device={cfg.stt_device}")
    print(f"tts:    fish checkpoint={cfg.fish_checkpoint_path} "
          f"exists={cfg.fish_checkpoint_path.exists()}")
    print(f"voice:  reference asset={cfg.tts_voice_path} "
          f"exists={cfg.tts_voice_path.exists()}  <-- MISSING is expected (user-provided)")
    print(f"cache:  {cfg.ack_cache_path}")
    try:
        import torch
        print(f"torch:  {torch.__version__} cuda_available={torch.cuda.is_available()}")
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            print(f"vram:   free={free/1e9:.2f}GB total={total/1e9:.2f}GB")
    except Exception as e:  # noqa: BLE001
        print(f"torch:  unavailable ({e})")

    # ---- 1. STT graceful paths --------------------------------------------
    section("STT: silence + sine PCM (expect empty transcript, no crash)")
    tr = Transcriber()
    t0 = time.perf_counter()
    r_sil = tr.transcribe(b"\x00\x00" * 16000)
    print(f"silence 1s  -> text={r_sil.text!r} rtf={r_sil.rtf:.3f} "
          f"({(time.perf_counter()-t0)*1000:.0f} ms)")
    sr = 16000
    t = np.arange(sr, dtype=np.float32) / sr
    tone = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2").tobytes()
    r_tone = tr.transcribe(tone)
    print(f"sine 440Hz  -> text={r_tone.text!r} rtf={r_tone.rtf:.3f} "
          f"(model load: {tr.load_ms:.0f} ms, device loaded lazily)")

    # ---- 2. fish-speech server --------------------------------------------
    section("TTS: fish-speech server startup + real synthesis")
    voice = get_voice(cfg)
    eng = voice.tts
    try:
        asyncio.run(eng.fish.ensure_started(timeout_s=240))
        if eng.fish.startup_ms is not None:
            print(f"fish server: HEALTHY at {eng.fish.base} "
                  f"(startup {eng.fish.startup_ms:.0f} ms)")
        else:
            print(f"fish server: HEALTHY at {eng.fish.base} (already running)")
    except TTSError as e:
        print(f"fish server: UNAVAILABLE code={e.code} detail={e.detail[:200]}")
        print("-> degraded fallback path will be exercised below")
        eng.shutdown()
        _fallback_demo(voice)
        return

    async def run_stream(text, job):
        events = []
        async for ev in voice.speak(text, job=job):
            events.append(ev)
        return events

    text1 = "Understood. Executing now."
    t0 = time.perf_counter()
    events = asyncio.run(run_stream(text1, "j_smoke1"))
    dt = time.perf_counter() - t0
    frames = [speak_frame(e) for e in events]
    chunks = [e for e in events if e["event"] == "chunk"]
    total_bytes = sum(len(speak_payload(e)) for e in chunks)
    print(f"speak({text1!r}) -> {len(frames)} frames in {dt:.2f}s "
          f"({len(chunks)} chunks, {total_bytes/2/24000:.2f}s audio @24k)")
    print("start frame:", json.dumps(frames[0]))
    if chunks:
        mid = chunks[len(chunks)//2]
        print("mid chunk :", json.dumps(speak_frame(mid))[:220],
              f"payload={len(speak_payload(mid))}B")
        print("amplitudes:", [round(c["amplitude"], 3) for c in chunks][:12])
        print("pitch_hz  :", [c.get("pitch_hz") for c in chunks][:12])
    print("end frame  :", json.dumps(frames[-1]))

    # ---- 3. phrase cache hit ----------------------------------------------
    section("TTS: phrase cache (second identical speak)")
    t0 = time.perf_counter()
    events2 = asyncio.run(run_stream(text1, "j_smoke2"))
    dt2 = time.perf_counter() - t0
    print(f"cached speak -> {len(events2)} frames in {dt2*1000:.0f} ms "
          f"start.cached={events2[0]['cached']} engine={events2[0]['engine']} "
          f"end.engine={events2[-1].get('engine')}")

    # ---- 4. binary frame + stt_final helpers ------------------------------
    section("PROTOCOL frame helpers")
    if chunks:
        payload = speak_payload(chunks[0])
        b = encode_binary_frame(2, chunks[0]["seq"], payload)
        print(f"binary frame: magic={b[:4]!r} kind={b[4]} "
              f"seq={int.from_bytes(b[5:9],'big')} payload={len(b)-9}B "
              f"(total {len(b)}B)")
    print("stt_final  :", json.dumps(stt_final_frame("hello", "en", 0.42, job="j1")))
    print("error      :", json.dumps(error_frame("E_LOCAL_DOWN", "test")))

    # ---- 5. REAL round-trip: fish TTS -> whisper STT ----------------------
    section("Round-trip: fish-speech synthesis -> faster-whisper transcription")
    rt_text = "Analysis complete."
    cached = eng.cache.path_for(rt_text)     # force fresh synthesis each run
    if cached.exists():
        cached.unlink()
    ev = asyncio.run(run_stream(rt_text, "j_rt"))
    pcm24 = b"".join(speak_payload(e) for e in ev if e["event"] == "chunk")
    pcm16 = resample_s16le(pcm24, 24000, 16000)
    res = tr.transcribe(pcm16, sample_rate=16000)
    print(f"synthesized {rt_text!r} ({len(pcm24)/2/24000:.2f}s @24k) -> "
          f"whisper transcript: {res.text!r} (lang={res.lang} rtf={res.rtf:.3f})")
    print(f"normalized match: {normalize_text(res.text)!r}")

    # ---- 6. wake gate on the round-trip -----------------------------------
    section("Wake gate")
    m = voice.wake.gate("Raphael, what time is it", reason="wake")
    print(f"gate('Raphael, what time is it', wake) -> kind={m.kind} "
          f"command={m.command!r}")
    m = voice.wake.gate("open youtube", reason="wake")
    print(f"gate('open youtube', wake)            -> kind={m.kind} (ignored)")
    m = voice.wake.gate("open youtube", reason="ptt")
    print(f"gate('open youtube', ptt)             -> kind={m.kind} "
          f"command={m.command!r}")

    voice.shutdown()
    print("\nSMOKE_TEST_DONE")


def _fallback_demo(voice):
    """When fish is unavailable: exercise degraded speak path for real."""
    async def run(text):
        return [e async for e in voice.speak(text, force_fallback=True)]
    events = asyncio.run(run("Task complete."))
    frames = [speak_frame(e) for e in events]
    chunks = [e for e in events if e["event"] == "chunk"]
    print(f"fallback speak -> {len(frames)} frames, {len(chunks)} chunks, "
          f"amplitudes={[round(c['amplitude'],3) for c in chunks][:8]}")
    print("start:", json.dumps(frames[0]))
    print("end  :", json.dumps(frames[-1]))
    print("SMOKE_TEST_DONE (fallback only)")


if __name__ == "__main__":
    main()
