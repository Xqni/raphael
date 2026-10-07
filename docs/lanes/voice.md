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

- [x] [P0-BugD] **USER DIRECTIVE (2026-10-07): EVERY speech interaction uses the Japanese-English great-sage voice** (`assets/raphael_reference_jp.wav`, stitched from the Raphael-slime reference clips, user-approved) — no fallback to default/Zira ever; missing ref = fail loud + coord attention, never silent synthesis; log ref path+bytes per synthesis. **Implemented (2026-10-07):** `check_reference()`/`_references()` raise when required+missing (subtitle notice `[tts] BLOCKED (reference)`, ZERO audio); proof line `[tts] ref sent: path=… bytes=… sha1=…` on every synthesis; phrase cache namespaced `assets/acks/<sha1(ref)[:12]>/` + `refresh_reference()` re-namespaces on swap; fish `use_memory_cache: "off"` (text-keyed cache can't replay another voice); path resolution verified CWD-independent. Tests: `brain/voice/tests/test_reference.py` (10). **Live proof:** `brain/voice/scripts/prove_reference.py` ready — exits 3 while fish is unreachable (never spawns), run at next bring-up.
- [x] [COORD] spawn-kill-safe fish test fixture (Rule 14 RAM): integration tests spawn ONLY with `RAPHAEL_FISH_SPAWN=1`, and anything spawned is registered + killed per-test (fixture) AND at process exit (atexit) — `_kill_spawned_fish`, unit-tested; a server we didn't spawn is never touched.
- [x] [SPEED] Sentence-streamed fish TTS stays local and instant (Rule 15). Verified: `speak()` streams sentence N while N+1 generates (test_speak_frames_and_binary_audio asserts incremental chunk arrival), and there is no cloud-TTS code path at all — fish is the only synthesis engine (cache hit → fish → subtitle-only fallback).

## TASK 2026-10-07 — lightweight TTS evaluation (PocketTTS vs fish)

- [ ] Evaluate **PocketTTS (Kyutai)** as fish-speech replacement (research winner:
  `.opencode/research/lightweight-tts-options.md` —100M params, ~1.1GB RAM CPU-only
  (fish = 2GB GPU), zero-shot cloning from WAV reference, 24kHz streaming, MIT/CC-BY,
  community OpenAI-compatible server). (a) measure REAL RSS on this box; (b) clone the
  JP great-sage reference `assets/raphael_reference_jp.wav` once -> persisted state;
  (c) A/B render the exact sample sentences from `assets/reference/samples/` (compare
  against fish output — mind the caveat: accent transfer JP-reference -> English text is
  partial per research); (d) map the streaming path onto brain/voice/tts.py seam
  (community server = possible zero-change drop-in). (e) KittenTTS disqualified (no
  cloning), Voicebox has no released weights — note in report. RULE 14: one-server rule
  binds — prefer OFFLINE inference calls for the eval (no persistent server while fish
  is up); if you need a server window, file a request to integrator first. Deliver a
  recommendation: switch / keep fish / hybrid, with measured numbers.

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Voice pipeline failure modes: **fish death mid-speak recovery** (ONE restart+retry via `_synthesize_resilient`/`_restart_fish`; ownership-safe — only a process WE spawned is stopped, external/supervisor fish is reused; one-time notice "Voice engine restarted mid-reply." on success, loud degraded notice on failure, reference errors NEVER retried; bounded 90 s restart timeout), **STT outage path** (`stt_outage_subtitle()` returns a §10-code-set, secret-free notice so a cloud-STT failure is never a silent drop — wire-up in ws.py is brain-core's file: OPEN request `voice__to__brain-core__stt-outage-subtitle.md`), **audio soak** (`test_soak_*`: 1000 brain segments + 400 VAD open/close cycles, all state asserted bounded — accelerated stand-in for 24h continuity, honest: not a real 24h run), **Bug H regression guards** (async router transcribe awaited + typed error inside a running loop + no coroutine leak, `stt_language: en` loaded AND reaching the provider, wake extract strips ALL leading wake/filler repeats). Tests: `brain/voice/tests/test_wave4_hardening.py` (10).

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Spoken delivery of the new formats: **Report/Answer read-aloud pacing** — `TTSEngine.speak(max_sentences=…)` now caps what is ever *synthesized* at `voice_personality.spoken_reply_max_sentences` (default 2; `0` disables), so fish never burns GPU on unheard audio (Rule 15) while the subtitle/UI keeps the full text; cache + playback-echo registry are keyed by what was actually SPOKEN. **Notice level-tinted phrasing** — `notice_spoken_text(text, level)` (info as-is, warn -> idempotent "Warning: " lead-in, unknown levels coerce like `notice.build()`) + `VoiceStack.speak_notice()`; narrating notices is brain-core's call-site → OPEN request `voice__to__brain-core__speak-warn-notices.md`. **Persona-tier voice profiles (config surface)** — `persona.tier` (env `RAPHAEL_PERSONA_TIER` → config.yaml → config.d/evolution-persona.yaml, fail-closed to great_sage) resolves the reference: great_sage/raphael keep the approved JP reference, ciel gets slot `voice.tts_voice_ciel` (per their §5 design) with LOUD one-time fallback notice when the file is missing; tier flips re-namespace the phrase cache LIVE (no restart). Tests: `brain/voice/tests/test_personality_delivery.py` (11).
- [x] qa residual C1/C2 voice-confirm — **analyzed + reported to the conductor**: (C1) qa's xfail fails BEFORE the voice path — `test_spoken_yes_resolves_pending_confirmation` times out waiting for `needs_confirm` because its text ('echo voice approval path') hits fastpath's `echo ` intent and matches no RISKY pattern, so no confirmation is ever pending; the voice wiring itself EXISTS (ws.py `_clear_yes_no` → `confirmer.resolve_oldest_pending(answer, via='voice')`, and `brain/tests::test_audio_path_listening_and_voice_confirm` passes in the 184-green consumer run). Suggested fix is qa's test text (use a risky-triggering phrase like their other tests). (C2) needs `confirm_resp.channel` in PROTOCOL §9 — integrator/brain-core, already a qa→integrator OPEN request; my `voice_confirmation_answer(..., low_risk=)` encodes the voice-side half.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  - Wave 3: natural-conversation polish (utterance-end handling, interruptions, `spoken_reply_max_sentences` short replies).
  - Wave 4: speaker verification for sensitive confirmations, phrase-bank prebuild tool, second voice-reference slot.
  - Wave 5: persona voices (raphael / ciel reference clips selected by persona.tier).
