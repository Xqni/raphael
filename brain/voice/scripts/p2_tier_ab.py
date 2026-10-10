#!/usr/bin/env python
"""P2 (Wave 5P, 2026-10-09) — per-tier warmth A/B vs the JP reference.

Renders the P0 drift battery's 10 sentences at EACH persona tier
(great_sage warmth 0.0 -> T0.2, raphael 0.3 -> T~0.30, ciel 0.6 -> T~0.40)
through the REAL FishSpeechServer, then measures per tier:

  text_fidelity  faster-whisper small round-trip similarity vs source
                 (the P0 drift metric; ACCEPT >= 0.90 -> battery ">=9/10")
  timbre         spectral distance to assets/raphael_reference_jp.wav
                 (0 = identical voice; higher = drifted) — the JP-reference
                 bar the packet asks us to A/B against

RULE 14: this spawns its OWN fish (no live one is up) and STOPS it in
`finally`. Never runs alongside another fish. Exit 3 = fish never became
healthy (checkpoint/venv missing) -> reported as blocked, not a fake pass.

Usage:
  brain/.venv/bin/python brain/voice/scripts/p2_tier_ab.py
Output: ~/.raphael/voice/eval/tier_ab/{tier}/{NN}.wav + summary.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import wave
from difflib import SequenceMatcher
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import load_voice_config            # noqa: E402
from brain.voice.tts import (FishSpeechServer,       # noqa: E402
                             wav_bytes_to_s16le_pcm)
from brain.voice.wake import normalize_text          # noqa: E402

TIERS = ["great_sage", "raphael", "ciel"]
SENTENCES = [
    "Paris is the capital of France.",
    "The sum of 2 plus 2 is 4.",
    "Working on it.",
    "Understood. Executing now.",
    "Please open YouTube and search for lo-fi music.",
    "There are three tasks running and one awaiting your confirmation.",
    "The weather forecast says light rain this afternoon, high of 18 degrees.",
    "She navigated to the downloads folder and renamed the file report-final.",
    "Absolutely, I will remind you at half past seven tomorrow morning.",
    "Analysis complete. Two risks found: low disk space and an outdated driver.",
]
ACCEPT = 0.90
OUT = Path.home() / ".raphael" / "voice" / "eval" / "tier_ab"


def write_wav(path: Path, pcm: bytes, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
        f.writeframes(pcm)


def similarity(src: str, hyp: str) -> float:
    a, b = normalize_text(src), normalize_text(hyp)
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 3)


def transcribe_en(path: Path, model) -> str:
    import numpy as np
    import soundfile as sf
    d, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = d.mean(axis=1)
    if sr != 16000:
        n = int(len(mono) * 16000 / sr)
        mono = np.interp(np.linspace(0, len(mono) - 1, n),
                         np.arange(len(mono)), mono).astype("float32")
    segs, _info = model.transcribe(mono, language="en", beam_size=5)
    return " ".join((s.text or "").strip() for s in segs).strip()


def read_wav_pcm(path: Path) -> "tuple":
    import soundfile as sf
    d, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return d.mean(axis=1), sr


def timbre_to_ref(wav_path: Path, ref_path: Path) -> float:
    """Cosine timbre similarity of a rendered wav vs the JP reference
    (1 = same voice; measured wrong-voice floor 0.13-0.64)."""
    from brain.voice.tts import timbre_similarity
    mono, sr = read_wav_pcm(wav_path)
    import numpy as np
    pcm = (np.clip(mono, -1, 1) * 32767).astype(np.int16).tobytes()
    t = timbre_similarity(pcm, sr, ref_path)
    return -1.0 if t is None else round(float(t), 4)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ref_path = _REPO / "assets" / "raphael_reference_jp.wav"
    summary = {"ref": str(ref_path), "accept": ACCEPT, "tiers": {}}

    # one fish for all tiers; spawn here, stop in finally (Rule 14)
    cfg = load_voice_config()
    fish = FishSpeechServer(cfg)
    try:
        asyncio.run(fish.ensure_started())
        if not asyncio.run(fish.health()):
            print("FISH UNHEALTHY after ensure_started", file=sys.stderr)
            return 3

        from faster_whisper import WhisperModel
        wm = WhisperModel("small", device="cpu", compute_type="int8")

        for tier in TIERS:
            # re-derive this tier's params exactly as production does
            os.environ["RAPHAEL_PERSONA_TIER"] = tier
            tcfg = load_voice_config()
            fish.cfg = tcfg          # _references()/synthesize read cfg live
            tier_out = OUT / tier
            scores, timbres = [], []
            for i, s in enumerate(SENTENCES, 1):
                t0 = time.perf_counter()
                wav = asyncio.run(fish.synthesize(s))
                gen = time.perf_counter() - t0
                pcm, sr = wav_bytes_to_s16le_pcm(wav, tcfg.tts_sample_rate)
                wp = tier_out / f"{i:02d}.wav"
                write_wav(wp, pcm, sr)
                hyp = transcribe_en(wp, wm)
                sc = similarity(s, hyp)
                td = timbre_to_ref(wp, ref_path)
                scores.append(sc); timbres.append(td)
                print(f"  [{tier} T{tcfg.fish_temperature:.3f}] {i:02d} "
                      f"sim={sc} timbre={td} gen={gen:.1f}s")
            n_pass = sum(1 for s in scores if s >= ACCEPT)
            summary["tiers"][tier] = {
                "temperature": tcfg.fish_temperature,
                "warmth": tcfg.tier_warmth,
                "text_pass": f"{n_pass}/{len(scores)}",
                "min_sim": min(scores), "mean_sim": round(sum(scores)/len(scores), 3),
                "mean_timbre": round(sum(timbres)/len(timbres), 4),
                "scores": scores, "timbre": timbres,
            }
            print(f"  == {tier}: text {n_pass}/{len(scores)} >= {ACCEPT}, "
                  f"T={tcfg.fish_temperature:.3f}, "
                  f"mean_timbre={summary['tiers'][tier]['mean_timbre']}")
    finally:
        fish.stop()                              # Rule 14: always tear down
        print("fish stopped (Rule 14)")

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nsummary -> {OUT / 'summary.json'}")
    print("samples -> " + ", ".join(f"{t}/" for t in TIERS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
