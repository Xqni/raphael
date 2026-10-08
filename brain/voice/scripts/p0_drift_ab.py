#!/usr/bin/env python
"""P0 (2026-10-08) — non-English drift on some responses: ref-TEXT A/B.

Diagnosis under test: the approved reference `assets/raphael_reference_jp.wav`
is NATIVE Japanese narration (Groq + local whisper transcripts agree) and we
have been sending it with `references[].text = ""` (no sidecar), so fish
conditions on speaker audio only — hard English sentences drift toward
foreign phonation.

  phase BEFORE : assets/raphael_reference_jp.txt ABSENT  -> text='' (live behavior)
  phase AFTER  : sidecar present                         -> reference text sent

For each of 10 varied English sentences: render through the REAL
FishSpeechServer (live fish reused — never spawned, Rule 14), then whisper
round-trip (faster-whisper small, pinned language=en) and score similarity
vs the source (difflib on normalized text — the metric used in earlier A/Bs).

ACCEPTANCE: every sentence >= 0.90 in the AFTER phase.

Usage:
  brain/.venv/bin/python brain/voice/scripts/p0_drift_ab.py --phase before
  (create the sidecar, then)
  brain/.venv/bin/python brain/voice/scripts/p0_drift_ab.py --phase after
Exit 3 = fish unreachable (never spawns it).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from difflib import SequenceMatcher
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import load_voice_config            # noqa: E402
from brain.voice.tts import FishSpeechServer, wav_bytes_to_s16le_pcm  # noqa: E402
from brain.voice.wake import normalize_text          # noqa: E402

SENTENCES = [
    "Paris is the capital of France.",
    "The sum of 2 plus 2 is 4.",                       # known-bad case
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
SIDECAR = _REPO / "assets" / "raphael_reference_jp.txt"


def write_wav(path: Path, pcm: bytes, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["before", "after"], required=True)
    args = ap.parse_args()

    cfg = load_voice_config()
    fish = FishSpeechServer(cfg)
    if not asyncio.run(fish.health()):
        print("FISH NOT REACHABLE (never spawns) — exit 3", file=sys.stderr)
        return 3

    sidecar = cfg.tts_voice_path.with_suffix(".txt")
    refs = fish._references()                   # the REAL payload path
    ref_text_len = len(refs[0]["text"]) if refs else -1
    print(f"phase={args.phase} sidecar={'PRESENT' if sidecar.exists() else 'ABSENT'} "
          f"-> reference text sent = {ref_text_len} chars")

    out = Path.home() / ".raphael" / "voice" / "eval" / f"drift_{args.phase}"
    out.mkdir(parents=True, exist_ok=True)

    # render all sentences through live fish
    render_t = []
    for i, s in enumerate(SENTENCES, 1):
        t0 = time.perf_counter()
        wav = asyncio.run(fish.synthesize(s))
        gen = time.perf_counter() - t0
        pcm, sr = wav_bytes_to_s16le_pcm(wav, 24000)
        write_wav(out / f"{i:02d}.wav", pcm, sr)
        render_t.append(round(gen, 2))
        print(f"  render {i:02d}: {gen:.2f}s")

    # whisper round-trip scoring
    from faster_whisper import WhisperModel
    wm = WhisperModel("small", device="cpu", compute_type="int8")
    rows = []
    for i, s in enumerate(SENTENCES, 1):
        hyp = transcribe_en(out / f"{i:02d}.wav", wm)
        score = similarity(s, hyp)
        rows.append({"idx": i, "sentence": s, "similarity": score,
                     "pass": score >= ACCEPT, "hyp": hyp})
        print(f"  [{args.phase}] {i:02d} sim={score} "
              f"{'PASS' if score >= ACCEPT else 'FAIL'} <- {hyp[:70]!r}")

    passed = sum(1 for r in rows if r["pass"])
    report = {
        "phase": args.phase,
        "sidecar_present": sidecar.exists(),
        "ref_text_chars_sent": ref_text_len,
        "acceptance": ACCEPT,
        "passed": passed, "total": len(rows),
        "meets_acceptance": passed == len(rows),
        "render_times_s": render_t,
        "rows": rows,
    }
    (out / "scores.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n{args.phase.upper()}: {passed}/{len(rows)} sentences >= {ACCEPT} "
          f"-> {'MEETS' if report['meets_acceptance'] else 'BELOW'} acceptance")
    print(f"wrote {out}/scores.json + {len(SENTENCES)} wavs")
    return 0 if report["meets_acceptance"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
