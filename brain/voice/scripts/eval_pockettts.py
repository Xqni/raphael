#!/usr/bin/env python
"""PocketTTS (Kyutai) evaluation for Raphael — Wave-5 task 2026-10-07.

OFFLINE inference only (AGENT_RULES §14 / conductor instruction): loads the
model in-process, renders, prints metrics, EXITS — no HTTP server is ever
started while the live fish server is up.

Measures (the five research validation points, `.opencode/research/
lightweight-tts-options.md` §130):
  (a) real RSS: baseline -> after import -> after load -> per-render series
      (balloon check: early `serve` leaked to 32GB; we track RSS every render),
  (b) zero-shot clone of assets/raphael_reference_jp.wav + PERSISTED state
      (.safetensors export + reload timing),
  (c) A/B renders of the exact sentences the live stack speaks
      (config voice_personality.speech_forms) -> wav files next to the fish
      renders for a same-text, same-reference comparison,
  (d) RTF + time-to-first-chunk via generate_audio_stream (streaming path
      mapping onto brain/voice/tts.py),
  (e) int8 quantize variant as a separate process (--quantize) for the RAM lever.

Run (isolated venv, outside the repo — Rule 14: kill what you spawn; this is
a single process that exits):
  ~/.raphael/voice/eval/.venv-pockettts/bin/python \\
      brain/voice/scripts/eval_pockettts.py [--quantize] [--rounds N]
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import wave
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

DEFAULT_REF = _REPO / "assets" / "raphael_reference_jp.wav"
DEFAULT_OUT = Path.home() / ".raphael" / "voice" / "eval"
CONFIG = _REPO / "config.yaml"

_FALLBACK_SENTENCES = [
    "Understood. Executing now.",
    "Confirmed.",
    "Analysis complete.",
    "Task complete.",
    "That failure was within expectations. Adjusting.",
]


def rss_kb() -> int:
    return int(open("/proc/self/status").read().split("VmRSS:")[1]
               .split("kB")[0].strip())


def peak_rss_kb() -> int:
    return int(open("/proc/self/status").read().split("VmHWM:")[1]
               .split("kB")[0].strip())


def load_sentences() -> list:
    try:
        import yaml
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        s = (data.get("voice_personality") or {}).get("speech_forms") or []
        return [str(x) for x in s if str(x).strip()] or list(_FALLBACK_SENTENCES)
    except Exception:  # noqa: BLE001 — eval must not die on config parsing
        return list(_FALLBACK_SENTENCES)


def write_wav(path: Path, tensor, sample_rate: int) -> float:
    """torch tensor (float [-1,1]) -> 16-bit PCM wav via stdlib only."""
    import numpy as np
    import torch

    x = tensor.detach().cpu().float().numpy() if isinstance(tensor, torch.Tensor) \
        else np.asarray(tensor, dtype="float32")
    x = np.clip(x, -1.0, 1.0)
    pcm = (x * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())
    return len(pcm) / float(sample_rate)


def slug(text: str, n: int) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in text.lower())
    return "_".join(keep.split())[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--ref", default=str(DEFAULT_REF))
    ap.add_argument("--quantize", action="store_true")
    ap.add_argument("--rounds", type=int, default=3,
                    help="repeat renders to watch RSS (balloon check)")
    ap.add_argument("--stream-sentence", default="Task complete.")
    args = ap.parse_args()

    out = Path(args.out_dir) / ("q_int8" if args.quantize else "fp32")
    out.mkdir(parents=True, exist_ok=True)
    ref = Path(args.ref)
    sentences = load_sentences()
    result = {
        "variant": "int8" if args.quantize else "fp32",
        "torch": None, "ref": str(ref), "ref_bytes": ref.stat().st_size,
        "sentences": sentences, "rss_kb": {}, "renders": [],
        "stream": {}, "state": {}, "errors": [],
    }

    import torch
    result["torch"] = torch.__version__
    result["rss_kb"]["baseline"] = rss_kb()

    import pocket_tts as p
    result["rss_kb"]["imported"] = rss_kb()

    t0 = time.perf_counter()
    model = p.TTSModel.load_model(language="english",
                                  quantize=bool(args.quantize))
    result["load_s"] = round(time.perf_counter() - t0, 2)
    result["rss_kb"]["loaded"] = rss_kb()
    result["peak_rss_kb_after_load"] = peak_rss_kb()
    result["sample_rate"] = int(model.sample_rate)

    # ---- (b) clone the approved reference + persist the voice state --------
    # NOTE: `kyutai/pocket-tts` (cloning-enabled) is `gated: auto` on HF with
    # a prohibited-use terms form. Without that acceptance the library falls
    # back to `kyutai/pocket-tts-without-voice-cloning` and voice cloning
    # raises. We NEVER accept terms on the user's behalf — we degrade to a
    # catalog voice so footprint/RTF/streaming still measure, and record the
    # block for the re-run once the user accepts.
    voice_used = None
    try:
        t0 = time.perf_counter()
        state = model.get_state_for_audio_prompt(ref)
        result["state"]["clone_s"] = round(time.perf_counter() - t0, 2)
        result["state"]["clone_ok"] = True
        voice_used = f"cloned:{ref.name}"
    except Exception as e:  # noqa: BLE001 — gated repo: degrade, don't die
        result["state"]["clone_ok"] = False
        result["state"]["blocked"] = f"{type(e).__name__}: {str(e)[:300]}"
        result["errors"].append("CLONE BLOCKED (HF gated repo — user must "
                                "accept https://huggingface.co/kyutai/pocket-tts "
                                "terms); falling back to a catalog voice for "
                                "the non-voice metrics")
        for cand in ("alba", "jane", "anna"):
            try:
                state = model.get_state_for_audio_prompt(cand)
                voice_used = f"catalog:{cand}"
                result["state"]["voice_used"] = voice_used
                break
            except Exception as e2:  # noqa: BLE001
                result["errors"].append(f"catalog voice {cand}: {e2}")
        else:
            print("FATAL: no usable voice state", file=sys.stderr)
            return 2
    result["rss_kb"]["after_clone"] = rss_kb()
    state_path = out / ("great-sage_int8.safetensors"
                        if args.quantize else "great-sage.safetensors")
    t0 = time.perf_counter()
    try:
        if voice_used and voice_used.startswith("cloned"):
            p.export_model_state(state, str(state_path))
            result["state"]["exported"] = str(state_path)
            result["state"]["export_bytes"] = state_path.stat().st_size
            result["state"]["export_s"] = round(time.perf_counter() - t0, 2)
            # reload FROM the persisted file — the "instant voice preset" path
            t0 = time.perf_counter()
            state2 = model.get_state_for_audio_prompt(str(state_path))
            result["state"]["reload_s"] = round(time.perf_counter() - t0, 3)
            result["state"]["reload_ok"] = isinstance(state2, dict)
            state = state2
        result["rss_kb"]["after_state_reload"] = rss_kb()
    except Exception as e:  # noqa: BLE001 — report, don't die
        result["errors"].append(f"state export: {type(e).__name__}: {e}")

    # ---- (c) renders: exact live-stack sentences, R x N (balloon check) ----
    for rnd in range(1, args.rounds + 1):
        for i, text in enumerate(sentences, 1):
            t0 = time.perf_counter()
            try:
                wav = model.generate_audio(state, text, max_tokens=200)
            except Exception as e:  # noqa: BLE001
                result["errors"].append(f"render r{rnd} #{i}: "
                                        f"{type(e).__name__}: {e}")
                continue
            gen_s = time.perf_counter() - t0
            dur = write_wav(out / f"r{rnd}_{i:02d}_{slug(text, 28)}.wav",
                            wav, model.sample_rate)
            result["renders"].append({
                "round": rnd, "idx": i, "text": text, "gen_s": round(gen_s, 3),
                "audio_s": round(dur, 3),
                "rtf": round(dur / gen_s, 2) if gen_s else None,
                "rss_kb": rss_kb(),
            })
    result["rss_kb"]["after_renders"] = rss_kb()
    result["peak_rss_kb"] = peak_rss_kb()

    # ---- (d) streaming: first-chunk latency (the tts.py seam) -------------
    try:
        t0 = time.perf_counter()
        chunks, first = 0, None
        total = 0.0
        for ch in model.generate_audio_stream(state, args.stream_sentence,
                                              max_tokens=200):
            if first is None:
                first = time.perf_counter() - t0
            n = len(ch) if hasattr(ch, "__len__") else int(getattr(ch, "numel", 0))
            total += n / float(model.sample_rate)
            chunks += 1
        result["stream"] = {
            "chunks": chunks,
            "first_chunk_s": round(first, 3) if first else None,
            "audio_s": round(total, 3),
        }
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"stream: {type(e).__name__}: {e}")

    (out / "pockettts_eval.json").write_text(json.dumps(result, indent=2))

    # ---- human summary ------------------------------------------------------
    print("=" * 72)
    print(f"PocketTTS eval — variant={result['variant']} torch={result['torch']}")
    print(f"  ref: {ref} ({result['ref_bytes']} bytes)")
    print(f"  load_model: {result['load_s']}s   quantize={args.quantize}")
    print(f"  RSS: baseline {result['rss_kb'].get('baseline')} kB -> "
          f"import {result['rss_kb'].get('imported')} kB -> "
          f"loaded {result['rss_kb'].get('loaded')} kB -> "
          f"after {args.rounds}x{len(sentences)} renders "
          f"{result['rss_kb'].get('after_renders')} kB")
    print(f"  peak RSS: {result.get('peak_rss_kb')} kB")
    if result["renders"]:
        rtfs = [r["rtf"] for r in result["renders"] if r.get("rtf")]
        first = result["renders"][0]
        print(f"  first render: {first['gen_s']}s for {first['audio_s']}s "
              f"audio (RTF x{first['rtf']})")
        if rtfs:
            print(f"  RTF: min x{min(rtfs)} / mean x{sum(rtfs)/len(rtfs):.1f} "
                  f"/ max x{max(rtfs)}  (audio-sec per wall-sec)")
    print(f"  clone: {result['state'].get('clone_s')}s, "
          f"export {result['state'].get('export_bytes')} bytes "
          f"({result['state'].get('exported')}), "
          f"reload {result['state'].get('reload_s')}s")
    if result.get("stream"):
        print(f"  stream: {result['stream']}")
    if result["errors"]:
        print("  ERRORS:", *result["errors"], sep="\n    ")
    print(f"  json: {out / 'pockettts_eval.json'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
