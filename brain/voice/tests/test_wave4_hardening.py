"""Wave 4 — voice pipeline failure modes + Bug H regression guards.

  A. fish death mid-speak: ONE restart + retry (ownership-safe: never kills an
     externally managed server), one-time notice on success, loud degraded
     notice on failure; reference errors are NEVER retried.
  B. STT outage: a cloud-STT failure yields a subtitle notice (PROTOCOL §10
     code set) instead of a silent drop of what the user just said.
  C. audio soak: accelerated continuity run (stand-in for 24h segment flow) —
     every subsystem's state must stay BOUNDED after many segments.
  D. Bug H regression guards: async router transcribe is awaited (typed error
     inside a running loop), stt_language is pinned from config and reaches
     the provider, wake extract strips ALL leading wake/filler repeats.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import sys
import types
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# stub sounddevice before the body modules import it (no device, no pip)
if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

import brain.router as router  # noqa: E402
from brain.voice import (SUBTITLE_CODES, VoiceConfig, VoiceSTTError,  # noqa: E402
                         VoiceStack, WakeGate, get_playback_echoes,
                         load_voice_config, reset_activation, reset_stt,
                         stt_outage_subtitle)
from brain.voice.stt import CloudTranscriber  # noqa: E402
from brain.voice.tts import TTSEngine, TTSError  # noqa: E402
from body.win import audio_in  # noqa: E402

SR = 16000


def _loud_pcm(ms=400, rms=2500, freq=220.0, sr=SR):
    n = int(sr * ms / 1000)
    t = np.arange(n, dtype=np.float64) / sr
    a = min(32000.0, rms * np.sqrt(2.0))
    return (a * np.sin(2 * np.pi * freq * t)).astype("<i2").tobytes()


def _tone_wav(ms=400, sr=32000, freq=300.0):
    """A real wav (decoder rate), as fish would return it."""
    pytest.importorskip("soundfile")
    import io

    import soundfile as sf

    n = int(sr * ms / 1000)
    t = np.arange(n, dtype=np.float32) / sr
    buf = io.BytesIO()
    sf.write(buf, (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32),
             sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


async def _drain(aiter):
    return [e async for e in aiter]


@pytest.fixture(autouse=True)
def _fresh():
    reset_stt()
    reset_activation()
    yield
    reset_stt()
    reset_activation()


class _FakeFish:
    """Controllable fake fish: fails according to a plan, counts calls.

    ensure_fail_on = N -> ensure_started raises from its Nth call onwards
    (call 1 = the speak precheck, call 2 = the mid-speak recovery attempt).
    """

    def __init__(self, fail_first_n=0, fail_forever=False, ensure_fail_on=None):
        self.fail_first_n = fail_first_n
        self.fail_forever = fail_forever
        self.ensure_fail_on = ensure_fail_on
        self.synth_calls = 0
        self.ensure_calls = 0
        self.stop_calls = 0
        self.last_error = None
        self.proc = None                # None = externally managed / not ours

    async def ensure_started(self, timeout_s=240.0):
        self.ensure_calls += 1
        if self.ensure_fail_on is not None and \
                self.ensure_calls >= self.ensure_fail_on:
            raise TTSError("E_TIMEOUT", "fish server not healthy in 90s")

    async def synthesize(self, text):
        self.synth_calls += 1
        if self.fail_forever or self.synth_calls <= self.fail_first_n:
            raise TTSError("E_LOCAL_DOWN", "connection reset (fish died)")
        return _tone_wav()

    def stop(self):
        self.stop_calls += 1

    def check_reference(self):
        """Tests control reference validity via the engine's cfg; the fake
        server's job here is only liveness/restart behaviour."""
        return Path("/nonexistent-ref-checked-by-test")


def _engine(tmp_path, fish, ref_bytes=b"JP_REF_BYTES"):
    cfg = VoiceConfig(ack_cache=str(tmp_path / "acks"),
                      tts_voice=str(tmp_path / "ref.wav"))
    Path(cfg.tts_voice).write_bytes(ref_bytes)
    eng = TTSEngine(cfg)
    eng.fish = fish                  # replace the real server with the fake
    return eng


# ---- A. fish death mid-speak recovery --------------------------------------
def test_fish_death_mid_speak_restarts_once_and_streams_on(tmp_path, capsys):
    fish = _FakeFish(fail_first_n=1)          # dies on the 1st sentence
    eng = _engine(tmp_path, fish)
    events = asyncio.run(_drain(eng.speak("Task complete. Executing now.",
                                          job="j_rec")))
    chunks = [e for e in events if e["event"] == "chunk"]
    assert chunks, "recovery must keep the reply streaming"
    assert fish.ensure_calls == 2              # precheck + ONE restart, no more
    assert fish.stop_calls == 0                # externally managed -> untouched
    end = events[-1]
    assert end["event"] == "end"
    assert end.get("notice") == "Voice engine restarted mid-reply."
    out = capsys.readouterr().out
    assert "fish recovery OK" in out
    # one-time: a second utterance does not repeat the notice
    events2 = asyncio.run(_drain(eng.speak("Analysis complete.", job="j_rec2")))
    assert events2[-1].get("notice") is None


def test_fish_death_recovery_gives_up_loudly(tmp_path, capsys):
    # precheck (call 1) succeeds, synthesis dies, recovery (call 2) fails
    fish = _FakeFish(fail_forever=True, ensure_fail_on=2)
    eng = _engine(tmp_path, fish)
    events = asyncio.run(_drain(eng.speak("Task complete.", job="j_dead")))
    assert not [e for e in events if e["event"] == "chunk"], \
        "no default/fake audio when the engine is truly down"
    end = events[-1]
    assert "TTS engine error" in (end.get("notice") or "")
    assert fish.ensure_calls == 2              # precheck + ONE recovery
    out = capsys.readouterr().out
    assert "fish recovery FAILED" in out


def test_reference_error_is_never_retried(tmp_path):
    """Bug D stays stronger than recovery: a missing reference fails loud
    immediately — a restart cannot fix it."""
    fish = _FakeFish()
    eng = _engine(tmp_path, fish)

    async def _synth_ref_error(text):
        fish.synth_calls += 1
        raise TTSError("E_INTERNAL",
                       f"voice reference MISSING: {eng.cfg.tts_voice}")
    fish.synthesize = _synth_ref_error

    events = asyncio.run(_drain(eng.speak("Task complete.", job="j_ref")))
    assert not [e for e in events if e["event"] == "chunk"]
    assert fish.ensure_calls == 1              # ONLY the precheck, no restart
    assert "reference" in (events[-1].get("notice") or "").lower()


# ---- B. STT outage -> subtitle notice, never silent ------------------------
def test_stt_outage_subtitle_is_surfaceable_codes_only():
    sub = stt_outage_subtitle("E_PROVIDER_429", "router rate limited")
    assert sub and "E_PROVIDER_429" in sub and len(sub) <= 160
    assert "router rate limited" not in sub      # raw detail never reaches screen
    for code in ("E_OFFLINE", "E_TIMEOUT", "E_LOCAL_DOWN", "E_LOCAL_OOM",
                 "E_LOCK_BUSY", "E_CONFIRM_TIMEOUT"):
        assert code in SUBTITLE_CODES
        assert stt_outage_subtitle(code, "secret-ish detail") is not None
    # fatal/internal codes show NO detail at all
    assert stt_outage_subtitle("E_INTERNAL", "boom") is None
    assert stt_outage_subtitle("E_AUTH", "token abc") is None


def test_stt_failure_yields_subtitle_instead_of_silence(monkeypatch):
    def _boom(audio, language=None, **kw):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(router, "transcribe", _boom, raising=False)
    with pytest.raises(VoiceSTTError) as ei:
        CloudTranscriber(VoiceConfig(profile="cloud_temp")).transcribe(
            _loud_pcm(), 16000)
    assert ei.value.code == "E_OFFLINE"
    sub = stt_outage_subtitle(ei.value.code, ei.value.detail)
    assert sub and "type it instead" in sub      # ws.py can subtitle THIS


# ---- C. audio soak (accelerated continuity) --------------------------------
def test_soak_brain_segment_flow_stays_bounded(tmp_path, monkeypatch):
    """Stand-in for the 24h segment-continuity soak: N sequential segments
    through pre-gate -> cloud STT (stub) -> wake gate -> interrupt bookkeeping.
    Everything must stay BOUNDED (nothing grows without limit)."""
    monkeypatch.setattr(router, "transcribe",
                        lambda audio, language=None, **kw: {
                            "text": "Raphael, status report", "rtf": 0.1},
                        raising=False)
    voice = VoiceStack(VoiceConfig(profile="cloud_temp",
                                   ack_cache=str(tmp_path / "acks")))
    segment = _loud_pcm(ms=600)
    echoes = get_playback_echoes()
    N = 1000
    for i in range(N):
        buf = bytearray(segment)              # ws.py accumulates kind=1 frames
        chunk = bytes(buf)
        buf.clear()                           # audio_end clears the buffer
        assert len(buf) == 0
        assert voice.should_transcribe(chunk, reason="wake")
        res = voice.transcribe_result(chunk, reason="wake")
        assert res.text == "Raphael, status report"
        match = voice.wake.gate(res.text, reason="wake")
        assert match.kind == "wake" and match.command == "status report"
        # loop.py narration bookkeeping per job — register/done must balance
        voice.interrupts.register(f"job_{i}")
        voice.interrupts.done(f"job_{i}")
        if i % 10 == 0:
            echoes.remember(f"reply sentence number {i}")     # her speech
    # --- boundedness after N segments -----------------------------------
    assert voice.interrupts.any_active() is False
    assert voice.interrupts._events == {}            # no leaked cancel events
    assert len(echoes.recent()) <= 8                 # deque is capped


def test_soak_vad_segmenter_state_stays_bounded():
    """Body-side continuity: hundreds of open/close cycles must not grow VAD
    state (pre-roll, evidence window, open flag all bounded)."""
    vad = audio_in.VadSegmenter()
    vad.noise = 20
    speech = _loud_pcm(ms=100)
    quiet = b"\x00\x00" * 1600                     # 100 ms silence
    opens = closes = 0
    for _ in range(400):                            # 400 utterances
        for _ in range(4):                          # enough hits to open
            for kind, _d in vad.feed(speech):
                if kind == "start":
                    opens += 1
        for _ in range(30):                         # > SILENCE_CLOSE chunks
            for kind, _d in vad.feed(quiet):
                if kind == "end":
                    closes += 1
    assert opens == closes and opens >= 100         # every segment closed
    assert len(vad._pre) <= 3                       # pre-roll bounded
    assert len(vad._hits) <= 5                      # evidence window bounded
    assert vad.open is False                        # ends idle, no stuck segment


# ---- D. Bug H regression guards -------------------------------------------
def test_bug_h_async_router_transcribe_is_awaited(monkeypatch):
    async def _fake_async(audio, language=None, **kw):
        return {"text": "hello from async router", "rtf": 0.1}

    monkeypatch.setattr(router, "transcribe", _fake_async, raising=False)
    # to_thread semantics: no running loop in this thread -> asyncio.run bridge
    res = CloudTranscriber(VoiceConfig(profile="cloud_temp")).transcribe(
        _loud_pcm(), 16000)
    assert res.text == "hello from async router"

    # inside a running loop it must fail TYPED (callers must use to_thread)
    async def _in_loop():
        return CloudTranscriber(VoiceConfig(profile="cloud_temp")).transcribe(
            _loud_pcm(), 16000)

    with pytest.raises(VoiceSTTError) as ei:
        asyncio.run(_in_loop())
    assert ei.value.code == "E_INTERNAL" and "to_thread" in ei.value.detail


def test_bug_h_stt_language_pinned_and_reaches_provider(monkeypatch):
    monkeypatch.delenv("RAPHAEL_PROFILE", raising=False)
    cfg = load_voice_config(_REPO / "config.yaml")
    assert cfg.stt_language == "en", \
        "stt_language must be loaded (BUG H: key parsed but never wired)"
    seen = []

    def _rec(audio, language=None, **kw):
        seen.append(language)
        return {"text": "ok", "rtf": 0.1}

    monkeypatch.setattr(router, "transcribe", _rec, raising=False)
    CloudTranscriber(cfg).transcribe(_loud_pcm(), 16000)
    assert seen == ["en"], "the pinned language must reach the provider call"


def test_bug_h_wake_extract_strips_all_leading_repeats():
    g = WakeGate("raphael")
    assert g.extract("Raphael raphael what time is it") == "what time is it"
    assert g.extract("hey um raphael open youtube") == "open youtube"
    assert g.extract("raphael") == ""
    m = g.gate("Raphael raphael, open YouTube", reason="wake")
    assert m.kind == "wake" and m.command == "open youtube"
