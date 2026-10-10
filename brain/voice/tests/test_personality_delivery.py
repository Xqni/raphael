"""Wave 5 — spoken delivery of the formats + persona-tier voice profiles.

  1. Persona-tier voice profiles (config surface): great_sage/raphael keep the
     current approved reference, ciel gets its own slot (`voice.tts_voice_ciel`
     — docs/evolution/02-persona-tiers.md §5) with a LOUD one-time fallback
     notice when the slot file is missing; tier flips re-namespace the phrase
     cache live (no restart); unknown tiers fail closed to great_sage.
  2. Report/Answer read-aloud pacing: at most `spoken_reply_max_sentences`
     sentences are ever SYNTHESIZED (subtitle carries the rest) — fish never
     burns GPU on unheard audio (Rule 15).
  3. Notice level-tinted phrasing: warn gets a crisp lead-in, info stays
     as-is; `VoiceStack.speak_notice()` speaks a notice frame's text that way.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import (VoiceConfig, VoiceStack, load_voice_config,  # noqa: E402
                         notice_spoken_text, reset_activation, reset_stt)
from brain.voice.tts import TTSEngine  # noqa: E402

JP_REF = _REPO / "assets" / "raphael_reference_jp.wav"


async def _drain(aiter):
    return [e async for e in aiter]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for var in ("RAPHAEL_PERSONA_TIER", "RAPHAEL_TTS_VOICE", "RAPHAEL_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    reset_stt()
    reset_activation()
    yield
    reset_stt()
    reset_activation()


class _FakeFish:
    def __init__(self):
        self.synth_calls = 0
        self.proc = None
        self.last_error = None

    async def ensure_started(self, timeout_s=240.0):
        return None

    def check_reference(self):
        return Path("/checked-by-cfg")

    async def synthesize(self, text):
        self.synth_calls += 1
        if JP_REF.exists():
            # reference-like audio so the P0 timbre gate ALLOWS caching
            # (test_cache_is_keyed_by_what_was_actually_spoken asserts it)
            return JP_REF.read_bytes()
        pytest.importorskip("soundfile")
        import io

        import numpy as np
        import soundfile as sf

        sr, ms = 32000, 300
        t = np.arange(int(sr * ms / 1000), dtype=np.float32) / sr
        buf = io.BytesIO()
        sf.write(buf, (0.3 * np.sin(2 * np.pi * 300.0 * t)).astype(np.float32),
                 sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    def stop(self):
        pass


def _engine(tmp_path, cfg=None):
    cfg = cfg or VoiceConfig(ack_cache=str(tmp_path / "acks"))
    eng = TTSEngine(cfg)
    eng.fish = _FakeFish()
    return eng


# ---- 1. persona-tier voice profiles ----------------------------------------
def test_tier_default_is_the_approved_repo_default():
    # Wave 5U/5P decision (integrator 2026-10-10, request
    # qa-security__to__voice__tier-default-test-conflict.md): the APPROVED
    # repo default tier is `raphael` (config.yaml persona.tier); the
    # fail-closed fallback for a MISSING/unknown tier is `great_sage` and is
    # covered separately (this test no longer conflates the two).
    cfg = load_voice_config(_REPO / "config.yaml")
    assert cfg.persona_tier == "raphael"             # approved repo default
    path, note = cfg.tier_voice_path()
    assert path == JP_REF and note is None           # the user-approved voice


def test_tier_ciel_uses_its_own_slot_when_present(tmp_path):
    slot = tmp_path / "ciel.wav"
    slot.write_bytes(b"CIEL_VOICE")
    base = tmp_path / "great.wav"
    base.write_bytes(b"GS_VOICE")
    cfg = VoiceConfig(tts_voice=str(base), tts_voice_ciel=str(slot),
                      persona_tier="ciel",
                      ack_cache=str(tmp_path / "acks"))
    path, note = cfg.tier_voice_path()
    assert path == slot and note is None


def test_tier_ciel_missing_slot_falls_back_loudly(tmp_path):
    base = tmp_path / "great.wav"
    base.write_bytes(b"GS_VOICE")
    cfg = VoiceConfig(tts_voice=str(base),
                      tts_voice_ciel=str(tmp_path / "nope_ciel.wav"),
                      persona_tier="ciel",
                      ack_cache=str(tmp_path / "acks"))
    path, note = cfg.tier_voice_path()
    assert path == base                              # approved voice, never default
    assert note and "ciel" in note and "missing" in note


def test_tier_env_override_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("RAPHAEL_PERSONA_TIER", "ciel")
    assert load_voice_config(_REPO / "config.yaml").persona_tier == "ciel"
    monkeypatch.setenv("RAPHAEL_PERSONA_TIER", "self_promoted_tier")
    assert load_voice_config(_REPO / "config.yaml").persona_tier == "great_sage"


def test_config_d_lane_fragments_are_consumed(tmp_path, monkeypatch):
    """evolution-persona ships voice.tts_voice_ciel + persona.tier + a
    voice_personality overlay in THEIR config.d fragment (request
    evolution-persona__to__voice__ciel-voice-reference-slot); the voice loader
    must merge lane fragments per INTERFACES §c (sorted, later wins)."""
    (tmp_path / "config.d").mkdir()
    (tmp_path / "config.yaml").write_text(
        "profile: cloud_temp\nvoice:\n  tts_voice: assets/raphael_reference_jp.wav\n"
        "voice_personality:\n  spoken_reply_max_sentences: 2\n",
        encoding="utf-8")
    (tmp_path / "config.d" / "00a_evolution-persona.yaml").write_text(
        "persona:\n  tier: ciel\n"
        "voice:\n  tts_voice_ciel: my/custom-ciel.wav\n"
        "voice_personality:\n  spoken_reply_max_sentences: 5\n",
        encoding="utf-8")
    monkeypatch.setattr("brain.voice.config.REPO_ROOT", tmp_path)
    cfg = load_voice_config(tmp_path / "config.yaml")
    assert cfg.tts_voice_ciel == "my/custom-ciel.wav"   # their key, merged
    assert cfg.tts_voice == "assets/raphael_reference_jp.wav"
    assert cfg.persona_tier == "ciel"
    assert cfg.spoken_max_sentences == 5                # voice_personality too


def test_tier_flip_renamespaces_the_cache_live(tmp_path):
    base = tmp_path / "great.wav"
    base.write_bytes(b"GS_VOICE")
    slot = tmp_path / "ciel.wav"
    slot.write_bytes(b"CIEL_VOICE")
    cfg = VoiceConfig(tts_voice=str(base), tts_voice_ciel=str(slot),
                      persona_tier="great_sage",
                      ack_cache=str(tmp_path / "acks"))
    eng = TTSEngine(cfg)
    fp1, path1 = eng.reference_fp, eng.reference_path
    assert path1 == base
    eng.cache.store("Confirmed.", b"WAV_GS")

    cfg.persona_tier = "ciel"                        # user switches tier
    fp2 = eng.refresh_reference()
    assert eng.reference_path == slot and fp2 != fp1
    assert eng.cache.fingerprint == fp2
    assert eng.cache.load("Confirmed.") is None      # old-tier audio unreachable


def test_tier_fallback_notice_is_one_time(tmp_path):
    base = tmp_path / "great.wav"
    base.write_bytes(b"GS_VOICE")
    cfg = VoiceConfig(tts_voice=str(base),
                      tts_voice_ciel=str(tmp_path / "missing.wav"),
                      persona_tier="ciel",
                      ack_cache=str(tmp_path / "acks"))
    eng = _engine(tmp_path, cfg)
    ev1 = asyncio.run(_drain(eng.speak("Task complete.", job="j_t1")))
    assert "ciel" in (ev1[-1].get("notice") or "")
    ev2 = asyncio.run(_drain(eng.speak("Analysis complete.", job="j_t2")))
    assert ev2[-1].get("notice") is None             # one-time only


# ---- 2. read-aloud pacing (spoken_reply_max_sentences) ---------------------
def test_spoken_cap_limits_what_is_synthesized(tmp_path, capsys):
    eng = _engine(tmp_path, VoiceConfig(
        ack_cache=str(tmp_path / "acks"),
        spoken_max_sentences=2))
    long_reply = ("First sentence here. Second sentence here. Third one too. "
                  "Fourth for good measure. Fifth and last.")
    events = asyncio.run(_drain(eng.speak(long_reply, job="j_cap")))
    chunks = [e for e in events if e["event"] == "chunk"]
    assert chunks
    assert eng.fish.synth_calls == 2, "only the spoken sentences are synthesized"
    assert "spoken cap: synthesizing 2 of 5" in capsys.readouterr().out
    assert events[0]["text"] == long_reply            # full text still announced


def test_spoken_cap_can_be_disabled(tmp_path):
    eng = _engine(tmp_path, VoiceConfig(ack_cache=str(tmp_path / "acks"),
                                        spoken_max_sentences=2))
    long_reply = ("One. Two. Three. Four. Five.")
    events = asyncio.run(_drain(eng.speak(long_reply, job="j_uncapped",
                                          max_sentences=0)))
    assert eng.fish.synth_calls == 5


def test_cache_is_keyed_by_what_was_actually_spoken(tmp_path):
    eng = _engine(tmp_path, VoiceConfig(ack_cache=str(tmp_path / "acks"),
                                        spoken_max_sentences=1))
    full = "Only the first is spoken. The second stays on screen."
    asyncio.run(_drain(eng.speak(full, job="j_key")))
    spoken = "Only the first is spoken."
    assert eng.cache.load(spoken) is not None         # stored under spoken text
    assert eng.cache.load(full) is None              # full text was never said


# ---- 3. Notice level-tinted phrasing ---------------------------------------
def test_notice_spoken_text_tints_warn_only():
    assert notice_spoken_text("Battery at 12%.") == "Battery at 12%."
    assert notice_spoken_text("Battery at 12%.", "warn") == \
        "Warning: Battery at 12%."
    assert notice_spoken_text("Warning: already tinted", "warn") == \
        "Warning: already tinted"                    # idempotent
    assert notice_spoken_text("  spaced   out  ", "info") == "spaced out"
    assert notice_spoken_text("", "warn") == ""
    assert notice_spoken_text("Unknown level.", "critical") == "Unknown level."
    assert notice_spoken_text(None, "warn") == ""


def test_speak_notice_uses_tinted_phrasing(tmp_path):
    voice = VoiceStack(VoiceConfig(ack_cache=str(tmp_path / "acks")))
    voice.tts.fish = _FakeFish()
    events = asyncio.run(_drain(
        voice.speak_notice("Provider outage resolved.", level="info",
                           job="j_n1")))
    assert events[0]["text"] == "Provider outage resolved."
    events2 = asyncio.run(_drain(
        voice.speak_notice("Provider outage resolved.", level="warn",
                           job="j_n2")))
    assert events2[0]["text"] == "Warning: Provider outage resolved."
