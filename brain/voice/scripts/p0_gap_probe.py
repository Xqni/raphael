#!/usr/bin/env python
"""P0 gap probe — measures inter-chunk gaps of a multi-sentence reply.

Mirrors the integrator's WS pacing probe (91 chunks, mean 138ms, ONE 12.23s
hole) but at the speak-event source (identical cadence to what ws.py
broadcasts). Renders a deliberately STRESSFUL 4-sentence reply (one dense,
token-heavy sentence like the one fish spent 11.81s on) through the REAL
engine with live fish, timestamping every chunk.

Run:  brain/.venv/bin/python brain/voice/scripts/p0_gap_probe.py
Exit 3 when fish is unreachable (never spawns — Rule 14).
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

import dataclasses  # noqa: E402

from brain.voice import load_voice_config  # noqa: E402
from brain.voice.tts import TTSEngine  # noqa: E402

OUT = Path.home() / ".raphael/voice" / "eval" / "p0_gap_probe.json"
# Acceptance shape: EXACTLY 4 sentences (like the integrator's WS probe),
# sentence 3 word-level dense (no internal periods — keeps it ONE fish call).
TEXT = ("The keeper tended the lighthouse each night, watching the dark water. "
        "He recorded every ship that passed, noting their names and their flags. "
        "Status launched=notepad kind=path count=42 ok=1234567890 done. "
        "The sum of 2 plus 2 is 4, and the light never went out.")


async def main() -> int:
    cfg = load_voice_config()
    eng = TTSEngine(cfg)
    if not await eng.fish.health():
        print("FISH NOT REACHABLE (never spawns) — exit 3", file=sys.stderr)
        return 3

    ap_args = __import__("argparse").ArgumentParser()
    ap_args.add_argument("--fresh", action="store_true",
                         help="nonce the text so nothing is served from cache")
    args = ap_args.parse_args()
    text = TEXT
    if args.fresh:
        import random
        text = TEXT.rstrip(". ") + f" mark {random.randint(100000, 999999)}."

    chunks = []          # (t_arrival, seq, payload_bytes)
    t_start = time.perf_counter()
    preroll_log = []
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):      # keep the probe output clean
        async for e in eng.speak(text, job="j_gap", max_sentences=0):
            if e["event"] == "chunk":
                chunks.append((time.perf_counter() - t_start, e["seq"],
                               len(e["payload"])))
    preroll_log = [l for l in buf.getvalue().splitlines() if "preroll" in l]
    eng.shutdown()

    gaps = []
    for i in range(1, len(chunks)):
        gaps.append(round(chunks[i][0] - chunks[i - 1][0], 3))
    big = [g for g in gaps if g > 0.35]
    audio_s = sum(b for _, _, b in chunks) / 2 / 24000
    report = {
        "text_chars": len(text),
        "fresh": bool(args.fresh),
        "chunks": len(chunks),
        "first_chunk_s": round(chunks[0][0], 3) if chunks else None,
        "total_wall_s": round(chunks[-1][0], 3) if chunks else None,
        "audio_s": round(audio_s, 3),
        "gaps": {
            "count": len(gaps),
            "mean_ms": round(sum(gaps) / len(gaps) * 1000, 1) if gaps else 0,
            "max_ms": round(max(gaps) * 1000, 1) if gaps else 0,
            "holes_over_350ms": big,
            "p95_ms": round(sorted(gaps)[int(len(gaps) * 0.95)] * 1000, 1)
            if gaps else 0,
        },
        "preroll_log": preroll_log,
        "baseline_from_integrator_probe": {
            "mean_ms": 138, "one_hole_ms": 12230, "note": "pre-fix"},
    }
    OUT.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    ok = not big
    print("\nVERDICT:", "PASS — zero holes > 350ms" if ok else
          f"FAIL — {len(big)} hole(s) > 350ms")
    print(f"note: first chunk after {report['first_chunk_s']}s = pre-roll "
          f"(synthesizing the reply before speaking — the gapless tradeoff)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
