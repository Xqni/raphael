"""P0 2026-10-07 — lost JP accent + speaking gaps: regression tests.

  A. audio_out playback loss: a speak `start` while the previous tail is
     still draining must KEEP the audio (the old clear threw away up to 42%);
     only genuinely stale leftovers are dropped — and counted (`dropped`).
  B. legacy cache sweep: non-namespaced (pre-reference) hash wavs are moved
     out of the ack-cache root; user text-named acks + namespaced entries
     are untouched; idempotent.
  C. timbre gate: an off-voice render is NEVER cached (cos < 0.65 vs the
     configured reference) while a reference-matching render is — so a cached
     phrase can never replay the wrong voice.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import dataclasses
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# stub sounddevice before body modules import it (no device, no pip)
if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

from brain.voice import VoiceConfig  # noqa: E402
from brain.voice.tts import (STORE_MIN_COS, TTSEngine,  # noqa: E402
                             sweep_legacy_cache, timbre_similarity)
from body.win import audio_out  # noqa: E402

JP_REF = _REPO / "assets" / "raphael_reference_jp.wav"
HEX1 = "0123456789abcdef.wav"


def _pcm(ms=400, rms=3000, freq=220.0, sr=16000):
    n = int(sr * ms / 1000)
    t = np.arange(n, dtype=np.float64) / sr
    a = min(32000.0, rms * np.sqrt(2.0))
    return (a * np.sin(2 * np.pi * freq * t)).astype("<i2").tobytes()


# ---- A. playback loss (the 42% bug) ----------------------------------------
def test_speak_start_keeps_recent_pending_audio():
    """body: `end` handling is detached, so the NEXT sentence's `start` lands
    while the previous tail is still buffered — that tail must SURVIVE."""
    p = audio_out.StreamPlayer()
    p.feed(_pcm(300))                       # previous sentence's tail
    before = bytes(p._buf)
    assert before
    p.reset()                               # next sentence starts
    assert bytes(p._buf) == before          # KEPT, not cleared
    assert p.kept == len(before)
    assert p.dropped == 0


def test_speak_start_drops_only_stale_leftovers():
    p = audio_out.StreamPlayer()
    p.feed(_pcm(100))
    p._last_feed_ts = time.monotonic() - (audio_out.STALE_RESET_S + 1)
    p.reset()                               # nothing fed for >2.5s = stale
    assert len(p._buf) == 0
    assert p.dropped > 0                    # accounted, not silent


def test_reset_on_empty_buffer_is_free():
    p = audio_out.StreamPlayer()
    p.reset()
    assert p.dropped == 0 and p.kept == 0


def test_stats_expose_loss_accounting():
    p = audio_out.StreamPlayer()
    p.feed(_pcm(50))
    s = p.stats()
    assert {"dropped", "kept", "underruns"} <= set(s)


# ---- B. legacy cache sweep -------------------------------------------------
def test_sweep_moves_only_non_namespaced_hashes(tmp_path):
    root = tmp_path / "acks"
    (root / "f64bd512ea1e").mkdir(parents=True)
    (root / HEX1).write_bytes(b"PRE_JP_ZIRA")            # legacy flat hash
    (root / "confirmed.wav").write_bytes(b"USER_ACK")    # text-named user ack
    (root / "f64bd512ea1e" / "aaaa111122223333.wav").write_bytes(b"CURRENT")

    moved = sweep_legacy_cache(root, dest=tmp_path / "swept")
    assert [p.name for p in moved] == [HEX1]
    assert not (root / HEX1).exists()
    assert (tmp_path / "swept" / HEX1).read_bytes() == b"PRE_JP_ZIRA"
    assert (root / "confirmed.wav").exists()             # user ack untouched
    assert (root / "f64bd512ea1e" / "aaaa111122223333.wav").exists()

    # idempotent: a second sweep finds nothing
    assert sweep_legacy_cache(root, dest=tmp_path / "swept") == []


def test_engine_init_sweeps_cache_root(tmp_path):
    root = tmp_path / "acks"
    root.mkdir()
    (root / HEX1).write_bytes(b"LEGACY")
    cfg = dataclasses.replace(VoiceConfig(), ack_cache=str(root))
    TTSEngine(cfg)
    assert not (root / HEX1).exists()        # swept at construction


# ---- C. timbre gate: never cache a wrong-voice render ----------------------
def _harmonic_voice_pcm(sr=24000, seconds=2.0, f0=140.0):
    """A synthetic 'wrong voice' (different spectral envelope than the ref)."""
    t = np.arange(int(sr * seconds)) / sr
    x = sum((0.3 / k) * np.sin(2 * np.pi * f0 * k * t) for k in range(1, 9))
    return x.astype(np.float32)


def test_timbre_similarity_separates_ref_from_wrong_voice():
    pytest.importorskip("soundfile")
    import soundfile as sf

    data, sr = sf.read(str(JP_REF), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    ref_score = timbre_similarity(pcm, int(sr), JP_REF)
    # same recording as the reference -> very high similarity
    assert ref_score is not None and ref_score > 0.95

    # calibrated (measured on this box): our renders 0.74-0.98, a wrong
    # speech voice <= 0.64, threshold 0.65 sits between. NOTE: flat white
    # noise scores high (log-spectral cosine blind spot) — fish produces
    # speech, not noise, and both real wrong voices are far below.
    wrong = timbre_similarity(
        (np.clip(_harmonic_voice_pcm(), -1.0, 1.0) * 32767).astype("<i2")
        .tobytes(), 24000, JP_REF)
    assert wrong is not None and wrong < STORE_MIN_COS
    zira = (Path.home() / "raphael/assets/reference/samples/"
            / "02_zira_current_ref.wav")     # the retired voice (if present)
    if zira.exists():
        d, sr = sf.read(str(zira), dtype="float32", always_2d=True)
        z = (np.clip(d.mean(axis=1), -1, 1) * 32767).astype("<i2").tobytes()
        zscore = timbre_similarity(z, int(sr), JP_REF)
        assert zscore is not None and zscore < STORE_MIN_COS


class _FakeFishVoice:
    """Returns audio from a fixed wav file (ref-like or noise)."""

    def __init__(self, wav_bytes: bytes):
        self.wav_bytes = wav_bytes
        self.proc = None
        self.last_error = None
        self.calls = 0

    async def ensure_started(self, timeout_s=240.0):
        return None

    def check_reference(self):
        return JP_REF

    async def synthesize(self, text):
        self.calls += 1
        return self.wav_bytes

    def stop(self):
        pass


def _engine(tmp_path):
    cfg = dataclasses.replace(VoiceConfig(), ack_cache=str(tmp_path / "acks"))
    return TTSEngine(cfg)


async def _chunks(eng, text):
    out = []
    async for e in eng.speak(text, job="p0"):
        out.append(e)
    return [e for e in out if e["event"] == "chunk"]


def test_off_voice_render_is_never_cached(tmp_path, capsys):
    pytest.importorskip("soundfile")
    import io

    import soundfile as sf
    # synthesize a WRONG voice (different spectral envelope) -> must NOT be
    # cached, but the audio still plays (live playback is not gated)
    buf = io.BytesIO()
    sf.write(buf, _harmonic_voice_pcm(), 24000, format="WAV", subtype="PCM_16")

    eng = _engine(tmp_path)
    eng.fish = _FakeFishVoice(buf.getvalue())
    chunks = asyncio.run(_chunks(eng, "Task complete."))
    assert chunks                              # audio still PLAYS (live is live)
    assert eng.cache.load("Task complete.") is None     # but never cached
    assert "cache store REFUSED" in capsys.readouterr().out


def test_reference_matching_render_is_cached(tmp_path, capsys):
    pytest.importorskip("soundfile")
    eng = _engine(tmp_path)
    eng.fish = _FakeFishVoice(JP_REF.read_bytes())     # reference-like audio
    chunks = asyncio.run(_chunks(eng, "Task complete."))
    assert chunks
    assert eng.cache.load("Task complete.") is not None  # cached
    assert "cached phrase (timbre cos" in capsys.readouterr().out


# ---- P0 gaps: reply-level pre-roll (gapless burst) -------------------------
def _short_wav(ms=300):
    """A SHORT (0.3s) ref-like wav — keeps the adaptive early-start from
    firing (0.3s buffered < 1.3x estimated remaining gen) so the ALL-first
    contract can be asserted deterministically."""
    pytest.importorskip("soundfile")
    import io

    import soundfile as sf
    buf = io.BytesIO()
    sr = 32000
    t = np.arange(int(sr * ms / 1000), dtype=np.float32) / sr
    sf.write(buf, (0.3 * np.sin(2 * np.pi * 300.0 * t)).astype(np.float32),
             sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class _SlowFish(_FakeFishVoice):
    """Fake fish where every synthesis takes real (small) time, so the
    pre-roll order can be observed deterministically."""

    def __init__(self, wav_bytes: bytes, delay_s: float = 0.5):
        super().__init__(wav_bytes)
        self.delay_s = delay_s
        self.order: list = []

    async def synthesize(self, text):
        self.calls += 1
        self.order.append(text)
        await asyncio.sleep(self.delay_s)
        return self.wav_bytes


def test_multi_sentence_reply_is_prerolled_before_first_chunk(tmp_path):
    """The gapless contract: no chunk is sent until the reply's buffer can
    out-run the rest of generation — here (fast gen, short audio) that means
    ALL sentences are synthesized first (the 12.23s-hole contract)."""
    eng = _engine(tmp_path)
    fish = _SlowFish(_short_wav(), delay_s=0.5)
    eng.fish = fish

    first_chunk_at = None
    chunks = 0
    async def run():
        nonlocal first_chunk_at, chunks
        async for e in eng.speak("One sentence here. Two sentences here. "
                                 "Three sentences here.", job="j_pre",
                                 max_sentences=0):   # uncapped: all 3 count
            if e["event"] == "chunk":
                chunks += 1
                if first_chunk_at is None:
                    first_chunk_at = len(fish.order)
    asyncio.run(run())
    assert chunks > 0
    assert first_chunk_at == 3, "first chunk must wait for ALL sentences"


def test_single_sentence_reply_has_no_preroll_delay(tmp_path):
    pytest.importorskip("soundfile")
    eng = _engine(tmp_path)
    fish = _SlowFish(JP_REF.read_bytes(), delay_s=0.05)
    eng.fish = fish
    first_chunk_at = None
    async def run():
        nonlocal first_chunk_at
        async for e in eng.speak("Only one sentence.", job="j_one"):
            if e["event"] == "chunk" and first_chunk_at is None:
                first_chunk_at = len(fish.order)
    asyncio.run(run())
    assert first_chunk_at == 1   # nothing extra to wait for


def test_preroll_adaptive_start_when_buffer_wins(tmp_path, capsys):
    """LONG audio vs fast gen: speaking must start early (buffered audio can
    out-run estimated remaining generation) instead of waiting for everything."""
    pytest.importorskip("soundfile")
    eng = _engine(tmp_path)
    fish = _SlowFish(JP_REF.read_bytes(), delay_s=0.05)   # 8.5s audio each
    eng.fish = fish
    first_chunk_at = None
    async def run():
        nonlocal first_chunk_at
        async for e in eng.speak("Alpha one. Beta two. Gamma three.",
                                 job="j_adapt", max_sentences=0):
            if e["event"] == "chunk" and first_chunk_at is None:
                first_chunk_at = len(fish.order)
    asyncio.run(run())
    assert first_chunk_at == 1                     # adaptive, not full wait
    assert "preroll adaptive start" in capsys.readouterr().out


def test_preroll_budget_falls_back_to_live_streaming(tmp_path, capsys):
    """RAPHAEL_TTS_PREROLL_S=0 disables pre-roll (old behavior): chunks start
    after the FIRST sentence even though more are pending."""
    eng = _engine(tmp_path)
    eng.preroll_budget_s = 0.0                     # disabled (hard cap, 1st)
    fish = _SlowFish(_short_wav(), delay_s=0.03)
    eng.fish = fish
    first_chunk_at = None
    async def run():
        nonlocal first_chunk_at
        async for e in eng.speak("Alpha one. Beta two. Gamma three.",
                                 job="j_off"):
            if e["event"] == "chunk" and first_chunk_at is None:
                first_chunk_at = len(fish.order)
    asyncio.run(run())
    assert first_chunk_at == 1                     # streams from sentence 1
    assert "preroll budget" in capsys.readouterr().out
