# R5 — Build-vs-Adopt Decision Gate (integrator)

**Date:** 2026-10-09 · **Author:** integrator · **Status:** for USER REVIEW — nothing here is implemented; Wave R produced docs only.
**Inputs:** R1-ARCHITECTURE.md, R2-TOOLING.md, R3-VULNCLAW.md, R4-GAPS.md, plus internal measured evidence (lane studies, audits, the request-status audit).

Decision vocabulary: **ADOPT <tool>** = use the external tool as-is · **ADAPT <tool>** = borrow its approach/manifest/shim · **BUILD CUSTOM** = our code, eligible to re-enter WAVES as a code task after the user says go · **DEFER** = parked with the named gate · **HUMAN-ONLY** = cannot be done by any lane.

Standing constraints that bind every decision below (AGENT_RULES): cloud-only LLM/STT until the RAM upgrade (no new local models), no new dependencies during Wave R (adoption = proposal only), speed mandate, Core Guard non-negotiable, cost logged not optimized.

---

## 0. Overrides where R2's verdict loses to measured internal evidence

| R2 verdict | R5 decision | Reasoning (evidence) |
|---|---|---|
| Adopt **openWakeWord** for wake-word | **REJECT** | Already measured and rejected with data by voice's AUD-06 study (cited in `docs/lanes/voice.md` AUD-06 entry + `brain/voice/AUD06-local-wake-gate-study.md`): +100 MB RSS on this laptop and deaf to the custom "Raphael" keyword; openWakeWord keywords are pre-trained classes, not arbitrary phrases. A measured rejection outranks a survey recommendation. AUD-06's consent-vs-PTT path remains the human's call. |
| Adopt **silero-vad** (primary) | **DEFER** (RAM-upgrade gate) | Silero is a local model — violates the cloud-only/no-local-models mandate until the RAM upgrade is decided (WAVES wave-6 human gate). Current VAD (SILENCE_CLOSE/EndGrace in `body/win/audio_in.py`) is shipped, measured, and split-safe. Re-evaluate at the RAM gate with the PocketTTS/whisper local-stack review. |
| Adopt **FlaUI** via pythonnet | **DEFER** | pywinauto+UIA covers the current surface (incl. `focused_is_password` via `CurrentIsPassword`, shipped and tested). pythonnet adds a .NET runtime dependency to the Body for no measured need. Revisit only on a concrete UIA failure pywinauto cannot solve. |
| Adopt **fastMCP** / MCP python-sdk | **DEFER** (adopt-on-first-use) | We consume MCP today via tools-memory's client; we host no MCP servers. The day an MCP *server* is wanted (e.g., exposing Raphael tools), fastMCP is the default pick (Apache-2.0, active). No work until that use case exists. |
| Adopt **trufflehog** (CI-only) | **REJECT** | AGPL-3.0 with zero incremental coverage over our gitleaks+baseline setup (qa's scanners job). License risk for no gain. |
| Adopt **AutoGPT** concepts / refactor conductor | **REJECT adoption; keep BUILD CUSTOM** | Our coord bus + conductor just executed a full 10-lane sprint (Wave R itself) with ownership checks, QA-4 CI gating, and pause mechanics. No framework beats that on fit; borrowing "task-queue concepts" is churn. |
| Adopt **Fish-Speech + faster-whisper** | **ADOPT-CONFIRMED (status quo, no change)** | Already the shipped picks. Two follow-ups: (a) licensing re-verify for fish *weights* before any proprietary redistribution (R2 flagged no-SPDX — treat as NOT VERIFIED); (b) PocketTTS remains the gated alternative (user HF acceptance). |
| Adapt **OpenAI-Plugin-like `skill.json`** | **ADAPT (verify-first)** | A small local manifest schema for `skills/` is worth having; but R2's cited repo (`openai/openai-plugins`) was NOT independently verified and the OpenAI plugin ecosystem was sunset — do not align to a dead spec. Build a minimal local `skill.json` convention (name/inputs/outputs/version), S effort. |

---

## 1. Decisions for every R4 gap

### Security (must-pass cluster — these unblock qa's pinned xfails)

| Gap | Decision | One-line reasoning |
|---|---|---|
| SEC-5 `.env` symlink ingestion | **BUILD CUSTOM** (S) | Presence-only secret checks; pure code hygiene in the router/voice readers, no tool exists for this. |
| SEC-6 Hyper-V firewall | **HUMAN-ONLY / DEFER** | The narrow Rule script exists (`scripts/win/allow-brain-localhost.ps1`); running it elevated is the user's call (blanket-allow stays rejected). The user-space relay remains the interim. Already mirrored in ATTENTION. |
| voice-confirm-wiring (pinned tests red) | **BUILD CUSTOM** (L) | Our voice/confirm protocol; R1's "Confirm Facade / SecurityFacade" decoupling is the right *shape* — adapt the concept, write the wiring (brain-core + voice halves, both already exist per the request audit). Highest-priority code batch: it closes2 xfails and completes the voice-first loop the user actually wants. |
| voice-confirm-channel (`confirm_resp.channel`) | **BUILD CUSTOM** (M) | Contract field + code; rides the same batch as above. |
| REST-rate-limit | **BUILD CUSTOM** (S) | A per-IP limiter + auth-fail ban is ~30 lines on top of the existing `token_auth`; a dependency (slowapi) is not justified yet — revisit only if we need sliding-window sophistication. |
| lock-busy-code (`E_LOCK_BUSY` mapping) | **BUILD CUSTOM** (S) | Loop-level error-code mapping + PROTOCOL §10 row; contract work, no tool. |
| disable-fastapi-docs | **BUILD CUSTOM** (S) | `docs_url=None, redoc_url=None, openapi_url=None` outside tests; trivial but Core-Guard-adjacent. |
| circuit-open-code (`E_CIRCUIT_OPEN` catalog) | **BUILD CUSTOM** (S) | PROTOCOL §10 catalog row + router mapping parity. |
| activity-endpoint (F-3 chain) | **BUILD CUSTOM** (M) | REST route implementing the SIGNED orb↔pc act-journal schema; pc's body half is already merged, brain-core's route is the missing link (audit: `/activity` = 0 hits in brain/). |
| config-confirm-categories (AUD-11) | **BUILD CUSTOM** (S) | `safety.confirm_actions` additions in integrator-owned `config.yaml` (open_arbitrary_file, gui_submission). |

### Reliability (R1 findings)

| Gap | Decision | One-line reasoning |
|---|---|---|
| lock-timeout watchdog | **DEFER (user-decision)** | Auto-cancelling a user-visible job holding the input lock is a product-behavior choice (what if it's mid-write?). Design + user say-so before code; R1's `jobs.lock_max_seconds` shape noted. |
| persistent model-unsupported cache | **BUILD CUSTOM** (S) | Persist the capability-learning flags to `run/` and reload at router init; prevents re-hitting 400s every restart. |
| circuit-breaker threshold tuning (R1 risk) | **BUILD CUSTOM** (S) | Config-driven thresholds + reopen backoff; rides the router lane, cheap. |

### Plan-not-built / tests

| Gap | Decision | One-line reasoning |
|---|---|---|
| Laya advisory adapter | **DEFER** (existing human gate) | TODO §5 already gates this on the user's go-ahead + zero-shot accuracy work; the RAM/cloud-only mandate makes any local-tier wiring a wave-6+ conversation. |
| voice-confirm tests (missing suite) | **BUILD CUSTOM** (test code) | Follows automatically with the voice-confirm batch above; qa's pinned tests already specify the contract. |
| Missing docs (R4: none) | **—** | Accepted; no doc gap beyond what the code fixes will update. |

### Security-testing posture (R3)

| Item | Decision |
|---|---|
| VulnClaw | **ADOPT-FOR-TESTING-ONLY** per R3, gated on: user authorization, disposable VM, allow-listed network to the exposed test surface only, `ask`/`auto_review` never `full_access`. Not a Wave-6 code task; needs the user to schedule an authorized test window. |
| Semgrep in CI (R2 area 5) | **ADOPT (S)** — the one genuinely missing scanner (WAVES criterion already names "semgrep or bandit"; bandit is in, semgrep closes the gap with custom policy rules for PROTOCOL invariants). CI-only, no runtime dep. |
| Skills manifest (`skill.json`) | **ADAPT (S)** — local descriptor convention for `skills/` (see override table). |

---

## 2. What may re-enter WAVES as code tasks (only after the user says go)

Priority order (dependencies first):
1. **Voice-confirm batch** (wiring + channel + tests + confirm categories) — closes4+ open requests and the user-facing voice-first loop.
2. **Small security batch** (REST rate-limit, FastAPI docs off, E_LOCK_BUSY, E_CIRCUIT_OPEN, .env presence-only).
3. **F-3 activity endpoint** (signed schema) — unlocks the orb viewer.
4. **Router resilience batch** (persistent capability cache, breaker tuning).
5. **CI adoption**: semgrep rules (S) — qa lane.
6. **skill.json convention** (S) — tools-memory lane.

Everything else is DEFER/HUMAN: Laya (user gate), watchdog (user decision), firewall rule (user), local-model candidates silero/openWakeWord (RAM gate), VulnClaw test window (user authorization).

---

## 3. Honesty notes

- R1's citations spot-checked by the integrator (engine PriorityQueue, loop header, fastpath registration) — accurate; its coupling findings (confirm-in-cancel, lock-name derivation, hard-coded risk regex) are real seams, recommendations kept as proposals.
- R2's per-item star/license data was taken as reported; two citations were NOT independently verified (openai-plugins repo, crewAI inactivity claim) and one recommendation (openWakeWord) is overridden by internal measurements. Fish-weights licensing remains NOT VERIFIED — a gate before any redistribution, not before local use.
- R3 was produced by the original free-model run and completed successfully; its framing constraints are reproduced verbatim in the report.
- R4's file was delivered with literal `\n` escapes and was reformatted by the integrator; content unaltered.
- No code, dependencies, or runtime state changed during Wave R; the stack remains stopped; all lanes remain paused until the user reviews this gate.

*End of R5. Next step is the human's: review docs/research/R1–R5 and say which items (if any) to open as wave-6 work.*
