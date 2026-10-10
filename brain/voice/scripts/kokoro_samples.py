#!/usr/bin/env python
"""Wave 5U §5.3 (item 2) — render 3 Kokoro calm-female samples for the owner.

Renders the SAME sentence with each candidate voice (af_nicole, af_heart,
af_bella — the calm female English presets) through the REAL KokoroSynth
engine (lazy load, in-process, CPU). Output goes to the gitignored eval dir
(~/.raphael/voice/eval/kokoro_samples/) so nothing personal/derived is ever
committed. The owner picks one; set voice.kokoro_voice (or
RAPHAEL_KOKORO_VOICE) to the winner.

Usage:
  bash brain/voice/scripts/download_kokoro_weights.sh   # once (~337MB)
  brain/.venv/bin/python brain/voice/scripts/kokoro_samples.py
Exit 3 = weights missing (never spawns/downloads itself).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import load_voice_config            # noqa: E402
from brain.voice.tts import KokoroSynth              # noqa: E402

CANDIDATES = ("af_nicole", "af_heart", "af_bella")
SENTENCE = ("Understood. Executing now. Analysis complete — two risks found, "
            "both handled, and the weather this afternoon is light rain.")
OUT = Path.home() / ".raphael" / "voice" / "eval" / "kokoro_samples"


def main() -> int:
    cfg = load_voice_config()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for voice in CANDIDATES:
        cfg.kokoro_voice = voice
        synth = KokoroSynth(cfg)
        try:
            t0 = time.perf_counter()
            wav = asyncio.run(synth.synthesize(SENTENCE))
            gen = time.perf_counter() - t0
        except Exception as e:  # noqa: BLE001 — report, don't crash the batch
            print(f"  {voice}: FAILED — {type(e).__name__}: {e}")
            results[voice] = {"error": str(e)[:200]}
            continue
        path = OUT / f"{voice}.wav"
        path.write_bytes(wav)
        # wav = 2-byte s16le mono at 24k
        dur = len(wav) / 2.0 / 24000.0
        rtf = gen / dur if dur else -1
        results[voice] = {"wav": str(path), "seconds": round(dur, 2),
                          "gen_s": round(gen, 2), "rtf": round(rtf, 3),
                          "bytes": len(wav)}
        print(f"  {voice}: {dur:.1f}s audio in {gen:.2f}s (RTF {rtf:.2f}) "
              f"-> {path}")
    (OUT / "samples.json").write_text(json.dumps(
        {"sentence": SENTENCE, "results": results}, indent=2))
    print(f"\nsummary -> {OUT / 'samples.json'}")
    print("owner picks a voice -> set voice.kokoro_voice (or RAPHAEL_KOKORO_VOICE)")
    return 0 if all("wav" in r for r in results.values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
