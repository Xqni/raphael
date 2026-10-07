# router — status

Updated: 2026-10-06 (Wave 2 **MERGED into main `1a8c2f6`** — criterion 3 amended to *BLOCKED: human decision pending*; idle until `wave_open`)

## Done (Wave 2 — all lane tasks except the one blocked request)

Commits on `agent/router`:
- `44fa303` — facade + providers + resilience + privacy + `config.d/router.yaml`
- `d06f000` — mock-server test suite (79 tests)

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

## Blocked
- **Wave 2 exit criterion 3 (live vision answer) — BLOCKED, HUMAN DECISION PENDING.**
  Amendment to the earlier "OPTION 3" call (coord inbox 2026-10-06; authority rule,
  commit `340398b`: **exit criteria are the human's to change**): criterion 3 is back
  on the exit list in `docs/WAVES.md`, annotated *BLOCKED — human decision pending*,
  with the two options — (a) defer to Wave 6, or (b) approve a spend-capped vision
  slot. An ATTENTION is posted for the user. **Nothing changes on my side:** no free
  vision model exists in the chain, so `vision()` keeps raising
  `E_OFFLINE`/`no_model` (never guess an image-capable model), and `wave_done` stands.
  Tech evidence (unchanged, independently verified by the integrator): Groq 11 ids
  (none vision), Zen 88 ids / 14 `-free` (none vision), Zen's only vision id
  (`deepseek-v4-flash-vision-exp`) is paid — paid-pool spend is human-only
  (AGENT_RULES §7), so no slot can be approved without the user.
- **`E_BLOCKED` DECLINED for Wave 2** — `reason` remains the discriminator
  (`private_mode` / `blocked_window` / `cloud_vision_disabled` / `chain_exhausted`).
  No PROTOCOL §10 edit; revisit only if a consumer needs code-level branching.
- Original request: `docs/requests/router__to__integrator__vision-free-model-gap.md`
  (Status flip is the integrator's).

## Wave 2 closed
- **MERGED:** `agent/router` → `main` at `1a8c2f6` (Wave 2; my head `147281e` is an
  ancestor of `main`). Router is first in merge order
  (`router → brain-core → pc-control → …`).
- `wave_done` posted to the coord bus. Suites green at post time:
  **80 router + 30 brain-core + 2 conformance = 112 passed** (commit `7413216`).

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
4. Vision criterion 3: not mine to resolve — wire a slot in one commit only if the
   user picks option (b) or a free vision endpoint appears in the chain.

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
$ brain/.venv/bin/python -m pytest -q brain/router/tests
79 passed in 20.49s

$ brain/.venv/bin/python -m pytest -q brain/tests        # brain-core, my changes must not break it
30 passed, 1 warning in 9.36s                            # warning = fastapi/starlette deprecation, unrelated

$ brain/.venv/bin/python -m pytest -q tests/conformance
2 passed in 0.01s
```
Live, read-only probes used to tune hints (dev-time only, no completions, no spend,
no keys printed): Groq `GET /models` → 200/11 models (also proved the need for a real
`User-Agent` — Cloudflare 1010 rejects urllib's default); Zen `GET /models` → 200/88
models, no `free`/capability metadata. No live chat/vision/STT run was performed —
those are the integrator's (AGENT_RULES §5).
