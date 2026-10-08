"""SEC-3 tripwire (Wave 5H audit gate exit criterion) — pre-STT gate must be
FAIL-CLOSED: no cloud upload without an explicit wake/ptt verdict.

Quotes fixed in this pass (see docs/status/voice.md):
  - brain/voice/activation.py `return GateDecision(True, reason or "unknown")`
  - brain/voice/activation.py `return GateDecision(True, "error_fail_open")`

Chain under test (the audit's three quotes):
  brain/ws.py audio_end -> voice.transcribe_result(buf, reason=reason)
  -> VoiceStack.transcribe_result (brain/voice/__init__.py)
  -> ActivationGate.should_transcribe (brain/voice/activation.py)
  -> SttEngine/CloudTranscriber (brain/voice/stt.py)  [must NOT be reached]

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import sys
import types
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

import brain.router as router  # noqa: E402
from brain.voice import VoiceConfig, VoiceStack, reset_activation  # noqa: E402
from brain.voice import activation as activation_mod  # noqa: E402
from brain.voice.stt import reset_stt  # noqa: E402

SR = 16000


def _loud(ms=400, rms=2500):
    n = int(SR * ms / 1000)
    t = np.arange(n, dtype=np.float64) / SR
    a = min(32000.0, rms * np.sqrt(2.0))
    return (a * np.sin(2 * np.pi * 220.0 * t)).astype("<i2").tobytes()


class _Recorder:
    def __init__(self):
        self.calls = 0

    def __call__(self, audio, language=None, **kw):
        self.calls += 1
        return {"text": "should never happen", "rtf": 0.1}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    reset_stt()
    reset_activation()
    rec = _Recorder()
    monkeypatch.setattr(router, "transcribe", rec, raising=False)
    yield rec
    reset_stt()
    reset_activation()


def _stack(tmp_path):
    return VoiceStack(VoiceConfig(profile="cloud_temp",
                                  ack_cache=str(tmp_path / "acks")))


def test_tripwire_undecided_reason_never_reaches_provider(tmp_path, _fresh):
    """THE SEC-3 exit criterion: loud, non-silent audio with NO wake/ptt
    verdict is discarded locally — the provider is never called and nothing
    is written to disk."""
    voice = _stack(tmp_path)
    for reason in (None, "", "bogus", "unknown_reason", 42):
        res = voice.transcribe_result(_loud(), reason=reason)
        assert res.text == "", f"reason={reason!r} must yield no transcript"
    assert _fresh.calls == 0, "provider was called without a verdict"
    # nothing written: ack cache holds no FILE (the empty ref-namespace dir
    # is created eagerly at engine init — no segment data ever lands there)
    ack = tmp_path / "acks"
    files = [p for p in ack.rglob("*") if p.is_file()] if ack.exists() else []
    assert files == [], f"undecided audio must not touch disk: {files}"


def test_tripwire_gate_exception_fails_closed(tmp_path, _fresh, monkeypatch):
    """The old `except Exception -> GateDecision(True, "error_fail_open")`
    branch: a broken gate must DISCARD, not upload."""
    def _boom(*_a, **_k):
        raise RuntimeError("synthetic gate failure")

    monkeypatch.setattr(activation_mod, "is_effectively_silent", _boom)
    voice = _stack(tmp_path)
    decision = voice.should_transcribe(_loud(), reason="wake")
    assert not decision.ok and decision.reason == "error_fail_closed"
    res = voice.transcribe_result(_loud(), reason="wake")
    assert res.text == ""
    assert _fresh.calls == 0


def test_ptt_and_wake_verdicts_still_work(tmp_path, _fresh):
    """Fail-closed must not break the two legitimate verdicts (packet:
    'PTT/wake keep working')."""
    voice = _stack(tmp_path)
    for reason in ("ptt", "wake"):
        decision = voice.should_transcribe(_loud(), reason=reason)
        assert decision.ok and decision.reason == reason
        res = voice.transcribe_result(_loud(), reason=reason)
        assert res.text == "should never happen"   # provider reached
    assert _fresh.calls == 2


def test_ptt_only_profile_still_drops_wake(tmp_path, _fresh):
    voice = VoiceStack(VoiceConfig(profile="cloud_temp",
                                   always_listen=False,
                                   ack_cache=str(tmp_path / "acks")))
    res = voice.transcribe_result(_loud(), reason="wake")
    assert res.text == "" and _fresh.calls == 0


def test_silence_still_short_circuits_before_verdict(tmp_path, _fresh):
    """Silence is dropped regardless of reason (cheapest path, unchanged)."""
    voice = _stack(tmp_path)
    res = voice.transcribe_result(b"\x00\x00" * SR, reason="wake")
    assert res.text == "" and _fresh.calls == 0
    d = voice.should_transcribe(b"\x00\x00" * SR, reason=None)
    assert not d.ok and d.reason == "silence"
