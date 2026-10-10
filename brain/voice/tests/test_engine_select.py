"""Wave 5U §5.3 (item 1) — Synth engine seam + selection matrix.

TTSEngine picks its active Synth via `voice.tts_engine` (fish | kokoro).
The phrase cache is namespaced by engine+voice id, so the two engines can
NEVER replay each other's cached audio. Kokoro is in-process (single lazy
session, Rule 14 holds trivially); fish is the JP-clone server tier.

These are pure-selection + namespace tests (no weights, no server): kokoro's
_k is never loaded here, fish's server is never spawned. A real-kokoro test
lives in test_kokoro_real.py (marked integration, skipped in CI).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests/test_engine_select.py -q
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if "sounddevice" not in sys.modules:
    import types
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

from brain.voice.config import VoiceConfig  # noqa: E402
from brain.voice.tts import (FishSpeechServer, KokoroSynth,  # noqa: E402
                             Synth, TTSEngine)


def _engine(tts_engine: str, **over) -> TTSEngine:
    cfg = VoiceConfig(tts_engine=tts_engine, **over)
    return TTSEngine(cfg)


# ---- Synth contract --------------------------------------------------------
def test_fish_and_kokoro_are_synths():
    assert issubclass(FishSpeechServer, Synth)
    assert issubclass(KokoroSynth, Synth)


def test_kokoro_voice_id_carries_engine_and_voice():
    k = KokoroSynth(VoiceConfig(kokoro_voice="af_nicole"))
    assert k.voice_id() == "kokoro-af_nicole"


def test_fish_voice_id_is_reference_fingerprint():
    f = FishSpeechServer(VoiceConfig())
    vid = f.voice_id()
    assert vid and vid != "noref"      # a real fingerprint, not the placeholder


# ---- engine selection matrix ----------------------------------------------
def test_default_engine_is_fish():
    eng = _engine("fish")
    assert eng.engine_name == "fish"
    assert isinstance(eng.synth, FishSpeechServer)
    assert eng.fish is eng.synth        # fish path keeps self.fish wired


def test_kokoro_engine_selected():
    eng = _engine("kokoro")
    assert eng.engine_name == "kokoro"
    assert isinstance(eng.synth, KokoroSynth)
    assert eng.fish is None             # no fish server under kokoro


def test_unknown_engine_falls_back_to_fish():
    eng = _engine("whispernet")         # garbage -> fail-closed to fish
    assert eng.engine_name == "fish"
    assert isinstance(eng.synth, FishSpeechServer)


def test_env_selects_kokoro_engine(monkeypatch):
    monkeypatch.setenv("RAPHAEL_TTS_ENGINE", "kokoro")
    from brain.voice.config import load_voice_config
    cfg = load_voice_config()
    assert cfg.tts_engine == "kokoro"


# ---- engine-namespaced phrase cache ---------------------------------------
def test_engines_get_distinct_cache_namespaces():
    """THE regression this seam guards: fish and kokoro must never share a
    cache namespace, or switching engines replays the other engine's audio.
    (PhraseCache truncates the fingerprint to 12 chars for the subdir name —
    that truncation is fine as long as the two engines stay distinct.)"""
    fish = _engine("fish")
    koko = _engine("kokoro")
    assert fish.cache_fp != koko.cache_fp
    assert koko.cache_fp.startswith("kokoro-")
    # the on-disk subdir names (what actually separates the audio) differ
    assert fish.cache.subdir.name != koko.cache.subdir.name


def test_kokoro_cache_namespace_is_stable_across_reference_refresh():
    eng = _engine("kokoro")
    before = eng.cache_fp
    subdir = eng.cache.subdir.name
    eng.refresh_reference()             # must be a NO-OP for kokoro
    assert eng.cache_fp == before
    assert eng.cache.subdir.name == subdir


# ---- kokoro fallback (missing weights/install -> subtitle, never silent) ---
def test_kokoro_missing_weights_raises_loud_pointer():
    """No weights on disk -> TTSError pointing at the download script (this
    test relies on the weights being gitignored/absent in a lean checkout)."""
    import pytest
    from brain.voice.tts import TTSError
    k = KokoroSynth(VoiceConfig(
        kokoro_model="brain/voice/models/kokoro/__absent__.onnx",
        kokoro_voices="brain/voice/models/kokoro/__absent__.bin"))
    with pytest.raises(TTSError) as ei:
        k._ensure()
    assert "download_kokoro_weights" in ei.value.detail


def test_kokoro_speak_falls_back_to_subtitle_when_unloadable():
    """engine=kokoro with no weights -> speak() yields engine='fallback' +
    a one-time notice, ZERO chunk frames (never a silent/placeholder voice)."""
    import asyncio
    eng = _engine("kokoro",
                  kokoro_model="brain/voice/models/kokoro/__absent__.onnx",
                  kokoro_voices="brain/voice/models/kokoro/__absent__.bin")
    # point cache at a tmp dir so the test never touches the real ack cache
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        eng.cache.dir = Path(td)
        eng.cache.subdir = Path(td) / eng.cache_fp
        eng.cache.subdir.mkdir(parents=True, exist_ok=True)

        async def _run():
            return [e async for e in eng.speak("Confirmed.", job="j_test")]
        events = asyncio.run(_run())
    chunks = [e for e in events if e.get("event") == "chunk"]
    end = [e for e in events if e.get("event") == "end"]
    assert chunks == []                 # no audio synthesized
    assert end and end[-1].get("engine") == "fallback"
    assert end[-1].get("notice")        # one-time explanatory notice present
