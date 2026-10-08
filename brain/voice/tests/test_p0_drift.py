"""P0 non-English drift (2026-10-08) — regression tests for the three fixes:
  1. reference TRANSCRIPT sidecar is sent with every synthesis,
  2. isolated digits are spelled out (fish garbled digit runs),
  3. sampling params A/B'd (temperature 0.2, repetition_penalty 1.2).

Battery evidence (live fish, faster-whisper round-trip, 10 sentences):
  BEFORE (text="", temp0.7) = 2/10 >= 0.90
  AFTER  (+transcript, +digits, +T0.2/RP1.2) = 10/10 (saved run),
          9/10 twice on re-runs (single-word 0.846-0.881 near-misses)

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

from brain.voice import VoiceConfig  # noqa: E402
from brain.voice.tts import (FishSpeechServer, TTSEngine,  # noqa: E402
                             expand_spoken_numbers)


# ---- 2. digit expander -----------------------------------------------------
def test_expand_spoken_numbers_digits_become_words():
    assert expand_spoken_numbers("The sum of 2 plus 2 is 4.") == \
        "The sum of two plus two is four."
    assert expand_spoken_numbers("high of 18 degrees") == "high of eighteen degrees"
    assert expand_spoken_numbers("5 tasks remain") == "five tasks remain"
    assert expand_spoken_numbers("100 percent sure") == "one hundred percent sure"


def test_expand_spoken_numbers_never_touches_protected_forms():
    # decimals / versions / IPs / times / ranges / years / adjacency
    for keep in ("v1.5", "192.168.1.5", "4.5 percent", "at 19:45",
                 "10-20 files", "on 2026", "mp3 file", "utf8 encoding",
                 "Room 101A", "chapter 2b"):
        assert expand_spoken_numbers(keep) == keep, keep
    # already-spelled text is untouched (idempotent)
    assert expand_spoken_numbers("two plus two is four") == \
        "two plus two is four"
    assert expand_spoken_numbers(expand_spoken_numbers("2 plus 2")) == \
        expand_spoken_numbers("2 plus 2")


def test_expand_applies_to_payload_not_subtitle():
    """The WIRE text is expanded; the spoken text drives audio only."""
    cfg = VoiceConfig(tts_voice=str(_REPO / "assets" / "raphael_reference_jp.wav"))
    srv = FishSpeechServer(cfg)
    refs = srv._references()
    payload = srv._payload("Please book 2 tickets for 19:30.", refs)
    assert payload["text"] == "Please book two tickets for 19:30."   # time kept


# ---- 1. reference transcript sidecar ---------------------------------------
def test_reference_transcript_is_sent(tmp_path):
    ref = tmp_path / "jp.wav"
    ref.write_bytes(b"JP_AUDIO_BYTES")
    txt = tmp_path / "jp.txt"
    txt.write_text("コク カウンターにいる兵士に話しかけると。", encoding="utf-8")
    cfg = VoiceConfig(tts_voice=str(ref), ack_cache=str(tmp_path / "acks"))
    refs = FishSpeechServer(cfg)._references()
    assert len(refs) == 1
    assert refs[0]["text"].startswith("コク")           # sidecar goes on the wire


def test_missing_transcript_warns_once_and_still_sends_audio(tmp_path, capsys):
    ref = tmp_path / "jp.wav"
    ref.write_bytes(b"JP_AUDIO_BYTES")
    cfg = VoiceConfig(tts_voice=str(ref), ack_cache=str(tmp_path / "acks"))
    srv = FishSpeechServer(cfg)
    assert srv._references()[0]["text"] == ""      # audio still sent
    assert "transcript missing" in capsys.readouterr().out
    srv._references()                              # second call: silent
    assert "transcript missing" not in capsys.readouterr().out


# ---- 3. sampling params (A/B evidence) -------------------------------------
def test_payload_carries_ab_tuning():
    cfg = VoiceConfig(tts_voice=str(_REPO / "assets" / "raphael_reference_jp.wav"))
    payload = FishSpeechServer(cfg)._payload("Hello there.", [])
    assert payload["temperature"] == 0.2
    assert payload["repetition_penalty"] == 1.2
    assert payload["use_memory_cache"] == "off"


def test_echo_registry_keys_on_spoken_digits(tmp_path):
    """STT returns WORDS, so the echo registry must hold the expanded form
    she actually says (otherwise '2' vs 'two' would defeat self-trigger
    rejection for digit sentences)."""
    pytest.importorskip("soundfile")
    from brain.voice import get_playback_echoes, reset_activation
    reset_activation()
    cfg = VoiceConfig(tts_voice=str(_REPO / "assets" / "raphael_reference_jp.wav"),
                      ack_cache=str(tmp_path / "acks"))
    eng = TTSEngine(cfg)

    class _Fish:
        proc = None
        async def ensure_started(self, timeout_s=240.0):
            return None
        def check_reference(self):
            return Path("/ok")
        async def synthesize(self, text):
            return (cfg.tts_voice_path).read_bytes()
        def stop(self):
            pass

    eng.fish = _Fish()
    asyncio.run(_consume(eng.speak("I have 2 apples in the demo.", job="j_echo")))
    recent = " | ".join(get_playback_echoes().recent())
    assert "two apples" in recent, recent
    assert "2 apples" not in recent
    reset_activation()


async def _consume(aiter):
    return [e async for e in aiter]
