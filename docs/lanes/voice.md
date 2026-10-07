# voice — lane task list (owner: voice lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/voice.md. Requests to you: `ls docs/requests/*__to__voice__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] STT seam: route transcription through router.transcribe() when voice.stt_engine=groq; keep faster-whisper behind profile local (code stays).
- [ ] Keep wake/PTT/VAD behavior as-is (already live-tested); no threshold tuning beyond correctness fixes.
- [ ] Fish TTS speak loop correctness (lifecycle start/chunk/end, fallback notice) — NO performance work.
- [ ] Assert no local-model/ollama/whisper-CUDA paths are hit under cloud_temp (mock-based).
- [ ] Voice suite green (brain/voice/tests), acks cache untouched.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
