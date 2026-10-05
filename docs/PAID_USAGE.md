# PAID_USAGE.md — running paid-pool spend log (Raphael build)

Rules: paid Zen models + Go models beyond the Go limits both draw on the same **$2.00** pool. Assume every Go call is billed. Log BEFORE (estimate) and AFTER (actuals). Stop paid use below $0.30 remaining. Ask the user if a single call > $0.25.

| # | Date | Task | Provider | Model | Est in/out tok | Est cost | Actual in/out tok | Actual cost | Running total | Remaining est. | Why it qualified (T3/T4 rule) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| — | — | (none yet) | — | — | — | $0.00 | — | $0.00 | **$0.00** | $2.00 | — |

## Notes
- 2026-10-04: log created. Free tiers in use for all Phase 0 work.
- Free models that are also free on the Go endpoint (`longcat-2.5-preview-free`, `space-bunny-free`) are T0-cost but still logged here if called via Go, for reconciliation.

## 2026-10-05 — Authorization: opencode-go as sparing fallback
- User directive: "we can use the opencode go models now but sparingly" — Go tier re-authorized as
  FALLBACK when Ollama free-plan cloud (gpt-oss:120b-cloud etc.) rate-limits or underperforms.
- Rules: cheapest-first (opencode-go/mimo-v2.5 default; qwen3.7-plus only for hard debugging),
  log every Go call here with model + estimated cost, $2.00 paid-pool cap still governs.
