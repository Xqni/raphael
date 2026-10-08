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

## Wave 3 — Bug D (JP great-sage voice on EVERY speech) + Rule 14 fish kill-safety (2026-10-07)

**Coordinator inbox addressed:**
- **#5 (inventory / stitch / A-B)** — **already satisfied by the integrator's
  run, nothing for me to switch**: `assets/reference/` no longer exists on
  disk (no clips left to inventory), `assets/raphael_reference_jp.wav` IS
  present (751686 bytes), `config.yaml voice.tts_voice` already points at it,
  and Bug D records the user heard + approved the A/B. I made no auto-switch;
  the config value was the integrator's (user-approved).
- **#6 (spawn-kill-safe test)** — DONE, see below.
- **#9 (user directive -> Bug D)** — code DONE; live proof pending fish (below).

**Bug D fixes (`brain/voice/tts.py`, `brain/voice/config.py`):**
1. **LOUD reference loading** — `check_reference()` / `_references()` raise
   `TTSError` when `voice.tts_reference_required` (default **True**) and the
   file is missing/empty/unreadable. speak() then degrades with a specific
   subtitle notice (`Voice reference unavailable ...`) + `[tts] BLOCKED
   (reference)` log and **zero audio chunks** — the silent default-voice path
   (suspect #1) is gone. Only `VoiceConfig(tts_reference_required=False)`
   opts out (tests/tooling). `warmup()` logs the reference at boot too.
2. **Proof per synthesis** — `[tts] ref sent: path=... bytes=... sha1=...
   sentence=...` (flushed -> brain log) on EVERY sentence.
3. **Phrase cache namespaced by reference** — `assets/acks/<sha1(ref)[:12]>/`
   (now `f64bd512ea1e`); the stale Zira-era top-level hash
   `assets/acks/9c03c5b020d75c39.wav` is unreachable (tested).
   `TTSEngine.refresh_reference()` re-namespaces automatically when the ref
   file changes — no restart, old-voice wavs dead from the first chunk.
4. **fish's text-keyed memory cache off** — `use_memory_cache: "off"`
   (suspect #3); value verified against the vendored schema
   (`tools/schema.py: Literal["on","off"] = "off"`).
5. **Suspect #1 (CWD) ruled out** by test: `tts_voice_path` resolves against
   REPO_ROOT regardless of process CWD.
6. Defaults (`VoiceConfig.tts_voice` + loader fallback) now point at the JP
   reference, so direct constructions use it too.

**Rule 14 / inbox #6 — spawn-kill-safe fish fixture:** integration tests skip
unless a server is already reachable; with explicit `RAPHAEL_FISH_SPAWN=1` a
spawned server is registered in `_SPAWNED_SERVERS` and killed (a) after EVERY
test via an autouse fixture and (b) at process exit via `atexit`
(`_kill_spawned_fish` -> SIGTERM/SIGKILL on the process group). A server we
did NOT spawn is never touched (reuse, don't kill). Kill path unit-tested
without real processes.

### Test output (real runs; one suite at a time per Rule 14)

```
$ brain/.venv/bin/python -m pytest brain/voice/tests -q -rs
93 passed, 2 skipped in 2.46s     # 2 skips = fish down (deterministic, no spawn)
$ brain/.venv/bin/python -m pytest brain/tests -q
125 passed in 9.80s
$ brain/.venv/bin/python -m pytest brain/router/tests -q
92 passed in 27.57s
$ brain/.venv/bin/python brain/voice/scripts/prove_reference.py
configured reference : /home/dami/raphael-wt/voice/assets/raphael_reference_jp.wav
exists               : True (751686 bytes)
fingerprint          : f64bd512ea1e
reference_required   : True
phrase-cache dir     : .../assets/acks/f64bd512ea1e/  (namespaced per reference)
FISH NOT REACHABLE at http://127.0.0.1:8777 — this script never spawns it ...
exit=3 ; orphan check after run: zero (no tools.api_server process)
```

### Live proof status: PENDING fish reachability

INTERFACES §d + Rule 14: the voice lane does not spawn fish. At the next
bring-up (or ping me when the stack is up — I'll render one phrase and post
the log line):

```
brain/.venv/bin/python brain/voice/scripts/prove_reference.py
# expect exit 0 +: [tts] ref sent: path=.../assets/raphael_reference_jp.wav bytes=751686 sha1=f64bd512ea1e
grep -m1 '\[tts\] ref sent' logs/*.log      # same line from a REAL live answer
```

## Wave 3 pre-handoff verification (2026-10-07, post-rebase)

Inbox [10]: live-proof request **ACCEPTED** — the integrator runs
`prove_reference.py` at the next user-gated live bring-up and it is on the
wave-3-close gate checklist (`docs/BUGS-WAVE2.md`). Lanes never spawn fish —
the conductor confirmed the correct call.

Rebased onto main (`43ea91b`, over brain-core's wave-3 merge) and re-verified
ONE suite at a time (Rule 14):

```
$ brain/.venv/bin/python -m pytest brain/voice/tests -q
93 passed, 2 skipped in 2.57s     # skips = fish down, deterministic, no spawn
$ brain/.venv/bin/python -m pytest brain/tests -q
152 passed, 1 warning in 11.45s, rc=0
  (first attempt was killed by an external SIGKILL — no OOM, no parallel
   suite found, no orphan left; immediate retry green, recorded honestly)
orphans after runs: zero (ps: no tools.api_server)
```

Voice lane Wave 3 list = **DONE** (Bug D + spawn-kill-safe fixture + SPEED
verified). Posting `wave_done`; queued at merge position 4 (after pc-control).

## Wave 4 — voice pipeline failure modes (2026-10-07)

Rebased on main first; the live stack was UP by user directive — fish was
**reused, never spawned** (Rule 14 / INTERFACES §d).

1. **fish death mid-speak recovery** (`brain/voice/tts.py`):
   `_synthesize_resilient()` = ONE restart + single retry per utterance
   (`_restart_fish`, bounded 90 s). Ownership rule enforced: we only
   `stop()` a process **we** spawned (`fish.proc` set) — an externally
   managed/supervisor fish is merely re-checked and reused (tested:
   `stop_calls == 0`). Success → one-time subtitle notice
   "Voice engine restarted mid-reply."; failure → the loud degraded notice,
   zero fake audio; **reference errors are never retried** (Bug D outranks
   recovery).
2. **STT outage path**: `stt_outage_subtitle(code, detail)` in
   `brain/voice/stt.py` — brief, secret-free notice restricted to the
   PROTOCOL §10 surfaceable code set (fatal/internal → None, raw detail never
   shown). The ws.py call-site is brain-core's file → OPEN request
   `docs/requests/voice__to__brain-core__stt-outage-subtitle.md` (4-line
   snippet included). Seam-level proof: a router outage raises typed
   `E_OFFLINE` → helper returns the subtitle (test).
3. **audio soak (accelerated, honest)**: `test_soak_brain_segment_flow_stays_bounded`
   = 1000 full segments (buffer → pre-gate → stub cloud STT → wake gate →
   interrupt register/done → echo registry) and
   `test_soak_vad_segmenter_state_stays_bounded` = 400 VAD open/close cycles;
   every state container asserted bounded (pre-roll ≤3, evidence ≤5, cancel
   dict empty, echo deque ≤8, ends idle). This is a deterministic stand-in
   for the 24 h continuity run — **not** a real 24 h soak.
4. **Bug H regression guards**: (a) async `router.transcribe` is awaited in
   the to_thread bridge AND fails typed (`E_INTERNAL`, "to_thread") inside a
   running loop, closing the coroutine (no ResourceWarning); (b)
   `stt_language: en` is actually loaded from config and reaches the provider
   call; (c) wake `extract()` strips ALL leading wake/filler repeats
   ("Raphael raphael …" → clean command).

### Live proof captured (Bug D gate line — fish reused, not spawned)

```
$ brain/.venv/bin/python brain/voice/scripts/prove_reference.py
configured reference : .../assets/raphael_reference_jp.wav   (751686 bytes)
fingerprint          : f64bd512ea1e   reference_required: True
phrase-cache dir     : .../assets/acks/f64bd512ea1e/
[tts] ref sent: path=.../assets/raphael_reference_jp.wav bytes=751686 sha1=f64bd512ea1e sentence='Analysis complete.'
engine: fish | chunks: 272 (1629484 bytes) | PROOF OK | exit=0
```

### Test output (real runs, one suite at a time — Rule 14)

```
$ brain/.venv/bin/python -m pytest brain/voice/tests/test_wave4_hardening.py -q
10 passed in 0.62s
$ brain/.venv/bin/python -m pytest brain/voice/tests -q -rs
104 passed, 1 skipped in 8.52s
  (integration tests ran against the REAL live fish + JP reference;
   the 1 skip = an intelligibility check that needs local whisper — environmental)
orphans after runs: zero (no tools.api_server spawned by me)
```

## Wave 5 — spoken delivery + persona-tier voice profiles (2026-10-07)

Rebased on main first; no requests addressed to this lane.

1. **Report/Answer read-aloud pacing** — `TTSEngine.speak(max_sentences=)`
   caps SENTENCES SYNTHESIZED at `voice_personality.
   spoken_reply_max_sentences` (loaded by the voice config; default 2; `0`
   disables). loop's `_SentenceSpeaker` already limits what it forwards, so
   this is the voice-layer guarantee for every OTHER caller (narrate(),
   REST `/say` with `max_sentences=0` opt-out) — and it means fish never
   synthesizes audio nobody hears (Rule 15). The echo registry + phrase cache
   are now keyed by the SPOKEN text, so a later cap change can't replay the
   wrong audio.
2. **Notice level-tinted phrasing** — `notice_spoken_text(text, level)`
   (info unchanged; warn gets an idempotent `Warning: ` lead-in; unknown
   levels coerce exactly like `brain/notice.build()`) + `VoiceStack.speak_
   notice(text, level=...)` speaking it through the normal stream. Notices
   are broadcast-only today, so the narrate call-site is brain-core's →
   OPEN request `docs/requests/voice__to__brain-core__speak-warn-notices.md`.
3. **Persona-tier voice profiles (config surface)** —
   `persona.tier` resolution: `RAPHAEL_PERSONA_TIER` → config.yaml →
   `config.d/evolution-persona.yaml` (read-only), fail-closed to
   `great_sage` (same rule as their `tier_of()`; the tier can never
   self-promote). Reference resolution (`VoiceConfig.tier_voice_path()`):
   - great_sage / raphael → `voice.tts_voice` (the approved JP reference —
     the raphael tier keeps "the current voice" per their tier table),
   - ciel → `voice.tts_voice_ciel` slot (exactly the key their design §5
     specifies, default `assets/ciel_reference.wav`), missing slot →
     fall back to the approved reference + ONE-TIME subtitled notice
     (never a default voice — Bug D intact),
   - tier flips re-resolve on the next `speak()` (`refresh_reference()`)
     and re-namespace the phrase cache LIVE — old-tier audio unreachable.
4. **qa residual C1/C2 analysis (reported, not lane-owned):**
   - C1 xfail fails BEFORE any voice code: its command text
     ('echo voice approval path') matches fastpath's `echo ` intent and no
     RISKY pattern → `needs_confirm` never fires → the test times out waiting
     for it (verified with `--runxfail`). The voice wiring EXISTS
     (ws.py `_clear_yes_no` → `resolve_oldest_pending(answer, via='voice')`)
     and brain's own `test_audio_path_listening_and_voice_confirm` passes in
     the 184-green consumer run. Suggested: qa re-targets the test at a
     risky-triggering phrase (as their other tests do).
   - C2 needs `confirm_resp.channel` in PROTOCOL §9 → integrator/brain-core
     (their existing qa→integrator request); my
     `voice_confirmation_answer(..., low_risk=False → None)` already encodes
     the voice-side rule.

### Test output (real runs, one suite at a time — Rule 14)

```
$ brain/.venv/bin/python -m pytest brain/voice/tests/test_personality_delivery.py -q
11 passed in 0.24s
$ brain/.venv/bin/python -m pytest brain/voice/tests/test_reference.py \
      brain/voice/tests/test_personality_delivery.py -q
21 passed in 0.27s
$ brain/.venv/bin/python -m pytest brain/voice/tests -q
115 passed, 1 skipped in 7.81s      # skip = whisper intelligibility (environmental)
$ brain/.venv/bin/python -m pytest brain/tests -q          # consumer
184 passed, 1 warning in 14.91s
$ tests/.venv/bin/python -m pytest tests/regression/test_confirm_flow.py -q -rxX
17 passed, 2 xfailed   # C1/C2 tripwires (analysis above)
orphans: zero (no fish spawned)
```

## Wave 5 — PocketTTS evaluation (task 2026-10-07)

Full report: **`brain/voice/EVAL-pockettts.md`** (all numbers, table, integration
map, recommendation). Scripts: `brain/voice/scripts/eval_pockettts.py` (offline,
Rule 14 — never spawns a server) + `eval_ab_compare.py` (reuses the live fish
server). Artifacts: `~/.raphael/voice/eval/{fp32,q_int8,fish}/` (outside git).

Headline numbers (this box, measured):
- **RSS peak 1.45 GB** (load 1.23 GB; +89 MB over 15 renders → no balloon on
  v3.2.x in-process; int8 = same RAM, buys speed only: RTF ×3.0 → ×4.4).
- **Speed: PocketTTS RTF ×3.0 (fp32) / ×4.4 (int8) vs fish ×0.5** → ~6–9×
  faster; **first audio 79 ms** (48 ms int8) vs fish's 2.5–8.4 s per sentence —
  attacks the known `TTS latency 13.4s/phrase` pain, frees the RTX 4060.
- **A/B on the 5 live-stack sentences** (fish real payload vs pocket catalog
  voice): pocket intelligibility **1.00 everywhere**, auto-lang `en`;
  fish 0.14–0.96 = the JP accent defeating EN-ASR (hypotheses show heavy
  mangling) — an ASR artifact, not a quality verdict; the OUR-voice A/B is the
  switch gate.
- **BLOCKED (b)**: `kyutai/pocket-tts` is `gated:auto` + prohibited-use form;
  our token only received `kyutai/pocket-tts-without-voice-cloning` →
  `get_state_for_audio_prompt` refuses cloning. We did NOT accept terms on the
  user's behalf. Ask posted to coord: user accepts the HF gate once → rerun →
  `great-sage.safetensors` + our-voice A/B → user listens → switch decision.
- Recommendation: **HYBRID now (fish stays live) → SWITCH after the clone gate
  + user's ear.** KittenTTS disqualified (no cloning), Voicebox not installable.
- Rule 14: both eval processes ran offline and exited; orphan checks after
  every run = zero; fish server untouched (health-checked, reused, never
  spawned).

## P0 2026-10-07 — lost JP accent + speaking gaps (fix FIRST)

**Verdict: both root-caused, fixed, live-purged, re-proven.** Details with
numbers in `docs/lanes/voice.md` "## P0" (checkboxes). Summary:

1. **Accent (stale cache):**
   - 18 flat wavs (all Zira-timbre, cos 0.84-0.98 vs Zira) → swept to
     `~/.raphael/cache_swept/`; **0 non-namespaced wavs remain** (acceptance).
     Code: `sweep_legacy_cache()` runs at every engine init (`shutil.move` —
     `os.replace` was EXDEV-failing silently on tmpfs tests), hex-named only.
   - Real poison: ONE off-voice entry INSIDE the JP namespace
     (`2a9906eaed4e87a3`, cos 0.643) → purged. 9 JP entries kept (0.797-0.968).
   - fish suspect refuted from vendored source: memory cache is keyed by
     **sha256(reference audio)** (not text) and `use_memory_cache:"off"`
     re-encodes our reference per call; A/B showed no speed gain for "on".
   - **Durable fix: `STORE_MIN_COS=0.65` timbre gate on every cache write**
     (measured split: ours 0.74-0.98 / wrong voices ≤0.64; blind spot = flat
     noise, which fish does not produce — documented). Off-voice renders play
     live but are never cached → a wrong voice can never be REPLAYED.
   - **Re-probe: 12/12 renders ≥0.65 (every phrase JP both times)** + cache
     isolation (2nd speak = hit of first) ✓.
2. **Speaking gaps (42% never played):**
   - Root cause in `body/win/audio_out.py` (mine): ws_client fires `end`
     handling as a **detached task**, next sentence's `start` called
     `reset()` which CLEARED the still-draining tail (fits the logs:
     utterance B: in +73560, out +0).
   - Fix: `reset()` keeps pending audio < 2.5s old (continuous playback),
     drops only stale leftovers and **counts** (`dropped`/`kept` in stats);
     `finish()` deadline now logs+counts what it abandons.
   - Remaining inter-sentence pauses = fish generation (2-3s/sentence,
     RTF ×0.5, inherent; fish cache lever A/B'd — no gain).
   - Mock tests: `brain/voice/tests/test_p0_fixes.py` (9 tests).
3. **Proof + samples:** 4-sentence uncapped reply rendered complete through
   the real engine (48 chunks / 5.80s / valid §6 frames); samples copied to
   `assets/reference/samples/`: `P0_BEFORE_offvoice_cached.wav`,
   `P0_BEFORE_zira_era_cached.wav`, `P0_AFTER_jp_voice_fresh.wav`,
   `P0_AFTER_3sentence_reply_uncapped.wav`.

### Test output (real runs)
```
$ brain/.venv/bin/python -m pytest brain/voice/tests -q
125 passed, 1 skipped in 13.16s     (first attempt: external SIGKILL #4, reported)
$ brain/.venv/bin/python -m pytest brain/tests -q
192 passed, 1 warning in 16.05s
orphans: zero (fish reused for renders, never spawned)
```

### Requires restart to take live effect (requested from coord)
- **body** restart → new `audio_out.py` (the 42% loss fix); post-restart
  proof: body log line shows `dropped=0, kept>0` on a multi-sentence reply.
- **brain** restart → timbre gate + auto-sweep active (live data was already
  purged directly, so accent is fixed even before restart).

## P0 follow-up — the 12.23s brain-side hole (finish P0)

Root cause (with fish-server evidence): **per-sentence speak cadence** — fish
generates serially at ~RTF 0.5 (per-request 2-9s; 11.81s for one 145-token
dense request; 26.4s when ANOTHER client's request queues ahead of ours),
and while sentence N+1 generates, NOTHING is sent → the body drains → hole.
The integrator's probe (mean 138ms, ONE 12230ms hole) matches exactly.

Fix in `TTSEngine.speak()` (`brain/voice/tts.py`):
- **reply-level pre-roll**: multi-sentence replies are synthesized first,
  then burst-sent — the body never starves (single-sentence replies and cache
  hits unaffected: no added latency);
- **adaptive early-start**: as soon as buffered audio ≥ 1.3× estimated
  remaining generation, speaking begins and the tail streams in;
- **hard budget** `RAPHAEL_TTS_PREROLL_S` (default 60s, 0 disables → old
  behavior): beyond it we stream live (logged "gaps possible") so a stuck fish
  can never hang a reply; one-time notice when pre-roll >8s
  ("Preparing the full reply — one moment.");
- fish-death recovery wait tightened 90s → 8s (never stalls a stream long).

Measured (`brain/voice/scripts/p0_gap_probe.py`, same metric as the
integrator's WS probe):
| run | chunks | mean gap | max gap | holes >350ms |
|---|---|---|---|---|
| baseline (integrator) | 91 | 138 ms | **12 230 ms** | 1 |
| after fix (cached reply) | 210 | 0.0 ms | **1.0 ms** | **0** |
| after fix (cached, 2nd run) | 228 | 82.7 ms | 0.0 ms* | 0 |
| after fix (FRESH, 8-sentence stress, contended) | 228 | — | 18 782 ms | 1 (budget hit at 7/8 — expected fallback, logged) |

* p95 = 0 in all post-fix runs.
Honest limits: (1) a fresh reply whose TOTAL generation exceeds the budget
falls back to streaming (by design — budget vs holes tradeoff); when fish is
slower than realtime across a whole reply, gapless requires waiting (the
notice covers UX). (2) The streamed-LLM path (one `speak()` per sentence in
`loop.py::_SentenceSpeaker`) is brain-core's cadence → OPEN request
`docs/requests/voice__to__brain-core__streamed-sentence-batching.md`.
- Contract tests: `brain/voice/tests/test_p0_fixes.py` — **13 passed**
  (preroll-all, adaptive-start, budget-fallback, single-sentence no-delay,
  reset-keeps, stale-drop, sweep, timbre gate, stats).

### Test output
```
$ brain/.venv/bin/python -m pytest brain/voice/tests -q
129 passed, 1 skipped in 14.85s
$ brain/.venv/bin/python -m pytest brain/tests -q
192 passed, 1 warning in 15.08s
orphans: zero (fish never spawned by this lane)
```

### Pending on fish availability
The final **fresh** 4-sentence acceptance re-run (`p0_gap_probe.py --fresh`)
could not complete — the live fish server went down mid-session and this lane
never spawns it (INTERFACES §d / Rule 14). Re-run when the stack's fish is
back: `brain/.venv/bin/python brain/voice/scripts/p0_gap_probe.py --fresh`
(expect: zero holes >350ms while fish is uncontended; the budget-fallback
path logs loudly if not).

## Wave 5H — audit packet `docs/audit-tasks/voice.md` (verify-first)

**SEC-3: CONFIRMED → FIXED (P0).**
- Quote (pre-fix, `brain/voice/activation.py:147-150`, verbatim):
  `# reason unknown/None -> caller has not told us; do not drop audio` /
  `return GateDecision(True, reason or "unknown")` /
  `except Exception:  # noqa: BLE001 — activation must never break audio` /
  `return GateDecision(True, "error_fail_open")` — **fail-open on BOTH paths**
  (unknown reason AND gate exception).
- Chain quoted: `brain/ws.py:747` `asyncio.to_thread(voice.transcribe_result, buf, reason=reason),`
  → `brain/voice/__init__.py:78-85` `VoiceStack.transcribe_result` (gate then
  `self.stt.transcribe`) → `brain/voice/activation.py::should_transcribe` →
  `brain/voice/stt.py` CloudTranscriber (provider).
- Fix: verdict required — `reason='ptt'` or `'wake'` allowed; unknown/missing
  reason → `GateDecision(False, f"undecided:{reason!r}")`; any gate exception →
  `GateDecision(False, "error_fail_closed")` + loud log. No cloud upload, no
  disk write without a wake/ptt verdict; PTT/wake paths unchanged.
- **Tripwire (gate exit criterion)**: `brain/voice/tests/test_sec3_gate.py` —
  undecided reasons (`None`, `""`, `"bogus"`, `42`) → provider call count **0**
  + zero files in the ack cache; gate exception → fail-closed + 0 provider
  calls; ptt/wake still reach the provider (2 calls); silence short-circuit
  unchanged. Suite: voice **133 passed / 2 skipped**, consumer brain **194 passed**.

**SEC-9: CONFIRMED → FIXED.**
- Quote (pre-fix, `body/win/audio_in.py:11-22`, verbatim):
  `def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):` /
  `subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet',`
  `('%s==%s' % (pkg, pin)) if pin else pkg])` / `_ensure_pkg('sounddevice', pin='0.5.1')`
  / `_ensure_pkg('numpy', pin='2.2.6')`.
- `body/win/audio_out.py` — **NOT-APPLICABLE for pip** (imports were bare:
  `import numpy as np` / `import sounddevice as sd`, no install call), but it
  got the same fail-loud wrapper for a clear error.
- Fix: `_require_or_die(pkg, pin)` in both audio modules → `RuntimeError`
  naming the package, the pin, and the provisioning command; zero pip calls
  remain (grep-verified: only docstring mentions).
- Hashed env: `brain/voice/body-audio-requirements.txt` — pins
  `numpy==2.2.6`, `sounddevice==0.5.1` (+`cffi==2.1.1`, `pycparser==3.0`)
  with sha256 for linux cp312 **and** win_amd64 cp312 (wheels from PyPI,
  hashes via `pip hash`). Verified:
  `pip install --dry-run --require-hashes --platform manylinux2014_x86_64 --python-version 3.12 …` → rc 0
  and `--platform win_amd64 …` → rc 0.

**F-5: ALREADY-DONE (user decision) + record WRITTEN.**
- Decision of record: **keep fish-speech** (user's word 2026-10-07);
  one-page record at **`docs/voice/TTS-DECISION.md`** (measured table, blind
  A/B protocol, latency threshold ask→first-audio ≤3.0 s, reopen criteria =
  RAM upgrade + user HF-gate acceptance + user's word). No default switch
  made (F-5 rule).
- Blind A/B samples prepared: `~/.raphael/voice/eval/decision_ab/`
  (`line01..05_{A,B}.wav`, randomized labels, sealed `KEY.txt` + `README.txt`;
  same 5 canonical lines, same machine) — for the user's ear.
- **Rule 15 ask→first-audio before/after:** before (fish live) **2.49–9.76 s**
  fresh / **0.015 s** cached; after (PocketTTS candidate) **79 ms** first
  stream chunk (int8 48 ms). ≈30–120× faster — recorded as the REOPEN reason,
  not a switch.

**Scope note (packet rule "ONLY the IDs below"):** the earlier chat request
SEC-1 (anime-derived tracked refs) is NOT in the registered packet. For the
record, current tracked files (`git ls-files assets/`):
`assets/raphael_reference.wav` (synthesized Zira v1 — `docs/VOICE_DATA_SPEC.md:5`
"SYNTHESIZED reference … Microsoft Zira SAPI") and
`assets/raphael_reference_jp.wav` (stitched from the 3 Raphael-slime clips —
`PROGRESS.md:341` "stitched 3 clean clips"; anime sources themselves live
under `assets/reference/` which is gitignored). History scrub = human-gated,
no action taken.

### Test output (real runs, one suite at a time — Rule 14)
```
$ brain/.venv/bin/python -m pytest brain/voice/tests -q
133 passed, 2 skipped in 6.34s     (2 skips = fish not running / env, no spawn)
$ brain/.venv/bin/python -m pytest brain/tests -q
194 passed, 1 warning in 15.38s
$ pip install --dry-run --require-hashes … (linux + win_amd64 targets)
rc 0 / rc 0
orphans: zero (stack down; no server spawned by this lane)
```
