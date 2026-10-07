# router — lane task list (owner: router lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/router.md. Requests to you: `ls docs/requests/*__to__router__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Interface first + deterministic mock: `chat/vision/transcribe/health` exactly per INTERFACES §(a) with `MockProvider` (chain `["mock"]` / `RAPHAEL_ROUTER_MOCK=1`) so other lanes can build against it with no key and no network.
- [x] Groq client behind chat() — OpenAI-compatible https://api.groq.com/openai/v1, key from .env (presence-only checks).
- [x] Chain wiring: providers.chain=[groq, zen_free]; Go/paid gates stay enforced; discovery never hardcodes model IDs (live `GET /models` + `router.role_hints` scoring; deny-hints keep classifiers/TTS out; Zen = free-vs-paid by id, everything else paid).
- [x] Real implementations: OpenAI-style tool calls (normalized + JSON repair) and SSE streaming; vision via base64 `image_url`; model-vanished → re-discover once.
- [x] transcribe() = Groq Whisper for voice.stt_engine=groq (keep local faster-whisper seam behind profile local — `set_local_transcriber()`).
- [x] vision() cloud seam (config vision.provider) — caller passes pre-gated, downscaled images (PROTOCOL §7); router still re-checks Private Mode + blocklist + byte cap.
- [x] **Vision-only PAID slot** (new task from coord inbox, USER-APPROVED 2026-10-06, `docs/PAID_USAGE.md`): `providers.allow_vision_paid` unlocks ONE Go-tier vision model for the `vision()` purpose ONLY — chat/tools/STT never see it (`allow_go_runtime`/`allow_paid_runtime` stay false); discovery by capability (live `/models` + vision-hint score, never hardcoded ids, score 0 → `E_OFFLINE`/`no_model` with zero spend); `vision_paid_daily_cap_usd` hard stop → `vision()` raises `E_OFFLINE` + coord attention "vision daily cap hit" (once/day); state in `<repo>/run/vision_paid_daily.json` (date rollover resets); cost = provider-reported amount or tokens × conservative price (`config.d/router.yaml → router.vision_paid_price_per_mtok`, MODEL_POLICY sibling upper bound); mock unit tests only, no live paid calls.
- [x] RouterError -> PROTOCOL §10 codes for every failure class; health() covers groq+zen.
- [x] Resilience: Retry-After + x-ratelimit-* headers, 429/5xx backoff with jitter, per-provider RPM/TPM budgets, circuit breakers (jittered cooldown), failover along the chain, spoken-friendly `E_PROVIDER_*` details.
- [x] Privacy gates: secret redaction before every cloud call, Private Mode = zero egress, foreground-blocklist hook (`set_foreground_check`) forces vision refusal, images metadata-only in logs.
- [x] Unit tests with mocked HTTP only (no network, no keys in output) + placeholder-text guard that fails on any `[provider:model] response`.
- [x] ~~**BLOCKED → request sent:** `vision()` has no FREE vision model to select~~ **BLOCKED — HUMAN DECISION PENDING** (amended decision, inbox 2026-10-06): Wave 2 exit criterion 3 stays on the exit list in docs/WAVES.md annotated *BLOCKED — human decision pending* (options: defer to Wave 6 / approve a spend-capped vision slot; ATTENTION posted to the user — exit criteria are the human's to change, authority rule `340398b`). **No code change:** `vision()` keeps refusing with `E_OFFLINE`/`no_model` — never send an image to a model that never claimed the capability (Groq 11 ids / Zen 14 `-free` ids, none vision; Zen's only vision id is paid, spend is human-only per AGENT_RULES §7). **`E_BLOCKED` DECLINED for Wave 2** — `reason` stays the discriminator (`private_mode` / `blocked_window` / `cloud_vision_disabled` / `chain_exhausted`); no PROTOCOL §10 edit, zero consumer churn.

## Wave 3 (start only when WAVES.md says so — current_wave: 3 — opened via coord inbox `wave_open`)

(start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — full evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

## Wave 3 (docs/WAVES.md current_wave: 3 — opened via coord inbox `wave_open`)
- [x] **Usage/rate tracking surfaced in `/status`** — `brain.router.usage_status()`
      (`brain/router/status.py`): 24 h `usage.jsonl` aggregation (calls/tokens/
      by_provider/by_purpose/error codes) + live RPM/TPM/cooldown/circuit state per
      provider + `vision_paid` budget; no network, no keys, survives missing/corrupt
      logs (8 tests). Endpoint is brain-core's → request
      `router__to__brain-core__surface-usage-in-status.md` **APPROVED**, brain-core wires it.
- [x] **Schema-normalization edge cases** — 18 mock tests pinning provider dialects
      (`test_normalization_edge.py`) + 3 real fixes they caught: non-list `choices`
      no longer yields a silent empty success, non-numeric `usage` tokens coerce to 0
      (was a raw `ValueError`), non-dict `message`/`usage` guarded.
- [x] **Go provider code kept but off** — `GoProvider` still gated by
      `allow_go_runtime: false` (regression: `test_go_provider_stays_gated_off`).
- [x] **Speed mandate** (PAID_USAGE broad approval 2026-10-07): `mimo` added to fast
      role hints (opencode-go/mimo-v2.5 / flash-class defaults) + MODEL_POLICY `never`
      models (`grok`, `kimi`) denied for chat/vision in code defaults AND the
      `config.d/router.yaml` fragment — cost hygiene stays in force.
- [x] **BUGS-WAVE2 Bug A** — regression test: every Go-endpoint request carries
      `x-opencode-session` (stable per process) + router User-Agent; proven failing
      without the hotfix.
- [x] **BUGS-WAVE2 Bug B (router half)** — intent→tool mapping lives in brain-core's
      `brain/fastpath.py` → request filed and **APPROVED**
      (`router__to__brain-core__fastpath-open-search-mapping.md`); pc-control owns the
      body `open_app` half.

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [ ] Provider failure-injection resilience suite (429/5xx/network-drop storms, circuit-breaker transitions, failover ordering) + usage-log integrity audit + prompt-bias STT seam regression (Wave-3 live gate).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
