# Wave 2 — Voice phase 1 (brain/voice/) — RUNNING LOG

Owner: voice-dev. Scope: faster-whisper STT + VAD segments, Fish-Speech TTS adapter
(sentence-stream speak frames + phrase cache + amplitude), wake word/PTT/interrupt
interfaces, loop.py handoff. Edit-tool writes outside brain/voice are denied by
permission config; this log is written via shell heredoc (orchestrator-instructed path).

## Environment facts (verified 2026-10-05)
- brain/.venv: Python 3.12.8; fastapi 0.142.2, uvicorn 0.54.0, torch 2.14.0+cu126,
  numpy 2.5.3, pydantic 2.13.5, transformers 5.18.0, huggingface_hub (hf CLI in venv).
- GPU: NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB (shared with Ollama + Laya).
- assets/raphael_reference.wav — MISSING (assets/ holds only orb-reference jpgs +
  assets/reference/orb/ jpg duplicates). Per config.yaml + addendum §10: fallback voice
  + spoken notice when reference missing. TTS must not crash on missing asset.
- assets/acks/ (ack_cache) — does not exist yet (voice-dev owns assets/ per ARCH §2).
- No .wav anywhere in repo (find /home/dami/raphael -iname "*.wav" → empty).
- Already in venv: torch 2.14.0+cu126, numpy 2.5.3, pydantic 2.13.5, transformers 5.18.0.
- brain/voice/ did NOT exist before this run.

## Installs (REAL output)
$ uv pip install --python brain/.venv/bin/python faster-whisper soundfile
Resolved 26 packages in 1.63s
Installed 6 packages in 7ms
 + av==19.0.1 + cffi==2.1.1 + ctranslate2==4.8.2 + faster-whisper==1.2.1
 + pycparser==3.0 + soundfile==0.14.0

## Fish-Speech feasibility notes (checked 2026-10-05)
- PyPI `fish-speech` 0.1.0 (2025-07-07, owner "quocvu"): deps pin numpy<=1.26.4 and
  pydantic==2.9.2 → would DOWNGRADE numpy 2.5.3 / pydantic 2.13.5 in brain/.venv and
  break brain-dev's live app + Laya. Verdict: do NOT install the full stack into
  brain/.venv. Checkpoint provenance of the PyPI sdist unverified.
- Plan: try `uvx --from fish-speech ...` (isolated) only if a checkpoint download is
  proven first; otherwise TTS adapter keeps fish-speech hook + wave-file fallback,
  with the exact blocker named in README + final report.

## Downloads
(pending)

## Test runs (REAL outputs pasted verbatim)
(pending)

## RESUME state
(kept at end of session)
