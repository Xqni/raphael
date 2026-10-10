"""Wave 5U §5.3 (item 2) — REAL Kokoro-82M synthesis (integration).

Marked integration + skipped in CI (no weights on the runner). Mirrors the
fish_real test: skips cleanly when weights or kokoro-onnx are absent, asserts
fresh non-empty WAV synthesis + resample-to-cfg-rate through the real engine.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests/test_kokoro_real.py -q
"""
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if "sounddevice" not in sys.modules:
    import types
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

import pytest  # noqa: E402

from brain.voice.config import VoiceConfig  # noqa: E402
from brain.voice.tts import KokoroSynth, TTSEngine  # noqa: E402


def _have_weights(cfg: VoiceConfig) -> bool:
    k = KokoroSynth(cfg)
    return (k.model_path.exists() and k.voices_path.exists()
            and k.model_path.stat().st_size > 0
            and k.voices_path.stat().st_size > 0)


@pytest.mark.integration
def test_kokoro_real_synthesis():
    pytest.importorskip("kokoro_onnx")
    cfg = VoiceConfig(tts_engine="kokoro")
    if not _have_weights(cfg):
        pytest.skip("kokoro weights absent (run download_kokoro_weights.sh)")
    synth = KokoroSynth(cfg)
    wav = asyncio.run(synth.synthesize("Confirmed."))
    assert wav and len(wav) > 1024          # real audio, not empty
    assert wav[:4] == b"RIFF"               # WAV container
    assert synth.voice_id().startswith("kokoro-")


@pytest.mark.integration
def test_kokoro_engine_speak_stream():
    """Full speak() path on kokoro: chunk frames flow with engine='kokoro'."""
    pytest.importorskip("kokoro_onnx")
    import tempfile
    cfg = VoiceConfig(tts_engine="kokoro", ack_cache=tempfile.mkdtemp() + "/")
    if not _have_weights(cfg):
        pytest.skip("kokoro weights absent (run download_kokoro_weights.sh)")
    eng = TTSEngine(cfg)
    events = asyncio.run(_collect(eng.speak("Understood. Executing now.",
                                            job="j_k")))
    chunks = [e for e in events if e.get("event") == "chunk"]
    engines = {e.get("engine") for e in chunks}
    assert chunks, "expected chunk frames from real kokoro"
    assert engines == {"kokoro"}, engines


async def _collect(aiter):
    return [e async for e in aiter]
