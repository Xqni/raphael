#!/usr/bin/env python
"""STT -> reply latency probe (Wave 5H, verify-first measurement).

Answers the conductor's ask: measure the CURRENT segment-close -> subtitle
latency, broken into stages, before proposing any cut.

Pipeline measured (exactly production-shaped, no stack needed):
  audio_end (segment closed)
    -> [S2] voice.transcribe_result via asyncio.to_thread (REAL cloud STT:
        router.transcribe / Groq Whisper, real .env keys, real 16k PCM)
    -> [S3a] voice.wake.gate (phonetic wake gate)
    -> [S3b] engine.submit (queue + 'queued' event)
    -> [S3c] fastpath intent runs -> narrate -> FIRST `subtitle` frame
  (S1 = body VAD hangover — the constant BEFORE segment-close: SILENCE_CLOSE
   x BLOCK=2.5 s — reported as context, not part of close->subtitle.)

TTS is stubbed (speak -> no-op): the subtitle fires BEFORE any speak event
(narrate broadcasts subtitle synchronously), and this isolates the STT path
from fish/GPU variance.

Run:  brain/.venv/bin/python brain/voice/scripts/stt_reply_latency.py [--runs 5]
Exit 3 = cloud STT unreachable (never fabricates numbers).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# isolate the job DB BEFORE brain.jobs imports (never touch repo runtime db)
os.environ.setdefault("RAPHAEL_DB_PATH",
                      str(Path(tempfile.mkdtemp(prefix="stt_lat_")) / "lat.db"))

FIXTURE = Path.home() / ".raphael/voice/kws/fixtures/wake.wav"


class _StubHub:
    """Captures broadcasts with timestamps (the ws hub's fanout surface)."""

    def __init__(self):
        self.frames = []

    def broadcast(self, frame, roles=None):
        self.frames.append((time.perf_counter(), frame))

    def broadcast_binary(self, *_a, **_k):
        pass

    def refresh_orb_state(self, *_a, **_k):
        pass


def _load_pcm_16k() -> bytes:
    import numpy as np
    import soundfile as sf
    from brain.voice.tts import resample_s16le, float32_to_pcm_s16le
    d, sr = sf.read(str(FIXTURE), dtype="float32", always_2d=True)
    pcm = float32_to_pcm_s16le(d.mean(axis=1))
    if sr != 16000:
        pcm = resample_s16le(pcm, int(sr), 16000)
    return pcm


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()

    from brain.voice import get_voice, stt_final_frame  # noqa: F401
    from brain.jobs.engine import get_engine
    from brain.loop import build_runner

    voice = get_voice()

    # -- sanity: cloud STT reachable (no fabricated numbers) -----------------
    probe = _load_pcm_16k()
    try:
        res = await asyncio.to_thread(voice.transcribe_result, probe,
                                      reason="wake")
    except Exception as e:  # noqa: BLE001
        print(f"CLOUD STT UNAVAILABLE: {type(e).__name__}: {e} — exit 3",
              file=sys.stderr)
        return 3
    print(f"cloud STT probe: {res.text!r} rtf={res.rtf}")

    # -- stub ONLY the TTS (subtitle fires before any speak event) ----------
    async def _no_speak(*_a, **_k):
        if False:
            yield None
    voice.tts.speak = _no_speak

    engine = get_engine()
    hub = _StubHub()
    runner = build_runner(hub=hub)

    s2, s3a, s3b, s3c = [], [], [], []
    for i in range(args.runs):
        hub.frames.clear()
        t0 = time.perf_counter()
        res = await asyncio.to_thread(voice.transcribe_result, probe,
                                      reason="wake")
        t1 = time.perf_counter()
        match = voice.wake.gate(res.text, reason="wake")   # real wake verdict
        t2 = time.perf_counter()
        # ALWAYS submit a benign fastpath command: a real 'open youtube'
        # would dispatch pc tools and need a live Body (not our metric).
        command = "echo latency probe run"
        snap = await engine.submit(text=command, priority="user_facing",
                                   source="voice")
        t3 = time.perf_counter()
        await runner(snap)                     # fastpath intent -> narrate
        sub = next((t for t, f in hub.frames
                    if f.get("type") == "subtitle"), None)
        if sub is None:
            print("NO SUBTITLE FRAME — probe invalid (exit 4)", file=sys.stderr)
            return 4
        t4 = sub
        s2.append((t1 - t0) * 1000)
        s3a.append((t2 - t1) * 1000)
        s3b.append((t3 - t2) * 1000)
        s3c.append((t4 - t3) * 1000)
        print(f"run{i + 1}: S2 STT={s2[-1]:.0f}ms gate={s3a[-1]:.1f}ms "
              f"submit={s3b[-1]:.1f}ms fastpath->subtitle={s3c[-1]:.0f}ms "
              f"| transcript={res.text!r}")

    total = [a + b + c + d for a, b, c, d in zip(s2, s3a, s3b, s3c)]
    report = {
        # close(12 frames=1.2s) + continuation grace(13=1.3s) = 25 chunks —
        # SAME 2.5s worst-case as the old SILENCE_CLOSE=25 (zero split
        # regression), but resumes inside the window now MERGE instead of
        # waiting in an open segment
        "s1_body_vad_hangover_ms": 2500,
        "S2_cloud_stt_ms": {"median": round(statistics.median(s2)),
                            "min": round(min(s2)), "max": round(max(s2))},
        "S3a_gate_ms": round(statistics.median(s3a), 1),
        "S3b_submit_ms": round(statistics.median(s3b), 1),
        "S3c_fastpath_to_subtitle_ms": {"median": round(statistics.median(s3c)),
                                        "min": round(min(s3c)),
                                        "max": round(max(s3c))},
        "close_to_subtitle_ms": {"median": round(statistics.median(total)),
                                 "min": round(min(total)), "max": round(max(total))},
        "perceived_with_vad_hangover_ms": round(statistics.median(total) + 2500),
        "runs": args.runs,
    }
    out = Path.home() / ".raphael/voice/eval/stt_reply_latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print("\n" + json.dumps(report, indent=2))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
