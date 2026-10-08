# PROGRESS full log — 2026-10-06/07 onward (mirror; PROGRESS.md keeps a slim current-state view)

## Session 2026-10-06/07 (overnight, integrator) — LIVE E2E GATE + WAVE 3 HANDOFF

**User decisions tonight (verbatim logs in docs/PAID_USAGE.md):** JP slime voice is
PERMANENT, Zira retired ("zira is a bit too robotic so we are not using it");
paid fast models authorized broadly, use them for speed ("make the most of it
while we can") → new **AGENT_RULES Rule 15 (SPEED)**: near-instant responses,
fast cloud defaults, fish stays local for TTS only; "continue as normal and
hand off designated work to correct agent lanes".

- DONE (T2): **Live E2E gate** on the real stack (supervisor + brain + body + orb +
  fish + relay, manual bring-up, scheduled task stayed Disabled). Result **3/5**:
  2 = free-form answers SPOKEN via fish ✓; 4 = 6 distinct live orb_states ✓
  (idle/listening/thinking/acting/speaking/error); 5 = pause/private/kill ✓
  (private blocks cloud exactly as designed). 1 = FAIL (`open_app`); 3 = paid
  vision slot proven in-process (real "Blue" answer, go_vision,
  deepseek-v4-flash-vision-exp, ~$0.001) but live WS path blocked by a foreground-
  verification bug. Full evidence: **docs/BUGS-WAVE2.md** (Bugs A–G, per-lane).
- DONE (T2): **Fix landed as integrator glue:** `GoVisionProvider` now sends the
  mandatory `x-opencode-session` header (was: Go `HTTP 400 MissingSessionID` on
  every live vision call) — `brain/router/zen.py`, committed.
- DONE (T0): **Two silent test-killers documented:** (a) stale `/tmp/raphael-brain.pid`
  made the E2E "restart" a no-op (all pre-restart tests ran on old code — resolve
  via `ss -tlnp`); (b) `raphael stop` sees a LIVE Windows supervisor as "dead" from
  WSL. Both → infra Bug G.
- DONE (T1): **Japanese voice:** stitched 3 clean clips → `assets/raphael_reference_jp.wav`
  (committed; config now points at it), direct fish A/B renders approved by user
  live on speakers (`assets/reference/samples/01_jp_slime_ref.wav` vs `02_zira_...`),
 9.2s master-line clip for the user's Insta story at
  `C:\<win-user>\Downloads\raphael_master_story.wav`. Live-TTS ref mismatch is
  voice-lane Bug D.
- DONE (T1): Orb speaking-state debug: delivery chain verified end-to-end
  (brain→main→preload→renderer `STATE CHANGE -> speaking`, zero exceptions);
  remaining visual issues (no pulse, cage morph wedging) = orb Bug C, debug
  instrumentation reverted, re-instrument guide in BUGS-WAVE2.md.
- DONE (T2): Model routing → `opencode-go/mimo-v2.5` for this session and the
  conductor handler runs (Rule 15). Full 757-test run: 756 pass + 1 order-flake
  (passes isolated; quarantined for qa-security). Conductor suites 34/34 green.
  Core Guard OK.
- DONE (T0): **Wave 3 open:** `current_wave: 3` (WAVES.md gate record updated —
  `wave-2-gate` NOT tagged, honest 3/5, full gate re-runs at wave-3 close after
  Bugs B/D/F); `wave_open` posted to all 10 lane inboxes; all
  `docs/lanes/*.md` rewritten with per-lane P0 tasks + speed mandate.
- DONE (T0): **Clean teardown verified** (rule 14): supervisor/body/orb/brain/fish/
  relay all killed — 0 listeners, 0 fish, 0 electron, 0 Windows procs; GPU
  2047→358 MiB; RAM 6.2 GB free; `live_e2e=false` (watchdog exemption off);
  conductor tmux `raphael-conductor` still running (pid 1396).

**NEXT (user):** send the CONTINUE prompt to the lane sessions — wave 3 P0s are
Bug B (open YouTube), D (live JP voice), F (vision foreground) first; when they
land, the integrator re-runs the full six-criterion live gate for `wave-2-gate`.

## Coord loop 2026-10-07 (wave 3, intake → hand-off)
- router: Bug A regression VERIFIED (13/13 + my own rerun) — landed `test_vision_paid_slot.py`;
  usage/rate `/status` slice DONE (8/8, `brain.router.usage_status()`); two requests to
  brain-core APPROVED (fastpath open+search mapping = Bug B router half; additive
  surface-usage wiring). Next assigned: schema-normalization edge cases.
- infra: Bug G started (heartbeat). brain-core: two approved requests + Bug E assigned, pinged.
- **CI bug found (run 37574556616, also breaks branch pushes):** `.github/workflows/ci.yml`
  ownership step hardcodes `--lane qa-security` for every push — non-qa pushes fail by
  construction; `ownership_check --lane integrator` passes by design (merge-loop does real
  enforcement). File is qa-security-owned → assigned as its urgent NEXT TASK (suggested fix
  shape in its inbox). Main CI stays red until that lands — known, not silent.
- CI fixed per USER DIRECTIVE: qa-security's lane-derivation fix cherry-picked early to main
  as `be6814a` (merge-order deviation documented; branch keeps its commits for the in-order
  merge). Background watcher verifies the run → `.opencode/research/ci-green-check.md`.
- Wave-3 review loop: brain-core wave-3 batch verified (134 brain green = +9 new tests;
  assigned NEXT: post wave_done), infra Bug G verified (82/82 supervisor; NEXT: post
  wave_done, queued at merge position 7), qa-security CI fix verified+landed (NEXT:
  P0-REGRESSIONS), voice started Bug D (JP ref on every synthesis). Killed a live
  keepalive orphan (pid 6079) infra spotted — Bug G evidence.
- CI CONFIRMED GREEN: run 37576160561 (be6814a) = success; ownership step printed
  `lane=integrator ref=main` → ownership OK. The "fails every time" era is over —
  evidence in `.opencode/research/ci-green-check.md`.
- Wave-3 merge loop: **brain-core merged (18744b3)** — Bug E speaking-hold, fastpath
  open+search (Bug B router half), /status router block; OWNERSHIP amended (brain-core
  += brain/orbstate.py, was unlisted gap); ws.py audio_start comment corrected. qa's
  precedence request adjudicated SUPERSEDED by the merge (its parked xfail flips on
  branch sync). Merge queue: router ✓ → brain-core ✓ → **pc-control NEXT (pinged)** →
  voice → computer-use → orb → infra → qa-security (wave_done's queued: infra@7, qa@8,
  voice@4 once pc-control lands). voice's live `prove_reference.py` proof added to the
  wave-3-close gate checklist (BUGS-WAVE2 Bug D).
- PROTOCOL §3 += `notice` frame (brain-core proposal APPROVED: ui+cli, info/warn,
  no state change; emitters restart-recovery + ratelimited outage only; confirm-expiry
  DEFERRED). qa nudged (conformance whitelist), orb/infra nudged (optional render).
  pc-control Bug B body half verified (85/85) → next: wave_done (merge pos 3).
  tools-memory woken with brain-core's conversation-hook request.
- **pc-control merged (wave 3)** — Bug B body half lands: no-console spawns, act_res
  always answered, stage-count errors, 17 tools schema-offered. Merge order: router ✓,
  brain-core ✓ (follow-up goal 3 in progress), pc-control ✓ → voice next.
- **brain-core wave-3 follow-up merged** — goal 3 Notice events live (approved scope;
  integrator co-signed the 6-line ws.py flush hook; brain/notice.py ownership granted).
  brain-core wave COMPLETE (all 3 goals + P0s + 2 requests). Conversation-hook ts fix
  landed (tools-memory had accepted). Queue: voice (pos 4) next, then computer-use, orb,
  infra, qa, tools-memory (started prep), evolution-persona.
- **voice wave-3 MERGED** — Bug D lands: JP great-sage reference required on EVERY
  synthesis (loud fail + zero audio otherwise), per-synthesis proof line, phrase cache
  ref-sha1 namespaced. Voice 93 + brain 152 green post-merge. orb wave_done queued@6.
- **computer-use wave-3 MERGED** — Bug F lands (honest reachability-vs-privacy verdicts,
  blocklist on every observation, terminal-foreground tests, 1-probe speed). Queue plug
  cleared: orb(6) can now merge when its turn comes, then infra(7), qa(8).
- **orb Bug C FIXED + verified** (npm PASS): pulse restored (seq guard removed), stuck
  cages = morph target 144≠180 floats + pre-set shapeHint killing animate's morph — one
  masked by pose-lock screenshots in the old matrix; flip latency 1ms. Notice banner
  accepted (level-tinted, never a state). tools-memory: memory core (FTS5/BM25) +
  skills/plugins gates done (41/58 tests green).
- INCIDENT (self-inflicted, resolved): a trailing `cat >> PROGRESS.md; git commit` in a
  shell that had `cd`'d into ~/raphael-wt/tools-memory for a test run committed my bullet
  onto agent/tools-memory (6d174f0) instead of main — tools-memory hit a perfect rule-4
  stop and filed a request. Fixed option (a): bullet re-landed on main (ff8a4c7), lane
  told to rebase --skip the now-empty commit. LESSON: per-command `cd /home/<wsl-user>/raphael`
  before ANY git write (single-shell cwd drift).
- qa-security wave_done queued@8 (regressions strict incl. flipped Bug E, notice whitelist,
  flake quarantined, 263/9). tools-memory wave_done queued@9 pending its rebase fix.
- **Merged in wave gate batch:** orb 8ec70be (Bug C + notice banner + de-flaked matrix),
  infra 9446b26 (Bug G pid hygiene + zero-teardown + speed caps), qa-security 2cbd5d6
  (gate-bug regressions STRICT incl. flipped Bug E, notice conformance row, flake
  quarantined — root 263 green). Positions 1-8 of 10 DONE. Remaining: tools-memory@9
  (rebase --skip pending its session), evolution-persona@10 (never started, pinged).
- **tools-memory wave-3 MERGED** (39 files, ownership OK, memory 116 green post-merge,
  core guard OK) — memory core + skills/plugins + full tools bulk + MCP client all in
  main. Rule-4 incident fully closed (rebase --skip of empty 6d174f0 verified by lane).
  **9/10 lanes landed.** Only evolution-persona remains: design-notes task DONE (2e3c534,
  verified), assigned post wave_done at final position 10 — session asleep, ping queued.
- **WAVE-3 MERGE BOARD COMPLETE: 10/10** (evolution-persona closed it at 6aa52f0).
  Full mock gate sweep green: tests/run_all --with-brain = 272 passed, rc=0.
  WAVES.md gate record updated; attention posted — **wave-3 live E2E re-run awaits the
  user's GO** (starting the live stack is human-only). Open item: shadow-instance
  request (evolution-persona -> brain-core) blocks Wave-4 shadow runs only.

## Session 2026-10-07 (day) — USER GO: live gate + drive to "alive and usable"

**User approval (verbatim):** "im going to work, but you keep working brother and make
sure its done to the very end where raphael is alive and usable and can control my
laptop" — treated as the GO for the wave-3 live E2E (attention "Wave 3 gate ready")
AND instruction to LEAVE THE STACK RUNNING at the end (manual bring-up; scheduled task
stays Disabled per rule 12; one-fish rule 14 still binds).
- CI CONFIRMED FULLY GREEN after encoding fix: run 37618571343 — Ubuntu success + Windows
  success (research/ci-encoding-fix-green.md by watcher).
- Stack UP for live gate (user GO): brain pid191414 healthy, sessions body=1 ui=1, fish
  ONE + 8777 listening + GPU 2.1GB, JP reference loaded ("reference present:
  raphael_reference_jp.wav"), first live utterances played (audio_out 404/418 chunks).
  live_e2e=true restored (watchdog was correctly killing fish while flag was false —
  rule-14 design verified in the wild).

## WAVE-3 GATE PASSED 🎉 + WAVE 4 OPEN (2026-10-07, user GO run)

**Tag `wave-3-gate` pushed — all six criteria PASS live:**
1. TEXT: "open YouTube and search lo-fi" → search_youtube → `results?search_query=lo-fi`
   opened (Bug B fixed); laptop control: `open notepad` → system32\notepad.exe act ok.
2. VOICE (acoustic, x2 clean runs): speaker→mic→wake segment→STT (rtf 0.13)→wake gate
   →extract→fastpath→open_app→**notepad launched (ok=True 108-141ms)**. Spoken answer:
   "Paris is the capital of France." 63 fish chunks in JP voice; prove_reference.py
   PROOF OK (sha1=f64bd512ea1e).
3. VISION: real screen description via Go paid slot ("tiling WM, Python editor, browser
   open to YouTube…") — spend $0.0007/day of $1 cap.
4. ORB: distinct live states incl speaking (Bug C).
5. pause/private/kill: all acked (private blocks cloud exactly right).
6. MOCK: `tests/run_all --with-brain` 272 passed rc=0.

**Bug H (found+fixed by the live gate, all committed 07cadcb):** voice input was SILENTLY
dead since wave 2 — stt.py never awaited the async Router.transcribe (empty transcripts);
plus stt_language parsed-then-discarded in the loader + pinned `en` (whisper returned
hangul for the wake word under the JP voice), wake extract left a repeated wake copy,
fastpath passed "notepad please" as app name, whisper now gets a wake-word prompt bias
(additive transcribe seam kwarg). CI encoding fix (qa absorbed+extended) green both OSes.

**current_wave → 4** (hardening/resilience/audit/crash-recovery/evolution): wave_open to
all 10 lanes with Wave-4 sections written. **Stack left ALIVE per user directive:**
brain+body+orb+fish+relay up, live_e2e=true (watchdog exempt), scheduled task still
Disabled, zero orphans, conductor running. Stop with `scripts/raphael stop` (+ set
live_e2e=false) when wanted.
- **router wave-4 merged** (position 1): resilience suite (429/5xx/breaker/network-drop/
  exhaustion), crash-safe usage logging, 2 qa requests closed with evidence. 144 router
  tests (+24), core guard OK.
- **brain-core wave-4 merged** (position 2, $MERGED): journal replay hardening, kill-safety
  matrix + engine.shutdown speech-kill FIX, outage drills, lock stress. infra wave_done
  queued@7 (corrected my position mislabel), orb fps-audit approved with isolation
  conditions (mock-brain, separate instance, kill-verify).
- **pc-control wave-4 merged** (position 3): 17-tool failure tables, lock-release audit,
  partial-failure matrix, E2E injection. Board: router ✓ brain-core ✓ pc-control ✓ →
  voice(4) next, then computer-use(5), orb(6), infra(7), qa(8 incl. flake fix), tools(9), evo(10).
- **voice wave-4 merged** (position 4): fish-recovery ownership-safe, STT-outage path,
  soak, Bug H guards (request to brain-core rides the merge). computer-use verified with
  a REAL security fix (blocklist bypass via untitled KeePass window → composite
  'title | process' identity) → wave_done next (pos 5). Board: 4/10 landed.
- **WAVE-4 MERGE BOARD COMPLETE (10/10, local)**: qa-security d828c20 (resilience matrix,
  registry-flake fix, OWNERSHIP-EXCEPTIONS MECHANISM integrator-reviewed: assignment-backed
  exact-path, founding 3 = my inbox[18] sanction; 8-area security re-audit), tools-memory
  284cba4 (sqlite/FTS/injection/MCP hardening + export/wipe controls), evolution-persona
  fa3fc1a (journal/rollback/zone spikes + persona tier deep-merge; shadow runs CARRIED on
  brain-core's approved row). All suites green at every gate (286/145/63 + core guard).
  NOTE: GitHub receive-pack returning 500 on push (reads+REST+status green) — background
  watcher retrying; batch pending = 11 commits. Verdict → research/push-recovery.md.
- **WAVE-4 GATE PASSED — tag `wave-4-gate` pushed.** 10/10 lanes merged; mock sweep
  308 passed rc=0; GitHub receive-pack 500s recovered (all 15 commits landed
  a61c801..d841a3a); watcher false-success corrected in research/push-recovery.md.
- **WAVE 5 OPEN** (current_wave=5): Raphael features — Answer/Notice/Report formats,
  Analysis, Simulation, parallel-minds visuals, persona tiers (great_sage→raphael→ciel).
  wave_open to all 10 lanes with Wave-5 sections; carried: brain-core shadow row,
  voice C1+C2 confirm residual (qa re-audit).
- Wave-5 early: brain-core shadow row + STT-outage MERGED (577f09c, position-2 deviation
  ahead of unstarted router — recorded in merge msg + exceptions file; evolution shadow
  runs UNBLOCKED). CI fix: test_hardening bare-module import (qa pattern missed file) —
  exact CI step 738 green, pushed c60c23c.
- Wave-5 rolling: router Analysis routing (e80c8fd) + answer/report emitters + PROTOCOL §3
  hand-edit (239eb90/a4b1565, atomic conformance whitelist pair) + loader-authority-guard
  (security, qa request → brain-core decision/implementation → merged) all landed.
  Queued: infra@7, evolution@10; qa (whitelist rebase + wave_done) next.
- **Wave-5 queue batch positions 3-7 MERGED** (a96f7ba pc report-act, 2fb9f4c voice pacing/
  tiers, 486fbe0 computer-use gather_context+vision guard, a0960a1 orb banners/fan-out/themes,
  aa5cf83 infra tier CLI): gates all green, brain 184, conformance 4/4, core guard OK, pushed.
  Remaining wave-5: qa(8) whitelist rebase + wave_done, tools-memory(9), evolution(10).
- Wave-5 closing batch MERGED: qa 2ffc185 (instance-count cross-source fix, field-shape
  tests, loader-guard flip STRICT, voicespy kwargs fix), tools-memory 2a7d1fb (kind-aware
  memory feeding + report cache + injection probes), evolution eb3fb0d (persona tier
  implementation, shadow/baseline, formats, probation — 140 tests in its gate).
  Positions 1-10 ALL MERGED. ONE KNOWN RED on main (attributed, deliberate):
  qa's armed analysis/sim privacy tripwire — missing gates = brain-core's P0 next batch
  (assigned + pinged); wave-5 tag waits on it.
- **WAVE-5 GATE PASSED — tag `wave-5-gate` pushed.** brain-core P0 merged (5262845:
  Analysis/Simulation + all 3 privacy gates, tripwire GREEN), full sweep 346 rc=0,
  root 313 zero failures. current_wave stays 5 — wave 6 (local-model cutover) is
  human-gated on the RAM upgrade; attention posted with options.
- Orb USER DIRECTIVE merged: shape-morph revert (constant circle, kind accents off,
  flagged machinery kept; colour + speaking pulse + banners retained; distinctness
  104/104 via colour). tests-heavy CI round 2 GREEN both jobs (full battery + orb gates
  in the cloud — laptop-free testing verified end to end). TTS research: PocketTTS wins
  (1.1GB CPU, clones JP ref) — voice eval task assigned.
- Voice P0 COMPLETE on main: accent (namespaced cache + timbre gate + sweep) + gaps
  (audio_out 42%-loss fix + reply-level pre-roll — probe max gap 1.0ms vs 12230ms).
  Opencode chain live-verified (zen_free/go serve, groq STT-only caps + chat-cap require).
  config.yaml HARD REFACTOR: 97/97 semantic equality, all suites green.
  Cage restored (3D wireframe spheres, radius proof). Stack DOWN by default
  (spawn-on-test policy broadcast); cost anxiety lifted (PAID_USAGE).
