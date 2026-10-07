# voice — lane task list (owner: voice lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/voice.md. Requests to you: `ls docs/requests/*__to__voice__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] STT seam: route transcription through router.transcribe() when voice.stt_engine=groq; keep faster-whisper behind profile local (code stays).
- [x] Keep wake/PTT/VAD behavior as-is (already live-tested); no threshold tuning beyond correctness fixes.
  - deviation, documented: VAD gains an `echo_guard` that only raises the OPEN threshold while TTS playback is active (her bleed 40-225 vs speech 2000+, measured); open-segment hysteresis untouched.
- [x] Fish TTS speak loop correctness (lifecycle start/chunk/end, fallback notice) — NO performance work.
  - degraded mode = subtitle-only + ONE-TIME notice (no placeholder tone).
- [x] Assert no local-model/ollama/whisper-CUDA paths are hit under cloud_temp (mock-based).
- [x] Voice suite green (brain/voice/tests), acks cache untouched.

## Wave 2 (session brief 2026-10-06)
- [x] 0. Instance isolation via RAPHAEL_INSTANCE (fish port + voice log dir; main defaults unchanged).
- [x] 1. STT in cloud_temp: VAD segments -> router.transcribe (Groq Whisper); local whisper kept, disabled.
- [x] 2. Activation: pre-STT cloud gate + phonetic wake gate decides commands; PTT hotkey fallback; self-trigger prevented (body echo guard + playback-echo registry). OPEN request: ws.py should pass `reason` (docs/requests/voice__to__integrator__audio-end-pass-reason.md).
- [x] 3. TTS: sentence chunking -> Fish -> `speak` JSON + binary frames w/ amplitude; degrade = subtitle-only + one-time notice; barge-in via hotkey/wake (interrupt controller + echo guard keeps wake barge-in alive while she speaks).
- [x] 4. Voice confirmation parsing (yes/no/modify) for LOW-risk only, fail-closed; high-risk = non-voice. OPEN request: docs/requests/voice__to__brain-core__voice-confirm-wiring.md.
- [x] 5. Mock-based tests for the whole voice path (fake mic frames in, fake Fish out).

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [P0-BugD] **USER DIRECTIVE (2026-10-07): EVERY speech interaction uses the Japanese-English great-sage voice** (`assets/raphael_reference_jp.wav`, stitched from the Raphael-slime reference clips, user-approved) — no fallback to default/Zira ever; missing ref = fail loud + coord attention, never silent synthesis; log ref path+bytes per synthesis. Live TTS must use the JP slime reference — user decision 2026-10-07: JP voice PERMANENT (`config.yaml voice.tts_voice = assets/raphael_reference_jp.wav`), Zira retired (too robotic). Live E2E answers did NOT use it while direct renders with the same file sound correct (docs/BUGS-WAVE2.md Bug D). Suspects: silent `_references()` empty-fallback (tts.py:343), phrase cache keyed by text only, fish `use_memory_cache`. Task: LOUD ref loading (log path+bytes per synthesis; warn/fail on missing), invalidate/namespace the phrase cache on ref change, produce live proof; approved samples in assets/reference/samples/.
- [SPEED] Sentence-streamed fish TTS stays local and instant (Rule 15).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  - Wave 3: natural-conversation polish (utterance-end handling, interruptions, `spoken_reply_max_sentences` short replies).
  - Wave 4: speaker verification for sensitive confirmations, phrase-bank prebuild tool, second voice-reference slot.
  - Wave 5: persona voices (raphael / ciel reference clips selected by persona.tier).
