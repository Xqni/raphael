---
current_wave: 5
updated: 2026-10-07
---

# WAVES.md — wave goals, exit criteria, merge order (integrator-owned)

Lanes read this every task (AGENT_RULES §11). Only the integrator bumps `current_wave`.

## Global constraints (apply to every wave)

- Scheduled task "Raphael" stays **Disabled**; no live stack starts until the user says go (real runs = integrator, AGENT_RULES §5/§12).
- Profile **`cloud_temp`**: no local models (no Ollama, no local Whisper, no local vision). Chat/tools = Groq → Zen free; STT = Groq Whisper; vision = cloud per PROTOCOL §7; TTS = local Fish-Speech. **Paid/Go models are AUTHORIZED** per user approvals logged in `docs/PAID_USAGE.md` (vision-only slot 2026-10-06; broad paid-fast 2026-10-07) — within their caps; never exceed a stated cap.
- **SPEED MANDATE (user, 2026-10-07):** cloud is paid now — aim for NEAR-INSTANT replies everywhere: pick fast cloud model ids by default (flash-class, `opencode-go/mimo-v2.5`), short chains, no gratuitous retries/waiting. Fish-Speech stays the only local model (TTS). Escalate to bigger models only when a task actually needs it.
- **No performance/VRAM/latency optimization ENGINEERING work** — correctness, completeness, polish only. (The speed mandate above is about model/route selection, not micro-optimization.)
- Local model code paths stay in the repo (profile-gated, never deleted).

## Merge order (dependency-safe — integrator merges in exactly this order)

`router → brain-core → pc-control → voice → computer-use → orb → infra → qa-security → tools-memory → evolution-persona`

## Wave 2 — cloud conversational MVP (MERGED 2026-10-07 — all 8 lanes merged to main)

**LIVE GATE RESULT (2026-10-07, integrator):** 3/5 PASS — criterion 2 (spoken
answers), 4 (6 distinct live orb states), 5 (pause/private/kill) verified on the
real stack. Criterion 1 FAILs on Bug B (`open_app`), criterion 3 = paid slot proven
in-process but live WS path blocked by Bug F. Full evidence + bug assignment:
`docs/BUGS-WAVE2.md`. **`wave-2-gate` tag NOT created** — gate re-runs (all six
criteria) at wave-3 close once Bugs B/D/F land. Wave 3 was bumped early on the
user's "continue as normal" directive; the three bugs are wave-3 P0.

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

## Wave 3 — P0 gate bugs first, then the wave goals

**MERGE BOARD COMPLETE 2026-10-07 — all 10/10 lanes merged to main** (router, brain-core,
pc-control, voice, computer-use, orb, infra, qa-security, tools-memory, evolution-persona).
Every P0 gate bug (A/B/C/D/E/F/G) landed with regression tests. Full mock sweep green:
`tests/run_all --with-brain` = 272 passed, rc=0.

**GATE PASSED 2026-10-07 — tag `wave-3-gate`** (user GO, live run by integrator):
all six criteria PASS live — 1) text+voice YouTube command (search_youtube URL opened;
acoustic chain mic→STT→wake→extract→open_app→notepad launched ×2), 2) spoken answer in
JP great-sage voice (`prove_reference.py` PROOF OK, sha1=f64bd512ea1e), 3) real vision
answer via Go paid slot (spend $0.0007/day of $1), 4) distinct live orb states incl
speaking (Bug C), 5) pause/private/kill acked, 6) mock suite 272 passed rc=0.
Bugs fixed during the gate (integrator glue, all committed): **Bug H** stt.py async
never-awaited (voice input was silently dead), stt_language config dropped in loader +
pinned `en`, wake extract-all, fastpath tail fillers, whisper prompt bias (additive).
**current_wave bumped to 4** per gate procedure. One open cross-lane item:
evolution-persona's shadow-instance request (OPEN with brain-core) is Wave-4 scope.


**P0 (from the live gate, `docs/BUGS-WAVE2.md` — do these before wave goals):**

1. **Bug B** (pc-control + router): `open_app` fails "open YouTube and search lo-fi"
   (blank cmd window + error, no act_res) — robust Windows launch + right tool choice.
2. **Bug D** (voice): live TTS must use the JP slime reference (`assets/raphael_reference_jp.wav`,
   user-permanent) — loud ref-loading, phrase-cache invalidation, live proof.
3. **Bug F** (computer-use): foreground verification refuses vision on a normal
   terminal window — fix `foreground_info` path.
4. **Bug A regression** (router): test that every go_vision request carries
   `x-opencode-session`. **Bug E** (brain-core): no speaking→listening flicker
   between sentences. **Bug C** (orb): speaking pulse + cage-morph polish.
   **Bug G** (infra): supervisor-owned bring-up/teardown with correct pids.

**Then the wave goals:** Memory, skills/plugins, web/files/shell/github/schedule tools, MCP client, Chrome automation via CDP, job-concurrency polish, proactive "Notice" events.

**Exit criteria for wave 3:** re-run the full Wave-2 live gate (all 6 criteria, honest
pass) + the wave's own goal demos + full mock suite green.

## Wave 4

Hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure (shadow instance, rollback, journal).

## Wave 5

**WAVE-4 GATE PASSED 2026-10-07 — tag `wave-4-gate`:** all 10 lanes merged (incl. the
ownership-exceptions mechanism, integrator-reviewed), full mock sweep 308 passed rc=0,
CI green (both OSes). CARRIED into this wave: brain-core's shadow instance row
(port 8911, APPROVED+assigned — blocks evolution's shadow verification runs only);
qa's re-audit residual C1+C2 voice-confirm (docs/reviews/2026-10-07-wave4.md).

## Wave 5

Raphael features (Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals), persona tiers `great_sage → raphael → ciel`.

## Wave 6 — NOT NOW

**WAVE-5 GATE PASSED 2026-10-07 — tag `wave-5-gate`:** all 10 lanes merged; mock sweep
346 passed rc=0; root 313 zero failures; armed Analysis/Simulation privacy tripwire GREEN
(the one deliberate red — brain-core's P0 gates batch, merged 5262845). Contracts
decided-first throughout (answer/report/kinds/minds/report-act/purpose-enum/privacy).
**current_wave NOT bumped** — wave 6 needs the human's RAM upgrade decision first
(WAVES: local-model cutover NOT NOW); attention posted.



Local-model cutover **after the RAM upgrade** (re-enable local models/profile `local`, restore the PROTOCOL §7/§11 screenshot invariant, verify on real hardware).

## Gate procedure (integrator, when all lanes meet the current wave's exit criteria)

1. Verify exit criteria with real runs on the real instance (user's go required).
2. Tag `wave-N-gate`.
3. Bump `current_wave` above.
4. Tell the user to send the CONTINUE prompt to the other sessions.
