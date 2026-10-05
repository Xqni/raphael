# TEAM_ROSTER.md — proposed build team (Phase 0, awaiting user OK)

All agents live in `.opencode/agents/<name>.md` (verified format: frontmatter `mode`, `description`, `model`, `steps`, `permissions`; Markdown body = system prompt). Default model = Tier 1 `opencode/mimo-v2.6-flash-free`. **Tier 2 (selected 2026-10-04 by 2-round tool-calling test, all PASS): `opencode/big-pickle` — 33s on the multi-step chain; fallback `opencode/fledge-alpha-free` (37s).**

| Agent | Owns (directories) | Default tier | Key permissions (least privilege) |
|---|---|---|---|
| `scout` | writes `SYSTEM_REPORT.md` only | T1 | edit: only SYSTEM_REPORT.md; no web, no subagents |
| `protocol-architect` | `docs/PROTOCOL.md`, `docs/ARCHITECTURE.md` | T1→T2 | edit: docs/**; shell: read-only inspection; webfetch yes, websearch no |
| `orb-dev` | `body/orb/**` | T1 | edit: body/orb/**; shell (npm/test); no websearch; no subagents |
| `body-dev` | `body/win/**` | T1→T2 | edit: body/win/**; shell (tests); webfetch for pywinauto docs |
| `brain-dev` | `brain/**` (loop, jobs, memory) | T1→T2 (T3 only after 2 failed attempts on job-engine races) | edit: brain/**; shell (pytest) |
| `router-dev` | `brain/router/**`, benchmark | T1→T2 | edit: brain/router/**; shell (benchmark runs) |
| `voice-dev` | `brain/voice/**` | T1→T2 | edit: brain/voice/**; shell |
| `supervisor-dev` | `supervisor/**`, `scripts/**` | T1→T2 | edit: supervisor/**, scripts/**; shell (no sudo / no wsl --shutdown) |
| `test-engineer` | `tests/**` | T1 | edit: tests/**; shell (pytest, raphael selftest) |
| `security-reviewer` | read-only audit | T2 (T3 for the main auth/security design review — qualifies as hard task) | edit: denied everywhere; read all; no subagents |
| `docs-writer` | `README.md`, `docs/**` (except PROTOCOL/ARCHITECTURE/MODEL_POLICY while others own them) | T1 | edit: README.md, docs/troubleshooting etc.; shell: read-only |
| `reviewer` | none — review only | T2 | edit: denied; read all; shell: read-only (tests allowed) |

**Paid-tier variants (T3/T4, only on explicit orchestrator decision):**
- `brain-dev-pro` — T3 `opencode-go/glm-5.3-flash` (alt `gpt-6-luna`): reserved for job-engine/interoperability bugs that failed twice at T1/T2.
- `architect-pro` — T4 `opencode-go/qwen3.7-plus`: reserved for security design review / race-condition architecture, single tightly-scoped call, logged in PAID_USAGE.md first.

**Shared deny rules for every agent:** `subagent: deny` (only the orchestrator spawns), `read *.env: deny` (allow `*.env.example`), `shell sudo *: deny`, `shell wsl --shutdown *: deny`, no downloads/installs of system software or models without orchestrator approval (stated in each system prompt).

**Concurrency:** max 2-3 subagents in parallel; back off exponentially on 429/5xx.

**Integration:** `git init` + one branch per workstream (per wave), orchestrator merges and runs integration tests. Builder briefs always include: goal, files owned, protocol interfaces to honor, acceptance tests, explicit do-not-touch list, and a structured report-back format (built / tests run with real output / open issues).
