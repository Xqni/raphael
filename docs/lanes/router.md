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

- [x] Provider failure-injection resilience suite (429/5xx/network-drop storms, circuit-breaker transitions, failover ordering) + usage-log integrity audit + prompt-bias STT seam regression (Wave-3 live gate). **DONE 2026-10-07** — `test_resilience.py` (12: 429 storm + Retry-After cooldown, 5xx storm → breaker OPEN → half-open recovery, network-drop isolation, §10 exhaustion code matrix, failover ordering via request timestamps, bounded 10-call storm), `test_usage_log_integrity.py` (6: stable schema, FAILED lines carry §10 codes, no prompts/keys/images in the log, concurrent writes, torn-line crash recovery + crash-safe append fix in core), `test_stt_seam_prompt_bias.py` (6: wake_word → `prompt` field on the Groq multipart, STT-only, INTERFACES signature unchanged, repo config wiring). Failure-path usage logging added (per-provider error counts for `/status`). Also answered qa-security's 2 OPEN requests (both already DONE by Wave-2 → Status DONE with evidence); circuit-open tripwire stays with the integrator request. 144 router / 152 brain / 197 root tests green — mock only, live stack untouched.

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Analysis-mode routing: tier-aware model policy (deeper model for Analysis/Simulation kinds, still Rule-15 fast for normal turns) + usage accounting for the new purposes. **DONE 2026-10-07** — new `deep` role (hints `120b…large/pro/max/ultra`, tie → BIGGEST id, deny-hints apply → `grok`/`kimi` unreachable in every tier); `purpose_roles: {analysis: deep, simulation: deep}` in code defaults + `config.d/router.yaml`; `_role_for` lets a deep-mapped purpose outrank the tools→strong rule (chat/ack/tools unchanged → Rule 15 intact); usage accounting buckets the new purposes (`usage_status().by_purpose.analysis|simulation`, `usage.jsonl.task_kind`, failure lines too). 10 tests (`test_tiered_analysis_routing.py`). Contract: `router__to__integrator__interfaces-purpose-enum-analysis.md` (OPEN) extends INTERFACES §a purpose enum — implementation backward-compatible either way. Known unrelated root failure `test_interfaces_instance_table_is_collision_free` (12 rows after the APPROVED shadow row) reproduces on clean main and is already filed by brain-core (`brain-core__to__qa-security__shadow-row-count.md`).

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [x] Read `docs/audit-tasks/router.md` → your IDs: **SEC-8, ARCH-5, F-4** — VERIFY-FIRST (verbatim file:line, then CONFIRMED / NOT-APPLICABLE / ALREADY-DONE), QA-4: link a green CI run with your wave_done. Source register + dedupe: `docs/AUDIT-2026-10-07.md`. Rules: stack down (spawn only for your test), one suite at a time, heavy suites in cloud (`gh workflow run tests-heavy.yml`), Rule 15 speed, cost not a factor. **DONE 2026-10-08** (verify-first, quotes in docs/status/router.md + coord task_dones): SEC-8 = CONFIRMED→FIXED (append-only `run/vision_paid_ledger.jsonl`, daily $1 + $10 total ceilings, `E_BUDGET` fail-closed incl. write-failure + race lock + malformed-usage floor, 8 tests); ARCH-5 = CONTRIBUTED (chain presets requested — fragment route blocked by Core-Guard, exact YAML in request; per-provider data-handling table with UNVERIFIED retention flags); F-4 = DONE (`rate_headroom()` in `/status`, orb shipped + closure ANSWERED, `router__to__orb__headroom-in-menu.md`); QA-4 = CI 37722900664 (branch green) + fresh heavy runs below.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
