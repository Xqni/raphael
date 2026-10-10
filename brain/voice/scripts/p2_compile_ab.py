#!/usr/bin/env python
"""P2-adj (Wave 5P, 2026-10-09) — fish `--compile` latency A/B (TODO §6).

The vendored fish server exposes `--compile` (tools/server/api_utils.py:31,
wired into the generate pipeline at tools/api_server.py:81). torch.compile
trades a ONE-TIME warmup hit (paid on the FIRST synthesis; the disk compile
cache persists across restarts) for faster steady-state synthesis. TODO §6
expects ~2x on the recorded 13.4s/phrase baseline (PROGRESS 2026-10-05).

Measures, on the SAME 3 JP-reference phrases, WITHOUT --compile then WITH:
  startup        spawn -> /health 200 (server load; compile is lazy, so this
                 should be ~equal for both)
  first_call     the FIRST /v1/tts after startup = the torch.compile warmup
  steady_state   the next 2 calls (compile cache warm) = the real speedup
  drift          faster-whisper round-trip similarity vs source, >=0.90 = pass
                 (P0 battery spot-check — a speedup that garbles speech fails)

The --compile server is driven through the production config flag
(voice.fish_compile) so we measure EXACTLY what production would spawn.

RULE 14: spawns its OWN fish, one server at a time (baseline torn down BEFORE
the compile server launches), everything stopped in `finally`. Exit 3 = fish
never became healthy or the vendored server lacks --compile.

Usage:  brain/.venv/bin/python brain/voice/scripts/p2_compile_ab.py
Output: ~/.raphael/voice/eval/compile_ab.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import load_voice_config            # noqa: E402
from brain.voice.tts import FishSpeechServer         # noqa: E402
from brain.voice.wake import normalize_text          # noqa: E402

PHRASES = [
    "Paris is the capital of France.",
    "Understood. Executing now.",
    "Analysis complete. Two risks found.",
]
ACCEPT = 0.90
OUT = Path.home() / ".raphael" / "voice" / "eval"
ENV_KEY = "RAPHAEL_FISH_COMPILE"


def similarity(src: str, hyp: str) -> float:
    a, b = normalize_text(src), normalize_text(hyp)
    return 0.0 if not a or not b else round(SequenceMatcher(None, a, b).ratio(), 3)


def transcribe_en(wav_bytes: bytes, model) -> str:
    import io
    import numpy as np
    import soundfile as sf
    d, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
    mono = d.mean(axis=1)
    if sr != 16000:
        n = int(len(mono) * 16000 / sr)
        mono = np.interp(np.linspace(0, len(mono) - 1, n),
                         np.arange(len(mono)), mono).astype("float32")
    segs, _ = model.transcribe(mono, language="en", beam_size=5)
    return " ".join((s.text or "").strip() for s in segs).strip()


async def _startup_s(fish: FishSpeechServer, timeout_s: float = 300.0) -> float:
    t0 = time.perf_counter()
    await fish.ensure_started(timeout_s=timeout_s)
    if not await fish.health():
        raise RuntimeError("fish unhealthy after ensure_started")
    return time.perf_counter() - t0


def _measure(label: str, use_compile: bool) -> "tuple":
    """Returns (metrics_dict, last_wav_bytes). Spawns + tears down its own fish."""
    os.environ[ENV_KEY] = "true" if use_compile else "false"
    cfg = load_voice_config()          # reads ENV_KEY -> fish_compile
    assert cfg.fish_compile == use_compile, "env->cfg compile flag mismatch"
    fish = FishSpeechServer(cfg)
    try:
        startup = asyncio.run(_startup_s(fish))
        calls, last_wav = [], b""
        for i in range(3):
            t0 = time.perf_counter()
            wav = asyncio.run(fish.synthesize(PHRASES[i % len(PHRASES)]))
            calls.append(round(time.perf_counter() - t0, 2))
            if not wav or len(wav) < 128:
                raise RuntimeError(f"call {i} returned empty audio")
            last_wav = wav
    finally:
        fish.stop()                                  # Rule 14
    metrics = {
        "label": label,
        "compile": use_compile,
        "startup_s": round(startup, 2),
        "first_call_s": calls[0],                    # warmup when --compile
        "steady_state_s": calls[1:],                 # the speedup that matters
        "steady_mean_s": round(sum(calls[1:]) / len(calls[1:]), 2),
        "last_wav_bytes": len(last_wav),
    }
    return metrics, last_wav


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    probe = FishSpeechServer(load_voice_config())
    if not probe._compile_supported():
        print("--compile NOT supported by vendored server", file=sys.stderr)
        return 3

    from faster_whisper import WhisperModel
    wm = WhisperModel("small", device="cpu", compute_type="int8")

    print("== baseline (no --compile) ==")
    base, _ = _measure("baseline", use_compile=False)
    print(json.dumps(base, indent=2))
    print("== compile (--compile) ==")
    comp, comp_wav = _measure("compile", use_compile=True)
    print(json.dumps(comp, indent=2))

    # drift spot-check on the COMPILE server's last render (must stay >=0.90)
    hyp = transcribe_en(comp_wav, wm)
    drift = similarity(PHRASES[-1], hyp)
    comp["drift_similarity"] = drift
    comp["drift_pass"] = drift >= ACCEPT
    print(f"drift spot-check: sim={drift} (>= {ACCEPT} = pass) hyp={hyp!r}")

    speedup = (base["steady_mean_s"] / comp["steady_mean_s"]
               if comp["steady_mean_s"] else 0.0)
    summary = {
        "baseline_steady_mean_s": base["steady_mean_s"],
        "compile_steady_mean_s": comp["steady_mean_s"],
        "compile_first_call_s": comp["first_call_s"],
        "compile_startup_s": comp["startup_s"],
        "speedup_x": round(speedup, 2),
        "expect": "~2x (TODO §6)",
        "drift_similarity": drift,
        "drift_pass": drift >= ACCEPT,
        "baseline": base, "compile": comp,
    }
    (OUT / "compile_ab.json").write_text(json.dumps(summary, indent=2))
    print(f"\nspeedup {speedup:.2f}x (steady {base['steady_mean_s']}s -> "
          f"{comp['steady_mean_s']}s); compile first-call "
          f"{comp['first_call_s']}s = warmup cost")
    print(f"summary -> {OUT / 'compile_ab.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
