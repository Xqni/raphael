# Wave 2 — Brain phase 3: Integration Seams

Date: 2026-10-05. Status: **IN PROGRESS**.

## Objectives
1. Mic Lane: `audio_start` → binary frames → `audio_end` → `voice.transcribe` → `engine.submit`.
2. Speak Lane: `voice.speak` iterator → `hub.broadcast` (JSON) + `hub.send_binary` (PCM).
3. Barge-in: `audio_start` during speech → `voice.interrupts.interrupt()`.
4. Act Pipeline: loop GUI-class tools → `act_req` to body → `act_res` awaiting.
5. Verification: Pytest + live round-trip for act/speak.

## Implementation Log
(Updates to follow)
