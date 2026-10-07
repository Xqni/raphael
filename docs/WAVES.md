---
current_wave: 2
updated: 2026-10-05
---

# WAVES.md — wave goals, exit criteria, merge order (integrator-owned)

Lanes read this every task (AGENT_RULES §11). Only the integrator bumps `current_wave`.

## Global constraints (apply to every wave)

- Scheduled task "Raphael" stays **Disabled**; no live stack starts until the user says go (real runs = integrator, AGENT_RULES §5/§12).
- Profile **`cloud_temp`**: no local models (no Ollama, no local Whisper, no local vision). Chat/tools = Groq → Zen free; STT = Groq Whisper; vision = cloud per PROTOCOL §7; TTS = local Fish-Speech. Go/paid stay OFF.
- **No performance/VRAM/latency optimization work** — correctness, completeness, polish only.
- Local model code paths stay in the repo (profile-gated, never deleted).

## Merge order (dependency-safe — integrator merges in exactly this order)

`router → brain-core → pc-control → voice → computer-use → orb → infra → qa-security → tools-memory → evolution-persona`

## Wave 2 — cloud conversational MVP (current)

Cloud provider chain + tool calling; conversational loop with persona; orb states VISIBLY changing end-to-end; voice loop (Groq STT, Fish TTS, PTT/wake, typed input); Windows control tools; cloud-vision "see my screen" + computer-use loop; supervisor cloud profile; `raphael` CLI; mock-based test harness; instance isolation.

**EXIT criteria (all must hold for the live E2E on the real instance, with the user's go):**

1. "Open YouTube and search lo-fi" works by voice **and** by text.
2. A free-form question gets a real cloud answer in her voice.
3. "What am I looking at" returns a real vision answer. **— REOPENED 2026-10-06: user approved
   a spend-capped VISION-ONLY paid slot ("use the opencode go paid models for vision for now").
   Chain: groq -> zen free -> Go-tier vision model (discovered: `opencode-go/deepseek-v4-flash-vision-exp`),
   gated by `providers.allow_vision_paid: true` + `vision_paid_daily_cap_usd: 1.00`; chat/tools stay
   free-only. Falls back to E_OFFLINE/no_model if the slot is exhausted or disabled (previous known-gap
   text lives in docs/requests/router__to__integrator__vision-free-model-gap.md, branch agent/router).
4. Per-state orb screenshots prove distinct visuals.
5. Pause / private / kill all work.
6. Full mock test suite green.

## Wave 3

Memory, skills/plugins, web/files/shell/github/schedule tools, MCP client, Chrome automation via CDP, job-concurrency polish, proactive "Notice" events.

## Wave 4

Hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure (shadow instance, rollback, journal).

## Wave 5

Raphael features (Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals), persona tiers `great_sage → raphael → ciel`.

## Wave 6 — NOT NOW

Local-model cutover **after the RAM upgrade** (re-enable local models/profile `local`, restore the PROTOCOL §7/§11 screenshot invariant, verify on real hardware).

## Gate procedure (integrator, when all lanes meet the current wave's exit criteria)

1. Verify exit criteria with real runs on the real instance (user's go required).
2. Tag `wave-N-gate`.
3. Bump `current_wave` above.
4. Tell the user to send the CONTINUE prompt to the other sessions.
