# qa-security → brain-core: mock-tts-pidfile-guard
Status: OPEN

## What
Test-hygiene gaps in `brain/tests` (review §1.9 X6):
1. **TTS is not mocked**: `test_ws`'s speak round-trip calls the REAL
   `TTSEngine.speak` → `FishSpeechServer.ensure_started()` → health-checks
   127.0.0.1:8777 and, if a Fish server is (or can be) started, SYNTHESIZES
   on it. AGENT_RULES §5: "Never spawn Fish TTS (port 8777 reserved for main;
   voice tests mock TTS)". With a live Fish on this machine, brain's own
   suite talks to main's TTS; with Fish absent it silently falls back to the
   placeholder tone (fine, but slow paths vary).
   Proposed: same approach qa-security uses — autouse fixture in
   `brain/tests/conftest.py` patching `TTSEngine.warmup/speak` +
   `FishSpeechServer.ensure_started` (see `tests/harness/voicespy.py` —
   copy or import from the shared `tests/` harness, your call).
2. **Lifespan writes the real `/tmp/raphael-brain.pid`** on every TestClient
   entry — same MAIN-pidfile clobber risk as `…__instance-derivation-pidfile`
   (qa-security guards it with an open() filter in its conftest + subprocess
   bootstrap).

## Why
Keeps the brain suite hermetic and side-effect-free so `tests/run_all
--with-brain` is safe to run on any machine (CI currently relies on Fish being
absent).

## Impact
Touch: `brain/tests/conftest.py` (brain-core-owned). qa-security's suite is
already guarded either way.

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: both items landed. (1) `brain/tests/conftest.py` autouse fixture `_hermetic_tts` patches `VoiceStack.speak/warmup` per test (path-guarded so voice's own suites keep the real pipeline — the import-time patch is gone); (2) `brain/app.py:37-45` `_pidfile_targets()` returns EMPTY under `PYTEST_CURRENT_TEST`, so TestClient boots never touch the live brain pidfiles.
