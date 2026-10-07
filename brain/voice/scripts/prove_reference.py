#!/usr/bin/env python
"""Live PROOF for Bug D (voice lane, Wave 3 P0).

Renders ONE short phrase through the REAL fish-speech server with the
configured reference (assets/raphael_reference_jp.wav) and prints:
  - the `[tts] ref sent: path=... bytes=... sha1=...` proof line (emitted by
    brain/voice/tts.py for EVERY synthesis),
  - chunk/engine stats for the produced speak stream.

RULES honored (INTERFACES §d + AGENT_RULES Rule 14):
  * this script NEVER spawns fish — if no server is reachable it exits 3 with
    a clear message (the live stack / integrator owns bringing fish up);
  * it renders exactly one phrase (tiny RAM/time), then exits.

Usage:
  brain/.venv/bin/python brain/voice/scripts/prove_reference.py

Exit codes: 0 = proof produced, 3 = fish not reachable, 2 = no chunks.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import VoiceConfig, load_voice_config           # noqa: E402
from brain.voice.tts import (TTSError, reference_fingerprint,    # noqa: E402
                             TTSEngine)


async def main() -> int:
    cfg = load_voice_config()
    ref = cfg.tts_voice_path
    print(f"configured reference : {ref}")
    print(f"exists               : {ref.exists()} "
          f"({ref.stat().st_size if ref.exists() else 0} bytes)")
    print(f"fingerprint          : {reference_fingerprint(ref)}")
    print(f"reference_required   : {cfg.tts_reference_required}")
    print(f"phrase-cache dir     : {cfg.ack_cache_path}"
          f"/{reference_fingerprint(ref)}/  (namespaced per reference)")

    eng = TTSEngine(cfg)
    if not await eng.fish.health():
        print(f"\nFISH NOT REACHABLE at {eng.fish.base} — this script never "
              f"spawns it (INTERFACES §d / Rule 14). Start the live stack "
              f"(or ask the integrator), then re-run.")
        eng.shutdown()
        return 3

    try:
        eng.fish.check_reference()
    except TTSError as e:
        print(f"\nREFERENCE BLOCKED (expected loud failure): {e.detail}")
        eng.shutdown()
        return 2

    print("\nrendering one phrase ...")
    events = []
    async for ev in eng.speak("Analysis complete.", job="j_ref_proof"):
        events.append(ev)
    eng.shutdown()

    chunks = [e for e in events if e["event"] == "chunk"]
    end = events[-1] if events else {}
    print(f"engine               : {end.get('engine')}")
    print(f"chunks               : {len(chunks)} "
          f"({sum(len(c.get('payload', b'')) for c in chunks)} bytes of audio)")
    if end.get("notice"):
        print(f"notice               : {end['notice']}")
    if not chunks:
        print("NO AUDIO — see the [tts] BLOCKED / ref line above.")
        return 2
    print("\nPROOF OK: synthesis used the configured reference "
          "(see the `[tts] ref sent:` line above).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
