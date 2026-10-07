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

## Done (flake hardening, coordinator task 2026-10-06)

Root cause of "fails 2/3 at plain `pytest brain/voice/tests`, 5-7 failures
while suites run in parallel, green in isolation" — NOT timing sleeps (the
suite has none): **cross-suite session state + a nondeterministic integration
gate**. Reproduced with `pytest brain` (combined session) → 6 failures, then
fixed:

1. **Env leak from `brain/tests/test_config.py:62`** (`os.environ
   ['RAPHAEL_PROFILE']='local'`, raw write, never restored) → my config test
   now pins/deletes `RAPHAEL_PROFILE` + `RAPHAEL_STT_ENGINE` itself via
   `monkeypatch` (immune to whatever the session inherited). Request filed:
   `docs/requests/voice__to__brain-core__test-isolation-hygiene.md`.
2. **`VoiceStack.speak` class-patched session-wide** by
   `brain/tests/conftest.py` (their hermetic TTS mock, installed at import
   time and never undone) → 4 `test_voice_path` tests got `['start','end']`.
   My pipeline tests now go through **`voice.tts.speak`** (the real engine —
   the correct seam anyway), and one explicit delegation test asserts
   `VoiceStack.speak` forwards to the engine, **skipping honestly** when
   another suite's mock is installed instead of failing on their session
   state.
3. **Integration tests spawned Fish** (up to 240 s startup, GPU contention,
   port races — and a rule violation: INTERFACES §d says lanes never spawn
   Fish) → new `_require_fish()` gate: **skip unless a server is already
   healthy**; `RAPHAEL_FISH_SPAWN=1` is the explicit integrator opt-in.
   Unit-tested both branches (no network: health/stubbed).
4. **Mid-test fish death asserted instead of skipping** → environmental
   (fallback/no-audio/empty-ASR) outcomes now skip with the reason; a
   wrong-but-non-empty transcript still FAILS, so the real signal stays.
5. **TOCTOU in phrase-cache eviction** (`exists()` then `unlink()`, and
   non-atomic `write_bytes` letting a concurrent reader see a half file) →
   `unlink(missing_ok=True)` + **atomic `store()`** (temp file + `os.replace`),
   which also protects the live stack's cache.
6. **Wall-clock rtf assertion** → deterministic stubbed clock
   (`brain.voice.stt.time` patched in-test; `rtf == 0.25` exactly).
7. **Nondeterministic ASR language auto-detect** in the round-trip test
   (the one failure that survived every other fix) → `language="en"` pinned
   (we synthesized English) and the bogus 24 kHz whisper pass removed.
8. **Optional-dep failures in lean venvs** → `pytest.importorskip` for
   `soundfile`/`faster_whisper`: the root suite in qa's python3.14 venv went
   from **6 failed → 0 failed** (5 skips + my subtitle-only fallback fix let
   `brain/tests/test_ws.py`'s speak test pass there too).

## In progress
- — (flake-hardening task complete; awaiting `wave_open`)

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

## Handoff (voice lane, Wave 2 — READY FOR MERGE REVIEW)
- Scope delivered: everything in `docs/lanes/voice.md` Wave 2 (session brief
  items 0-5), 6 commits `b0124da..8ead9d3` on `agent/voice`, no files outside
  this lane's owned paths except the two `docs/requests/` files (its own
  mechanism) and `docs/{lanes,status}/voice.md` (its own docs).
- Not run here, on purpose (integrator's job): real mic, real Fish, real
  Groq, the live stack (AGENT_RULES §5/§12 — the scheduled task stays
  Disabled).
- Dependencies this lane waits on: router must implement
  `brain.router.transcribe()` (INTERFACES §a) before live voice STT works;
  `router.transcribe` is already consumed + mocked in the tests.
- Merge-order position: `voice` merges after `pc-control` (WAVES.md) — the
  only cross-file touch point is `body/win/audio_*` (owned by this lane).
- To resume: read this file + `docs/lanes/voice.md`; the two OPEN requests
  need their owners' decisions.

## Test output (real runs only — never claim unrun tests)

### Flake-hardening verification (2026-10-06, post-fix)

```
# lane suite (integration included; fish DOWN -> deterministic skips, no spawn)
$ brain/.venv/bin/python -m pytest brain/voice/tests -q
84 passed in 10.75s            (earlier run under GPU contention: 82 passed, 2 skipped — 0 failed either way)
$ brain/.venv/bin/python -m pytest brain/voice/tests -m integration -q -rs
SKIPPED [2] fish server not running — lanes never spawn Fish (INTERFACES §d); start it or set RAPHAEL_FISH_SPAWN=1
2 skipped, 82 deselected in 6.79s

# combined session (the exact repro: 6 failures before the fix)
$ brain/.venv/bin/python -m pytest brain -q
290 passed, 1 skipped in 40.28s       # before: 6 failed, 283 passed

# PARALLEL load (the pc-control scenario) — all green, exit code 0
3x concurrent `pytest brain`            -> 290+290+289 passed, 0 failed
2x concurrent `pytest brain` + 1x voice -> all rc=0
3x concurrent round-trip/fish subset x3 rounds -> 9/9 rc=0

# qa's lean root venv (python3.14, no soundfile/faster-whisper)
$ tests/.venv/bin/python -m pytest -q .
395 passed, 10 skipped, 1 failed         # before: 6 failed, 122 passed
  the 1 failure is NOT lane-owned: tools/conductor/tests/test_e2e.py::
  TestCoordE2E::test_full_scenario — passes alone (1 passed in 3.83s),
  fails only in the full root run (shared ~/.raphael-coord state; my lane
  lock is held by design). Reported to the coordinator, not touched by me.
```

### Earlier Wave 2 runs

```
$ brain/.venv/bin/python -m pytest brain/voice/tests -q -m "not integration"
80 passed, 2 deselected in 2.88s
$ RAPHAEL_INSTANCE=voice ... -m "not integration"
80 passed, 2 deselected in 3.19s
$ brain/.venv/bin/python -m pytest brain/tests brain/router/tests -q
40 passed, 1 warning in 9.52s
```

Not run (on purpose): anything that spawns Fish, opens a real microphone,
registers a hotkey, or calls a live provider (AGENT_RULES §5, INTERFACES §d).
