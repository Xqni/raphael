#!/usr/bin/env python
"""P0 accent probe — is the LOST JP accent a cache problem or a fish problem?

Decisive experiment (live fish, never spawns it — Rule 14):
  1. for every canonical phrase: load the LIVE cached wav (JP namespace) if
     the key exists — that is what the user has been HEARING;
  2. render the SAME phrase FRESH through FishSpeechServer (identical payload
     to live speak(): JP reference, use_memory_cache as configured);
  3. score everything (cached / fresh / the JP reference clip / the Zira clip)
     with a coarse timbre fingerprint: median F0 + 16-band log-spectral
     cosine distances;
  4. structural cache-isolation check: two TTSEngine speaks of the same text
     through a throwaway cache must return byte-identical audio (i.e. the
     brain cache serves ONLY what it just synthesized).

Outputs ~/.raphael/voice/eval/p0_before/*.wav + p0_probe.json (user-listenable).
Exit 3 when fish is unreachable (never spawns).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import wave
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402

from brain.voice import load_voice_config  # noqa: E402
from brain.voice.tts import (FishSpeechServer, TTSEngine,  # noqa: E402
                             wav_bytes_to_s16le_pcm)
from brain.voice.wake import normalize_text  # noqa: E402

MAIN = Path("/home/dami/raphael")
JP_NS = "f64bd512ea1e"
REFS = {
    "jp_file": _REPO / "assets" / "raphael_reference_jp.wav",
    "jp_slime_sample": MAIN / "assets/reference/samples/01_jp_slime_ref.wav",
    "zira_sample": MAIN / "assets/reference/samples/02_zira_current_ref.wav",
}


def read_audio(path: Path, target_sr: int = 16000):
    """wav file -> float32 mono at target_sr (stdlib + numpy only)."""
    with wave.open(str(path), "rb") as w:
        sr, n = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if n > 1:
        x = x.reshape(-1, n).mean(axis=1)
    if sr != target_sr:
        m = int(len(x) * target_sr / sr)
        x = np.interp(np.linspace(0, len(x) - 1, max(m, 1)),
                      np.arange(len(x)), x).astype(np.float32)
    return x, target_sr


def fingerprint(x: np.ndarray, sr: int) -> dict:
    """Median F0 (voiced frames) + 16-band log-spectral vector."""
    frame, hop = int(0.04 * sr), int(0.02 * sr)
    bands = np.logspace(np.log10(200), np.log10(7000), 17)
    spec_vec, f0s = [], []
    for i in range(0, len(x) - frame, hop):
        f = x[i:i + frame]
        rms = float(np.sqrt(np.mean(f * f)))
        if rms < 0.03:
            continue
        win = f * np.hanning(frame)
        mag = np.abs(np.fft.rfft(win))
        freqs = np.fft.rfftfreq(frame, 1 / sr)
        e = [float(np.sum(mag[(freqs >= bands[j]) & (freqs < bands[j + 1])] ** 2)
                  + 1e-9) for j in range(16)]
        spec_vec.append(np.log(e))
        s = np.signbit(f)
        zcr = float(np.count_nonzero(s[1:] != s[:-1])) / (len(f) - 1)
        hz = zcr * sr / 2.0
        if 60 <= hz <= 400:
            f0s.append(hz)
    spec = np.mean(np.stack(spec_vec), axis=0) if spec_vec else np.zeros(16)
    return {"f0_hz": round(float(np.median(f0s)), 1) if f0s else None,
            "spec": spec}


def cos(a, b):
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return round(float(np.dot(a, b) / n), 3) if n else None


def write_wav(path: Path, pcm: bytes, sr: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / ".raphael/voice/eval/p0_before"))
    ap.add_argument("--fresh-per-phrase", type=int, default=2)
    args = ap.parse_args()
    out = Path(args.out)

    cfg = load_voice_config()
    fish = FishSpeechServer(cfg)
    if not asyncio.run(fish.health()):
        print("FISH NOT REACHABLE (never spawns) — exit 3", file=sys.stderr)
        return 3

    import yaml
    cfg_doc = yaml.safe_load((_REPO / "config.yaml").read_text(encoding="utf-8")) or {}
    phrases = (cfg_doc.get("voice_personality", {}) or {}).get("speech_forms") or []
    phrases = [str(p) for p in phrases]

    # fingerprints of the references
    fps = {"_refs": {}}
    for name, p in REFS.items():
        if p.exists():
            x, sr = read_audio(p)
            fps["_refs"][name] = {k: v for k, v in fingerprint(x, sr).items()
                                  if k != "spec"}
            fps.setdefault("_spec", {})[name] = fingerprint(x, sr)["spec"]

    result = {"phrases": [], "refs": fps.get("_refs", {}),
              "fish_base": fish.base, "ref_sent": str(cfg.tts_voice_path)}
    specs = dict(fps.get("_spec", {}))

    from brain.voice.tts import reference_fingerprint
    ns = reference_fingerprint(cfg.tts_voice_path)
    live_dir = MAIN / "assets" / "acks" / ns
    print(f"JP namespace dir: {live_dir}")

    for i, text in enumerate(phrases, 1):
        key = normalize_text(text)
        import hashlib
        h = hashlib.sha1(key.encode()).hexdigest()[:16] + ".wav"
        row = {"text": text, "key": h}
        cached = live_dir / h
        if cached.exists():
            x, sr = read_audio(cached)
            fp = fingerprint(x, sr)
            row["cached"] = {"file": str(cached), "f0_hz": fp["f0_hz"],
                             "bytes": cached.stat().st_size}
            specs[f"c{i}"] = fp["spec"]
        # fresh renders straight from fish (bypass the brain cache)
        for k in range(1, args.fresh_per_phrase + 1):
            wav = asyncio.run(fish.synthesize(text))
            pcm, sr2 = wav_bytes_to_s16le_pcm(wav, 24000)
            p = out / f"fresh_{i}_{k}.wav"
            write_wav(p, pcm, sr2)
            x, sr = read_audio(p)
            fp = fingerprint(x, sr)
            row.setdefault("fresh", []).append(
                {"file": str(p), "f0_hz": fp["f0_hz"],
                 "bytes": len(pcm), "duration_s": round(len(pcm) / sr2, 2)})
            specs[f"f{i}_{k}"] = fp["spec"]
        result["phrases"].append(row)
        print(f"[{i}] {text!r}: cached={'yes' if 'cached' in row else 'no'} "
              f"fresh={[f['f0_hz'] for f in row.get('fresh', [])]}")

    # ---- distance matrix vs references -------------------------------------
    ref_specs = {k: v for k, v in specs.items() if k in ("jp_file", "jp_slime_sample",
                                                         "zira_sample")}
    dist = {}
    for k, v in specs.items():
        if k in ref_specs:
            continue
        dist[k] = {rn: cos(v, rv) for rn, rv in ref_specs.items()}
    result["timbre_cosine"] = dist   # higher = closer to that reference
    result["note"] = ("cosine similarity of 16-band log-spectral fingerprints "
                      "(coarse timbre proxy — NOT a speaker-verification "
                      "score); f0 = median voiced ZCR-pitch. Decisive read: "
                      "fresh renders near jp_file/jp_slime and FAR from "
                      "zira = fish is producing the JP voice; cached rows far "
                      "from fresh rows = stale cache serving old audio.")

    # ---- structural cache isolation ----------------------------------------
    import dataclasses
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="p0_cache_"))
    eng = TTSEngine(dataclasses.replace(load_voice_config(),
                                         ack_cache=str(tmp)))
    async def _twice():
        outs = []
        for _ in range(2):
            ev = []
            async for e in eng.speak("Task complete.", job="p0"):
                ev.append(e)
            outs.append([x for x in ev if x["event"] == "chunk"])
        return outs
    ch1, ch2 = asyncio.run(_twice())
    b1 = b"".join(c["payload"] for c in ch1)
    b2 = b"".join(c["payload"] for c in ch2)
    result["cache_isolation"] = {
        "first_bytes": len(b1), "second_bytes": len(b2),
        "second_was_cache_hit": bool(ch2) and all(c.get("cached") for c in ch2),
        "byte_identical": b1 == b2,
        "first_engine": ch1[0].get("engine") if ch1 else None,
        "second_engine": ch2[0].get("engine") if ch2 else None,
    }
    (out / "p0_probe.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in
                      ("refs", "cache_isolation", "timbre_cosine")},
                     indent=2)[:2000])
    print(f"\nwrote {out}/p0_probe.json + {len(list(out.glob('*.wav')))} wavs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
