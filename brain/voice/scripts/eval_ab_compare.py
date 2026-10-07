#!/usr/bin/env python
"""A/B: fish-speech vs PocketTTS on the exact sentences the live stack speaks.

Run in brain/.venv (has httpx/soundfile/faster-whisper). Rule 14: reuses the
ALREADY-RUNNING fish server (never spawns one) and exits.

  (1) renders all config voice_personality.speech_forms through the REAL
      `FishSpeechServer.synthesize()` payload (JP reference, use_memory_cache
      off) — i.e. byte-for-byte what live speak() sends -> out/fish/*.wav
  (2) transcribes BOTH sets (faster-whisper, pinned language=en — same engine
      as the integration round-trip test) -> transcript similarity vs source
  (3) auto-detect pass on the PocketTTS set -> accent-drift heuristic (the
      research caveat: JP reference -> English text is partial)
  (4) coarse timbre proxy: median voiced-frame pitch (ZCR) per set
  (5) writes ab_report.json + prints a markdown table

Usage:
  brain/.venv/bin/python brain/voice/scripts/eval_ab_compare.py \
      [--pocket-dir ~/.raphael/voice/eval/fp32] [--out ~/.raphael/voice/eval]
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

from brain.voice import load_voice_config                    # noqa: E402
from brain.voice.tts import (FishSpeechServer, wav_bytes_to_s16le_pcm,  # noqa: E402
                             pcm_s16le_to_float32, split_sentences)
from brain.voice.wake import normalize_text                  # noqa: E402


def write_wav(path: Path, pcm: bytes, sr: int) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return len(pcm) / 2 / float(sr)


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    return data, sr


def similarity(src: str, hyp: str) -> float:
    a, b = normalize_text(src).split(), normalize_text(hyp).split()
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, " ".join(a), " ".join(b)).ratio(), 3)


def median_pitch(pcm: bytes, sr: int):
    """Coarse voiced-pitch proxy: median ZCR-frequency over RMS-gated frames."""
    import numpy as np
    x = pcm_s16le_to_float32(pcm)
    if len(x) < sr // 10:
        return None
    frame = int(sr * 0.05)
    pitches = []
    for i in range(0, len(x) - frame, frame):
        f = x[i:i + frame]
        rms = float(np.sqrt(np.mean(f * f)))
        if rms < 0.05:
            continue
        s = np.signbit(f)
        zcr = float(np.count_nonzero(s[1:] != s[:-1])) / (len(f) - 1)
        hz = zcr * sr / 2.0
        if 60 <= hz <= 400:
            pitches.append(hz)
    return round(float(np.median(pitches)), 1) if pitches else None


def transcribe_local(path: Path, model, language="en"):
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != 16000:
        import numpy as np
        n = int(len(mono) * 16000 / sr)
        mono = np.interp(np.linspace(0, len(mono) - 1, n),
                         np.arange(len(mono)), mono).astype("float32")
    segs, info = model.transcribe(mono, language=language, beam_size=5)
    text = " ".join((s.text or "").strip() for s in segs).strip()
    return text, (info.language if info is not None else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pocket-dir", default=str(Path.home() / ".raphael/voice/eval/fp32"))
    ap.add_argument("--out", default=str(Path.home() / ".raphael/voice/eval"))
    ap.add_argument("--round", type=int, default=1)
    args = ap.parse_args()

    pocket_dir = Path(args.pocket_dir)
    out = Path(args.out)
    cfg = load_voice_config()
    sentences = (json.loads((pocket_dir / "pockettts_eval.json").read_text())
                 ["sentences"])

    # ---- (1) fish side: real synthesis payload, fresh every run -----------
    fish_dir = out / "fish"
    fish = FishSpeechServer(cfg)
    if not asyncio.run(fish.health()):
        print("FISH NOT REACHABLE — this script never spawns it "
              "(INTERFACES §d / Rule 14).", file=sys.stderr)
        return 3
    fish_stats = []
    for i, text in enumerate(sentences, 1):
        t0 = time.perf_counter()
        wav = asyncio.run(fish.synthesize(text))
        gen_s = time.perf_counter() - t0
        pcm, sr = wav_bytes_to_s16le_pcm(wav, 24000)
        dur = write_wav(fish_dir / f"{i:02d}.wav", pcm, sr)
        fish_stats.append({"idx": i, "text": text, "gen_s": round(gen_s, 3),
                           "audio_s": round(dur, 3),
                           "rtf": round(dur / gen_s, 2) if gen_s else None})
        print(f"fish #{i}: {gen_s:.2f}s -> {dur:.2f}s audio")

    # ---- (2)(3)(4) analyse both sets --------------------------------------
    from faster_whisper import WhisperModel
    wm = WhisperModel("small", device="cpu", compute_type="int8")

    rows = []
    for i, text in enumerate(sentences, 1):
        row = {"idx": i, "text": text}
        # pocket file = round_r_NN_slug.wav
        pfiles = sorted(pocket_dir.glob(f"r{args.round}_{i:02d}_*.wav"))
        ffile = fish_dir / f"{i:02d}.wav"
        if pfiles:
            pcm, sr = read_wav(pfiles[0])
            hyp_en, _ = transcribe_local(pfiles[0], wm, "en")
            _hyp_auto, lang_auto = transcribe_local(pfiles[0], wm, None)
            row.update({
                "pocket_file": str(pfiles[0]),
                "pocket_sim": similarity(text, hyp_en),
                "pocket_hyp": hyp_en,
                "pocket_auto_lang": lang_auto,
                "pocket_pitch": median_pitch(pcm, sr),
            })
        if ffile.exists():
            pcm, sr = read_wav(ffile)
            hyp_en, _ = transcribe_local(ffile, wm, "en")
            row.update({
                "fish_file": str(ffile),
                "fish_sim": similarity(text, hyp_en),
                "fish_hyp": hyp_en,
                "fish_pitch": median_pitch(pcm, sr),
            })
        rows.append(row)

    report = {
        "sentences": len(sentences),
        "fish": fish_stats,
        "pocket_variant": (json.loads((pocket_dir / "pockettts_eval.json")
                                      .read_text()).get("variant")),
        "rows": rows,
        "note": "similarity = difflib ratio on normalized transcripts "
                "(transcribed by local faster-whisper-small, language=en) — "
                "a coarse intelligibility proxy, not strict WER; "
                "auto_lang = accent-drift heuristic (JP-ref cloning caveat).",
    }
    (out / "ab_report.json").write_text(json.dumps(report, indent=2))

    print("\n| # | sentence | fish sim | pocket sim | fish pitch | pocket pitch | pocket auto-lang |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['idx']} | {r['text'][:44]} | "
              f"{r.get('fish_sim', '-')} | {r.get('pocket_sim', '-')} | "
              f"{r.get('fish_pitch', '-')} | {r.get('pocket_pitch', '-')} | "
              f"{r.get('pocket_auto_lang', '-')} |")
    if fish_stats:
        rtfs = [f["rtf"] for f in fish_stats if f.get("rtf")]
        if rtfs:
            print(f"\nfish RTF: mean x{sum(rtfs)/len(rtfs):.1f} "
                  f"(min x{min(rtfs)} / max x{max(rtfs)})")
    print(f"\nreport: {out / 'ab_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
