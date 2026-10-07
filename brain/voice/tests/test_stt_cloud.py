"""Wave 2 task 1 — STT seam: cloud_temp transcribes through
`router.transcribe()` (Groq Whisper), local faster-whisper stays behind the
profile gate (code untouched, never loaded under cloud_temp).

Everything here is mock-based: brain.router.transcribe is stubbed, no network,
no model weights (AGENT_RULES §5, WAVES.md cloud_temp constraint).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import struct
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import brain.router as router  # noqa: E402
from brain.voice import VoiceConfig, VoiceSTTError  # noqa: E402
from brain.voice.stt import (CloudTranscriber, SttEngine,  # noqa: E402
                             Transcriber, is_effectively_silent,
                             pcm_to_wav_bytes, reset_stt, transcribe,
                             transcribe_result)


def _pcm(seconds=1.0, sr=16000, amp=0.35, freq=220.0, seed=0):
    """Loud-ish voiced-like tone: comfortably above the silence floor so it
    takes the cloud path (VAD has already filtered real segments)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    x = 0.6 * np.sin(2 * np.pi * freq * t) + 0.4 * rng.standard_normal(len(t)).astype(np.float32)
    x = (np.clip(x, -1, 1) * amp * 32767).astype("<i2")
    return x.tobytes()


@pytest.fixture(autouse=True)
def _stub_router_transcribe(monkeypatch):
    """Default stub: records calls, answers a canned transcript."""
    calls = []

    def fake(audio, language=None, **kw):
        calls.append({"audio": audio, "language": language})
        return {"text": "open youtube", "rtf": 0.25, "provider": "groq"}

    monkeypatch.setattr(router, "transcribe", fake, raising=False)
    reset_stt()
    yield calls
    reset_stt()


# ---- container / silence helpers -------------------------------------------
def test_pcm_to_wav_is_valid_wav():
    pcm = _pcm(seconds=0.5)
    wav = pcm_to_wav_bytes(pcm, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    with wave.open(__import__("io").BytesIO(wav), "rb") as w:
        assert w.getnchannels() == 1 and w.getframerate() == 16000
        assert w.getsampwidth() == 2
        assert w.readframes(w.getnframes()) == pcm


def test_silence_is_local_not_cloud():
    assert is_effectively_silent(b"", 16000)
    assert is_effectively_silent(b"\x00\x00" * 8000, 16000)      # 0.5 s digital silence
    assert not is_effectively_silent(_pcm(seconds=0.5), 16000)
    # sub-minimum duration is refused even when loud
    loud_short = _pcm(seconds=0.05, amp=0.9)
    assert is_effectively_silent(loud_short, 16000)


# ---- cloud path -------------------------------------------------------------
def test_cloud_transcribe_routes_through_router(_stub_router_transcribe):
    cfg = VoiceConfig(profile="cloud_temp")
    res = CloudTranscriber(cfg).transcribe(_pcm(seconds=1.2), 16000)
    assert res.text == "open youtube"
    assert res.rtf == 0.25
    assert res.duration_s == pytest.approx(1.2, abs=0.01)
    assert len(_stub_router_transcribe) == 1
    sent = _stub_router_transcribe[0]
    assert sent["audio"][:4] == b"RIFF"          # WAV on the wire, not bare PCM
    assert sent["language"] is None               # auto-detect default


def test_cloud_transcribe_passes_language(_stub_router_transcribe):
    cfg = VoiceConfig(profile="cloud_temp", stt_language="en")
    CloudTranscriber(cfg).transcribe(_pcm(), 16000)
    assert _stub_router_transcribe[-1]["language"] == "en"


def test_silence_returns_empty_without_router_call(_stub_router_transcribe):
    cfg = VoiceConfig(profile="cloud_temp")
    res = CloudTranscriber(cfg).transcribe(b"\x00\x00" * 16000, 16000)
    assert res.text == "" and res.duration_s > 0
    assert _stub_router_transcribe == []          # never left the machine


def test_router_missing_transcribe_is_typed(monkeypatch):
    monkeypatch.delattr(router, "transcribe", raising=False)
    with pytest.raises(VoiceSTTError) as ei:
        CloudTranscriber(VoiceConfig()).transcribe(_pcm(), 16000)
    assert ei.value.code == "E_INTERNAL"
    assert "INTERFACES" in ei.value.detail


def test_router_errors_map_to_protocol_codes(monkeypatch):
    class ProviderError(Exception):
        def __init__(self, code):
            super().__init__(f"boom {code}")
            self.code = code

    monkeypatch.setattr(router, "transcribe",
                        lambda *a, **k: (_ for _ in ()).throw(
                            ProviderError("E_PROVIDER_429")), raising=False)
    with pytest.raises(VoiceSTTError) as ei:
        CloudTranscriber(VoiceConfig()).transcribe(_pcm(), 16000)
    assert ei.value.code == "E_PROVIDER_429"

    monkeypatch.setattr(router, "transcribe",
                        lambda *a, **k: (_ for _ in ()).throw(
                            ConnectionError("no route to host")), raising=False)
    with pytest.raises(VoiceSTTError) as ei:
        CloudTranscriber(VoiceConfig()).transcribe(_pcm(), 16000)
    assert ei.value.code == "E_OFFLINE"

    monkeypatch.setattr(router, "transcribe",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("HTTP 401 unauthorized")), raising=False)
    with pytest.raises(VoiceSTTError) as ei:
        CloudTranscriber(VoiceConfig()).transcribe(_pcm(), 16000)
    assert ei.value.code == "E_PROVIDER_AUTH"


def test_dict_result_without_rtf_computes_it(monkeypatch, _stub_router_transcribe):
    def no_rtf(audio, language=None, **kw):
        _stub_router_transcribe.append({"audio": audio, "language": language})
        return {"text": "hello there"}

    monkeypatch.setattr(router, "transcribe", no_rtf, raising=False)

    # deterministic wall clock instead of the real one: exactly 0.25 s elapses
    # between the two perf_counter() readings (no timing flake possible)
    class _Clock:
        def __init__(self):
            self.t = 100.0

        def perf_counter(self):
            self.t += 0.25
            return self.t

    monkeypatch.setattr("brain.voice.stt.time", _Clock())
    res = CloudTranscriber(VoiceConfig()).transcribe(_pcm(seconds=1.0), 16000)
    assert res.text == "hello there"
    assert res.rtf == pytest.approx(0.25)      # derived from the stubbed clock


# ---- profile gate: no local model under cloud_temp --------------------------
def test_cloud_temp_never_touches_faster_whisper(monkeypatch):
    already_imported = "faster_whisper" in sys.modules
    cfg = VoiceConfig(profile="cloud_temp", stt_engine="local")  # config asks local
    eng = SttEngine(cfg)
    assert eng.kind == "groq"                     # profile wins

    def boom(*_a, **_k):
        raise AssertionError("local faster-whisper touched under cloud_temp")

    monkeypatch.setattr(Transcriber, "transcribe", boom)
    monkeypatch.setattr(Transcriber, "load", boom)
    res = eng.transcribe(_pcm(), 16000)
    assert res.text == "open youtube"
    assert eng._local is None                     # never even constructed
    with pytest.raises(VoiceSTTError) as ei:
        _ = eng.local                             # guarded accessor
    assert ei.value.code == "E_LOCAL_DOWN"


def test_profile_local_selects_faster_whisper(monkeypatch):
    cfg = VoiceConfig(profile="local", stt_engine="local")
    eng = SttEngine(cfg)
    assert eng.kind == "local"
    local = eng.local                             # lazy Transcriber (no load yet)
    assert isinstance(local, Transcriber)
    assert eng._cloud is None


def test_module_level_transcribe_uses_selected_engine(_stub_router_transcribe):
    text = transcribe(_pcm(seconds=0.8), cfg=VoiceConfig(profile="cloud_temp"))
    assert text == "open youtube"
    res = transcribe_result(_pcm(seconds=0.8), cfg=VoiceConfig(profile="cloud_temp"))
    assert res.text == "open youtube"
