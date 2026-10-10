# MODEL_POLICY.md — Raphael build-time model tiering (DRAFT, Phase 0)

## VALUE MODEL LADDER — 2026-10-09 catalog audit (200 unique models priced; user: "good but also cheap")

Full-catalog dedupe done via the models API; picks below are the cost-per-quality winners,
with the cache-read price called out because long sessions are cache-dominated (today's
Sol burn was cache+output on a 1M-token session, not the per-call price).

| Role | Pick | Price in/out per 1M (cache read) | Why |
|---|---|---|---|
| Integrator default | opencode/mimo-v2.6-flash-free | $0 (free) | policy #1; paid only per-turn by request |
| Lane routine default ('everything else') | opencode-go/mimo-v2.5 | $0.14/$0.28 ($0.0028) | USER 2026-10-09: 'other cheaper models for everything else' — proven workhorse; best cache economics |
| Lane sessions (ALL) | opencode-go/mimo-v2.5 | $0.14/$0.28 ($0.0028) | USER 2026-10-09: no model upgrades on sessions — flagships/strong models are per-DELEGATION subagent picks only; the earlier haiku session assignments were reverted |
| Issues & debugging (SPARINGLY) | opencode-go/claude-haiku-5-5 | $0.10/$0.50 ($0.01) | USER 2026-10-09 (revised same day: 'use haiku sparingly... burning through my creds') — ONLY for small-context issues/debugs. READING-HEAVY work (repo-wide reviews, big-file audits) goes to opencode-go/mimo-v2.5: identical speed class but cache-read $0.0028 vs $0.01 = 3.5x cheaper on large contexts. Haiku never for whole-repo tasks; deepseek-v4-pro only if cheaper tiers stall |
| Reading-heavy reviews | opencode-go/mimo-v2.5 | $0.14/0.28 ($0.0028) | cheapest cache economics — the right tool when a task means READS a lot of files |
| Small paid per-delegation (user-approved set) | claude-haiku-5-5 ($0.10/$0.50), gpt-6-luna ($0.10/$0.50), deepseek-v4-pro ($0.66/$1.98) | | USER 2026-10-09: approved 'when needed' AND 'only for really tough tasks' — qualifying class ONLY: hard debugging after 2 failed cheaper attempts, intricate race/security design, or one-off hard problems. NOT for routine delegation; free/mimo covers everything else; never session defaults |
| Big-context tasks (>200k) | opencode-go/minimax-m3 | $0.30/$1.20 ($0.06) | 512k context — cheapest big-brain |
| Code-specialist escalations | opencode-go/kimi-k2.7-code | $0.95/$4.00 ($0.19) | named-task only |
| Cheap strong alternates | gpt-6-luna ($0.10/$0.50), qwen3.8-flash ($0.15/$0.47), deepseek-v4.1-flash ($0.15/$0.60, $0.003 cache), glm-5.3-flash ($0.15/$0.50) | | substitution pool when a primary is rate-limited |
| Flagship on user's named task only | qwen3.8-max / grok-4.7 ($2/$6), sonnet-5.5 / sol ($2/$10), glm-5.3 ($1.4/$4.4) | | requires the user to name the task |
| Never | muse-spark (trains on prompts), gpt-5.5-pro ($30/$180), o3-pro ($20/$80), daybreak ($12.5/$75), astra/fable/opus as defaults | | matrix bans + runaway cost |

Notable bargains found in the audit: gpt-6-luna and claude-haiku-5.5 both at $0.10 input
(the cheapest capable inputs); minimax-m3 buys 512k context for $1.20/M out. Notable
trap: openrouter mirrors exist for most models at identical prices — no arbitrage, so
pick by provider reliability, not price.

## CURRENT SPENDING POLICY — 2026-10-09 (overrides historical tier advice below)

Incident record: switching the long-context integrator session to Sol burned
~$3 of extra-usage credit within minutes ($9.72 -> $6.75, user-verified on the
web dashboard). Root cause: ~1M+ token session context x $0.2/M cache-read +
$10/M output per turn. The rules below exist because of that burn.

1. **Integrator stays on a FREE model by default** (mimo-v2.6-flash-free).
   A paid model for the integrator session requires an explicit per-turn user
   request; paid context cost scales with session length, so short turns are
   mandatory regardless of model.
2. **Last-reported credit is the working runway: $6.75 (2026-10-09).** Update
   this figure in PAID_USAGE.md whenever the user shares a dashboard reading.
   The Console MCP usage ledger is a DIFFERENT meter (cost ledger) — never
   subtract it from the credit balance, never treat it as a hard guard.
3. **Free-first while weekly quota = 100%** (resets ~2026-10-10 ~21h window):
   lane defaults and subagents use free models (mimo-v2.6-flash-free,
   big-pickle, ollama gpt-oss:120b-cloud, zen free flash). Paid (balance) only
   when a task genuinely cannot be done free AND the expected value > cost.
4. **Flagship models (Sol/Astra/Fable/Opus/o3-pro/Daybreak, any >$2/M output):
   never a lane default, never a whole-lane assignment.** Per-task paid
   delegation only, one at a time, short prompts, file-based handoffs to keep
   context small. Astra/Fable-class ($10+/M output) additionally require the
   user to name the task first.
5. **Balance floor: below $2.00 remaining credit, paid delegation stops
   entirely** (free-only + report blocked). User may move this floor.
6. **Any billing/limit error stops the paid path immediately** — save state,
   log, free fallback or report blocked. No paid retries.
7. **Every paid delegation gets logged** to docs/PAID_USAGE.md with model,
   task, and estimated cost; the user is told when a burn >$0.50 happens.
8. No budget cap, recharge change, or model-disable is set without the user
   saying so (their explicit standing instruction).

Lane sessions currently default to opencode-go/mimo-v2.5 (cheap paid); when
Wave 5P opens, flip suitable lanes to free defaults per rule 3.


Applies to the BUILD only (orchestrator + subagents). Raphael's own runtime model chain is defined in `config.yaml` and never uses paid-pool models unless the user flips `allow_paid_runtime` / `allow_go_runtime`.

## Verified facts (checked against live docs 2026-10-04)

- OpenCode v2.0.22. Agents: `.opencode/agents/<name>.md`, frontmatter `mode: primary|subagent|all`, `description`, `model: provider/model`, `steps`, `permissions` (ordered rules, last match wins). Docs: https://opencode.ai/v2/docs/agents/, /permissions/, /skills/, /plugins/, /mcp-servers/. (`v2.opencode.ai/agents.md` 404s.)
- A subagent uses its configured model, or inherits the parent's model if none is set. The native `subagent` tool accepts a per-call `model` override → the orchestrator CAN pick the tier per delegation (confirmed in practice: scout launched with explicit model).
- **Free Zen models (live list, 8):** `fledge-alpha-free`, `ling-3.1-flash-free`, `longcat-2.5-preview-free`, `space-bunny-free`, `mimo-v2.6-flash-free`, `muse-spark-1.3-contributor-free`, `nemotron-3.5-lightning-free`, `big-pickle` — all $0/$0 input/output.
- **Go (paid pool after limits):** user has Go at 100% with "Use balance" ON → every Go call is assumed billed to the $2.00 Zen balance (Go docs: "Go will fall back to your Zen balance after you've reached your usage limits"). CAUTION: GitHub issues #42938/#39470/#33495/#45324 report the fallback sometimes fails and requests block instead — so a billing-style error is NOT retried; fall back to free tiers immediately.
- Go per-token prices (USD/1M, input/output) verified via `opencode models` + Go docs: gpt-6-luna 0.10/0.50 · muse-spark-1.3-contributor 0.10/0.20 · mimo-v2.5 0.14/0.28 · glm-5.3-flash 0.15/0.50 · qwen3.8-flash 0.15/0.47 · deepseek-v4.1-flash 0.15/0.60 · minimax-m3 0.30/1.20 · qwen3.7-plus 0.40/1.60 · deepseek-v4-pro 0.66/1.98 · (grok-4.7 2/6, kimi-k3 3/15 — never).

## Tiers (cheapest sufficient wins)

| Tier | What | Models | Used for |
|---|---|---|---|
| T0 | No LLM | scripts/grep/linters/tests | anything a shell command can do |
| T1 | Default free | `opencode/mimo-v2.6-flash-free` | boilerplate, config, scripts, small edits, run tests, docs, status |
| T2 | Best other free | **`opencode/big-pickle`** (PASS, 33s), fallback `opencode/fledge-alpha-free` (PASS, 37s); backups: ling-3.1-flash-free (59s), nemotron-3.5-lightning-free (117s) | full-module implementation against protocol, debugging a failing test, code review, T1 shaky output |
| T3 | Paid pool, cheap | primary: `opencode-go/mimo-v2.5` (0.14/0.28 — cheapest output; actually used for the Wave-2 dispatches); alts: `opencode-go/glm-5.3-flash` (0.15/0.50), `opencode-go/gpt-6-luna` (0.10/0.50), `opencode-go/deepseek-v4.1-flash` | only after T1/T2 failed twice (log both attempts) or a listed hard task |
| T4 | Paid pool, strong | `opencode-go/qwen3.7-plus` (0.40/1.60) | rare; genuinely complex (job-engine races, WSL<->Windows interop, security design review) |

**Hard-qualifying tasks for T3/T4 (all conditions in the brief must hold):** concurrent job engine + resource arbitration design/debug, WSL<->Windows networking interop edge cases, auth/security design review, an intricate race/deadlock, or a bug persisting after 2 real Tier 1/2 attempts.

**Never paid:** Phase 0 scouting, docs, boilerplate, config, UI polish, repetitive edits, running tests, summarizing.

## Budget rules (hard)

- Paid pool cap: **$2.00** total; STOP paid calls when estimated remaining < **$0.30**.
- Every paid call: estimate cost BEFORE (input size + output cap, round up), record AFTER with actual tokens → `docs/PAID_USAGE.md`.
- Single call estimated > $0.25 → ask the user first. Ask user to check console balance every ~$0.50 of estimated spend.
- Any billing/limit error → stop, log, fall back to free tiers. No retry loops.
- Cheapest capable model; one good call over several mediocre ones.
- Agent-specific models live in `.opencode/agents/<name>.md` frontmatter; tier variants (`<name>-pro`) exist only for T3/T4 and are invoked only by explicit orchestrator decision. Per-delegation `model` override on the `subagent` call is the normal mechanism.
- Record the tier used for every delegation in `PROGRESS.md`.

## Escalation ladder

Free T1 → T2 → paid T3 → T4 → STOP and ask the user. On repeated free-model failure (3×), or rate-limit storms: save state to `PROGRESS.md`, back off exponentially, then move up one tier. If no free model works at all → stop and ask the user.
