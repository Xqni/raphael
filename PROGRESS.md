# Raphael — PROGRESS

Status legend: DONE / IN-PROGRESS / BLOCKED / NEXT
Model tier used per step: T0 = no LLM, T1 = mimo-v2.6-flash-free, T2 = strongest other free, T3/T4 = paid pool (log to docs/PAID_USAGE.md)

## Session 2026-10-04

- DONE (T1): Verified live OpenCode v2 agents docs (`opencode.ai/v2/docs/agents/`): `.opencode/agents/<name>.md`, frontmatter `mode: primary|subagent|all`, `description`, `model: provider/model`, `steps`, `permissions` (ordered rules, last match wins), subagent inherits parent model unless configured. `v2.opencode.ai/agents.md` 404s — use opencode.ai/v2/docs/.
- DONE (T0): Initial env probe: WSL2 Ubuntu 26.04, kernel 6.18.33.2, 20 cores, 7.6 GiB WSL RAM / 2.0 GiB swap, `/` 869G free, `/mnt/c` 483G free, interop present (wsl.exe/powershell.exe/cmd.exe).
- DONE (T1): Phase 0 — `scout` subagent wrote `SYSTEM_REPORT.md` (218 lines; user correction applied: WSL VHD shares C:'s 482.8 GB — one storage pool).
- DONE (T1): Local model verification — `qwen3.5` family live on Ollama (4b=3.3GB unified text+vision resident pick; 9b=6.6GB on-demand offline fallback; Ajax not released → gated optional candidate).
- DONE (T1): Tier-2 shootout, 2 rounds, real `opencode run` invocations: basic = 3/3 PASS; multi-step chain = 4/4 PASS with times big-pickle 33s, fledge-alpha-free 37s, ling-3.1-flash-free 59s, nemotron-3.5-lightning-free 117s. **T2 = `opencode/big-pickle`** (fallback fledge-alpha-free). Docs updated.
- DONE (T1): `docs/MODEL_POLICY.md`, `docs/PAID_USAGE.md`, `docs/TEAM_ROSTER.md` written. Paid spend still $0.00.
- DONE (T1): Post-Phase-0 directives captured in `docs/REQUIREMENTS_ADDENDUM.md`: Raphael-as-orchestrator north star; GitHub tool (user creates private build repo; runtime repo creation with visibility heuristics, public=confirm); Odysseus-style memory (researched live: pinned+hybrid retrieval, untrusted-context wrap, owner scoping); self-writing skills (Odysseus SKILL.md format, draft+confidence gate); `slut` model permanently excluded.
- DONE (T0): `.wslconfig` created at `C:\Users\jxesu\.wslconfig` (memory=10GB, swap=4GB, vmIdleTimeout=600000) with user approval — takes effect next WSL restart/reboot, NOT shut down now. Windows RAM recheck: 5.3 GB free (Premiere closed; low reading during scout was Premiere).
- DONE (T0): `git init` (branch `main`), `.gitignore` (.env/venvs/logs/db excluded), remote `origin = https://github.com/Xqni/raphael.git` (private). `gh` authenticated as Xqni (keyring) → can push without user action.
- DONE (T1): Addendum §7-9: voice-first confirmation loop, Raphael auto-grants runtime worker permissions (dedicated auto-permit OpenCode config dir; gate = her own confirmation layer), GitHub repo URL.
- DONE (T1): `docs/PROTOCOL.md` written (transport :8765 + NAT/localhostForwarding rationale, token handshake, roles body/ui/cli + capability matrix, message catalog, binary PCM frames, job state machine, act_req allow-list incl. no-arbitrary-shell rule, confirmation flow, 16 error codes, security invariants).
- DONE (T1): `docs/ARCHITECTURE.md` written (process topology + mutual watchdog, directory layout + per-agent ownership map, job engine/input-lock/priority/limits, fast path, router chain, privacy rules, memory+skills design, latency instrumentation, config.yaml surface, reliability matrix).
- IN-PROGRESS (T1): background subagent creating 13 `.opencode/agents/*.md` files per roster (ses_ef58fead1ffeVNLV0b7eVuL1To).
- NEXT: verify agent files + spawn-test one; initial commit; Wave 1 (2-3 of: supervisor / orb / router / body per dependencies); reviewer gate after each module.

## Paid-pool spend log
See docs/PAID_USAGE.md. Running total: $0.00 of $2.00.
