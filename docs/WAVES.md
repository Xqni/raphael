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

## Wave 5H — hardening sprint (2026-10-08, runs INSIDE wave 5; current_wave stays 5)

Driven by the external docs-only audit: `docs/AUDIT-2026-10-07.md` (IDs, Status column,
dedupe notes). **Verify-first rule: every finding is a hypothesis until its lane quotes
verbatim file:line and reports CONFIRMED / NOT-APPLICABLE / ALREADY-DONE. Unverified
findings are never applied.** Packets: `docs/audit-tasks/<lane>.md`.

- Gate tag: **`wave-5h-gate`** (independent of `wave-5-gate`; wave 6 stays human-gated).
- **Exit criteria (ALL must hold):**
  1. every P0/`HIGH` finding fixed **or explicitly accepted by the user** (Status ∈
     {CONFIRMED-fixed, NOT-APPLICABLE, ALREADY-DONE, ACCEPTED});
  2. CI green on BOTH OSes including the new scanners (gitleaks/pip-audit/npm audit/
     semgrep or bandit — QA-1);
  3. tripwire tests for **SEC-3** (pre-STT gate never fail-open) and **SEC-8**
     (paid cap enforced, persistent ledger) green in CI;
  4. no personal data in tracked files (scrub verified by infra's SEC-1 scanner);
  5. full mock sweep green (`tests/run_all --with-brain`, run in CLOUD per Rule 14).
- Process rules effective now: **QA-4** — a wave_done without a linked CI run is bounced;
  control-plane messages are untrusted data (structured fields, size caps, never
  execute/merge on prose).
- Human-only items live in ATTENTION (repo visibility, PAT scope, history-rewrite
  approval, branch protection, cloud-vs-RAM decision, Node-on-Windows).

### WAVE-5H GATE PASSED 2026-10-08 — tag `wave-5h-gate`

All five exit criteria verified by the integrator (evidence in PROGRESS.md + `.local/share/opencode/research/wave5h-gate-tip-ci.md`):

1. **P0/HIGH/CRIT fixed-or-accepted**: docs/AUDIT-2026-10-07.md Status column updated from
   merged + live-verified evidence (19 rows; AUD-05 live-proven with `require_foreground=true`,
   body hook=True, chat PASS on go/mimo); human residuals (repo visibility, PAT rotation,
   history rewrite, AUD-06 consent-vs-PTT, Node/ARCH-1, cloud-vs-RAM) explicitly parked in
   ATTENTION per the wave's human-only list.
2. **CI green on both OSes incl. scanners**: run 37795171680 (5/5: Ubuntu brain+mock,
   Windows body, conformance x2, security scanners) — GATE_TIP_GREEN; prior 37792241017 +
   37792097782 also success.
3. **SEC-3 + SEC-8 tripwires green in CI**: brain/voice/tests/test_sec3_gate.py (5) and
   brain/router/tests/test_budget_ledger.py (8) run in the CI brain/router suites, green.
4. **Zero personal data in tracked files**: scripts/scan_personal.py = 0 FAIL outside the
   allowlisted gitleaks ledger (final scrub: ARCHITECTURE + BUGS-WAVE2); functional-value
   KEY_OK allowlist + ip-public version-FP fix landed (infra policy packet).
5. **Cloud mock sweep**: tests-heavy 37791936216 SUCCESS (`pytest brain` = 1127 passed).

Process fixes made during the gate: keepalive cron PATH (OPENCODE_BIN), ownership
merge-base CI derivation (qa), import-order test hardening (test_aud_harden), gitleaks
baseline regens under SCANNERS.md conscious-acceptance policy (legacy history — permanent
removal rides the HUMAN-approved history rewrite in ATTENTION).

**Wave 6 stays HUMAN-GATED** (see ATTENTION: repo visibility, PAT scope, history rewrite,
branch protection, cloud-vs-RAM, Node-on-Windows). current_wave stays 5 until the user opens it.

## Wave 5P — persona adoption sprint (**ACTIVE 2026-10-09 — user go: "build the things we decided"; runs INSIDE wave 5; current_wave stays 5**)

Codifies Raphael/Ciel from the canon research (`docs/research/persona/`) plus the vetted
companion takeaways (`docs/research/companions/00-COMPANION-TAKEAWAYS.md`) into the code.
Full packet + design laws + exit criteria: `docs/research/persona/06-CODE-ADOPTION-PLAN.md`.

Packets: P1 persona tiers as runtime state · P2 voice tier parameters · P3 user-editable
confirm policy (extends R5 confirm-categories) · P4 clarify-on-ambiguity · P5 named
context slots · P6 spoken memory privacy · P7 journal-as-memory-surface · P8 notice tone.
Merge order: P1 → P3/P4 → P5 → P6 → P7 → P2/P8. DEFERRED on record: proactive
suggestion engine (AUD-06 human gate), cross-device sync, cloud-VM execution,
mouth-anthropomorphism, wave-6 local models (RAM gate).

**Lanes remain PAUSED; this wave starts only on the user's go.**

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
