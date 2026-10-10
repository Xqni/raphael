# R3-VULNCLAW: Paper-only VulnClaw Integration Assessment for Raphael

**Assessment ID:** R3-VULNCLAW
**Type:** QA-Security Reviewer (paper-only)
**Project:** <repo-root>
**Date:** Fri Oct 09 2026
**Scope:** Evaluate VulnClaw strictly as an external black-box security test tool against Raphael's deliberately exposed surface (WS/REST API, relay, web UI). No runtime execution, no installation, no scanning, no code changes.

**NON-NEGOTIABLE FRAMING (top of report, per Wave R directive):**
VulnClaw is an autonomous offensive security agent with real exploitation and arbitrary command/code execution tools (`shell_command`, `python_execute`, PoC generation), and an optional `full_access` mode that skips all confirmations. Its own docs warn that `full_access` is unsafe outside an isolated throwaway environment because content from a target is untrusted and can drive unconfirmed command execution via prompt injection. It is NEVER a dependency of Raphael's runtime and NEVER gets API/tool access to Raphael's own control plane, secrets, or the user's real machine. The only legitimate use under evaluation is: pointed FROM an isolated VM/container AT Raphael's own exposed surface (the WS/REST API, the relay, any web UI) as an external black-box security test, with the user's explicit authorization since it's their own system, and only in `ask` or `auto_review` mode, never `full_access`.

## 1) Sources Consulted (cite URLs and access date)

All sources fetched from VulnClaw public repository (paper-only). Accessed 2026-10-09.

- README (EN): https://raw.githubusercontent.com/Netw0rkNoob/VulnClaw/main/README_EN.md (accessed 2026-10-09)
- README (ZH): https://raw.githubusercontent.com/Netw0rkNoob/VulnClaw/main/README.md (accessed 2026-10-09)
- SECURITY.md: https://raw.githubusercontent.com/Netw0rkNoob/VulnClaw/main/SECURITY.md (accessed 2026-10-09)
- CHANGELOG.md: https://raw.githubusercontent.com/Netw0rkNoob/VulnClaw/main/CHANGELOG.md (accessed 2026-10-09)
- GitHub Repo API: https://api.github.com/repos/Netw0rkNoob/VulnClaw (accessed 2026-10-09)
- Commits (latest): https://api.github.com/repos/Netw0rkNoob/VulnClaw/commits?per_page=1 (accessed 2026-10-09)

Quotes below reference section/file names from those sources.

## 2) Live Repo Metadata (verified)

From GitHub API (accessed 2026-10-09):

- **Repository:** Netw0rkNoob/VulnClaw (public)
- **Stars:** 3516
- **Forks:** 486
- **Open Issues:** 4
- **License:** MIT (SPDX MIT)
- **Language:** Python
- **Alpha self-description:** "Public alpha" stated in README_EN: "Public alpha: VulnClaw is public alpha software for authorized security testing, CTFs, labs, and controlled research." (README_EN "Security Notice", accessed 2026-10-09)
- **Last commit:** 0b34878f84b089b21fcf85ecd445315f14df0672 (commit message "Dev (#301)"), authored/committed 2026-10-05T15:34:33Z (verified signature present in API response). (Commits API, accessed 2026-10-09)
- **Created:** 2026-04-18T13:02:17Z; updated 2026-10-09T21:05:01Z (Repo API, accessed 2026-10-09)
- **Releases/issue signals:** open_issues=4; no obvious "stable" release banner emphasized beyond PyPI v0.4.1 badge in README (badges show PyPI v0.4.1). (README badges, Repo API, accessed 2026-10-09)

**Verification note:** All above values were fetched via GitHub API/raw files. No local git operations performed.

## 3) Capabilities Relevant to Safety (evidence from docs)

From README_EN features (accessed 2026-10-09):
- **Model-Led Solver Engine (default)** and autonomous loop.
- **Execution approval modes**: "ask (default, y/N per request), auto_review (read-only allowlist runs unattended, rest still prompt), full_access (everything runs, no prompts)". (README_EN "Execution Approvals")
- **Dangerous tools**: "Dangerous tools (shell / python / PoC) prompt 'Approve this execution? [y/N]' before every run by default." and built-in tools include `python_execute`, `shell_command`. (README_EN)
- **Safety warning on full_access:** "Under `full_access`, target responses, page content and reports are untrusted input — prompt injection can drive unconfirmed arbitrary command execution. Reserve it for isolated labs, CTFs and throwaway VMs; for real engagements prefer `auto_review` plus your own trusted prefixes." (README_EN "Execution Approvals", emphasis in docs)
- **PoC generation & reporting:** auto report + runnable Python PoC scripts. (README_EN Features)
- **Native HTTP tools:** `fetch`, `http_probe_batch`, traffic evidence store; MCP optional (chrome-devtools/burp). (README_EN MCP/Tools)

From SECURITY.md (accessed 2026-10-09): "VulnClaw is designed for legal, authorized penetration testing, security auditing, and educational Capture the Flag (CTF) challenges. Running automated scans or exploit payloads against unauthorized targets is illegal." and vulnerability reporting via private channels.

**Conclusion (from docs):** VulnClaw is explicitly an offensive agent with real execution capabilities and an unsafe `full_access` mode. It is not presented as a safe-by-default scanner-only tool.

## 4) (a) Maturity/Maintenance Verdict (skepticism for public Alpha)

**Verdict:** Public Alpha — **cautiously maintainable but not production-hardened**. Skepticism is warranted.

**Rationale (evidence-based):**
- **Status:** Explicitly "Public alpha" (README_EN Security Notice). No "stable" release claim found.
- **Recent activity:** Active development visible (last commit 2026-10-05T15:34:33Z, v0.4.1 changelog entries including Windows TUI fixes). Maintainer active recently. (CHANGELOG.md v0.4.1, Commits API)
- **Scale/community:** 3516 stars, 486 forks — healthy interest, but popularity ≠ maturity. Open issues small (4). (Repo API)
- **Risk surface:** Model-led autonomous loop + `shell_command` + `python_execute` + PoC generation means behavior depends on LLM tool use and untrusted target content. Docs explicitly call out `full_access` prompt-injection risk. (README_EN)
- **Tooling scope:** Sub-agent fan-out, evidence memory, context compaction, traffic store — non-trivial agent design (recent changelog shows ongoing hardening). (CHANGELOG.md)
- **Skepticism points (Alpha-appropriate):**
  - Prompt injection from target responses can influence tool selection/arguments (documented risk).
  - `full_access` removes confirmations entirely (must not be used).
  - Execution is real (shell/python) — misuse or misconfiguration is dangerous.
  - External MCP dependencies (chrome-devtools/burp) add moving parts.
  - Public Alpha means interface/behavior can change; not "battle-tested" as a general dependency.

**Maintenance signal:** Recent commits suggest maintenance, but Alpha status remains the correct classification. (NOT VERIFIED: internal test coverage metrics beyond codecov badge; not fetched.)

## 5) (b) Minimum Safe Sandbox (paper-only proposal; do not execute)

The only legitimate use under evaluation is external black-box test against Raphael's exposed surface (WS/REST API, relay, web UI), from an isolated environment, user-authorized, in `ask` or `auto_review` mode, never `full_access`.

Proposed minimum controls (paper-only):

- **Disposable isolated VM:** Run VulnClaw in a throwaway VM (no persistence of secrets across runs). Snapshot before test; revert after.
- **No host-shared filesystem/clipboard:** VM has no shared folders/clipboard to host. All artifacts exported via controlled means only if needed.
- **Network allow-list only to Raphael test surface:** Restrict egress/ingress to Raphael's deliberately exposed test port(s) (e.g. WS/REST/relay/web UI). Block all other destinations. Treat target as untrusted.
- **No shared creds/secrets:** VulnClaw must not have access to Raphael control plane credentials, user real machine secrets, or any shared tokens. Use test-only credentials if any.
- **Snapshot/revert:** Pre-test snapshot; automatic/explicit revert after session.
- **Resource limits/logging:** CPU/memory/NET caps; full command/evidence/traffic logs stored inside VM (ephemeral) with timestamped audit trail.
- **User authorization gate:** Explicit written authorization recorded (scope, ports, duration). Enforce scope in network policy (allow-list).
- **Safety mode enforcement:** Force `ask` or `auto_review` (never `full_access`). Treat read-only allowlist strictly; review any shell/python/PoC execution.
- **No outbound requests beyond allowed test scope:** Per user constraint (and VulnClaw fetches are target-scoped). Block arbitrary outbound.
- **Containment of artifacts:** PoCs/reports generated inside VM; review before any export.

These are proposed guardrails (paper-only). Not executed.

## 6) (c) Decision: adopt-for-testing-only / reject / revisit-later

**Decision: ADOPT-FOR-TESTING-ONLY** (conditional), with strict constraints.

**Why (evidence):**
- **Legitimate narrow use case:** External black-box assessment of Raphael's exposed surface is the only proposed use. VulnClaw's model-led engine + HTTP tools (`fetch`, `http_probe_batch`) are capable of black-box probing of WS/REST/relay/web UI endpoints (from docs). (README_EN Features)
- **Safety is configurable:** Modes exist (`ask`, `auto_review`) to require confirmation; `full_access` is explicitly warned against. SECURITY.md mandates authorized testing.
- **Maturity acceptable for isolated lab:** Public Alpha but recent maintenance (v0.4.1 Oct 2026) and active community. With strict sandboxing it's usable for authorized internal testing.
- **Not a runtime dependency:** "It is NEVER a dependency of Raphael's runtime…" per framing; keeping it external is key.
- **Constraints required:**
  - Never `full_access` — only `ask` or `auto_review`.
  - Isolated disposable VM + strict network allow-list to Raphael test ports only.
  - No access to Raphael control plane/secrets/host.
  - User authorization gate.
  - Evidence gates: require review of any proposed shell/python/PoC execution.

**Why not reject now:** The tool exists and matches the black-box external tester role if contained. Rejecting outright is not necessary given documented safety modes and authorized-only intent.

**Why not full adopt (production):** Alpha status, prompt-injection risk (documented), real execution surface — unsuitable as a persistent/production dependency or unrestricted use.

**Revisit-later triggers:** If repo becomes stable (non-alpha) with stronger guardrails, or if Raphael's test surface changes significantly. Current state supports testing-only with controls.

## 7) (d) What it can/cannot test about Raphael (WS/REST/relay) + evidence/reporting gates

### What it CAN test (black-box, external)
- **HTTP/REST surface:** `fetch` + `http_probe_batch` allow method/headers/params/cookies/body probing, response inspection (status, headers, body), same-body grouping. Can enumerate endpoints if discovered. (README_EN Features: "Enhanced fetch request tool", "Batch HTTP Probing")
- **Web UI:** Can interact via HTTP; optional MCP (chrome-devtools) enables browser automation if deployed, but MCP setup required (separate). Not mandatory. (README_EN MCP)
- **WebSocket/relay surface (black-box):** Can attempt WS handshakes/frames only via tools it has (fetch is HTTP; browser MCP may support some WS actions if configured). **NOT VERIFIED** from fetched docs whether built-in tools include a dedicated raw WS client beyond browser/MCP. Assume limited unless configured.
- **Fingerprinting/behavior:** Response diffing, traffic evidence store (`traffic_list/view/repeat/sitemap`) provides auditable request/response pairs. (README_EN "Native Traffic Evidence Store")
- **Vuln discovery/exploitation PoCs (black-box):** Model-led testing with safety modes; PoC generation + reporting. (README_EN Features)

### What it CANNOT test (by design/scope)
- **Internal control plane:** No API/tool access to Raphael's own control plane, secrets, or host machine by framing; black-box only. Cannot read internal configs/secrets not exposed.
- **Non-exposed paths:** Cannot discover internals not reachable from allowed test surface.
- **Host/runtime internals:** Cannot introspect Raphael process internals unless exposed via API/WS.
- **Unsafe actions without approval:** Blocked by `ask`/`auto_review`. Cannot run in `full_access` under these constraints.
- **Verification of some server-side logic:** Black-box limits (timing side-channels etc may be noisy). (NOT VERIFIED: full tool catalog beyond README; source files not fetched per "no code" except docs)

### Evidence/reporting gates (required)
Before/after any test run:

- **Authorization proof:** Scope, allowed ports/hosts, duration, user approval recorded.
- **Safety mode enforced:** Confirm `safety.permission_mode = ask` or `auto_review` (never `full_access`). Log mode at start.
- **Network policy enforcement:** Allow-list to Raphael test surface only; blocklist/egress deny by default.
- **Evidence completeness:** Require traffic evidence (`traffic_list/view`) for all external requests; `evidence_list/search/view` review for high-signal findings. (README_EN Evidence features)
- **Approval audit:** Log every shell/python/PoC execution approval/rejection (ask mode).
- **No leakage:** Review reports/PoCs before export (ensure no internal secrets/paths beyond allowed scope).
- **Scope compliance gate:** Any attempt to reach non-allowed host/port must be blocked and flagged.
- **Stop conditions:** On scope violation, safety mode change attempt, or unexpected egress → stop immediately.
- **Deterministic report review:** Use VulnClaw's solve report (deterministic from AgentState) as evidence; verify findings map to actual requests/responses. (README_EN "Automatic solve report")

## 8) Final Recommendation + 3 Key Facts

**Recommendation:** **ADOPT-FOR-TESTING-ONLY** — Point VulnClaw FROM an isolated disposable VM AT Raphael's deliberately exposed surface (WS/REST API, relay, web UI) for external black-box security testing, with explicit user authorization, and **only in `ask` or `auto_review` mode, never `full_access`**. Do not integrate into Raphael runtime; do not grant access to control plane/secrets/host.

**3 Key Facts:**
1. **High-risk execution surface:** VulnClaw includes `shell_command`, `python_execute`, PoC generation and an optional `full_access` mode that skips confirmations; docs warn `full_access` enables unconfirmed command execution via prompt injection from untrusted target content. (README_EN Execution Approvals)
2. **Alpha maturity with recent activity:** Public Alpha (README_EN), last commit 2026-10-05T15:34:33Z (v0.4.1), 3516 stars/486 forks — usable for isolated lab testing but not production-hardened. (Repo API/CHANGELOG)
3. **Safety is enforceable via modes + sandbox:** With `ask`/`auto_review`, strict network allow-list to test surface only, no host/shared creds/filesystem, snapshot/revert, and evidence/approval gates, external black-box testing is feasible without making it a Raphael dependency. (README_EN SECURITY.md)
