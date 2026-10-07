"""brain/voice/tests — voice stack unit + integration tests (voice-dev).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

# repo root on sys.path so `import brain.voice` works from any cwd
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import (  # noqa: E402
    PhraseCache, TTSError, VoiceConfig, VoiceSTTError, WakeGate,
    encode_binary_frame, error_frame, load_voice_config, normalize_text,
    split_sentences, stt_final_frame,
)
from brain.voice.stt import Transcriber, pcm_s16le_to_float32  # noqa: E402
from brain.voice.tts import (chunk_amplitude, chunk_pitch_hz,  # noqa: E402
                             resample_s16le, wav_bytes_to_s16le_pcm)
from brain.voice.wake import InterruptController, PTTGate  # noqa: E402


# ---- config ----------------------------------------------------------------
def test_config_defaults_and_yaml(tmp_path):
    cfg = load_voice_config(tmp_path / "nope.yaml")   # missing file -> defaults
    assert cfg.stt_model == "small"
    assert cfg.tts_sample_rate == 24000
    assert cfg.wake_word == "raphael"
    yml = tmp_path / "config.yaml"
    yml.write_text("voice:\n  stt_model: tiny\n  wake_word: Raph\n")
    cfg2 = load_voice_config(yml)
    assert cfg2.stt_model == "tiny"
    assert cfg2.wake_word == "Raph"


# ---- wake word / PTT -------------------------------------------------------
def test_wake_gate_variants():
    g = WakeGate("raphael")
    m = g.gate("Raphael, open YouTube", reason="wake")
    assert m.kind == "wake" and m.command == "open youtube"
    m = g.gate("hey raphael what time is it", reason="wake")
    assert m.kind == "wake" and m.command == "what time is it"
    m = g.gate("open youtube", reason="wake")
    assert m.kind == "none"                       # wake reason, no wake word
    m = g.gate("open youtube", reason="ptt")
    assert m.kind == "ptt" and m.command == "open youtube"
    assert g.gate("", reason="wake").kind == "none"
    assert g.gate("Raphael!!!", reason="wake").command == ""


def test_ptt_gate():
    p = PTTGate()
    assert p.open("s1", "ptt") is True
    assert p.is_active("s1") is True
    assert p.open("s2", "bogus") is False
    p.close("s1")
    assert p.is_active("s1") is False


def test_interrupt_controller():
    ic = InterruptController()
    ev = ic.register("job1")
    assert not ev.is_set()
    assert ic.any_active() is True
    assert ic.interrupt("job1") == 1
    assert ev.is_set()
    # interrupt-all
    e2, e3 = ic.register("a"), ic.register("b")
    assert ic.interrupt() == 2
    assert e2.is_set() and e3.is_set()


def test_normalize_text():
    assert normalize_text("  Hello,   WORLD!! ") == "hello world"
    assert normalize_text("Raphael…") == "raphael"


# ---- cache / sentences / frames --------------------------------------------
def test_phrase_cache(tmp_path):
    cache = PhraseCache(tmp_path)
    assert cache.load("Understood.") is None
    p = cache.store("Understood.", b"RIFFxxWAVEdata")
    assert p is not None and p.exists()
    assert cache.load("understood!") == b"RIFFxxWAVEdata"   # normalized key
    # human-named file wins
    (tmp_path / "confirmed.wav").write_bytes(b"HUMAN")
    assert cache.load("Confirmed") == b"HUMAN"


def test_split_sentences():
    assert split_sentences("Understood. Executing now.") == ["Understood.",
                                                             "Executing now."]
    assert split_sentences("") == []
    long = "word " * 100
    parts = split_sentences(long.strip(), max_chars=50)
    assert all(len(p) <= 50 for p in parts) and "".join(parts).replace(" ", "") \
        == ("word" * 100)


def test_binary_frame_encoding():
    frame = encode_binary_frame(2, 300, b"\x01\x02\x03")
    assert frame[:4] == b"RAPH"
    assert frame[4] == 2
    assert frame[5:9] == (300).to_bytes(4, "big")
    assert frame[9:] == b"\x01\x02\x03"


def test_frame_helpers():
    f = stt_final_frame("hello", "en", 0.42, job="j1")
    assert f == {"type": "stt_final", "v": 1, "job": "j1", "text": "hello",
                 "lang": "en", "rtf": 0.42}
    e = error_frame("E_OFFLINE", "x" * 500)
    assert e["code"] == "E_OFFLINE" and len(e["detail"]) <= 300


# ---- audio math ------------------------------------------------------------
def test_amplitude_and_pitch():
    sr = 24000
    t = np.arange(sr, dtype=np.float32) / sr
    tone = (0.5 * np.sin(2 * np.pi * 200 * t) * 32767).astype("<i2").tobytes()
    amp = chunk_amplitude(tone)
    assert 0.5 < amp <= 1.0
    pitch = chunk_pitch_hz(tone, sr)
    assert pitch is not None and abs(pitch - 200) < 30
    silence = b"\x00\x00" * sr
    assert chunk_amplitude(silence) == 0.0
    assert chunk_pitch_hz(silence, sr) is None


def test_resample_and_wav_roundtrip():
    import io

    import soundfile as sf

    sr_src, sr_dst = 32000, 24000
    t = np.arange(sr_src, dtype=np.float32) / sr_src
    x = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, x, sr_src, format="WAV", subtype="PCM_16")
    pcm, rate = wav_bytes_to_s16le_pcm(buf.getvalue(), sr_dst)
    assert rate == 24000
    assert abs(len(pcm) / 2 - sr_dst) < 10            # ~1 s at 24k
    # direct resample path
    raw = (x * 32767).astype("<i2").tobytes()
    out = resample_s16le(raw, sr_src, sr_dst)
    assert abs(len(out) / 2 - sr_dst) < 10


def test_pcm_decode_edge_cases():
    assert len(pcm_s16le_to_float32(b"")) == 0
    assert len(pcm_s16le_to_float32(b"\x01")) == 0     # odd byte dropped
    arr = pcm_s16le_to_float32(b"\x00\x80")           # -32768
    assert abs(arr[0] + 1.0) < 1e-6


# ---- STT integration (model cached on this machine) ------------------------
def test_stt_silence_and_sine_graceful():
    tr = Transcriber()
    res = tr.transcribe(b"")                            # empty
    assert res.text == "" and res.duration_s == 0.0
    sr = 16000
    silence = b"\x00\x00" * sr                          # 1 s silence
    res = tr.transcribe(silence)
    assert res.text == ""                               # VAD kills silence
    t = np.arange(sr, dtype=np.float32) / sr
    tone = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2").tobytes()
    res = tr.transcribe(tone)
    assert res.text == ""                               # pure tone -> no speech
    assert res.rtf >= 0.0


def test_stt_model_loads():
    tr = Transcriber()
    tr.load()
    assert tr.load_ms is not None and tr.load_ms > 0
    tr.load()                                            # idempotent


def test_stt_typed_error_on_bad_model(monkeypatch):
    cfg = VoiceConfig(stt_model="this-model-does-not-exist-xyz")
    tr = Transcriber(cfg)
    with pytest.raises(VoiceSTTError) as ei:
        tr.transcribe(b"\x00\x00" * 16000)
    assert ei.value.code in ("E_OFFLINE", "E_INTERNAL", "E_LOCAL_DOWN")
    # second call raises the SAME cached typed error (no crash-loop retries)
    with pytest.raises(VoiceSTTError):
        tr.transcribe(b"\x00\x00" * 16000)


# ---- TTS fallback path (no server needed) ----------------------------------
def _collect(events):
    return list(events)


def test_tts_fallback_events_shape(tmp_path):
    """Fish unavailable -> subtitle-only + ONE-TIME notice (no placeholder
    tone, no repeated apology — Wave 2 task 3)."""
    from brain.voice.tts import TTSEngine

    eng = TTSEngine(VoiceConfig(ack_cache=str(tmp_path)))
    events = _collect(asyncio.run(
        _consume(eng.speak("Task complete.", force_fallback=True))))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "end"
    assert "chunk" not in kinds                  # subtitle-only: no fake audio
    assert eng.stats.engine == "fallback"
    assert events[-1].get("notice")              # first degraded reply explains
    assert "TTS engine unavailable" in events[-1]["notice"]
    # one-time: the next degraded reply stays quiet (subtitle carries it)
    events2 = _collect(asyncio.run(
        _consume(eng.speak("Task complete again.", force_fallback=True))))
    assert events2[-1].get("notice") is None
    assert [e["event"] for e in events2] == ["start", "end"]


def test_tts_cancel_before_start():
    from brain.voice.tts import TTSEngine

    eng = TTSEngine(VoiceConfig(ack_cache=str(Path(__file__).parent / "_tcache")))
    cancel = asyncio.Event()
    cancel.set()

    async def _run():
        out = []
        async for e in eng.speak("Hello there.", cancel=cancel,
                                 force_fallback=True):
            out.append(e)
        return out

    events = asyncio.run(_run())
    assert events[0]["event"] == "start"
    assert events[-1]["event"] == "end" and events[-1].get("interrupted") is True
    assert all(e["event"] != "chunk" for e in events)


def _seed_cache_wav(eng, text, seconds=6.0, sr=24000):
    """Store a real wav in the phrase cache so the cache path streams chunks
    (used where the fallback no longer emits audio)."""
    pytest.importorskip("soundfile")   # brain/.venv has it; lean venvs may not
    import soundfile as sf

    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    x = 0.25 * np.sin(2 * np.pi * 180.0 * t)
    import io

    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype="PCM_16")
    eng.cache.store(text, buf.getvalue())


def test_tts_interrupt_mid_stream(tmp_path):
    from brain.voice.tts import TTSEngine

    eng = TTSEngine(VoiceConfig(ack_cache=str(tmp_path)))
    _seed_cache_wav(eng, "This is a fairly long sentence used to generate many "
                         "chunks so interruption lands mid stream.")
    cancel = asyncio.Event()

    async def _run():
        out = []
        async for e in eng.speak(
                "This is a fairly long sentence used to generate many chunks "
                "so interruption lands mid stream.", cancel=cancel,
                force_fallback=False):
            out.append(e)
            if e["event"] == "chunk" and len(out) == 3:   # interrupt early
                cancel.set()
        return out

    events = asyncio.run(_run())
    chunks = [e for e in events if e["event"] == "chunk"]
    assert len(chunks) >= 1                        # really did cut mid-stream
    assert all(0.0 <= c["amplitude"] <= 1.0 for c in chunks)
    assert events[-1]["event"] == "end" and events[-1].get("interrupted") is True


async def _consume(aiter):
    return [e async for e in aiter]


# ---- TTS fish-server integration (skips when server cannot start) ---------
@pytest.mark.integration
def test_tts_fish_real_synthesis():
    from brain.voice.tts import TTSEngine

    eng = TTSEngine(VoiceConfig())
    # evict any cached copy so this asserts FRESH synthesis, not a cache hit
    cached = eng.cache.path_for("Confirmed.")
    if cached.exists():
        cached.unlink()
    try:
        asyncio.run(eng.fish.ensure_started(timeout_s=240))
    except TTSError as e:
        pytest.skip(f"fish server unavailable: {e.code} {e.detail[:120]}")
    events = asyncio.run(_consume(eng.speak("Confirmed.", job="j_test")))
    engines = {e.get("engine") for e in events if e["event"] == "chunk"}
    assert engines == {"fish"}, f"unexpected engines {engines}"
    chunks = [e for e in events if e["event"] == "chunk"]
    assert chunks and all(0.0 <= c["amplitude"] <= 1.0 for c in chunks)
    total = sum(len(c["payload"]) for c in chunks)
    assert total > 24000                                 # > 0.5 s of audio
    # cache should now hold the phrase
    assert eng.cache.load("Confirmed.") is not None


@pytest.mark.integration
def test_round_trip_tts_to_stt():
    """Real end-to-end: synthesize with fish-speech, transcribe with whisper."""
    from brain.voice.tts import TTSEngine

    eng = TTSEngine(VoiceConfig())
    cached = eng.cache.path_for("Analysis complete.")   # force fresh synthesis
    if cached.exists():
        cached.unlink()
    try:
        asyncio.run(eng.fish.ensure_started(timeout_s=240))
    except TTSError as e:
        pytest.skip(f"fish server unavailable: {e.code}")
    events = asyncio.run(_consume(eng.speak("Analysis complete.",
                                            job="j_rt", force_fallback=False)))
    pcm = b"".join(c["payload"] for c in events if c["event"] == "chunk")
    assert pcm
    tr = Transcriber()
    res = tr.transcribe(pcm, sample_rate=24000)
    # whisper expects 16k; resample for the check
    pcm16 = resample_s16le(pcm, 24000, 16000)
    res = tr.transcribe(pcm16, sample_rate=16000)
    norm = normalize_text(res.text)
    assert "analysis" in norm or "complete" in norm, f"got: {res.text!r}"
