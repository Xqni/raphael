# qa-security — status

Updated: 2026-10-07 (Wave 3 open; CI ownership fix done)

## Wave 5 (current — docs/WAVES.md current_wave: 5; wave-4 GATE PASSED)

- **DONE 2026-10-07: approved shadow-row count fix [22]** — instead of a
  brittle `==11→==12` bump, `test_interfaces_instance_table_is_collision_free`
  now does **cross-source equality**: the §d doc table must list EXACTLY
  `brain/config.py::_INSTANCES` (+ per-row port equality). Green across the
  merge boundary (11/11 today), and any future sanctioned row (shadow,
  8911) must land in BOTH or the test goes red — sturdier than the count.
- **DONE 2026-10-07: Wave-5 gate tests (lane bullet, all three):**
  1. *Format contract:* production-emitter scan ⊆ PROTOCOL §3 (either half)
     — new Answer/Report emitters without a §3 row go red; §3↔whitelist
     two-way check already strict (`tests/conformance/`, now 5 tests).
  2. *Tier-switch safety:* STRICT property over every `tiers.TIERS` member
     (authority blocks byte-equal + only persona/voice_personality change)
     + ADVERSARIAL-fragment xfail → request
     `qa-security__to__brain-core__loader-authority-guard.md` (fragments
     can override safety/privacy/providers incl. profiles pivot today).
  3. *Analysis/Simulation privacy:* tripwire armed — skip-until-lands,
     **fails-if-ungated** (private gate + redact + untrusted), contract
     request filed first per the wave rule →
     `qa-security__to__integrator__analysis-simulation-privacy-contract.md`.
- **Suites (real run): 297 passed, 1 skipped, 8 xfailed.**

## Waves 3–4 (docs/WAVES.md current_wave: 4 since 2026-10-07; wave-3 gate PASSED)

- **DONE 2026-10-07: wave-4 resilience matrix + re-review (inbox [19])**
  - New `tests/resilience/` (3 tests, all green): provider-outage storm →
    §10 failures → breaker open → aged-breaker **recovery** + usage
    accounting; seeded-crash-DB **real-restart** drill → every non-terminal
    row `interrupted`, terminal immutable, never auto-resumed (PROTOCOL §5).
    Shared spawn helpers extracted to `tests/harness/instance_proc.py`
    (isolated ephemeral ports — live stack untouched, procs always stopped).
  - Audit-fix verification: §b tool-spec tests **promoted to strict**
    (landed API: schema= + BadToolSpec + discover full walk); risky-tool
    dispatch gate pinned by a new strict flow test (benign text +
    risky tool → confirm; deny → cancelled, no side effect); bind default
    tightened to **exact loopback**; storm/usage tests added.
  - **Re-review:** `docs/reviews/2026-10-07-wave4.md` (8 areas, request
    census: 4 DONE + 1 SUPERSEDED + 6 implemented-awaiting-owner-flip +
    11 genuinely open; C1/C2 voice-confirm = top residual).
  - **Matrix + CI:** resilience matrix table in the review; new full-brain
    CI step (import-hygiene/order-dependent guard — the class that caught
    the registry pollution); encoding guard already in the OS matrix.
- **Suites (2026-10-07, real runs): own `285 passed, 7 xfailed`; full
  `pytest brain` `608 passed, 12 skipped, 0 failed`.**

- **DONE 2026-10-07 (urgent):** CI ownership self-check un-hardcoded
  (`.github/workflows/ci.yml`, commit 67e64f3 — cherry-picked to main as
  be6814a): lane derived from the ref (`agent/<lane>` → per-lane gate;
  main/integrator/other → `--lane integrator` by design — evidence run
  37574556616 flagged every non-qa push); BASE fallback handles zero-sha
  (`merge-base origin/main` for branches, `HEAD~1` for main).
- **DONE 2026-10-07: P0-REGRESSIONS + order-flake quarantine**
  (`tests/regression/test_gate_bug_regressions.py`, 5 tests):
  1. Bug A — every go_vision HTTP request carries `x-opencode-session`
     (strict, real provider call against the mock, header asserted per hit);
  2. Bug B — `open_app` failure surfaces: act_req received, failed
     job_event names the tool, spoken subtitle "open_app failed.",
     act_res journaled `delivered: true` (strict);
  3. Bug E — `speaking` held over `listening` mid-utterance → **xfail**,
     request filed `qa-security__to__brain-core__bug-e-hold-speaking.md`
     (derive precedence + ws.py comment contradict the dossier fix);
  4. Bug F — non-blocklisted terminal titles never refuse vision; blocked
     window refused BEFORE capture; `see_screen` terminal happy-path +
     blocklist refusal with vision_fn never called (strict, 2 tests).
  - Bonus: `as_untrusted` wrapper strict test (untrusted-tool-results
    request landed by brain-core — loop uses it at the tool step).
  - **FLAKE QUARANTINED:** `test_kind1_mic_pcm_accumulates_and_transcribes`
    asserted `STT_CALLS[-1]` — a late `to_thread` from a prior test could
    append after the per-test clear (order-dependent). Now drains before
    the send and matches by unique payload (membership), never by index.
    Suite ran 2× back-to-back + 3.12 run — stable.
- Also on latest main: infra's ollama-profile-gate tripwires promoted to
  strict (both landed); Wave-2 work confirmed merged (this branch now sits
  on 048b0c1).
- **DONE 2026-10-07: registry-pollution flake (infra evidence, assigned) —
  ROOT-CAUSED + FIXED.** Full `pytest brain` had 2 order-dependent failures
  in `brain/memory/tests` (identity asserts vs the tool registry), isolated
  memory 116/116 green.
  **Root cause:** `brain/` has no `__init__.py` while
  `brain/tools/computer_use/tests/__init__.py` exists → pytest (prepend
  mode) walked up to `brain/`, put it on `sys.path`, and imported the whole
  tools tree a SECOND time as top-level `tools.*` (registered `tools.shell`
  fns into the registry) — memory tests then compared `brain.tools.shell`
  against `tools.shell` = two distinct function objects. Bisected with a
  temp state plugin (collection-finish hook): polluter =
  computer_use/tests collection alone.
  **Fix (test files only, registry untouched):** removed
  `brain/tools/computer_use/tests/__init__.py` + converted the two
  `from .harness import` to try-relative/except-bare (repo's own pattern).
  Full brain now **572 passed, 12 skipped, 0 failed — twice in a row**;
  my suite 279/9 unaffected.
  NOTE: computer-use-owned test files changed under the explicit
  assignment ("fix the tests; don't edit the registry") — flagged in the
  coord task_done.
- **DONE 2026-10-07: contract follow-ups after sync** (branch rebased on
  main 9e44c5c):
  - Bug E xfail **flipped green** — brain-core 18744b3 (speaking>listening
    hold + emit guard) + integrator 7f0d337 (ws.py comment); test promoted
    to STRICT; request marked SUPERSEDED by the decision on the bus.
  - PROTOCOL §3 `notice` frame (additive, integrator-approved): added the
    Brain→Client **whitelist test** (`tests/conformance/test_protocol.py`)
    parsing §3 against `BRAIN_TO_CLIENT_FRAMES` (both directions: new frames
    must be whitelisted deliberately, stale entries flagged) + `notice` row
    shape test (ui,cli / text,level,ts,job — escaped-pipe-safe).
- **Suite (2026-10-07, real runs): own suite `279 passed, 9 xfailed`
  (py3.14 + py3.12 CI recipe) + FULL brain suite `572 passed, 12 skipped,
  0 failed` ×2 after the pollution fix; core_guard OK; ownership OK.**
- Next per inbox/Wave-3 list: Wave-3 goals (docs/lanes/qa-security.md +
  docs/WAVES.md; SPEED MANDATE Rule 15) — wave close = re-run ALL six
  WAVES criteria live (status table in docs/BUGS-WAVE2.md).

## Wave 2 (MERGED 2026-10-06/07 — do not re-debug verified pieces)

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

## Follow-up (2026-10-06, coord wake #1)

Inbox items handled (2 messages: infra CI include APPROVED + 3-item nudge):
1. **CI include (APPROVED decision)** — `tests/run_all` now runs the
   documented root command `pytest -q tests supervisor/tests`
   (supervisor/tests collected whenever present; guarded note when absent —
   merge order puts infra first, so it exists at integration). Verified
   infra's suite in a detached worktree of `agent/infra`: **55 passed,
   8.9 s, self-contained**. Superseded the two placeholder mocks
   `tests/supervisor/{test_relay_parsing,test_tcp_splice}.py` (simulated
   logic / generic socket check) with infra's real
   `supervisor/tests/test_relay_bind.py` coverage — directory removed.
2. **`brain/auth.py::default_token_path`** — new brain-side auth tests in
   `tests/contract/test_token_paths.py` (14 tests, RAPHAEL_TOKEN_PATH
   fixture pattern): main path byte-identical, per-lane derivation,
   precedence, get_token/check_token round trip, deny-when-missing.
   Derivation tests assert paths only — never open a real token file.
3. **Rebased onto main (340398b)** — main moved the §d pidfile contract to
   `~/.raphael/<instance>/brain.pid` (legacy /tmp dual-write): table test
   updated. Core Guard: `brain/auth.py` drift re-pinned WITH approval
   reference (`pc-control__to__integrator__instance-token-path.md`,
   integrator-landed on main; evidence: commit 39e5653 + in-file approval
   note; `core_guard.py --approval` now also resolves request files that
   still live on a lane branch via git). PROTOCOL §7 enum additions
   (nudge item 1) do not affect our conformance tests — suite green.
4. Posted `heartbeat` (task start), `test_result`, `wave_done` on the bus.

## Follow-up 2 (2026-10-06, coord wake #2 — green on merged main)

Fix-list from inbox (5 failed + 6 errors on main 9e7269b) — all resolved:
1. **Fixture**: `router_to_mock` repointed to `brain.router.config.REPO_ROOT`
   (router moved it); usage log now via `RouterSettings.usage_log_path`
   (module `USAGE_LOG_PATH` gone).
2. **Core Guard re-pinned with BOTH approvals** (`--approval` now accepts
   repeated flags): `brain-core__to__integrator__confirm-hardening.md`
   (HIGH-risk non-voice rule — landed exactly as our request asked) +
   `pc-control__to__integrator__instance-token-path.md`.
3. **orbstate singleton isolation**: `orbstate.reset_for_tests()` added to
   the per-test reset (sticky speaking/error flags leaked across tests and
   caused the frame timeouts).
4. **Expectations updated to the MERGED contract** (all in tests/, none in
   others' files):
   - private = `mode` overlay, never state `private_overlay` (§e audit);
     private job now completes locally with `PRIVATE_NOTICE` (not failed);
   - loop semantic pin: `mode.private` gate before the single
     `await _agent_loop()` path (was `llm.plan`, removed);
   - **harness fix**: mock OpenAI now serves real SSE for `stream:true`
     (the merged loop always streams; plain JSON yielded zero deltas →
     'Done.' fallback). Ordered chunking + OpenAI `tool_calls` deltas.
5. **9 tripwires promoted to STRICT** (implementations landed): config
   loader/profile overlay (router+brain-core), config.d §c loader,
   orb listening/acting/speaking/error + confirm state + awaiting_confirm
   snapshot (brain-core orbstate), redaction scrubber + blocklist +
   private vision suppression (router privacy gates), provider 429 mapping
   (router), LLM tool-call dispatch + uia lock propagation (tool_calls
   path).

**Test output (real runs, post-fix):**
```
tests/run_all (py3.14)              → 187 passed, 11 xfailed, 0 failed, 34s
tests/run_all (py3.12 CI recipe)    → 187 passed, 11 xfailed, 35s
ownership --diff (58 files)         → OK
core_guard                          → OK (4 files, dual approval recorded)
```
Remaining 11 xfail = still-open requests: REST rate-limit, tool-spec
registry API, circuit-open §10 code, lock-busy code, supervisor/systemd
ollama gate ×2, voice-confirm ×2, instance derivation (infra/body),
FastAPI /docs. (supervisor/tests still pre-merge — collected by run_all
when present.)

## Test output (real runs only)

```
tests/run_all (2026-10-06, post-rebase)  → 175 passed, 23 xfailed in 68s   (py3.14 / tests/.venv)
                                           incl. 14 new default_token_path tests; supervisor mocks superseded
tests/run_all (fresh py3.12 venv)        → 175 passed, 23 xfailed in 69s   (CI interpreter recipe)
supervisor/tests on agent/infra (detached worktree) → 55 passed in 8.9s    (APPROVED CI include, pre-merge verification)
tests/run_all (earlier, pre-follow-up)   → 161 passed, 23 xfailed in 68s   (py3.14) / 69s (py3.12)
brain/router/tests (py3.12 venv)         → 10 passed
tests/ownership_check.py --diff          → ownership OK (57 files)
tests/core_guard.py                      → Core Guard OK (auth.py re-pinned w/ approval, 4 files byte-stable)
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
