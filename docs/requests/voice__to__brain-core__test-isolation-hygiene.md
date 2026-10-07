# voice → brain-core: session-wide test state leaking into other suites
Status: OPEN

## What
Two isolation issues in `brain/tests/` that make OTHER lanes' tests fail when
the suites run in one session (reproduced on main: `pytest brain` → 6 failures
that are green in isolation; all caused by these):

1. **Raw env leak** — `brain/tests/test_config.py:62`:
   ```python
   os.environ['RAPHAEL_PROFILE'] = 'local'     # raw write, never restored
   ```
   The module's `_clean_env` fixture uses `monkeypatch.delenv(...)` (tracked),
   but this line writes DIRECTLY, so the variable stays set for every later
   test in the session. `brain/voice/tests/test_instance.py::
   test_yaml_and_profile_overlay_parse` then read `profile == 'local'`.
   **Fix:** `monkeypatch.setenv('RAPHAEL_PROFILE', 'local')` (auto-restored).

2. **Import-time class patch** — `brain/tests/conftest.py:41-44`:
   ```python
   VoiceStack.speak = _fake_speak       # hermetic TTS mock for this suite
   VoiceStack.warmup = _fake_warmup
   ```
   Applied at conftest import, never undone → every later test in the session
   gets `['start','end']` instead of the real speak stream (broke 4
   `brain/voice/tests/test_voice_path.py` tests on main).
   Hermetic-TTS is the right call for your suite (INTERFACES §d — voice tests
   mock TTS); the scope is the problem. **Fix:** install it from an autouse
   fixture with setup/teardown restore instead of at import time — same
   hermeticity for `brain/tests`, no cross-suite bleed. If session-wide is
   intentional, say so and I'll keep my current workaround (documented below).

## Why
flake-hardening assignment (conductor, 2026-10-06): `pytest brain/voice/
tests` failed 2/3 intermittently and pc-control saw 5 failures while suites
ran in parallel — green in isolation. Root-caused to these two leaks.

## Impact
- voice-side mitigations ALREADY landed (no blocker either way): my tests
  pin their own env with `monkeypatch.delenv`, exercise the real pipeline via
  `voice.tts.speak`, and skip the `VoiceStack.speak` delegation assert when
  the mock is installed (`inspect.getsource` check).
- Your side is a 1-line + fixture-scoped change; no shared-contract change,
  no Core Guard involvement (AGENT_RULES §8).
- Untested-by-me risk: some `brain/tests` assertions may depend on the leak
  (e.g. expecting `profile == 'local'` afterwards) — run your suite after
  fixing.
