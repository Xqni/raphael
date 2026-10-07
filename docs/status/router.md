# router — status

Updated: 2026-10-06 (vision-only PAID slot implemented per new coord task — 211 tests green, re-posting `wave_done`)

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

## Test output (real runs only — 2026-10-06, `RAPHAEL_INSTANCE=router`)
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
