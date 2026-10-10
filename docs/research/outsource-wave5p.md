# Outsource Audit — Wave 5P (persona adoption)

**Date:** 2026-10-09 · **Author:** research sub-agent · **Status:** REPORT (no code, no installs, no commits)
**Scope:** For each hand-built Wave-5P component (see `docs/research/persona/06-CODE-ADOPTION-PLAN.md`), is there an OSS/GitHub project we should adopt instead? Areas: (1) confirm/guardrail policy frameworks, (2) agent-memory/context-slot frameworks, (3) Obsidian integration for the journal, (4) brief verdicts on remaining R4-gap/requests items.
**Out of scope (user's call):** vision/computer-use. **Not re-surveyed (per brief):** wake-word/VAD/MCP-SDK/UIA/SAST/orchestration/TTS-STT/skill-manifests — R2-TOOLING.md verdicts stand; no material error found in the overlap areas, so no updates issued.
**Method:** live verification of each repo via GitHub API (`stargazers_count`, `license.spdx_id`, `pushed_at`, `archived`) and docs/README fetches — **all checked 2026-10-09**. Cost bands: **S** ≈ ≤1 dev-day, **M** ≈ a few days, **L** ≈ >1 week / high risk.
**Binding constraints (from canon + Core Guard):** config-driven, confirm-first canon rules, gates strengthen-never-weaken, local-first (no cloud-memory without user approval), dependency-light async codebase.

---

## Area 1 — Confirm/guardrail policy frameworks (P3 user-editable confirm policy, P4 clarify-on-ambiguity)

Current implementation: `brain/confirm.py` — deterministic pre-dispatch gate: `RISKY_TOOLS` set + ordered `RISKY_PATTERNS` regex fallback → action ids → `config.yaml safety.confirm_actions` HIGH list; voice-yes rejected for HIGH risk; timeout aborts (never auto-approves). P3 makes the policy map user-editable config; P4 adds one clarify question on low-confidence intent.

| Candidate | Stars | Last push | License | Verified via | Verdict |
|---|---|---|---|---|---|
| **NeMo Guardrails** (NVIDIA-NeMo/Guardrails) | 7,270 | 2026-10-09 (active) | Apache-2.0 (LICENSE.md SPDX `Apache-2.0`; GitHub API spdx field says `NOASSERTION` because of SPDX-tag formatting — the *license text is Apache-2.0*) | [repo](https://github.com/NVIDIA-NeMo/Guardrails), [LICENSE.md](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/LICENSE.md) | **Reject** |
| **Guardrails AI** (guardrails-ai/guardrails) | 7,503 | 2026-10-09 (active) | Apache-2.0 | [repo](https://github.com/guardrails-ai/guardrails) | **Reject** |
| **LLM Guard** (protectai/llm-guard) | 3,217 | 2026-07-08 | MIT | [repo](https://github.com/protectai/llm-guard) — **`archived: true`** | **Reject (archived)** |

**Architectural fit — why all three fail the P3/P4 shape:**
- These frameworks guard *LLM conversation/output* (rails, validators, sanitizers). P3 gates *deterministic tool dispatch before execution* — a code-enforced, per-job, fail-closed path with voice-channel rules and scoped grants. NeMo Guardrails is config-driven (Colang/YAML) — it passes the "config-driven" checkbox — but its rails are evaluated **through an LLM runtime in the loop**; wiring it into the confirm path would put a probabilistic, latency-adding call inside a path that must abort-safe on any failure, and its rails model (dialog/input/output/execution) has no equivalent for "confirm per job id, non-voice channel for HIGH risk, timeout aborts". Guardrails AI validates LLM output structure — irrelevant to act-gating, and some Hub validators pull network resources (privacy smell). LLM Guard is archived — dead on arrival for a security control.
- **P4 (clarify-on-ambiguity)** is one clarifying question + max-1 repeat — ~30 lines of loop logic per the packet. A conversational-rails framework is 3 orders of magnitude more machinery for less control (and would need its own LLM config per rail).
- Adopting any of these would **add a dependency that can fail-open or hang** in the Core-Guard-adjacent path — a net security regression regardless of feature set.

**Conclusion:** keep `brain/confirm.py`; P3's externalized policy map in `safety.confirm_policy` (auto|confirm|never per named action class, regex fallback for unclassified tools) already delivers everything from these frameworks that fits our shape, with zero dependencies. Optional future (NOT 5P, no adoption): NeMo Guardrails could be evaluated as an *advisory, off-path* prompt-injection screen on inbound user text — only if a real injection gap is ever demonstrated; nothing in R4 shows one.

---

## Area 2 — Agent memory / context-slot frameworks (P5 named slots, P6 memory privacy)

Current implementation: `brain/memory/` — local SQLite (store/schema/fts/retrieval/profile/conversation), wave-4 export/wipe already shipped (`export.py`, `test_wave4_export_wipe.py`), plus reports/budgets. P5 adds slot-scoped retrieval ("switch to travel"); P6 adds spoken recall/forget/report affordances.

| Candidate | Stars | Last push | License | Local-first? | Verdict |
|---|---|---|---|---|---|
| **Mem0** (mem0ai/mem0) | 66,911 | 2026-10-09 (very active) | Apache-2.0 | **YES — verified:** Ollama LLM provider, Ollama embeddings (`nomic-embed-text`), local Chroma (`path`), self-hosted docker REST server with auth-by-default ([docs.mem0.ai](https://docs.mem0.ai/open-source/setup), [Ollama provider](https://docs.mem0.ai/components/llms/models/ollama), [Chroma](https://docs.mem0.ai/components/vectordbs/dbs/chroma)) | **Reject (replace) / Adapt (concepts)** |
| **Graphiti** (getzep/graphiti) | 31,600 | 2026-10-09 (active) | Apache-2.0 | Partial — Ollama via `OpenAIGenericClient` works, **but** requires Neo4j 5.26 / FalkorDB / Neptune + full-text backend service; **opt-out PostHog telemetry** (`GRAPHITI_TELEMETRY_ENABLED=false`); structured-output extraction degrades on small/local models | **Reject** |
| **Zep** (getzep/zep) | 4,953 | 2026-10-08 | Apache-2.0 (repo) | NO — Zep is now a **proprietary managed platform** ("Context Graph Engine" proprietary per Graphiti README's Zep-vs-Graphiti table); `getzep/zep` repo is examples/integrations only. **Zep self-hosted Community Edition server: NOT VERIFIED as a current offering** (2026-10-09) | **Reject** |
| **Letta** (letta-ai/letta, ex-MemGPT) | 25,093 | 2026-09-10 (~1 mo) | Apache-2.0 | YES — local mode + Ollama/LM Studio/llama.cpp verified ([docs.letta.com/self-hosting](https://docs.letta.com/self-hosting)); note Docker server image "no longer an actively maintained product surface" per docs | **Reject** |
| **LangMem** (langchain-ai/langmem) | 1,700 | 2026-10-02 (active) | MIT | In-process/Postgres via LangGraph stores; **hard dependency on LangGraph `BaseStore`** (README: `langgraph.store.memory.InMemoryStore`, `create_manage_memory_tool(namespace=(...))`) | **Reject (dependency) / Adapt (namespace idea)** |
| **cognee** (topoteretes/cognee) | 31,912 | 2026-10-09 (active) | Apache-2.0 | Local LLM possible but ETL-style extract→cognify pipeline needs LLM per ingest + graph/vector backend | **Reject (defer)** |

**Why nothing replaces `brain/memory` for P5/P6:**
- **P5 slots are a scoping feature, not a memory system.** A slot = a namespace on retrieval + session persistence — a `slot` column / metadata filter on an SQLite store we already own, test, and harden (injection/sqlite/fts hardening tests exist). Every candidate implements "memory" as an **LLM-in-the-loop extraction pipeline** (mem0 fact-extraction, graphiti edge extraction, cognee cognify, langmem background manager): each `add()` costs an LLM call, can hallucinate "facts", and adds failure modes to what is today a deterministic write. Latency-sensitive voice loop should not route memory writes through cloud LLM extraction by default (and local-extraction quality caveats are documented even by the vendors — graphiti README explicitly warns small/local models fail structured-output extraction).
- **P6 privacy is the strongest reason to reject:** "forget X" must be a *guaranteed* delete. A hand-owned SQLite row set is auditable and idempotent; a distributed memory fabric (vector store + graph DB + background consolidator) makes "did forget actually delete everywhere?" unprovable — directly against the P6 acceptance test "forget actually deletes (idempotent)".
- **Letta** is a whole agent *runtime* (agent server, Postgres state, its own memory blocks/recall/archival). Adopting it would replace `brain/loop.py` + jobs + protocol wholesale — total architectural conflict, L cost, and it obliterates the confirm/input-lock Core Guard. Reject with prejudice.
- **Mem0 is the least-bad and still wrong-shaped** for 5P, but two ideas are worth stealing at zero cost: (a) **metadata/user-run scoping** as the model for P5 slot filters, (b) its self-hosted posture is the reference for what "local-first memory" should mean if we ever revisit. No cloud platform usage without explicit user approval — noted and not proposed.
- **cognee/graphiti are "wave-7+ if ever"** candidates for long-term knowledge memory after the RAM upgrade; graphiti's opt-out telemetry is a standing red flag for this project's privacy canon.

---

## Area 3 — Obsidian integration for the journal (P7)

P7 spec: a `journal` tool appending a dated, redaction-checked entry to her vault journal (`vault/journal.md`, gitignored), read back on "what did you do recently". Vault is directly reachable from WSL (`/mnt/c/pipeline/vault`); existing `obsidian` subagent precedent = direct file writes.

| Candidate | Stars | Last push | License | Verified via | Verdict |
|---|---|---|---|---|---|
| **obsidian-local-rest-api** (plugin, coddingtonbear) | 3,013 | 2026-10-06 (active) | MIT | [repo](https://github.com/coddingtonbear/obsidian-local-rest-api) — description now: "A secure REST API **and Model Context Protocol (MCP) server** for your vault" | **Defer / optional add-on** |
| **mcp-obsidian** (MarkusPfundstein — note: `smithery-ai/mcp-obsidian` is **404/moved**) | 4,467 | 2026-08-31 | MIT | [repo](https://github.com/MarkusPfundstein/mcp-obsidian) README: requires the Local REST API plugin running + `OBSIDIAN_API_KEY`; tools = list/search/get/append/patch/delete; **pinned to `mcp` SDK 1.x, crashes on mcp≥2.0** (README warning) | **Reject (for P7 core)** |
| **obsidian-mcp-server** (cyanheads) | 695 | 2026-10-06 (active) | Apache-2.0 | [repo](https://github.com/cyanheads/obsidian-mcp-server) | Reject (duplicate of above, smaller) |
| **obsidian-mcp-tools** (jacksteamdev) | 829 | 2026-05-13 | MIT | [repo](https://github.com/jacksteamdev/obsidian-mcp-tools) — **`archived: true`** | Reject (archived) |

**Verdict — P7 core stays hand-built (trivial tool, cost S):**
- All MCP/REST routes require the **Local REST API community plugin installed and enabled inside Obsidian + an API key we must store** — i.e., the journal silently stops working when Obsidian isn't running or the plugin is disabled, and we take on a secret to manage. A direct file append works headless, always, with zero dependencies, and keeps **our redaction pass inside the write path** (an MCP `append_content` would bypass redaction unless we wrapped it anyway — at which point the MCP layer buys nothing).
- Sync caveat is a non-issue: Obsidian watches the filesystem and hot-reloads externally-written notes (existing obsidian-agent precedent).
- **Optional future adoption (defer, user opt-in):** the REST-API plugin now *bundles* an MCP server, so a single user-side plugin install could later give her broader vault read/search (richer "what did you do recently" answers, vault-wide Q&A) through opencode's existing MCP plumbing. That is a **feature expansion, not a P7 dependency** — and it needs the user to install the plugin and hand us the key (approval gate). If that day comes, prefer the plugin's own MCP server or MarkusPfundstein/mcp-obsidian (4.5k★, MIT) — but pin `mcp<2.0` for the latter.

---

## Area 4 — Brief verdicts: remaining R4-GAPS / docs/requests open items

| Gap/request | Any OSS to adopt? | Verdict | Notes |
|---|---|---|---|
| **REST-rate-limit** (R4 #5; `qa-security→brain-core__rest-rate-limit.md`) | **slowapi** — canonical repo is **laurentS/slowapi** (NOT `long2ice/slowapi` — 404): 2,068★, MIT, pushed 2026-10-08, active, 121 open issues ([repo](https://github.com/laurentS/slowapi)) | **Reject — hand-build** | The request explicitly says "Keep it dependency-free" and proposes reusing the WS ban structure (`WsHub._record_auth_fail`) for identical 429 semantics. slowapi would add `limits` + storage backend for ~40 lines of shared ban-map code. Cost M in-house. (If the dependency-free mandate is ever lifted, slowapi is the correct drop-in — S.) |
| **ws-query-token** (`qa-security→integrator__ws-query-token.md`) | none needed | **Reject — hand-build** | 5-line removal of the `?token=` query branch in `brain/ws.py`; header + frame auth already exist; no client uses query token. No library touches this. |
| **E_LOCK_BUSY / E_CIRCUIT_OPEN catalog entries** (R4 #6/#8) | none | **Reject — hand-build** | PROTOCOL.md §10 doc + error-mapping edits. |
| **disable-fastapi-docs** (R4 #7) | none | **Reject — hand-build** | `FastAPI(docs_url=None, redoc_url=None)` when production. One-liner. |
| **/activity endpoint** (R4 #9) | none | **Reject — hand-build** | Trivial FastAPI route + journal forwarding. |
| **config-confirm-categories AUD-11** (R4 #10) | none | **Reject — hand-build** | Config edit — this *is* P3's integrator-authored block; no framework applies. |
| **voice-confirm wiring/channel** (R4 #3/#4) | none | **Reject — hand-build** | Protocol-level wiring; R2 already covered orchestration. |
| **Laya unwired** (R4) | none (it's ours) | **Reject** | Laya is an in-house decision engine (`laya` skill); integration is shim work. |
| SEC-5 (.env presence-only), SEC-6 (Hyper-V firewall), lock-timeout watchdog, model-unsupported cache | none | **Reject — hand-build** | Policy/code fixes; nothing adoptable. |

---

## Final table — 5P-relevant components

| 5P component | Best candidate(s) examined | Decision | Cost if adopted | License | Architectural fit |
|---|---|---|---|---|---|
| **P3** user-editable confirm policy | NeMo Guardrails; Guardrails AI; LLM Guard (archived) | **REJECT all — hand-build policy map in config** (as planned) | — (adoption would be L + weakens Core Guard) | Apache-2.0/Apache-2.0/MIT-archived | ✗ LLM-in-loop, conversation-shaped, can't express per-job/channel/timeout rules |
| **P4** clarify-on-ambiguity | NeMo Guardrails conversational rails | **REJECT — hand-build** (one question, max 1 repeat) | — | Apache-2.0 | ✗ framework ≫ problem; adds LLM latency to turn loop |
| **P5** named context slots | Mem0; Graphiti; Letta; LangMem; cognee | **REJECT all — hand-build slot scoping on `brain/memory` SQLite**; **ADAPT** mem0's metadata-scoped-search semantics + LangMem namespace idea at zero dependency | — | — | ✗ all candidates route writes through LLM extraction (latency, hallucinated facts, failure modes); slot = a namespace column, not a memory system |
| **P6** spoken memory privacy | Mem0 (delete/search API); Letta (memory tools) | **REJECT all — hand-build on wave-4 export/wipe** | — | — | ✗ "forget" must be provably idempotent on owned rows; distributed stores make deletion unauditable |
| **P7** journal tool | obsidian-local-rest-api (+bundled MCP); MarkusPfundstein/mcp-obsidian; cyanheads/obsidian-mcp-server | **REJECT for core — hand-build trivial append+redaction tool**; **DEFER/optional ADOPT** of REST/MCP layer later as vault read-search expansion (user installs plugin + approves key) | S (deferred add-on) | MIT | ✓ direct file write always works headless; MCP route requires Obsidian running + API key + `mcp<2.0` pin |
| REST rate-limit (adjacent) | slowapi (laurentS/slowapi) | **REJECT — hand-build dependency-free** per request text (slowapi = fallback if mandate lifts) | S if later adopted | MIT | ~ shared ban map already exists in WS hub |

## Top-3 outsources worth doing (ranked)

Honest ranking given the constraints — this wave is **mostly "keep hand-building"**; the genuine outsources are small and two are conditional/deferred:

1. **P7 add-on (deferred, user-gated): obsidian-local-rest-api plugin** — 3,013★, MIT, active (2026-10-06), now bundles its own MCP server. One user-side install unlocks vault-wide read/search for her journal-surface expansion through existing MCP plumbing. **Cost S.** Do NOT make it a P7 dependency; ship the file-append journal tool first.
2. **slowapi for REST rate-limiting** — 2,068★, MIT, active (2026-10-08) — **only if** qa-security's "keep it dependency-free" constraint is explicitly lifted by integrator; otherwise the in-house shared-ban-map (cost M) is the right call and slowapi stays rejected. **Cost S** if adopted.
3. **Zero-dependency concept imports (do these regardless):** mem0's metadata/user-run scoping as the reference design for P5 slot filters, and LangMem's namespace-scoped memory-tools shape for slot naming. No code copied, no license entanglement, no runtime cost. **Cost ~0.**

Everything else in the 5P set — confirm policy, clarify loop, slot scoping, forget/export affordances, journal append — is *better* hand-built: smaller, deterministic, fail-closed, and already half-implemented by the existing `brain/confirm.py` + `brain/memory` + wave-4 export/wipe.

---

## Sources (all live-checked 2026-10-09)

- [NVIDIA-NeMo/Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) — 7,270★, pushed 2026-10-09, Apache-2.0 ([LICENSE.md](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/LICENSE.md))
- [guardrails-ai/guardrails](https://github.com/guardrails-ai/guardrails) — 7,503★, pushed 2026-10-09, Apache-2.0
- [protectai/llm-guard](https://github.com/protectai/llm-guard) — 3,217★, MIT, **archived**, last push 2026-07-08
- [mem0ai/mem0](https://github.com/mem0ai/mem0) — 66,911★, pushed 2026-10-09, Apache-2.0; [self-hosted setup](https://docs.mem0.ai/open-source/setup), [Ollama LLM](https://docs.mem0.ai/components/llms/models/ollama), [Chroma local](https://docs.mem0.ai/components/vectordbs/dbs/chroma), [Ollama embeddings source](https://github.com/mem0ai/mem0/blob/main/mem0/embeddings/ollama.py)
- [getzep/graphiti](https://github.com/getzep/graphiti) — 31,600★, pushed 2026-10-09, Apache-2.0; README (requirements, Ollama/OpenAIGenericClient, PostHog opt-out telemetry, Zep-vs-Graphiti proprietary-engine table)
- [getzep/zep](https://github.com/getzep/zep) — 4,953★, Apache-2.0, repo = examples; managed-platform posture per graphiti README
- [letta-ai/letta](https://github.com/letta-ai/letta) — 25,093★, pushed 2026-09-10, Apache-2.0; [self-hosting docs](https://docs.letta.com/self-hosting), [models docs](https://docs.letta.com/configuration/models)
- [langchain-ai/langmem](https://github.com/langchain-ai/langmem) — 1,700★, pushed 2026-10-02, MIT; README (LangGraph BaseStore dependency, namespace tools)
- [topoteretes/cognee](https://github.com/topoteretes/cognee) — 31,912★, pushed 2026-10-09, Apache-2.0
- [coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) — 3,013★, pushed 2026-10-06, MIT, bundles MCP server
- [MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) — 4,467★, pushed 2026-08-31, MIT; README (Local REST API plugin + API key required; `mcp` 1.x pin, breaks on 2.0)
- [cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) — 695★, pushed 2026-10-06, Apache-2.0
- [jacksteamdev/obsidian-mcp-tools](https://github.com/jacksteamdev/obsidian-mcp-tools) — 829★, MIT, **archived**
- [laurentS/slowapi](https://github.com/laurentS/slowapi) — 2,068★, pushed 2026-10-08, MIT (`long2ice/slowapi` → 404, moved)
- Local: `docs/research/persona/06-CODE-ADOPTION-PLAN.md`, `docs/research/R2-TOOLING.md`, `docs/research/R4-GAPS.md`, `docs/requests/qa-security__to__brain-core__rest-rate-limit.md`, `docs/requests/qa-security__to__integrator__ws-query-token.md`, `brain/confirm.py`, `brain/memory/` listing

**NOT VERIFIED:** Zep self-hosted Community Edition server availability as a current product (2026-10-09) — repo history suggests it was superseded by the managed platform; treated as non-existent for decision purposes. `smithery-ai/mcp-obsidian` — 404, superseded by MarkusPfundstein fork/rewrite.
