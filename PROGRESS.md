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
- brain-core [60-63]: ENTIRE critical packet done + wave_done (consumer/utt-continuation/chat-label/pidfile/FLAKE-FIX; 675+241 green; QA-4 37778951946+37778966595) -> queue waits on router (blocker pinged); after merge: live gate verify + flip require_foreground=true.
- tools-memory [41,42]: both blockers landed (main typo ACQUISITION + branch a99bfe3 w/ fb059a8) -> dispatch now; 2-literal FYI = stale-tree scan (accepted).
- integrator scrub: main pushed (docs placeholders, derived code, dynamic fixtures, conductor 45/45, guard OK); routed infra: ip-public version FP + runtime-config allowlist packet.
- qa [48,49]: packet reconcile (honest PARTIAL/NOT-started) + wave-3 golden transcripts ACCEPTED (replay-through-fresh-instance, credential-free, CI 37779361658 5/5, run_all 372); NEXT = QA-3 cron+evals.
- CYCLE-2 MERGES: router (position1, QA-4 37779640377 exact-head SUCCESS) + brain-core (position2, consumer+utt-cont+flake-fix) on main; PROTOCOL lane edit accepted under recorded grant; battery 287/169/8+guard green. voice pinged to re-measure Cut B; gate flip waits on pc (position3).
- PROTOCOL grants recorded in tests/ownership_exceptions.txt (=pc-control,brain-core; checker comma-list support) -> pc unblocked: rebase+dispatch+wave_done, position3, gate flip follows.
- REQUESTS DECIDED: E_BUDGET -> PROTOCOL §10 (qa catalog tripwire green) + ARCH-5 cloud/hybrid presets -> config.yaml (20 preset/budget tests green; hybrid dormant behind human gate). router -> ARCH-5 append grant + flip chat-label + WAIT.
- evolution [34]: wave_done position 10/10 ACCEPTED (QA-4 37780552325 exact head 5/5) — wave closes after tools-memory(9)+evolution merge. router requests E_BUDGET+ARCH-5 presets applied+pushed.
- ELECTRON 44.5.1 MERGED (PR #10, ac05b3c) on orb's MERGE-RECOMMENDED verdict: 0 vulns (closed ASAR HIGH), all orb gates green, API review zero breaks. orb -> rebase fold + fresh green id.
- router [50]: ARCH-5 append + chat-label flip verified/accepted; all requests ANSWERED -> WAIT sent.
- qa [50,51]: QA-3 COMPLETE accepted (12-eval harness + nightly cron + live CoreGuard-refusal proof; CI 37781177536 5/5, suites 384) -> NEXT = wave-5 evolution gate tests, then control-plane re-audit.
- infra [33]: scanner policy packet ACCEPTED (ip-public FP both-directions proof + exact-triple allowlist + 79->66); branch REWRITTEN+synced 9449ca6 -> dispatch for green id.
- voice [50]: Cut A body half accepted (close12+grace13==25 zero-split proof) + Cut B neutral-measurement accepted; LATENCY DECISION: accept ~550ms floor (perceived ~1.8s, -45%); closer-provider option needs human key (standing, not urgent); NEXT = branch CI + wave_done, position 4 behind pc.
- MERGES: voice pos4 (63b6245) + orb pos6 (c9d0ac6) pushed; battery 440/169/8+guard green. infra 9449ca6 + tools-memory 0c5e06c pushed+server-verified (both dispatching for green ids, positions 7 & 9).
- GATE LIVE PROVEN: hook=True -> consumer -> chat PASS provider=go/mimo subtitle2.97s + act 0.55s + refusal 16 tests. brain-core/pc/voice/orb notified.
- F-3 ADJUDICATED: signed act-journal agreement canonical; pc's older activity-viewer-schema SUPERSEDED (pushed).
- brain-core [68] heartbeat (idle WAIT).
- qa [52,53]: wave-5 evolution gate tests ACCEPTED (9 drills incl. tamper/boot-refusal/rollback/probation; SAFE_MODE test-infra poison fixed; CI 37784899899 5/5, run_all 393) -> NEXT = control-plane re-audit (note: coord.py REPO_ROOT + keepalive cron fix on main need fresh verify), then wave_done.
- voice [53] heartbeat; branch carry-over 7a224fc rides next cycle (noted, no action).
- INCIDENT + REPAIR: first infra merge grabbed stale ref bd2253a + markers committed (5bf0902 red) -> repaired (7fef959) + correct head9449ca6 merged (55ba77a), full battery 418/182/8/213+guard verified BEFORE push. LESSON RECORDED: never merge a stale ref (fetch origin/... after explicit push), never push without the battery green.
- infra position7 MERGED; tools-memory baseline-regen entry GRANTED on main (temp, remove-at-merge) -> their rebase+dispatch; 5 events handled.
- infra [38]: merged-ack + incident acknowledged; branch contained in main; WAIT.
- GITLEAKS MAIN RED FIXED: 4 uncovered = 49deea5 (pre-rewrite fixture literals via my mis-merge) -> baseline regen per SCANNERS.md conscious-acceptance (156, local 0 leaks, reason committed; permanent fix = human history rewrite ATTENTION).
- orb [42]: root-causes confirmed (gitleaks mine-fixed; ownership base-artifact -> qa improvement routed); pc [40]: focused-password accepted, rides next cycle.
- WAVE-5H GATE EVIDENCE: C1 register updated (18+1 statuses, all P0/HIGH/CRIT in accepted vocabulary) ✓; C2 runs tracked (37792241017 SUCCESS; tip run queued) ; C3 tripwires in CI suites ✓; C4 ZERO non-ledger FAILs ✓; C5 tests-heavy 37791936216 SUCCESS ✓.
- Straggler sweep MERGED (router/pc/voice/qa) + test_aud_harden import-order fix (IMPORT_FROM getattr-first) + 2 more baseline regens — all gates green, pushed; brain 1127.
- qa scanner-count clarification sent (their ~335 vs tool's 0); request-file flips nudged (infra safetycli, qa electron).
- infra [40]: safetycli request CLOSED (ANSWERED, grep=0 proof) + branch hygiene (9449ca6 restored/rebased, 4b0443f rides next batch); WAIT.
- qa [57]: scanner clarification closed (~335 retracted, 55/0 confirmed); electron request flip DONE (44.5.1, 0 highs, npm gate tightened); strict-severity PROPOSAL -> DECISION option1 (strict=FAIL-only, REVIEW advisory) -> infra implements, qa flips strict step after.
- qa [58]: post-gate batch (2 commits, CI 5/5) MERGED after their verify-first flag; brain-core/voice gate acks (cursors moved). All lanes idle pending wave_open (human-gated).
- qa [59]/router [54] heartbeats: option1 sequencing acked (qa pings when infra's strict flag lands) + router gate ack (head in main, credit trail noted). All lanes idle pending wave_open.
- orb [46]: closure-record commit 89f2f04 kept -> rides next merge pass (strict-flag sweep with infra batch); all else in main.
- STRICT-FLAG SWEEP MERGED: infra OPTION-1 (--strict FAIL-only, REVIEW advisory, proof15/15) + orb closure record 89f2f04 + infra rebase — battery+gitleaks gated green, pushed. qa pinged to wire tests-heavy strict step.
- qa [60]: SEC-1 STRICT gate wired (tests-heavy step + guard #8, CI 37799170764) -> MERGED on main, battery+strict+gitleaks gated green. orb [47]: all loops closed (commit merged + both requests flipped by owners). EVERYTHING post-gate complete; all lanes idle pending wave_open.
- qa [61] heartbeat: post-gate complete, 0-diff vs main, WAIT.
- qa [62] heartbeat: confirmed template wakes = conductor liveness (not unmet work); WAIT correct.

## 2026-10-09 — Wave R research sprint (COMPLETE, docs-only)
- Lanes paused live via direct session pings (after fixing the delivery bug: inbox appends alone don't wake sessions when the conductor/service is down); state.json mode=research_sprint; stack stayed OFF throughout.
- R1 architecture review (brain-core surface): boundary sound; real seams = confirm-in-cancel, lock-name derivation, hard-coded risk regex; target Mermaid diagram + prioritized mitigations.
- R2 tooling survey: 24 candidates across 8 areas; overrides applied by me where surveys meet measurements (openWakeWord REJECT per AUD-06 data; silero-vad DEFER to RAM gate; trufflehog REJECT; orchestrator frameworks REJECT — our coord bus proven by this very sprint).
- R3 VulnClaw: adopt-FOR-TESTING-ONLY (isolated VM, ask/auto_review, never full_access, user authorization) — framing reproduced verbatim.
- R4 gap list: 14 grounded gaps (9 security, incl. the voice-confirm cluster that keeps qa's xfails red).
- R5 decision gate: voice-confirm batch = top code priority when wave 6 opens; semgrep = only new CI adopt; everything else BUILD CUSTOM S/M or DEFER/HUMAN.
- Nothing implemented; R1-R5 + this summary pushed to main for the human's review.
- PERSONA RESEARCH COMPLETE (user side-quest): docs/research/persona/ — 5 canon-hardened reports (first pass had fabrications: Raziel/VA-Setoguchi/Hollow-Mixture/phantom arcs — all debunked via strong-model re-runs) + 00-CONSOLIDATED-BRIEF (lineage, service model, autonomy rules, tier mapping, TTS tone spec, debunk register). VA arbiter: Toyoguchi (JP)/Rodak (EN) for all three forms; Ciel = LN Vol15, not animated yet.
- HER OWN OBSIDIAN VAULT created at C:\<win-user>\raphael-vault (persona/ + journal.md + README rules; the temporary section inside the damianqt vault was removed on user correction); repo skill .opencode/skills/raphael-vault added so every session can use it.
- COMPANION RESEARCH (user side-quest): docs/research/companions/ — Grok bots, OpenAI Dots (real product: always-on cloud-VM agents, orb states, auto-review rules), Meta Muse (real product, launched 2026-09-08) — + 00-COMPANION-TAKEAWAYS. Verdict: market converged on our shape (6 patterns already shipped); genuinely new = clarify-on-ambiguity (S), user-editable confirm policy (S/M, extends R5 confirm-categories), named context slots (M), memory-privacy spoken affordance (S). Not taken on record: cloud-VM-only execution (privacy), social/mobile/AR surfaces, mouth-anthropomorphism.
- CODE-ADOPTION PLAN written (docs/research/persona/06-CODE-ADOPTION-PLAN.md) + proposed Wave 5P section in WAVES.md: P1 tiers-as-runtime-state, P2 voice tier params, P3 user-editable confirm policy (A2 + R5 confirm-categories + R1 config-risk), P4 clarify-on-ambiguity (A1), P5 context slots (A3), P6 spoken memory privacy (A4), P7 journal-as-memory-surface, P8 notice tone. All companion A-items folded in; defers/rejections on record; lanes still paused pending user go.
- PROMPT HARDENING PASS: 4 battle-scar rules added to all three coord prompts (delivery-proof pause via live pings, ls-remote before lane-branch pushes, battery-gate before every push, persona debunk guard); live copies synced, guard rehashed, pushed.
- WAVE 5P in motion: evolution P1 COMPLETE (tier prompts + debunk lint, 80 tests) -> wave_done next; tools-memory P5+P6+P7 COMPLETE (slots/privacy/journal, suites 212/242/271) -> branch pushed a8216da, CI dispatch next; qa reading persona packet; brain-core on P3/P4.
- Outsource audit verdict: nothing replaces our confirm/memory/journal; top-2 user-gated options = obsidian REST plugin + slowapi. Laya alive & advisory-tested (47.6ms GPU).
- LIVE FIXES (user report: can't talk + slow chat + mic): (1) WakeStream.CONTINUATION_GRACE missing -> AttributeError killed the wake task at startup (Cut A glue bug in voice-owned audio_in.py; integrator glue fix = constant now sources from VadSegmenter; wake task verified alive with live grace-hold/continuation logs); (2) mic auto-default CONFIRMED working (Realtek default armed after fifine vanished; device=None never hardcoded); (3) chat chain reordered zen_free-first (go slow while weekly-cap=100%/balance-billed:43s/16s vs zen's3-4s class) — config.yaml. (4) P0 UX bug dispatched: YouTube repeat-open must navigate-in-place (pc-control foreground Ctrl+L + brain-core fastpath mapping). (5) Adversarial design-review session launched (haiku-5.5): explain-or-reconsider report -> docs/research/design-review-2026-10-09.md. (6) MODEL_POLICY: haiku-5.5 = default issues/debugs tier per user.
- DESIGN REVIEW LANDED (docs/research/design-review-2026-10-09.md, mimo budgeted after user cut haiku burn):13 findings, verdict = sound + unusually self-documenting, no CRITICAL. Routed: infra HIGH (wsl-relay.py helper leg never got the zombie fix — likely THE cause of recurring relay wedges; port+watchdog), brain-core P3 sharpened (confirm_policy = dead config until P3 wires it; default-confirm vs classify-allow contradiction to resolve; MEDs: lock-holds-worker, foreground-refusal notice). MODEL_POLICY = single source of truth (AGENTS.md annotated). Haiku's508KB partial salvage preserved at /tmp/haiku-salvage/ (findings never consolidated; mimo report supersedes).
- LIVE STATUS: stack up; chat zen_free2.52s (chain reordered), act0.0s, speech playing, wake-task fixed (grace constant), mic auto-default confirmed. P0s in flight: voice (grace->config+8 + wake-drop visibility), router (zen-free fast role -> flash-class).
## 2026-10-10 — WAVE 5U OPENED (owner charter: USEFUL-NOW-PLAN.md)
- Owner answers recorded: (1) Go-first cloud chat profile YES + $0.50/day runtime chat cap; (2) Wave5U folding5P = good; (3) Kokoro calmest-female preset for now (custom-voice question answered: Kokoro = fixed voice bank, no cloning — custom voice stays the fish reference path / optional GPT-SoVITS later); (4) demos default-YES with strict one-stack + teardown rule (no stray live stacks, no duplicate spawns — pre-flight pgrep/port sweep + post-demo teardown verification every time).
- Charter committed first (docs/USEFUL-NOW-PLAN.md); Wave5U wired into WAVES/AGENT_RULES rule16/TODO/.gitignore; Wave A dispatched to7 lanes (brain-core, pc-control, tools-memory, voice, qa, orb, infra); router/computer-use/evolution WAIT.
- Integrator contract work landed: PROTOCOL (chat/worker roles, speak flag, confirm_resp channel, needs_confirm fields, browser act), config (typed_confirm+classes, personal_ok, chat cap0.50, auto_permit deprecated), OWNERSHIP grants (worldstate/agents/web-chat), INTERFACES CDP ports, Core-Guard standing approval request. Stack stays DOWN except demos (ask-first default yes per owner).
