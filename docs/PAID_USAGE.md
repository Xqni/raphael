# PAID_USAGE.md — running paid-pool spend log (Raphael build)

Rules: paid Zen models + Go models beyond the Go limits both draw on the same **$2.00** pool. Assume every Go call is billed. Log BEFORE (estimate) and AFTER (actuals). Stop paid use below $0.30 remaining. Ask the user if a single call > $0.25.

| # | Date | Task | Provider | Model | Est in/out tok | Est cost | Actual in/out tok | Actual cost | Running total | Remaining est. | Why it qualified (T3/T4 rule) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| — | — | Wave-2 Go dispatches (brain phase 2 + voice phase; details in notes below) | opencode-go | mimo-v2.5 | — | — | not captured | see notes | **~$1.70** | **~$0.30** | free tiers failed 3× / rate-limited → escalation rule 0→1 |

## Notes
- 2026-10-04: log created. Free tiers in use for all Phase 0 work.
- Free models that are also free on the Go endpoint (`longcat-2.5-preview-free`, `space-bunny-free`) are T0-cost but still logged here if called via Go, for reconciliation.
- 2026-10-05 evening — USER-REPORTED correction: ≈$1.70 of the $2.00 pool consumed across the Wave-2 Go dispatches (brain phase 2 + voice phase, opencode-go/mimo-v2.5; escalation rule 0→1 after free-tier failures/rate limits). Per-call token actuals were not captured — provider dashboard is the source of truth; the table above is corrected to the user-reported figure. **Remaining ≈$0.30 = AT the stop line → NO further Go/paid dispatches until the user re-authorizes (OC monthly reset ~2026-10-06).**

## 2026-10-05 — Authorization: opencode-go as sparing fallback
- User directive: "we can use the opencode go models now but sparingly" — Go tier re-authorized as
  FALLBACK when Ollama free-plan cloud (gpt-oss:120b-cloud etc.) rate-limits or underperforms.
- Rules: cheapest-first (opencode-go/mimo-v2.5 default; qwen3.7-plus only for hard debugging),
  log every Go call here with model + estimated cost, $2.00 paid-pool cap still governs.

## 2026-10-05 — Wave 2 brain phase 2 (orchestrator-managed, user asleep, "manage everything")
- Task: brain /ws + loop + confirm build. Free models failed 3x on this task (gpt-oss:120b-cloud tool-hallucination x2 + fabricated test output; mimo-v2.6-flash-free rate-limited) → escalation rule 0→1 applied.
- Dispatch: brain-dev phase 2 on `opencode-go/mimo-v2.5` (Tier-1 default), background.
- Precedent: earlier free dispatches (gpt-oss:120b-cloud) built body-win phase 1+2 and brain phase 1 at $0.

## 2026-10-06 — USER-APPROVED vision-only paid slot
- **Approval (verbatim):** "you can use the opencode go paid models please for vision for now at least"
  (conversation, 2026-10-06 ~22:25) = human sign-off per AGENT_RULES §7.
- **Scope:** vision purpose ONLY (`providers.allow_vision_paid: true`); chat/tools/STT stay on the
  free chain (`allow_go_runtime: false`, `allow_paid_runtime: false` unchanged).
- **Model:** Go-tier vision (discovered id `opencode-go/deepseek-v4-flash-vision-exp`).
- **Cap:** `vision_paid_daily_cap_usd: 1.00` — router enforces daily; exceed -> E_OFFLINE + attention.
- Implementation: router lane (brain/router/**); gate = config.yaml (integrator).

## 2026-10-06 — user directive: Go models for LLM needs (overnight session)
- **Verbatim:** "use opencode go models for anyhting that needs an LLM since we are not using
  anything local for that" + "both voice and vision goes into cloud until i upgrade my RAM".
- Applied: conductor headless runs model = `opencode-go/mimo-v2.5` (was mimo-v2.6-flash-free);
  interactive sessions already default to `opencode-go/mimo-v2.5` (global config).
- Raphael runtime under cloud_temp unchanged beyond vision: chat/tools = Groq -> Zen free,
  STT = Groq Whisper, vision = approved Go slot ($1/day cap), TTS = LOCAL Fish-Speech (kept —
  Fish-Speech has no cloud API; swapping TTS to cloud would mean a different paid provider and
  losing the local Zira reference voice unless it supports cloning).

## 2026-10-07 — broad paid-fast approval (user, verbatim)
> "bruh we can use paid fast models as well lol dont worry about free stuff for
> for now. my limit just reset for the month, and the 5hr is resetting in a
> couple house as well so make the most of it while we can"

Scope: ALL model usage (session, conductor runs, lanes, router tiers) — free-tier
scarcity no longer applies for this window. Cost hygiene rules (caps, no local
GPU, spend logging) stay in force.
