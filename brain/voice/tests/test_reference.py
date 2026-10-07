"""Wave 3 P0 — Bug D: the great-sage (JP) reference voice on EVERY synthesis.

USER DIRECTIVE (2026-10-07): no silent default/Zira voice, ever. This file
proves, mock-based (no fish server, no network):

  1. reference path resolution is CWD-independent (Bug D suspect #1),
  2. a missing reference FAILS LOUD: TTSError + subtitle notice + no audio
     chunks (never a default-voice render),
  3. the reference is sent on EVERY synthesis (payload assertions) with a
     proof log line (`[tts] ref sent: path=... bytes=...`),
  4. fish's text-keyed memory cache is OFF (Bug D suspect #3),
  5. the phrase cache is namespaced by sha1(reference)[:12] so a reference
     change can never replay another voice's audio (suspect #2) — including
     the stale top-level hashes from the Zira era,
  6. the configured repo reference (assets/raphael_reference_jp.wav) loads
     and its exact bytes are what goes on the wire.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import base64
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import VoiceConfig, load_voice_config  # noqa: E402
from brain.voice.tts import (FishSpeechServer, PhraseCache,  # noqa: E402
                             TTSEngine, TTSError, reference_fingerprint)


async def _drain(aiter):
    return [e async for e in aiter]


@pytest.fixture(autouse=True)
def _clean_ref_env(monkeypatch):
    """Another suite may leak RAPHAEL_TTS_VOICE/REQUIRED into os.environ —
    pin them so these assertions are about config, not session state."""
    for var in ("RAPHAEL_TTS_VOICE", "RAPHAEL_TTS_REFERENCE_REQUIRED"):
        monkeypatch.delenv(var, raising=False)


# ---- 1. path resolution ----------------------------------------------------
def test_reference_resolution_is_cwd_independent(tmp_path, monkeypatch):
    """Bug D suspect #1: relative path vs brain's CWD. tts_voice_path must
    resolve against the REPO root no matter where the process runs."""
    monkeypatch.chdir(tmp_path)                 # e.g. brain started elsewhere
    cfg = load_voice_config(_REPO / "config.yaml")
    path = cfg.tts_voice_path
    assert path.is_absolute()
    assert path == _REPO / cfg.tts_voice          # repo-root-relative, not CWD
    assert tmp_path not in path.parents          # never resolved under CWD


def test_configured_reference_is_the_jp_great_sage_voice():
    """User directive: EVERY speech uses the great-sage reference."""
    cfg = load_voice_config(_REPO / "config.yaml")
    assert cfg.tts_voice.endswith("raphael_reference_jp.wav")
    assert cfg.tts_reference_required is True    # no silent fallback, ever
    assert cfg.tts_voice_path.exists(), \
        f"configured reference missing on disk: {cfg.tts_voice_path}"


# ---- 2. missing reference fails LOUD ---------------------------------------
def test_missing_reference_raises_instead_of_defaulting(tmp_path):
    cfg = VoiceConfig(tts_voice=str(tmp_path / "nope.wav"),
                      ack_cache=str(tmp_path / "acks"))
    srv = FishSpeechServer(cfg)
    with pytest.raises(TTSError) as ei:
        srv.check_reference()
    assert "MISSING" in ei.value.detail and "nope.wav" in ei.value.detail
    with pytest.raises(TTSError):               # depth: payload builder too
        srv._references()


def test_missing_reference_blocks_speech_with_notice_no_audio(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """Loud degradation: start+end, a notice naming the reference, ZERO audio
    chunks — never a default-voice render."""
    cfg = VoiceConfig(tts_voice=str(tmp_path / "nope.wav"),
                      ack_cache=str(tmp_path / "acks"))
    eng = TTSEngine(cfg)

    async def _fish_up(timeout_s=240.0):
        return None

    monkeypatch.setattr(eng.fish, "ensure_started", _fish_up)
    events = asyncio.run(_drain(eng.speak("Task complete.", job="j_ref")))
    assert [e["event"] for e in events] == ["start", "end"]
    notice = events[-1].get("notice") or ""
    assert "reference" in notice.lower(), notice
    assert not any(e["event"] == "chunk" for e in events)   # NO default voice
    assert "[tts] BLOCKED (reference)" in capsys.readouterr().out


def test_optional_reference_mode_is_explicit(tmp_path):
    """The ONLY way to synthesize without a reference is an explicit opt-out."""
    cfg = VoiceConfig(tts_voice=str(tmp_path / "nope.wav"),
                      tts_reference_required=False,
                      ack_cache=str(tmp_path / "acks"))
    srv = FishSpeechServer(cfg)
    assert srv._references() == []              # no raise when opted out


# ---- 3/4. payload = reference on EVERY synthesis + proof log ---------------
class _Resp:
    status_code = 200
    content = b"\x00" * 512
    text = ""


def test_reference_sent_every_synthesis_with_proof_log(tmp_path, monkeypatch,
                                                       capsys):
    ref = tmp_path / "jp.wav"
    ref_bytes = b"JP_REFERENCE_BYTES"
    ref.write_bytes(ref_bytes)
    cfg = VoiceConfig(tts_voice=str(ref), ack_cache=str(tmp_path / "acks"))
    srv = FishSpeechServer(cfg)

    captured = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured.append(json)
            return _Resp()

    monkeypatch.setattr("brain.voice.tts.httpx.AsyncClient", _Client)
    out_wav = asyncio.run(srv.synthesize("Task complete."))
    assert out_wav == _Resp.content

    payload = captured[0]
    # Bug D suspect #3: fish's own text-keyed cache must be OFF
    assert payload["use_memory_cache"] == "off"
    # the reference goes out on EVERY synthesis, exact bytes
    assert len(payload["references"]) == 1
    assert base64.b64decode(payload["references"][0]["audio"]) == ref_bytes

    # proof line: path + bytes, per synthesis
    out = capsys.readouterr().out
    assert "[tts] ref sent: path=" in out
    assert f"bytes={len(ref_bytes)}" in out
    assert "sha1=" in out

    # ... and again on the next synthesis (every speech, not just the first)
    asyncio.run(srv.synthesize("Analysis complete."))
    assert len(captured) == 2
    assert all(len(p["references"]) == 1 for p in captured)


# ---- 5. phrase cache namespaced by reference fingerprint -------------------
def test_cache_cannot_replay_another_voices_audio(tmp_path):
    wav_v1 = b"RIFF_V1_AUDIO"
    c1 = PhraseCache(tmp_path, fingerprint="aaaa11112222")
    c1.store("Confirmed.", wav_v1)
    assert c1.load("Confirmed.") == wav_v1

    # another reference (voice) shares the dir but hears NOTHING from V1
    c2 = PhraseCache(tmp_path, fingerprint="bbbb33334444")
    assert c2.load("Confirmed.") is None

    # stale TOP-LEVEL hash (Zira era, e.g. assets/acks/9c03c5b0...wav) is
    # unreachable — hash lookups only happen inside the current-ref subdir
    stale = tmp_path / PhraseCache._hash_name(PhraseCache.key_for("Task complete."))
    stale.write_bytes(b"OLD_ZIRA_AUDIO")
    assert c1.load("Task complete.") is None

    # the documented user-dropped, TEXT-named ack still works
    (tmp_path / "custom phrase.wav").write_bytes(b"USER_ACK")
    assert c1.load("Custom phrase!") == b"USER_ACK"


def test_engine_renamespaces_when_reference_changes(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"VOICE_V1_AUDIO")
    cfg = VoiceConfig(tts_voice=str(ref), ack_cache=str(tmp_path / "acks"))
    eng = TTSEngine(cfg)
    fp1 = eng.reference_fp
    assert fp1 == reference_fingerprint(ref) and fp1 != "noref"
    eng.cache.store("Confirmed.", b"WAV_WITH_V1")

    ref.write_bytes(b"VOICE_V2_AUDIO")           # user swaps the recording
    fp2 = eng.refresh_reference()
    assert fp2 != fp1
    assert eng.cache.fingerprint == fp2
    assert eng.cache.load("Confirmed.") is None  # V1 audio unreachable now


def test_fingerprint_is_stable_and_content_addressed(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"SAME_BYTES")
    assert reference_fingerprint(ref) == reference_fingerprint(ref)
    assert reference_fingerprint(ref) != "noref"
    assert reference_fingerprint(tmp_path / "missing.wav") == "noref"


# ---- 6. the configured repo reference is what goes on the wire -------------
def test_repo_jp_reference_loads_exactly(tmp_path):
    cfg = load_voice_config(_REPO / "config.yaml")
    if not cfg.tts_voice_path.exists():
        pytest.skip(f"reference not present on disk: {cfg.tts_voice_path}")
    srv = FishSpeechServer(cfg)
    refs = srv._references()
    assert len(refs) == 1
    assert base64.b64decode(refs[0]["audio"]) == cfg.tts_voice_path.read_bytes()

    fp = reference_fingerprint(cfg.tts_voice_path)
    assert len(fp) == 12 and fp != "noref"
    eng = TTSEngine(VoiceConfig(tts_voice=str(cfg.tts_voice_path),
                                ack_cache=str(tmp_path / "acks")))
    assert eng.reference_fp == fp                 # cache namespaced by IT
    assert eng.cache.fingerprint == fp
