# router — status

Updated: 2026-10-07 (Wave 5 Analysis routing complete — 154 router / 167 brain / 203 root green + 1 known pre-existing root failure, already filed)

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
