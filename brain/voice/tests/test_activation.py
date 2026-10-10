"""Wave 2 task 2 — activation: which segments reach cloud STT (pre-gate),
which transcripts count as commands (phonetic wake gate), and how Raphael's
own playback is kept from re-triggering her (echo guard + echo registry).

Body-side pieces (audio_in/audio_out) are imported with a stubbed
`sounddevice` so no audio device and no pip install is needed (AGENT_RULES §5:
lanes never open the real microphone).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# stub sounddevice BEFORE the body modules import it (no device, no pip)
if "sounddevice" not in sys.modules:
    import types
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

from brain.voice import VoiceConfig  # noqa: E402
from brain.voice.activation import (ActivationGate, GateDecision,  # noqa: E402
                                    PlaybackEchoRegistry, reset_activation)
from brain.voice.wake import WakeGate  # noqa: E402
from body.win import audio_in, audio_out  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    reset_activation()
    yield
    reset_activation()


def _pcm(rms, ms=100, sr=16000, freq=200.0):
    """PCM chunk with the given int16 RMS (sine: amplitude = rms * sqrt(2))."""
    n = int(sr * ms / 1000)
    t = np.arange(n, dtype=np.float64) / sr
    a = min(32000.0, rms * math.sqrt(2.0))
    return (a * np.sin(2 * math.pi * freq * t)).astype("<i2").tobytes()


LOUD = 2500        # measured real user speech at the mic (2000+)
PLAYBACK = 200     # measured her-speaker bleed at the mic (40-225)


# ---- 1. pre-STT gate -------------------------------------------------------
def test_pre_gate_silence_never_reaches_cloud():
    g = ActivationGate(VoiceConfig())
    d = g.should_transcribe(b"\x00\x00" * 16000, reason="wake")
    assert not d.ok and d.reason == "silence"


def test_pre_gate_ptt_always_allowed():
    g = ActivationGate(VoiceConfig(always_listen=False))
    d = g.should_transcribe(_pcm(LOUD, ms=300), reason="ptt")
    assert d.ok and d.reason == "ptt"


def test_pre_gate_ptt_only_mode_drops_wake_segments():
    g = ActivationGate(VoiceConfig(always_listen=False))
    assert not g.should_transcribe(_pcm(LOUD, ms=300), reason="wake")
    # SEC-3 (Wave 5H): undecided reason -> FAIL CLOSED (no upload without a
    # wake/ptt verdict); the old behavior returned ok=True ("fail open")
    d = g.should_transcribe(_pcm(LOUD, ms=300), reason=None)
    assert not d.ok and d.reason.startswith("undecided")


def test_pre_gate_decision_is_truthy():
    assert bool(GateDecision(True, "ptt")) is True
    assert bool(GateDecision(False, "silence")) is False


def test_pre_gate_never_raises():
    g = ActivationGate(VoiceConfig())
    assert g.should_transcribe(b"\x01", reason="wake") is not None
    assert g.should_transcribe(None, reason="wake") is not None  # type: ignore


# ---- 2. playback echo registry (self-trigger loop prevention) --------------
def test_echo_registry_rejects_her_own_playback():
    reg = PlaybackEchoRegistry()
    reg.remember("Raphael online. Recovered from an unexpected shutdown — "
                 "interrupted tasks are listed.")
    # the mic picks her greeting up -> must NOT count as a wake command
    assert reg.is_echo("Raphael online recovered from an unexpected shutdown "
                       "interrupted tasks are listed")
    assert reg.is_echo("online recovered from an unexpected shutdown "
                       "interrupted tasks")           # partial playback
    assert not reg.is_echo("open youtube and search lo-fi")   # user's own words
    assert not reg.is_echo("yes")                      # short answers pass through
    assert not reg.is_echo("no thanks")                 # (<=2 words never echo)


def test_echo_registry_fuzzy_asr_variants():
    reg = PlaybackEchoRegistry()
    reg.remember("Analysis complete. The file was moved to the downloads folder.")
    # ASR noise: dropped words + typo-ish spelling still matches
    assert reg.is_echo("analysis complete the file was moved to the downloads folder")
    assert reg.is_echo("analysis complet the file moved to the downloads folder")


def test_echo_registry_ttl_and_bounding():
    reg = PlaybackEchoRegistry(maxlen=2)
    reg.remember("one two three four five six")
    reg.remember("seven eight nine ten eleven twelve")
    reg.remember("thirteen fourteen fifteen sixteen seventeen")   # evicts #1
    assert len(reg.recent()) <= 2
    reg.clear()
    assert reg.recent() == []


# ---- 3. phonetic wake gate + echo rejection (what ws.py calls) -------------
def test_activation_gate_is_the_wake_gate_plus_echo():
    g = ActivationGate(VoiceConfig())
    # normal wake command passes (filler + ASR spelling variance tolerated)
    m = g.gate("Raphael, open YouTube", reason="wake")
    assert m.kind == "wake" and m.command == "open youtube"
    m = g.gate("Rafael, what time is it", reason="wake")
    assert m.kind == "wake" and m.command == "what time is it"
    # no wake word -> ignored (unchanged behavior)
    assert g.gate("open youtube", reason="wake").kind == "none"
    assert g.gate("open youtube", reason="ptt").kind == "ptt"
    # ... but her own playback is rejected even though it starts with "Raphael"
    g.echoes.remember("Raphael online. Everything is running normally.")
    assert g.gate("Raphael online everything is running normally",
                  reason="wake").kind == "none"


def test_activation_gate_delegates_wake_gate_api():
    g = ActivationGate(VoiceConfig())
    assert g.matches_wake("hey raphael hello") is True      # duck-typed
    assert g.extract("hey raphael hello") == "hello"


# ---- 4. body-side echo guard (audio_in / audio_out) ------------------------
def _events_for(vad, rms, chunks=6, echo_guard=None):
    if echo_guard is not None:
        vad.echo_guard = echo_guard
    seen = []
    for _ in range(chunks):
        seen.extend(e[0] for e in vad.feed(_pcm(rms)))
    return seen


def test_vad_opens_on_her_playback_without_guard():
    """Baseline (live-tested behavior): playback-level audio CAN open a
    segment when the speaker is silent — that is what the wake chain relies on."""
    vad = audio_in.VadSegmenter()
    vad.noise = 20                     # measured quiet room
    kinds = _events_for(vad, PLAYBACK, echo_guard=False)
    assert "start" in kinds


def test_vad_echo_guard_blocks_her_playback_but_not_user_speech():
    vad = audio_in.VadSegmenter()
    vad.noise = 20
    # she is speaking: her bleed never opens a segment ...
    kinds = _events_for(vad, PLAYBACK, echo_guard=True)
    assert "start" not in kinds
    # ... but the user talking over her still does (barge-in keeps working)
    kinds = _events_for(vad, LOUD, echo_guard=True)
    assert "start" in kinds


def test_vad_echo_guard_does_not_change_open_segment_hysteresis():
    """Guard applies to OPENING only (rule: no threshold tuning on the
    live-tested open-segment path)."""
    vad = audio_in.VadSegmenter()
    vad.noise = 20
    vad.echo_guard = True
    opened = False
    for _ in range(6):                     # user speech opens it
        if any(e[0] == "start" for e in vad.feed(_pcm(LOUD))):
            opened = True
    assert opened and vad.open is True
    # while open, an ordinary (below-threshold) tail chunk is still forwarded
    tail = vad.feed(_pcm(60))
    assert any(e[0] == "speech" for e in tail)


def test_wake_stream_reads_playback_state(monkeypatch):
    """WakeStream consults audio_out.PLAYER for the guard signal."""
    class FakePlayer:
        def __init__(self, active):
            self._a = active
        def active(self):
            return self._a

    monkeypatch.setattr(audio_out, "PLAYER", FakePlayer(True))
    assert audio_in.WakeStream._playback_active() is True
    monkeypatch.setattr(audio_out, "PLAYER", FakePlayer(False))
    assert audio_in.WakeStream._playback_active() is False


def test_stream_player_active_flag():
    p = audio_out.StreamPlayer()
    assert p.active() is False
    p._buf += b"\x00\x00" * 4800        # 0.2 s buffered, stream not open yet
    assert p.active() is False          # nothing audible yet
    p._stream = object()                # pretend the device is open
    p._playing = True
    assert p.active() is True
    p.reset()                           # speak start -> leftovers dropped
    assert p.active() is False


# ---- Cut A body half: deferred audio_end + continuation (2026-10-08) -------
def test_end_grace_fires_exactly_after_grace():
    from body.win.audio_in import EndGrace
    g = EndGrace(13)
    g.vad_end()                                # candidate close -> hold
    fired = [g.tick() for _ in range(12)]
    assert fired == [False] * 12               # never fires early
    assert g.tick() is True                    # 13th tick = grace expiry
    assert g.tick() is False                   # one shot


def test_end_grace_resume_becomes_continuation():
    from body.win.audio_in import EndGrace
    g = EndGrace(13)
    g.vad_end()
    g.tick(); g.tick()
    assert g.vad_start() is True               # resume inside window
    assert g.tick() is False                   # hold cancelled: NO audio_end
    # a later, genuine resume after expiry is a FRESH wake segment
    assert g.vad_start() is False


def test_end_grace_without_hold_is_plain_wake():
    from body.win.audio_in import EndGrace
    g = EndGrace(13)
    assert g.vad_start() is False              # no held end -> fresh wake
    assert g.tick() is False                   # nothing to fire


def test_close_and_grace_are_config_driven_and_sum_to_the_old_slot():
    """P0-URGENT (coord inbox 47): close/grace are config-driven (env), so
    the old 12+13==25 invariant becomes PER-CONFIG: whatever the two resolve
    to, close+grace is what bounds worst-case end latency. Main default is
    now close=12, grace=8 (0.8s hold, trims perceived latency ~0.5-0.7s).
    An explicit override reconstructs the old 12+13==25 slot exactly."""
    from body.win.audio_in import VadSegmenter
    # config-driven defaults: close=12, grace=8 (was 13)
    assert VadSegmenter.SILENCE_CLOSE == 12
    assert VadSegmenter.CONTINUATION_GRACE == 8
    # per-config invariant: close+grace is the worst-case end-latency bound
    v_default = VadSegmenter()
    assert (v_default.SILENCE_CLOSE + v_default.CONTINUATION_GRACE) == 20
    # an explicit override reconstructs the ORIGINAL 25-chunk (2.5s) slot
    v_old = VadSegmenter(silence_close=12, continuation_grace=13)
    assert v_old.SILENCE_CLOSE + v_old.CONTINUATION_GRACE == 25


def test_continuation_grace_env_override(monkeypatch):
    """RAPHAEL_CONTINUATION_GRACE / RAPHAEL_SILENCE_CLOSE are honored; out of
    range / non-integer FAIL-CLOSED to the default (a typo must never deafen
    the mic or split every clause)."""
    from body.win import audio_in

    monkeypatch.setenv("RAPHAEL_CONTINUATION_GRACE", "13")
    monkeypatch.setenv("RAPHAEL_SILENCE_CLOSE", "12")
    import importlib
    importlib.reload(audio_in)
    try:
        assert audio_in.VadSegmenter.CONTINUATION_GRACE == 13
        assert audio_in.VadSegmenter.SILENCE_CLOSE == 12
        # out-of-range clamps into [1,100]
        monkeypatch.setenv("RAPHAEL_CONTINUATION_GRACE", "9999")
        importlib.reload(audio_in)
        assert audio_in.VadSegmenter.CONTINUATION_GRACE == 100
        # non-integer fails closed to the default (8)
        monkeypatch.setenv("RAPHAEL_CONTINUATION_GRACE", "not-a-number")
        importlib.reload(audio_in)
        assert audio_in.VadSegmenter.CONTINUATION_GRACE == 8
    finally:
        monkeypatch.delenv("RAPHAEL_CONTINUATION_GRACE", raising=False)
        monkeypatch.delenv("RAPHAEL_SILENCE_CLOSE", raising=False)
        importlib.reload(audio_in)   # restore production defaults


def test_wak_stream_wires_continuation_path():
    """Source-level wiring (device loop is not unit-testable): the wake
    stream holds its end, sends reason='continuation' on resume, and only
    fires audio_end via the grace tick."""
    src = (_REPO / "body/win/audio_in.py").read_text()
    assert 'dict(self._start_dict, reason="continuation")' in src
    assert "grace.vad_start()" in src and "grace.tick()" in src
    assert "grace.vad_end()" in src
    # on_end must only be reachable through the grace path in WakeStream.run
    run_src = src.split("async def run(")[1]
    assert run_src.count("await self.on_end()") == 1
    assert "grace.tick()" in run_src.split("await self.on_end()")[0]


def test_wake_stream_has_continuation_grace_constant():
    """Wake-loop regression (integrator glue 2026-10-09, coord inbox 46).

    The Cut A run loop reads `self.CONTINUATION_GRACE`, which originally
    lived only on VadSegmenter. WakeStream therefore raised
    AttributeError('WakeStream' object has no attribute 'CONTINUATION_GRACE')
    the moment run() reached `EndGrace(self.CONTINUATION_GRACE)`, killing the
    wake task at startup and leaving the mic DEAF (user-reported live bug).
    The source-level wiring test above missed it because it never constructs
    the object. Pin BOTH the shared constant and the live reference."""
    from body.win.audio_in import VadSegmenter, WakeStream
    # single source of truth: WakeStream mirrors VadSegmenter's grace
    assert WakeStream.CONTINUATION_GRACE == VadSegmenter.CONTINUATION_GRACE
    # the run-loop expression must resolve on a REAL instance (this is the
    # exact line whose AttributeError deafened the mic); the instance grace
    # mirrors its vad (P0: config-driven, default 8)
    ws = WakeStream(on_frame=lambda m: None,
                    on_start=lambda d: None, on_end=lambda: None)
    assert ws.CONTINUATION_GRACE == VadSegmenter.CONTINUATION_GRACE
    assert ws.CONTINUATION_GRACE == ws.vad.CONTINUATION_GRACE


def test_wake_stream_run_builds_endgrace_without_attribute_error(monkeypatch):
    """Drive the top of WakeStream.run() for ONE loop iteration with a
    stubbed sounddevice InputStream — the earliest point the production
    `EndGrace(self.CONTINUATION_GRACE)` expression is evaluated. Before the
    glue fix this raised AttributeError (mic deaf); now it must construct
    the grace machine and process the fed chunk normally. The stream is fed
    one silent chunk then _stop flips so run() exits cleanly."""
    import asyncio
    import types as _t
    from body.win.audio_in import WakeStream

    constructed = {}
    real_grace = audio_in.EndGrace

    def _spy(grace_chunks):
        constructed["grace"] = grace_chunks
        return real_grace(grace_chunks)

    monkeypatch.setattr(audio_in, "EndGrace", _spy)

    class _FakeStream:
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    fake_sd = _t.ModuleType("sounddevice")
    fake_sd.InputStream = lambda **kw: _FakeStream()
    fake_sd.query_devices = lambda kind=None: {"name": "stub-mic"}
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(audio_in, "sd", fake_sd)

    events = {"start": [], "frame": [], "end": []}
    ws = WakeStream(
        on_frame=lambda m: events["frame"].append(m),
        on_start=lambda d: events["start"].append(d),
        on_end=lambda: events["end"].append(True))

    async def _drive():
        task = asyncio.create_task(ws.run())
        await asyncio.sleep(0)                 # let run() reach the queue
        ws.vad.feed(b"\x00\x00" * 1600)        # pre-prime a silent chunk
        ws._queue.put_nowait(b"\x00\x00" * 1600)  # one 100ms silent frame
        await asyncio.sleep(0)                 # process that one iteration
        ws._stop = True
        ws._queue.put_nowait(b"\x00\x00" * 1600)  # unblock the await
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(_drive())
    # the grace machine was constructed with the shared constant -> the
    # exact production expression that used to AttributeError now resolves.
    # P0 (coord inbox 47): the default grace is now 8 (config-driven); the
    # important property is that EndGrace got the SAME value the wake stream
    # resolved, not any specific number.
    assert constructed.get("grace") == WakeStream.CONTINUATION_GRACE
    assert constructed.get("grace") == ws.CONTINUATION_GRACE
