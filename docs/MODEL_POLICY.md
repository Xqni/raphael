# MODEL_POLICY.md — Raphael build-time model tiering (DRAFT, Phase 0)

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
| T3 | Paid pool, cheap | primary: `opencode-go/glm-5.3-flash` (0.15/0.50); alt: `opencode-go/gpt-6-luna` (0.10/0.50), `opencode-go/deepseek-v4.1-flash` | only after T1/T2 failed twice (log both attempts) or a listed hard task |
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
