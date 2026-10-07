# voice — status

Updated: 2026-10-06 (Wave 2 complete for this lane — handoff below)

## Done (Wave 2, this lane; commits b0124da..d35e9e1)

1. **Instance isolation (AGENT_RULES §5, INTERFACES §d)** — `brain/voice/config.py`
   now derives everything this lane owns from `RAPHAEL_INSTANCE`:
   Fish port (`main`=8777 → unchanged; lane = 8777+index, voice=8781; unknown
   names → deterministic 8800-8876, never 8777 and never the 8901-8910 WS
   range) and the voice log dir (`main` → `brain/voice/logs/` unchanged, other
   instances → `~/.raphael/<instance>/voice/logs`). `RAPHAEL_FISH_PORT` /
   `RAPHAEL_PROFILE` still win over derivation. Unit tests cover all of it.
2. **STT seam (cloud_temp)** — `brain/voice/stt.py`:
   - `profile cloud_temp` → ALWAYS `router.transcribe()` (INTERFACES §a;
     Groq Whisper). PCM is WAV-wrapped before the call (Groq takes a file,
     not bare PCM), silence/sub-150 ms segments are answered locally with `''`
     (nothing leaves the machine), router exceptions map to PROTOCOL §10 codes
     (`E_PROVIDER_429`, `E_OFFLINE`, `E_PROVIDER_AUTH`, `E_TIMEOUT`,
     `E_INTERNAL`).
   - faster-whisper code path is intact and only reachable with
     `profile local` + `voice.stt_engine: local`; under cloud_temp the local
     accessor raises `E_LOCAL_DOWN` and tests stub `Transcriber.load` to fail
     loudly — no local model can load.
   - `profiles.local.voice.stt_engine` overlay now parses (was silently
     ignored before).
3. **Activation (task 2)** — `brain/voice/activation.py` + body echo guard:
   - Pre-STT gate `should_transcribe(pcm, reason)`: silence never transcribed;
     `reason='ptt'` always transcribed (hotkey = intent); wake segments
     dropped when `voice.always_listen: false`; unknown reason fails OPEN.
     Exported as `VoiceStack.should_transcribe()`; `transcribe_result()` now
     takes `reason=None` (keyword).
   - Post-STT: `VoiceStack.wake` is now an `ActivationGate` — the existing
     phonetic `WakeGate` (filler + phonetic-fold matching, unchanged) PLUS
     playback-echo rejection: what Raphael just said (last 8 utterances,
     120 s TTL, ≥3-word fuzzy match) is treated as echo → `kind='none'`, so
     her own "Raphael online." greeting cannot re-trigger a job.
     `brain/ws.py` needed no change for this (it calls `voice.wake.gate(...)`).
   - **Body echo suppression (`body/win/audio_in.py`, `audio_out.py`):**
     `VadSegmenter.echo_guard` raises only the segment-OPEN threshold to
     speech level (400 int16 RMS) while `audio_out.PLAYER.active()` — her
     measured bleed (40-225) can't open a segment, real speech (2000+) still
     opens it, so wake-word barge-in keeps working while she speaks.
     Open-segment hysteresis is untouched (live-tested behavior preserved),
     and the noise-floor EMA freezes during playback (her voice is not
     ambient). This is the one documented threshold addition — it is a
     correctness fix for self-triggering, not tuning.
   - PTT hotkey fallback was already wired body-side (`always_listen: false`
     → PTT stream); brain-side now double-checks it.
4. **TTS (task 3)** — `brain/voice/tts.py`:
   - sentence chunking → Fish → `speak` start/chunk/end JSON + amplitude +
     pitch_hz (unchanged, now covered by mock end-to-end tests incl. the
     PROTOCOL §6 binary wrapper round trip and the 500 ms chunk cap);
   - degraded mode is now **subtitle-only with a ONE-TIME notice**
     (placeholder tone removed; the apology is not repeated on every reply);
   - barge-in: hotkey/wake `audio_start` → `InterruptController` →
     `interrupted` end mid-stream (covered by tests), and the echo guard keeps
     wake barge-in reachable during playback.
   - `speak()` records its text in the playback-echo registry (self-trigger).
5. **Voice confirmation parsing (task 4)** — `brain/voice/confirmation.py`:
   `parse_voice_answer()` → `yes|no|modify|unrecognized`,
   `to_confirm_answer(..., low_risk=)` → `'yes'|'no'|None`.
   High-risk (`low_risk=False`) ALWAYS → `None` (voice is never an accepted
   channel there); conditional speech (`"yes, but only the PDFs"`) → `no`
   (abort + re-ask); unclear → `None` (timeout still aborts, never
   auto-approves). Vocab seeded read-only from `brain/confirm.py` so typed and
   spoken answers agree.
6. **Mock whole-path tests (task 5)** — `brain/voice/tests/test_voice_path.py`:
   fake mic PCM → real `VadSegmenter` → stub `router.transcribe` → wake gate →
   command; fake Fish → `speak` JSON + binary frames with amplitude; cache
   hit; barge-in; degraded subtitle-only; self-trigger loop assertions.

## In progress
- — (Wave 2 items above are all implemented and tested)

## Blocked
- —
- Two OPEN requests await their owners (both are additive, work continues
  without them):
  - `docs/requests/voice__to__integrator__audio-end-pass-reason.md` — ws.py
    should pass `reason` into `voice.transcribe_result` so the always_listen
    half of the pre-gate becomes active (currently fails open).
  - `docs/requests/voice__to__brain-core__voice-confirm-wiring.md` — spoken
    "yes" today cannot resolve a pending confirmation (it becomes a new job);
    needs `confirm.voice_safe(rowid)` + the ws.py resolve branch.

## Honest notes / known gaps
- The phonetic wake gate runs on TRANSCRIPTS, so it cannot literally decide
  *before* cloud STT. What prevents "streaming all audio to the cloud" in
  practice: body VAD segmentation (one utterance = one call), the silence
  short-circuit, the body echo guard (her playback never opens a segment),
  and PTT-only mode. Background human speech in the room IS still transcribed
  (and then rejected by the wake gate) — that is inherent to a transcript
  based wake gate without a local keyword spotter (cloud_temp has no local
  models; the local model code stays profile-gated).
- Barge-in during her speech clears the interrupt registry on `audio_start`
  (ws.py), so a brain-side "was she speaking" energy gate would be dead code;
  echo suppression lives on the body side instead.
- Real Fish / real mic / real Groq runs are NOT done here (AGENT_RULES §5:
  live runs are the integrator's). `brain/voice/tests` has 2 deselected
  `integration` tests that need the Fish server.

## Next
- Per docs/WAVES.md (current_wave: 2): Wave 2 exit criteria are the
  integrator's live E2E; this lane is ready for merge review + the two OPEN
  requests. Wave 3 tasks (utterance-end handling, `spoken_reply_max_sentences`
  short replies) only when WAVES.md bumps the wave (AGENT_RULES §11).

## Test output (real runs only — never claim unrun tests)

```
# voice suite (the lane's documented runner), 2026-10-06
$ brain/.venv/bin/python -m pytest brain/voice/tests -q -m "not integration"
80 passed, 2 deselected in 2.88s

# same suite under an isolated instance (AGENT_RULES §5)
$ RAPHAEL_INSTANCE=voice brain/.venv/bin/python -m pytest brain/voice/tests -q -m "not integration"
80 passed, 2 deselected in 3.19s

# consumers of brain.voice (brain-core loop/ws + router), no regressions
$ brain/.venv/bin/python -m pytest brain/tests brain/router/tests -q
40 passed, 1 warning in 9.52s

# full repo run in qa-security's lean venv (python3.14, no soundfile /
# faster-whisper installed there) — 6 failures, ALL pre-existing and verified
# identical on a stashed baseline (missing soundfile/faster-whisper in that
# venv); my new TTS-dependent tests skip cleanly there instead of failing
$ tests/.venv/bin/python -m pytest -q .
6 failed, 122 passed, 4 skipped, 3 warnings in 27.47s
```

Not run (on purpose): anything that spawns Fish, opens a real microphone,
registers a hotkey, or calls a live provider (AGENT_RULES §5, INTERFACES §d).
