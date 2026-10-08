# router — status

Updated: 2026-10-08 (Wave 5H follow-up batch complete — 211 router + 2 skipped / 232 brain / 241 root green; CI branch 37722900664 green)

## Wave 5H follow-up batch (2026-10-08: dispatched tasks — all ACCEPTED in coord)

1. **Chat→fast-role latency lever #2** (dispatch) — `_role_for` tier follows
   PURPOSE not payload shape: `purpose='chat'` + tools merely available → FAST
   (was `if tools: return strong`); strong kept for `tool`/`plan`, deep for
   `analysis`/`simulation`, unknown+tools conservative. Loop label is
   brain-core's half → `router__to__brain-core__chat-purpose-label.md`
   (ACCEPTED, assigned; `loop.py:699 purpose='tool' if specs`). **Live A/B**
   (real cloud, n=6/arm, seam first-delta): strong/qwen3.6-plus **3.85s** vs
   fast/mimo-v2.6-flash **3.48s** medians (first-sentence 3.94→3.53), model
   switch verified, ~0.4s gain, tail=provider variance. Side findings fixed:
   go RPM 10→30 (`config.d`, the A/B hit `local_rpm_budget`); zen400/groq-tools400
   findings → next item. Commits `8b40c9e`, `934d93d`. Tests: role matrix +
   facade both tiers (`test_tiered_analysis_routing.py` 10).
2. **turbo-STT Cut B** (voice request ACCEPTED) — live diagnosis: seam picked
   `whisper-large-v3` by first-seen tie (Groq listed plain v3 first); fix =
   stt hints weight fast variants (`turbo` first) → order-independent.
   **Live clip A/B** (`assets/raphael_reference_jp.wav`, 15.66 s, free, n=3):
   v3 med **1.29 s** (rtf .082) vs turbo med **1.16 s** (rtf .074), warm turbo
   0.68–1.16 s (≈ −0.4 s), transcripts identical (76 ch), seam lands turbo
   (`rtf 0.050`). Commit `8ad9a4e`, 2 tests.
3. **zen tool-slot finding** → fixed as **model-capability learning** with a
   live probe table: `gemini-3.5-flash-lite` (fast pick) 400s on EVERYTHING;
   `mistral-large-4` serves plain/stream/**tools**/tool_calls → provider-wide
   ban would have been wrong. 400s classified (`model_unsupported` /
   `no_tool_support`, both skip-reasons), dead/tools-dead sets on the provider,
   re-pick within the same provider (stream learns too), breaker never trips.
   5 tests (`test_model_capability_learning.py`). Live re-strike proof:
   `dead=['gemini-3.5-flash-lite']`; zen free quota then hit **403** (free
   tier exhausted — chat unaffected via go head). Commits `160e4dc`/`6f4f695`.
   Offer recorded: static provider ban available on request.
4. **Closures/reviews:** orb headroom request → **ANSWERED** (contract match,
   `lanes/orb.md:235-240`); audit packet boxes → **ticked** in
   `docs/lanes/router.md` (SEC-8/ARCH-5/F-4 evidence in the section below);
   loop-label + arch5 + e-budget requests remain with their owners.
5. **Blockers reported (not mine):** root `test_lock_action_sets_lock_true`
   was failing on clean main (3 heavy runs + local stash proof) → **fixed on
   main by others, re-verified green after rebase** (root 241+7 now).

**Suites after rebase onto the act/guard fixes:** router **211 passed + 2
skipped** · brain **232 passed** · root **241 passed + 7 xfailed** (all green,
sequential, stack untouched).

## Wave 5H P0 packet (inbox register PART 2: AUD-02/04/05/27) — DONE

Verify-first, one task at a time; each `task_done` carried `file:line` quotes + a green CI id.

**AUD-02 (CRITICAL): CONFIRMED → FIXED — router loader joins the Core-Guard**
- Pre-quote: `brain/router/config.py:117-123` `for frag in …: data = deep_merge(data, _load_yaml(frag))` (no strip) and `:280-283` applied a fragment-pivotable profile overlay → a malicious `config.d` fragment could set `providers.groq_base_url` (key exfil) or flip money/privacy gates.
- Fix: `config.py:128 AUTHORITY_KEYS = ("safety","privacy","providers")` · `:155 _strip_fragment` (exact `brain/config.py:140-157` policy incl. wholesale `profiles` strip, loud violation record) · `:173 _merged_tree` → **single authoritative merger** `:181 mod.load_config(cfg_path, force=True)` (brain-core Core-Guard) with local mirror fallback · `:355 load_config` uses it · `:143 authority_violations()` delegation.
- Tests: `test_config_authority.py` 9/9 **parametrized over both loader paths** — endpoints/money-gates/safety/privacy/profile-overlay all immutable to fragments (fail CLOSED), legit `router:` keys still merge, shipped fragment clean. Commit `478a553`.

**AUD-04: CONFIRMED → FIXED — configured redaction + free-model policy enforced**
- Pre-quotes: flag read at `config.py:387-388` with **zero enforcement sites** (repo grep); chat paths scrubbed secrets only (`core.py:617/645 redact_messages(...)` → `redact_secrets`), configured `privacy.redact` email/phone categories never applied on chat (`redact_categories` had no core callers); `config.yaml:50` claimed "local model only" while nothing enforced it.
- Fix: `privacy.py:273 PERSONAL_CATEGORIES` (∩ configured redact list) · `:276 detect_personal_data` (PII BEFORE redaction) · `:306 redact_messages(..., categories)` now on chat/stream/legacy-complete/vision-question (`core.py:823`) · `provider.py:47 free_tier` (billed Go `openai_compat.py:95`, local Ollama `ollama.py:82`) · gates `core.py:316 _skip_free` / `:322 _chain_for` → free tiers skipped for personal content when `allow_free_models_for_personal_data=false`; **fail closed** `:329 E_OFFLINE/personal_data_free_only` (zero free egress) when no paid/local remains; legacy `complete()` refuses on a free provider for PII.
- Honest policy (status §Handoff): scrub ALWAYS; personal → routed paid/local or refused TODAY; "local-only" remains the Wave-6 goal (`config.yaml:50` comment flagged for integrator reword).
- Tests: `test_personal_data_policy.py` 10/10. Commit `bfd975b`.

**AUD-05 (my half): CONFIRMED → FIXED — foreground gate fails CLOSED**
- Pre-quotes: `privacy.py:53-64 set_foreground_check` (never registered: `grep -rn set_foreground_check brain/ body/ tests/` → ZERO outside brain/router) + `foreground_window(): None → blocklist_hit: if not name: return None` = **allow** → cloud egress with an unverifiable focused window.
- Fix: `privacy.foreground_status()` (known vs unknown) + `config.py:265 require_foreground: bool = True` (escape hatch documented in `config.d/router.yaml`) → `core._gate_blocklist` raises `E_OFFLINE/foreground_unknown` for chat + stream + vision + legacy complete (zero egress verified); single-query blocklist match for known windows; `transcribe()` deliberately exempt (audio has no window semantics).
- **Harness exception (documented in code):** under `PYTEST_CURRENT_TEST` an unwired hook = known synthetic `pytest-window` — suites model a wired stack; production (no env) refuses until brain-core registers the hook (`router__to__brain-core__wire-foreground-hook.md`, their half incl. pc-control data source).
- Evidence trail: fail-closed gate alone broke 9 root tests while stashed-gate passed them (bisect: `require_foreground=false` → 2/2 pass); llm seam verified clean in-process (stream yields `{'finish':'error','code':'E_OFFLINE'}`, non-stream degrades) — no crash, close was the unwired-harness effect. After the pytest-window default: **router 201+2 / brain 216 / root 214+7 all green**. Tests: `test_foreground_gate.py` 10 (production-path fixture forces `_pytest_session=False`). Commit `4810ce4`.

**AUD-27: CONFIRMED → FIXED — bounded usage tail**
- Pre-quote: `status.py read_usage_events(): raw = path.read_text(...)` then `splitlines()[-tail:]` → whole ever-growing file loaded per `/status` poll.
- Fix: `status.py:27 TAIL_BYTES = 512 * 1024` · `:30 read_usage_events(..., max_bytes=TAIL_BYTES)` seeks the last window (`:50 fh.seek(size - max_bytes)`), **drops the torn first line** of an oversized window, keeps the 2000-line cap; small files unchanged (corrupt-line skip + 24h window preserved).
- Tests: `test_status.py` +3 — byte-window/torn-head proof with marker events, default-bound excludes HEAD-anchor in a >512 KiB file, small-file parity. Scope note (honest): `vision_paid_ledger.jsonl` is still read whole by design — its size is bounded by the spend caps themselves (line count ≈ ceiling/floor), and correctness of the all-time total requires the full history.
- Commit `c69892b`.

**Packet totals:** commits `478a553` · `bfd975b` · `4810ce4` · wiring request · `c69892b` (+request earlier). Suites (sequential, Rule 14, stack untouched):
```
brain/router/tests : 204 passed, 2 skipped
brain/tests        : 216 passed, 1 warning (fastapi deprecation)
tests/ (root)      : 214 passed, 7 xfailed
CI (cloud)         : tests-heavy 37720486202 + 37720097390 SUCCESS · ci 37719207437 SUCCESS
```

## Wave 5H — audit packet (docs/audit-tasks/router.md, VERIFY-FIRST)

Report format per packet: `ID: STATUS — file:line quote`. All tests mock-only,
stack untouched (policy 2026-10-07: DOWN by default), one suite at a time (Rule 14).

**SEC-8: CONFIRMED (4 gaps beyond the existing daily stop) → FIXED + tested**
- Pre-fix quotes (verbatim from the audit-time read): `spend.py:101-106` —
  `def _save(...)` … `tmp.write_text(...)` / `tmp.replace(self.path)` (**rewrite, not
  append-only**) and `except OSError: pass` (**write failure silently swallowed = the
  ledger-write-failure gap the packet asked about**); no `total_cap` anywhere
  (`grep total_cap brain/router/*.py` → only `global` keywords); `E_BUDGET` absent
  (`grep E_BUDGET brain/router docs/PROTOCOL.md` → empty).
- Now enforced **in code**:
  - append-only ledger: `brain/router/spend.py:184` `def _append(...)` →
    `spend.py:189` `self.path.parent.mkdir(parents=True, exist_ok=True)` + one JSONL
    line per event (`call|alert|import`) at `<repo>/run/vision_paid_ledger.jsonl`;
    file is the source of truth, survives restarts, malformed line charged at floor;
  - legacy live state carried forward: `/home/dami/raphael/run/vision_paid_daily.json`
    (113 B, 2026-10-07 07:14) is imported once then renamed `*.imported`
    (`spend.py::_import_legacy`);
  - daily + **all-time** ceilings: `config.py:200` `vision_paid_total_cap_usd: float = 10.00`
    with `config.d/router.yaml:58` `vision_paid_total_cap_usd: 10.00`; checked by
    `spend.py:237 def exhausted` / `spend.py:246 def total_exhausted`;
  - hard refusal **E_BUDGET**: `core.py:884 def _budget_refusal` →
    `core.py:905 RouterError(detail, code="E_BUDGET", reason=reason, …)`; fatal +
    spoken in `errors.py` (in FATAL_CODES, NOT in RETRYABLE_CODES, `_SPOKEN_DETAIL`
    line 88); catalog request filed (`router__to__integrator__e-budget-code.md`);
  - conservative counting: `core.py:817 floor_usd=spend.floor_usd` →
    `estimate_cost_usd(..., floor_usd=0.005)` returns the floor when neither cost nor
    tokens parse (config `vision_paid_unknown_call_floor_usd`);
  - fail-closed write gap: `core.py:820 except SpendLedgerError:` → E_BUDGET /
    `ledger_unwritable`, and `spend.exhausted` reads True while broken → later calls
    refused **pre-flight**;
  - race-proof admission: `core.py:282 self._vision_paid_lock = asyncio.Lock()` wraps
    check→send→charge per paid call.
- Tests (`brain/router/tests/test_budget_ledger.py`, 8): restart mid-day
  (:65), 5-way concurrent race → exactly 1 paid request + 4×E_BUDGET (:93),
  clock rollover keeps all-time ceiling (:123), malformed usage → floor (:154),
  write failure fail-closed (:189), plus E_BUDGET shape + status exposure.
- Note for integrator: `config.yaml:49` comment still says "refuses E_OFFLINE" →
  now E_BUDGET (cosmetic, your file).

**ARCH-5: CONTRIBUTED (design-note content) + presets REQUESTED (fragment route blocked)**
- Reality quoted: `config.yaml:42` `chain: [go, zen_free, groq]` (user directive
  2026-10-07) — my earlier `[groq, zen_free]` presets were already stale, now aligned.
- Blocker (correctly enforced by another lane's Core-Guard):
  `brain/config.py:129` `AUTHORITY_KEYS = ('safety', 'privacy', 'providers')` +
  wholesale `profiles` strip → my fragment was stripped LOUDLY at load
  (`AUTHORITY VIOLATION in config.d/router.yaml: stripped ['profiles']`). My fragment
  is authority-clean now (`config.d/router.yaml:62` comment + test
  `test_my_fragment_respects_authority_keys`: top keys ⊆ `{router}`).
- Contribution delivered in `docs/requests/router__to__integrator__arch5-router-contribution.md`:
  preset table + **exact YAML** for `profiles.cloud` / `profiles.hybrid` (integrator
  must paste — tests un-skip automatically: 2 `skipif` in `test_profiles.py`,
  currently 10 passed + 2 skipped), role-hint/tier policy, usage-accounting summary,
  and the **per-provider data-handling table** (what leaves the machine per provider,
  every retention cell marked **UNVERIFIED — verify with provider**).

**F-4: DONE (router side) + orb REQUESTED**
- `core.py:1055` `out["headroom"] = self.rate_headroom()` inside `usage_status()` and
  `core.py:1060 def rate_headroom(self)` (module facade `core.py:1350 def rate_headroom()`,
  exported as `brain.router.rate_headroom()`): per-provider
  `rpm_headroom / tpm_headroom / cooldown_s / circuit` + `vision_paid`
  (today/day-cap/total/total-cap/exhausted/ledger_broken) — in-memory, no I/O.
- Rides the already-wired endpoint: `brain/app.py:266` `'sessions': …, 'router': router_block`.
- Orb coordinates via `docs/requests/router__to__orb__headroom-in-menu.md` (exact JSON +
  suggested menu lines). Tests: `test_status.py:173 test_rate_headroom_shape_and_facade`
  (+ no-paid-slot variant).

**SEC-5 (user-audit addendum): DONE — one reader + two leak tripwires**
- Single reader: `privacy.py:151 def secret(name)` (env wins over `.env`, presence-
  checked value-blind); source scan proves no other file touches `.env` or
  `os.environ.get(<SECRET>)` — `test_key_handling.py:35`;
  every `Bearer ` builder must call `privacy.secret()` — `test_key_handling.py::test_every_bearer_header_comes_from_secret`.
- Log tripwire: `test_key_handling.py:73 test_no_key_material_in_logs` — caplog DEBUG
  across success/500/health with a sentinel key: no sentinel, no `gsk_/sk-/Bearer`-shaped
  token, no Authorization text in any record.
- Exception tripwire: provider echoing the key in a 401 body → `str(exc)` shows
  `[REDACTED]`, never the key (`test_key_handling.py::test_exception_text_scrubs_key_echoed_by_provider`).

**Private Mode tripwire (user-audit addendum): RE-VERIFIED + extended**
- Pre-existing: `test_privacy.py:55 assert srv.requests == [] # zero egress in Private Mode`
  and `:74 # health must not egress either`.
- New stream/legacy coverage: `test_privacy.py:258 test_private_mode_blocks_stream_with_zero_egress`
  — stream refuses before the first delta (`events == []`), `srv.requests == []`,
  and legacy `complete()` degrades to `E_OFFLINE`.

**Commits:** `ae498c7` (SEC-8 + F-4 code) · `491c7b0` (tests) · `f26e8f8` (3 requests).
**QA-4 CI links:** heavy run **37711345817** (`tests-heavy`, dispatch, **success**, 3m10s,
2026-10-08T01:07:44Z) · latest `ci.yml` green **37711974330** (success, 01:15:05Z).

## Wave 5 (current_wave: 5 — gate-open after wave-4; my position: 1)

Rebased on `main` first (brain-core's batch merged ahead — recorded deviation noted
in PROGRESS). Live stack still UP → no spawns; all tests on ephemeral loopback.

**Assigned task — DONE: Analysis-mode routing (tier-aware model policy + usage accounting)**
- **`deep` role** (`brain/router/roles.py`): hints for the biggest tier
  (`120b/90b/70b/48b/32b/27b/24b/plus/pro/max/ultra/large`); among equally-scored
  candidates the **BIGGEST id wins** (unlike `strong`, which keeps first-seen —
  pinned by test so the two tiers stay distinguishable); deny-hints apply →
  `grok`/`kimi` (MODEL_POLICY "never") unreachable in *every* tier.
- **Policy wiring:** `purpose_roles` maps `analysis → deep`, `simulation → deep`
  (code defaults in `roles.py` + explicit lines in `config.d/router.yaml`); the tier
  map stays pure config, so future purposes need one YAML line, no code.
- **`_role_for`:** a purpose mapped to `deep` **outranks the tools→strong rule**
  (depth is the point of Analysis); `chat`/`ack` → fast and tools → strong are
  untouched → Rule 15 speed mandate intact (pinned by `test_normal_turns_stay_fast`).
- **Usage accounting:** new purposes bucket automatically —
  `usage_status().by_purpose["analysis"|"simulation"]` (calls/errors/tokens),
  `usage.jsonl` `task_kind`, including FAILED lines from the Wave-4 failure logging.
- **Contract:** `docs/requests/router__to__integrator__interfaces-purpose-enum-analysis.md`
  (OPEN) — INTERFACES §a `purpose` enum gains `analysis|simulation` (doc-only for the
  integrator; router accepts them already and unknown purposes still default to fast).
- **Tests:** `brain/router/tests/test_tiered_analysis_routing.py` — 10, mock only.

**Known unrelated failure (not mine):** `tests/regression/test_instance_isolation.py::test_interfaces_instance_table_is_collision_free`
expects 11 §d rows; the APPROVED shadow row (8911) makes 12. Reproduces with my work
stashed (clean `main`), and brain-core already filed
`brain-core__to__qa-security__shadow-row-count.md` — no duplicate request filed.

Commits: `a175d4e` (policy) · `0906948` (tests) · `1123b59` (contract request).

## Wave 4 (current_wave: 4; wave-3 gate PASSED before open)

Rebased on `main` first. Note: live stack is UP by user directive — no servers
spawned; every test below runs on 127.0.0.1 ephemeral ports (AGENTS rule from
`wave_open`).

**Assigned task (docs/lanes/router.md Wave 4) — DONE:**
1. **Failure-injection resilience suite** — `tests/test_resilience.py` (12 tests):
   - 429 storm: backoff + retry then failover, **ordering proven** via request
     timestamps (every groq attempt before the zen attempt); long `Retry-After`
     → cooldown + skip (no stall, no retry);
   - 5xx storm → breaker OPEN after threshold → **zero new attempts** → cooldown →
     half-open probe → recovery → CLOSED (injected fast breaker, default semantics);
   - network drop (connection refused): single-provider isolation + all-down →
     `E_OFFLINE` retryable with spoken detail;
   - §10 exhaustion matrix: 401 → `E_PROVIDER_AUTH` (fatal, exactly 1 attempt),
     429 → `E_PROVIDER_429`, 5xx → `E_PROVIDER_5XX`, dead net → `E_OFFLINE`;
   - sustained 10-call storm: bounded by max_retries AND breaker (groq 10 requests
     = 2×5 calls then breaker-open, not 20); capability misses never trip breakers.
2. **Usage-log integrity audit** — `tests/test_usage_log_integrity.py` (6 tests):
   every line parses with a stable schema; failed flows now log one FAILED line per
   provider (new in core — powers `usage_status()` error counts); log contains **no
   prompts, no key values, no Bearer headers, no image bytes/base64**; concurrent
   `gather(8)` writes stay clean; a torn final line (crash mid-write) is isolated and
   the next event survives — fixed by a crash-safe append in `core._append_line`.
3. **Prompt-bias STT seam regression** (Wave-3 live gate glue `07cadcb`) —
   `tests/test_stt_seam_prompt_bias.py` (6 tests): `config.voice.wake_word` →
   `prompt="<wake>."` in the Groq multipart body, no prompt when wake_word is empty,
   prompt never leaks into chat, INTERFACES §a signature unchanged
   (`transcribe(audio, language)` — voice's call site keeps working), repo config
   wiring pinned (`voice.wake_word=raphael`, `stt_engine=groq`).

**Requests addressed to me:** `qa-security__to__router__fix-config-loader` +
`provider-429-mapping` → both verified ALREADY DONE by the Wave-2 rewrite (their
tests are pinned strict and pass); `Status: DONE` + evidence written into each file.
Third tripwire (`E_CIRCUIT_OPEN` in §10) = shared-contract decision — their
`qa-security__to__integrator__circuit-open-code.md` request already covers it; router
maps circuit-open → `E_OFFLINE` today and switches in one commit if approved.

Commits: `9faf427` (request answers) · `186dbfc` (failure logging + crash-safe append)
· `a090360` (three Wave-4 suites).

## Wave 3 (opened via coord `wave_open`; task list: docs/lanes/router.md)

Rebased on `main` first (AGENTS rule). Work this wave, in assignment order:

1. **Bug A regression test** (BUGS-WAVE2, P0) — `test_go_vision_requests_carry_session_header`
   asserts EVERY Go-endpoint request (discovery + completion) carries
   `x-opencode-session` (stable `raphael-brain-<pid>` per process) and the httputil
   User-Agent, and that free providers never send that header. **Proven valid:** fails
   with the integrator's `zen.py` hotfix removed, green with it. Conductor: VERIFIED.
2. **Usage/rate tracking for `/status`** (assigned goal #1) — `brain.router.usage_status()`
   in `brain/router/status.py` + `Router.usage_status()`: 24 h `usage.jsonl` aggregation
   (calls/tokens/by_provider/by_purpose/error codes) + live RPM/TPM/cooldown/circuit
   state per provider + `vision_paid` budget. No network, no keys, survives
   missing/corrupt logs (8 tests). Wiring request
   `router__to__brain-core__surface-usage-in-status.md` **APPROVED** (brain-core edits
   `brain/app.py` — I have no write authority there). Conductor: VERIFIED.
3. **Schema-normalization edge cases** (assigned goal #2) — `test_normalization_edge.py`
   (18 tests): multi-part content, flat tool-call objects, legacy `function_call`,
   dict/string/truncated/unrecoverable arguments, null `finish_reason`, missing
   `usage`, empty **and non-list** `choices`, provider-reported `cost`, deterministic
   call ids. **Three real fixes they caught:** non-list `choices` used to silently
   return an empty "success"; non-numeric `usage` tokens raised a raw `ValueError`
   (should be 0); non-dict `message`/`usage` unguarded.
4. **Go kept but off** — already gated (`allow_go_runtime: false`,
   `test_go_provider_stays_gated_off`); no change needed.
5. **Speed mandate** (PAID_USAGE broad approval 2026-10-07) — `mimo` added to fast role
   hints (picks `opencode-go/mimo-v2.5`/flash-class when a paid chain is enabled) and
   MODEL_POLICY `never` models (`grok` 2/6, `kimi` 3/15) added to deny-hints for
   chat/vision, in code defaults **and** `config.d/router.yaml` (cost hygiene stays in
   force). Unit test pins both behaviors.
6. **Bug B (router half)** — mapping lives in brain-core's `brain/fastpath.py`; exact
   patch proposed in `router__to__brain-core__fastpath-open-search-mapping.md`,
   **APPROVED** and posted to brain-core (pc-control owns the body `open_app` half).

Commits this wave: `6107f8e` (Bug A test) · fastpath request · usage-status +
tests · usage /status request · `f541bbd` (normalization + fixes) · `c9e319b`
(speed-mandate hints).

## Done (Wave 2 + the new user-approved vision paid slot)

Commits on `agent/router` (Wave 2 merged in `main` at `1a8c2f6`; paid slot pending merge):
- `44fa303` — facade + providers + resilience + privacy + `config.d/router.yaml`
- `d06f000` — mock-server test suite (79 tests)
- `0708ad1` — stream final-frame guarantee + usage polish (80 tests)
- `7413216` / `147281e` / `7fbfb76` — docs: handoff, decision record, authority-rule amendment
- `f745a7f` — **vision-only paid slot** (task from coord inbox, user-approved)
- `818494f` — paid-slot tests (→ 92 router tests)

1. **Interface first + deterministic mock** (`brain/router/__init__.py`, `mock.py`) —
   `chat(messages, tools, stream, purpose)`, `vision(image, question, purpose)`,
   `transcribe(audio, language)`, `health()` exactly as INTERFACES §(a):
   - non-stream `chat` → `await` → dict `{text, tool_calls, finish, provider, model, usage{input,output}}`;
   - `stream=True` → `async for` → `{"delta": …}` … one final `{"finish", "provider", "model", "tool_calls", "usage"}`;
   - every failure raises `RouterError(code=<PROTOCOL §10>)`, never a crash.
   - **Other lanes build against the mock:** `RAPHAEL_ROUTER_MOCK=1` (chain → `["mock"]`),
     or `brain.router.init_router(make_config(tmp, ["mock"]))`. Deterministic text,
     tool-call trigger `mock_call:<name>{json}`, failure trigger `mock_fail:E_CODE`.
2. **Groq + Zen (+Go, +Ollama) behind live discovery** — no hardcoded model IDs anywhere:
   `GET /models` at call time (cached `discovery_interval_s`), scored by
   `router.role_hints` (fast / strong / vision / stt) from `config.d/router.yaml`,
   with `deny_hints` keeping Groq's `llama-prompt-guard` / `gpt-oss-safeguard` /
   `orpheus` (TTS) out of chat/vision slots. **Zen returns no `free` flag → only ids
   positively matching `zen_free_hints` (`…-free`) are free; everything else is paid
   and filtered out** (money gate AGENT_RULES §7). Go stays gated by
   `allow_go_runtime: false` (code kept, `GoProvider` + test).
3. **Real calls**: OpenAI-style tool calls normalized to one shape
   (`function.arguments` is ALWAYS a repaired dict, original kept in `arguments_raw`,
   `repaired` flag), SSE streaming incl. fragmented tool-call arguments, vision via
   base64 `image_url`, Groq Whisper via multipart `/audio/transcriptions`
   (model chosen live — whisper slot), vanished model (404) → re-discover once.
4. **Resilience**: `Retry-After` (seconds + HTTP-date) and `x-ratelimit-*` headers
   honored (long wait → cooldown + immediate failover, short → jittered retry),
   429/5xx exponential backoff ±20% jitter, per-provider RPM + TPM sliding budgets
   (skip-to-next-provider, no breaker damage), circuit breaker with jittered cooldown,
   failover along `providers.chain`, aggregated `E_PROVIDER_429/5XX/AUTH/OFFLINE/…`
   with spoken-safe `detail` per §10.
5. **Privacy gates** (inside the router, so no caller can forget them):
   Private Mode → zero egress (chat/vision/transcribe/health probe all refuse,
   `reason="private_mode"`); `set_foreground_check(fn)` blocklist hook → vision always
   refused, chat refused when `router.block_chat_on_blocklist` (default true);
   every outbound string secret-redacted (loaded `.env` values + key/bearer/card
   patterns) before send; images are metadata-only in logs (`<image N bytes>`).
6. **Tests — mocked HTTP only**: scripted OpenAI-compatible server on 127.0.0.1
   (tool calls, malformed JSON, 429 + Retry-After, 5xx, 401, SSE, rate-limit headers,
   multipart STT, health), privacy/no-key-leak assertions (sentinel key never appears
   in any body/log/usage line), config load-order + profile switch tests
   (cloud_temp ⇄ local, incl. Ollama path + local STT seam), and a **placeholder guard**
   that fails if any output *or any router source line* matches `[provider:model] response`.
7. Config: `config.d/router.yaml` (lane fragment, AGENT_RULES §3) — role hints,
   deny hints, zen free hints, RPM/TPM, backoff, blocklist-chat flag, vision byte cap.
8. **Vision-only paid slot** (new task from coord inbox 2026-10-06, user-approved):
   - **Gate = `providers.allow_vision_paid`** (config.yaml, integrator). `GoVisionProvider`
     lives ONLY in `_vision_chain()` — `chat()`/`transcribe()` iterate `_chain()` and
     provably never touch the paid endpoint (test asserts zero paid requests);
     `allow_go_runtime`/`allow_paid_runtime` stay `false`.
   - **Discovery by capability:** live `GET {go_base_url}/models` → `roles.pick("vision")`
     needs a vision-hinted id (`…deepseek-v4-flash-vision-exp` matches `vision`);
     no match → `E_OFFLINE`/`no_model` and **zero paid calls** (test asserts no spend).
   - **Daily hard stop:** `providers.vision_paid_daily_cap_usd` (1.00) enforced by
     `spend.DailySpend` (state `<repo_root>/run/vision_paid_daily.json`, resets on date
     rollover). Cost = provider-reported `cost` if the response carries one, else
     tokens × `router.vision_paid_price_per_mtok` (default 0.66/1.98 = conservative
     `deepseek-v4-pro` sibling price from MODEL_POLICY, so the cap trips early;
     overshoot bounded by one call). Exceed → `vision()` raises `E_OFFLINE`
     (`reason="vision_paid_cap"`, spoken detail) + **coord attention
     "vision daily cap hit"**, posted once per day. `health()` now also returns
     `vision_paid: {cap_usd, spent_usd, calls, exhausted, date}` when the slot is on.
   - Free vision (if any exists) still works while capped — the cap gates paid only.

## Blocked
- **Wave 2 exit criterion 3 — PATH IMPLEMENTED, pending live E2E (integrator/human run).**
  Timeline: initially blocked (no free vision model) → OPTION 3 → authority-rule
  amendment (`340398b`: exit criteria are the human's to change, criterion back on the
  list as *BLOCKED: human decision pending*) → **user approved the vision-only paid
  slot** ("use the opencode go paid models please for vision for now", logged verbatim
  in `docs/PAID_USAGE.md`; gate `providers.allow_vision_paid: true`,
  cap `vision_paid_daily_cap_usd: 1.00`). I implemented the slot (Done §8): free chain
  first, paid as last resort, capability discovery, daily hard stop + coord attention.
  **Nothing blocks the router lane** — remaining step is a live "what am I looking at"
  run on the real instance, which is the integrator's (AGENT_RULES §5).
  - `vision()` still refuses (`E_OFFLINE`/`no_model`) when the slot is disabled,
    capped out, or discovery finds no vision-capable id — never a guess.
  - `E_BLOCKED` stays declined: `reason` remains the discriminator
    (`private_mode` / `blocked_window` / `cloud_vision_disabled` / `chain_exhausted` /
    `vision_paid_cap`). No PROTOCOL §10 edit.
  - Original request: `docs/requests/router__to__integrator__vision-free-model-gap.md`
    (Status flip is the integrator's).

## Wave 2 closed
- **MERGED:** `agent/router` → `main` at `1a8c2f6` (Wave 2; my head `147281e` was an
  ancestor of `main`). Router is first in merge order
  (`router → brain-core → pc-control → …`).
- `wave_done` posted to the coord bus; **re-posted after the paid-slot task**
  (`f745a7f`+`818494f`). Suites green at re-post time:
  **92 router + 117 brain-core + 2 conformance = 211 passed**.

## Next (in order)
1. **IDLE / WAIT until `wave_open`** (coord inbox handoff 2026-10-06: my work is
   merged; `coord mode` = `exit` → go idle, no polling, no wait loops — the conductor
   pings this session when every lane finishes Wave 2). Rebase on latest `main`
   before any new task (AGENT_RULES §4), starting with reading
   `docs/requests/*__to__router__*.md` + my inbox.
2. Wave 3 (only after the wave bump): usage/rate tracking surfaced in `/status`,
   schema-normalization edge cases, recorded-fixture contract tests for CI
   (coordinate with qa-security via a request first).
3. Consumers' notes (brain-core, computer-use, voice): see handoff below.
4. Vision criterion 3: paid slot implemented (Done §8) — remaining work is the
   integrator's live E2E ("what am I looking at") + PAID_USAGE reconciliation;
   I only re-touch it if the gate/cap/price config changes.

## Handoff for other lanes
- Import surface: `from brain.router import chat, vision, transcribe, health,
  RouterError, set_private_mode, set_foreground_check, set_local_transcriber`.
  Legacy seam (`brain/llm.py`) unchanged: `acquire_model()` / `complete()`.
- Errors: catch `RouterError`, surface `e.code` (§10), subtitle text only when
  `e.spoken` is not None; `e.reason` distinguishes
  `private_mode` / `blocked_window` / `cloud_vision_disabled` / `missing_key` /
  `circuit_open` / `local_rpm_budget` / `local_tpm_budget` / `chain_exhausted`.
- Hooks brain-core/pc-control must wire: `set_private_mode()` on `private_on/off`,
  `set_foreground_check()` returning the focused window/app name.
- Voice lane: register local STT with `set_local_transcriber(async fn)`; it is
  consulted only when `voice.stt_engine == "local"` (profile local).
- Computer-use: caller pre-gates (profile, redaction, downscale); router re-checks
  Private Mode + blocklist + `router.vision_max_bytes` and never logs the image.

## Test output (real runs only)
**Wave 5H verification, 2026-10-08** (sequential, Rule 14):
```
brain/router/tests : 172 passed, 2 skipped in 41.73s   (skips = ARCH-5 presets pending integrator)
brain/tests        : 194 passed, 1 warning in 15.19s    (fastapi deprecation)
tests/ (root)      : 214 passed, 7 xfailed              (shadow-row failure fixed on main; xfails = qa tripwires)
CI (cloud)         : tests-heavy 37711345817 SUCCESS · ci 37711974330 SUCCESS
```

**Wave 5 verification, 2026-10-07** (sequential, AGENT_RULES §14):
```
brain/router/tests : 154 passed in 36.00s   (+10 tier-routing)
brain/tests        : 167 passed, 1 warning in 14.39s
tests/ (root)      : 203 passed, 7 xfailed, 1 failed
                     (failure = pre-existing shadow-row count, reproduced on clean
                      main; already filed by brain-core → qa-security)
```

**Wave 4 verification, 2026-10-07** (sequential per AGENT_RULES §14, stack untouched):
```
brain/router/tests : 144 passed in 35.94s
brain/tests        : 152 passed, 1 warning in 12.09s   (fastapi deprecation, unrelated)
tests/ (root)      : 197 passed, 9 xfailed             (qa-security contract+supervisor; xfails = their open tripwires)
```

**Wave 3 verification, 2026-10-07** (`RAPHAEL_INSTANCE=router`, run one suite at a
time per AGENT_RULES §14, no orphan processes left):
```
$ brain/.venv/bin/python -m pytest -q brain/router/tests
120 passed in 28.10s

$ brain/.venv/bin/python -m pytest -q brain/tests
125 passed, 1 warning in 9.82s        # warning = fastapi/starlette deprecation, unrelated

$ brain/.venv/bin/python -m pytest -q tests/conformance
2 passed in 0.19s

TOTAL: 247 passed
```

**Wave 2 verification, 2026-10-06** (`RAPHAEL_INSTANCE=router`):
```
$ brain/.venv/bin/python -m pytest -q brain/router/tests        # includes 12 paid-slot tests
92 passed in 27.60s

$ brain/.venv/bin/python -m pytest -q brain/tests               # brain-core, my changes must not break it
117 passed, 1 warning in 9.94s                                  # warning = fastapi/starlette deprecation, unrelated

$ brain/.venv/bin/python -m pytest -q tests/conformance
2 passed in 0.01s

TOTAL: 211 passed
```
Paid-slot commits: `f745a7f` (implementation) + `818494f` (tests), on top of the merged
Wave 2 head (rebased onto `main` per AGENT_RULES §4). **No live paid call was made** —
every paid-path test runs against the local mock server (AGENT_RULES §7).

Earlier dev-time probes, kept for the record (read-only, no completions, no spend, no
keys printed): Groq `GET /models` → 200/11 models (also proved the need for a real
`User-Agent` — Cloudflare 1010 rejects urllib's default); Zen `GET /models` → 200/88
models, no `free`/capability metadata. Live paid-endpoint discovery (the
`opencode-go/deepseek-v4-flash-vision-exp` id in PAID_USAGE/WAVES) was the integrator's
observation, not a call from this lane.
