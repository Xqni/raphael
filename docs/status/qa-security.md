# qa-security — status

Updated: 2026-10-06 (Wave 2 complete — handoff below)

## Done (Wave 2 — all 5 brief items)

1. **Mock harness** (`tests/harness/`): scripted OpenAI-compatible provider
   (`mock_openai.py` — tool-call scripts, 429/5xx, malformed JSON, request
   counter on an ephemeral 127.0.0.1 port), `mock_body.py` (role=body,
   scripted act_req handlers: ok / error / drop), `mock_orb.py` (role=ui,
   records orb_state sequences), `wssession.py` (timed TestClient WS
   sessions), `voicespy.py` (TTS/STT mocked at class level — NEVER spawns
   Fish, never loads Whisper), `brain_boot.py` (hermetic brain subprocess).
   `tests/conftest.py`: `RAPHAEL_INSTANCE=qa-security` forced, temp token +
   temp DB (real `~/.raphael/token` and `memory.db` untouched), router
   disabled by default (no network possible unless a test re-points it at
   the mock), MAIN pidfile write guarded.
2. **Contract tests** (`tests/contract/`, 80 tests): auth (13, incl. 5 s
   deadline, E_AUTH_RATE ban, REST 401 matrix), rate limits + 8 MiB +
   3-strike malformed (5), role-capability matrix (36) + receive-side
   fan-out, binary frames §6 (7, incl. kind-1 PCM→STT round trip), error
   codes §10 (catalog partition + every wire code + 2 mapping xfails),
   config/tool contracts §b/§c (+ config-loader crash xfail).
3. **Regression tests** (`tests/regression/`, 46): no placeholder replies,
   orb lifecycle (core PASS; listening/acting/speaking/error + confirm as
   xfails with requests), confirm flow (timeout-abort, deny, scoped grant
   journaled, concurrent per-job isolation, fail-closed free text, voice +
   non-voice xfails), Private Mode = ZERO provider HTTP (counting mock),
   redaction/cloud-vision gates (config PASS, runtime xfails), cloud_temp
   never touches Ollama (config + runtime PASS; supervisor/systemd xfails),
   instance isolation (§d table collision-free + **two real brain
   subprocesses with separate tokens/job stores, zero cross-talk**), act
   pipeline (shape, fan-out, body-failure; extraction + lock-code xfails).
4. **`tests/run_all` + CI**: bash entry (qa suite; `--with-brain` opt-in),
   `tests/run_all.ps1` (Windows: body_win + conformance), `tests/requirements.txt`,
   `.github/workflows/ci.yml` — Ubuntu job (brain + mocks + ownership +
   Core Guard) and Windows job (Body unit tests, no GUI). No secrets needed.
5. **Security review** → `docs/reviews/2026-10-06-wave2.md` (8 mandated
   areas, severity-ranked) + **22 requests** in `docs/requests/
   qa-security__to__*.md` (router×2, brain-core×9, infra×2, pc-control×2,
   integrator×4, computer-use×1 — counts per review §4).

Also (lane task list): **ownership checker** `tests/ownership_check.py`
(lane table parsed from OWNERSHIP.md, 39 unit tests, self-check green on
this branch) and **Core Guard manifest** `tests/core_guard.py` +
`tests/core_guard_manifest.json` (byte-stable pin for confirm/auth/control/
mode + semantic tripwires); `tests/security/` adds 9 tests (secrets-in-logs
sentinel proof, route gating, Core Guard semantics).

## Test output (real runs only)

```
tests/run_all                       → 161 passed, 23 xfailed in 68s   (py3.14 / tests/.venv)
PYTHON=<3.12 venv> tests/run_all    → 161 passed, 23 xfailed in 69s   (CI interpreter recipe, fresh venv from tests/requirements.txt)
brain/router/tests (py3.12 venv)    → 10 passed
tests/ownership_check.py --diff     → ownership OK (32 files)
tests/core_guard.py                 → Core Guard OK (4 files byte-stable)
```

The 23 xfail = 23 documented contract gaps; each has a `docs/requests/` file
(see review §1/§4). They flip green as the owning lanes land fixes — no
maintenance needed on this side.

**Not run (stated honestly):** `brain/tests` is NOT re-run locally by this
lane — brain's conftest does not mock TTS and a live Fish server exists on
this machine (running it would synthesize on main's TTS; request
`…__mock-tts-pidfile-guard` filed). CI runs it where Fish cannot exist.
`tests/e2e_wave2.py` (live E2E) is integrator-only per AGENT_RULES §5.
Windows CI job is authored but not executed here (no Windows host).

## Blocked
- Nothing. All Wave-2 items that need other lanes are filed as requests
  (they don't block this lane).

## Next (per AGENT_RULES §11 — wave gate)
- WAVES.md `current_wave: 2` → **STOP here with this handoff.** Waves 3–5
  items from the session brief are queued for when the integrator bumps the
  wave:
  - **Wave 3**: golden job transcripts (replayable conversation/tool traces
    as a regression baseline — plan: record hub frame streams from the mock
    harness into `tests/golden/*.jsonl`, replay through a fresh instance and
    diff the frame sequence; hook point already exists in
    `harness/wssession.py` recording).
  - **Wave 4**: resilience suites (kill/restart mid-job, provider storms via
    the scripted mock, act timeouts) + re-review after fixes (expect many
    xfails gone — update review, re-run strict).
  - **Wave 5**: evolution-gate tests (Core Guard integrity — manifest tool
    already provides the primitive; rollback works; probation triggers).
- When other lanes' fixes merge: re-run `tests/run_all` — xfail→XPASS is
  reported, then convert the relevant tripwires to strict assertions in the
  Wave 4 re-review.
- Watch for requests addressed to this lane:
  `ls docs/requests/*__to__qa-security__*.md` (none at handoff time).
