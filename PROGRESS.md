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
- Wave-5H merges: router(pos1) + brain-core SEC-3(pos2) + pc-control SEC-9/F-3(pos3) +
  **voice SEC-3/SEC-9/F-5(pos4)** = SEC-3 WHOLE (both halves + tripwires in CI). Also
  fixed: ownership checker integrator-pass-before-config.d rule (CI reds 37713263876/
  37713400889 root-caused by pc-control's report — lane->lane rule intact, proven both
  directions). pre-commit hook noise = infra's SEC-1 scanner WIP (notified).

## 2026-10-08 (coord wake: 2 events)
- evolution-persona task_done: SEC-1 scrub 0 FAIL (own paths) — accepted; next = answer brain-core SEC-7 manifest-format request (pre-decision: format/ownership stay as-is).
- orb task_done: re-verify PASS (production CDP: #fps null, zero on-orb text, boot 13/13) — accepted; VISION ID delivered for 'weird box' = opencode TUI sidebar behind overlay (remove nothing; wallpaper re-capture = decisive test); next = white-only starting fix.
- CI context: main reds reduced to 1 known failure (qa's AUD-11 lock-test update, dispatched).
- evolution-persona task_done: SEC-7 manifest-format request ANSWERED (decision in-file: format/ownership unchanged; live coreguard verify ok + 7 tests) — accepted; sent WAIT (wave complete).
- evolution-persona task_done [31]: formal ratification of SEC-7 pre-decision sent to brain-core (request ANSWERED w/ confirmation, commit 907f70b); lane declares WAIT, wave_done queued at position 10. No reply needed — WAIT already in their inbox.
- computer-use [28] SEC-1 0->0 3-way verified -> WAIT (5H merged pos5).
- orb [33] vision close + white-starting (0.45 deviation APPROVED) + box ticks -> NEXT: 2D billboards (scoped).
- pc-control [33] qa visibility -> acked (qa P0 already dispatched; keepalive PATH fixed).
- voice [46,47] STT-latency packet accepted; 2 requests ACCEPTED -> brain-core (utt-continuation, coupling recorded) + router (turbo STT) -> WAIT.
- pc-control [34]: 2 qa requests closed ALREADY-DONE (evidence accepted, commit 7c35664); tripwire xfail isolated to brain/app.py pidfile half (brain-core); NEXT re-stated = AUD-05 foreground push.
- tools-memory [33-36]: addenda AUD-15/23/25/28 + SEC-1 accepted; wave_done ACK (QA-4: branch CI dispatch requested — cited run predates commits); queue pos9 behind qa(pos8, P0 lock patch).
- voice [48] heartbeat: requests tracked, idle until pinged.
- orb [34]: 2D conversion accepted (halo->sphere+fresnel); checklist full -> NEXT: wave_done + branch-CI data.ci_run.
- router [43,44]: fast-role A/B accepted (~0.4s med, model switch verified; RPM 10->30 accepted); loop-label request -> brain-core; zen_free tool-400 finding queued; CI red = qa P0 acked.
- tools-memory [37]: ownership request DECIDED (grant both trees), branch force-pushed d65d056 (stale pre-rebase remote realigned); re-dispatch CI assigned.
- orb [35]: verification-only accepted (rebase byte-identical to green gate, 7/7); ARCH-1 human gate re-surfaced in ATTENTION; NEXT restated = branch CI + wave_done with data.ci_run.
- MAIN GREEN PUSH aa8503e: guard fixed (dirty-pin root cause, evolution's catch) + qa merged (AUD-11 lock test) + coord.py SEC-1 scrub + OWNERSHIP qa scanner grant. Battery 182/232/8/guard OK.
- evolution [32] incident RESOLVED+replied; pc [35,36] fg half accepted -> brain-core consumer = critical path; router [45,46] turbo-STT + closure accepted -> next zen_free+packet; tools-memory [38] + orb [36,37] -> rebase+green-run instructions; computer-use [29] heartbeat.
- qa [46,47]: wave_done GREEN 5/5 (37775644704) accepted; batch merged 08622fe; NEXT = packet checkbox reconcile + wave-3 golden transcripts (eligible at wave5); ledger allowlist request -> infra.
- evolution [33]: guard follow-up verified green post-rebase; WAIT (wave_done queued pos10).
- router [47]: zen_free exclusion accepted as model-capability learning (evidence-first correction of my dispatch; no static ban); next = audit packet + wave_done w/ fresh CI id.
- tools-memory [39]: rebased f131c1a pushed (force-with-lease); dispatching CI for position-9 green id.
- voice [49]: QA-4 main-green 37776358400 accepted (ALL jobs); Cut B merges next cycle (voice re-measures on ping), Cut A parked on brain-core half. evolution pinged to post pos-10 wave_done.
- WAKE-COUNT RECORD: 74 = 73 stale state.json lag (10 lanes) + 1 real.
- tools-memory [40]: branch CI dispatched on rebased head f131c1a (run 37777015314, queued) — conclusion follows; merge position 9 waits on that green id.
- infra [29]: qa allowlist request DONE (exact-path + proof test) + own scrub 23->0 accepted; scanner FPs fixed; tests-heavy 37777005138 SUCCESS. NEXT: wave_done + per-owner breakdown of remaining 79 non-ledger FAILs (exit criterion 4 routing).
- MAIN GREEN CONFIRMED (watcher): 37776358400 CI + 37776618319 tests-heavy both success on aa8503e; report at .local/share/opencode/research/main-ci-green-attempt.md.
- ROUTED: orb -> evaluate dependabot electron-44.5.1 PR (urgent CVE line) vs full gates, verdict to me; infra -> safetycli private-source auth failure blocking dependabot npm on body/orb.
- pc [37]: F-3 co-share half accepted (schema agreement + stable ids + undo semantics); corrected their CI-id (was a dependabot run) + their misattributed red (it's the known job-concurrency flake, brain-core's stabilization list — NOT evolution); NEXT = wave_done w/ branch CI.
- tests-heavy 37777792901 red = known flake test_lock_fairness_and_cancel_while_waiting (brain-core stabilization queue).
- infra [30,31,32]: safetycli root-caused (integrity-verified, redirect fix) -> orb handoff relayed; 79-FAIL routing: INTEGRATOR 77 (mine — scrub queue: SYSTEM_REPORT 18, LAUNCH 12, .opencode 8, conductor 10, misc) + tools-memory 2 (post-merge) + infra 0; wave_done received w/ honest stale-branch disclosure -> branch PUSHED f963427, re-dispatch assigned.
