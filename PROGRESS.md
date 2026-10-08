# Raphael — PROGRESS (slim current-state view; ARCH-3)

Full session logs: `docs/history/` (PROGRESS-2026-10-04_05, -10-06, -10-07_FULL).
Status legend: DONE / IN-PROGRESS / BLOCKED / NEXT · Model tier: T0 no-LLM ·
T1 fast free · T2 strong free · T3/T4 paid (log to docs/PAID_USAGE.md).

## Where we are (updated 2026-10-08)

- **Waves**: 1–5 complete and GATED (`wave-3-gate`, `wave-4-gate`, `wave-5-gate` tags
  pushed). `current_wave: 5` + **Wave 5H audit-hardening sprint running**
  (register `docs/AUDIT-2026-10-07.md`, packets `docs/audit-tasks/*.md`, gate
  `wave-5h-gate`, exit criteria in docs/WAVES.md). Wave 6 = local-model cutover,
  HUMAN-gated on the RAM upgrade.
- **Live gate (wave 3)**: all six criteria passed on the real stack (incl. acoustic
  voice→laptop command); Bugs A–H fixed. Wave 4 = hardening (security bypasses fixed,
  resilience drills, ownership-exceptions mechanism). Wave 5 = Answer/Notice/Report
  formats, Analysis/Simulation (3 privacy gates enforced, armed tripwire green),
  parallel-minds, persona tiers (great_sage→raphael→ciel), answer/report emitters,
  report-delivery act, gather_context, shadow instance row.
- **Voice**: JP great-sage reference is PERMANENT (user); P0 lost-accent + speaking
  gaps fixed (namespaced cache + timbre gate + reply pre-roll: max gap 1.0ms vs
  12230ms baseline). fish kept (user decision over PocketTTS).
- **LLM chain**: opencode models own chat (`chain: [go, zen_free, groq]`,
  allow_go/paid = true, cost-not-a-factor); groq = STT-only caps; vision =
  deepseek-v4-flash-vision-exp (paid slot); cloud-only until RAM upgrade (user).
- **Orb**: cage = 3D wireframe spheres (radius proof); shape morphing HELD for the
  user's future plans (constant cage + circle-only hints; color + speaking pulse are
  the only per-state changes); boot-sequence rewire (starting→idle→event-driven):
  brain half merged, orb half in flight.
- **Policies**: scheduled task stays Disabled; stack DOWN by default — spawn only for
  lane tests, tear down after; heavy suites run in cloud CI (`gh workflow run
  tests-heavy.yml`); Rule 14 one-suite-at-a-time; Rule 15 speed; coord bus healthy
  (conductor running).
- **HUMAN-ONLY pending (ATTENTION)**: repo private, narrow PAT, history-rewrite
  approval (filter-repo plan to be prepared), branch protection, cloud-vs-RAM
  decision, Node-on-Windows for ARCH-1.
- **Security**: docs-only external audit registered (27 findings) — verify-first
  across 10 lanes; SEC-2 (shadow.service priv-esc), SEC-3 (pre-STT fail-open),
  QA-1 (CI scanners) are the P0s in flight.

## NEXT
1. Drive Wave 5H: verify reports → fix CONFIRMED P0s → CI scanners green both OSes →
   tripwires (SEC-3/SEC-8) → scrub verified → tag `wave-5h-gate`.
2. Close orb boot-sequence AMENDMENT-2 when orb half lands (live double-restart check).
3. Merge loop as wave_dones arrive (QA-4: require linked CI run).
4. When human answers ATTENTION items: prepare history filter-repo plan (do not run).
- **Wave-5H sprint report (34-event batch)**: SEC-2 live root-run disabled by human +
  repo remediation landed; SEC-3 CONFIRMED->FIXED both halves (brain-core ws.py batch
  MERGED pos2; voice activation fail-closed queued pos4); SEC-8 ledger hardened (router
  MERGED pos1); SEC-4 PAT code-side eliminated (tools-memory); SEC-9 pip-in-runtime
  removed (pc+voice); SEC-7 Core Guard 4->20 entries applied; F-1 propose-mode loop ran
  live; F-5 decision record written; F-6 Ciel checklist; ARCH-1 plan delivered (Node
  already installed!). wave_dones queued: pc(3)/voice(4)/computer-use(5)/tools(9)/
  evolution(10) — all CI-linked per QA-4.
