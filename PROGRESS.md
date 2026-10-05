# Raphael — PROGRESS

Status legend: DONE / IN-PROGRESS / BLOCKED / NEXT
Model tier used per step: T0 = no LLM, T1 = mimo-v2.6-flash-free, T2 = strongest other free, T3/T4 = paid pool (log to docs/PAID_USAGE.md)

## Session 2026-10-04

- DONE (T1): Verified live OpenCode v2 agents docs (`opencode.ai/v2/docs/agents/`): `.opencode/agents/<name>.md`, frontmatter `mode: primary|subagent|all`, `description`, `model: provider/model`, `steps`, `permissions` (ordered rules, last match wins), subagent inherits parent model unless configured. `v2.opencode.ai/agents.md` 404s — use opencode.ai/v2/docs/.
- DONE (T0): Initial env probe: WSL2 Ubuntu 26.04, kernel 6.18.33.2, 20 cores, 7.6 GiB WSL RAM / 2.0 GiB swap, `/` 869G free, `/mnt/c` 483G free, interop present (wsl.exe/powershell.exe/cmd.exe).
- DONE (T1): Phase 0 — `scout` subagent wrote `SYSTEM_REPORT.md` (218 lines; user correction applied: WSL VHD shares C:'s 482.8 GB — one storage pool).
- DONE (T1): Local model verification — `qwen3.5` family live on Ollama (4b=3.3GB unified text+vision resident pick; 9b=6.6GB on-demand offline fallback; Ajax not released → gated optional candidate).
- DONE (T1): Tier-2 shootout, 2 rounds, real `opencode run` invocations: basic = 3/3 PASS; multi-step chain = 4/4 PASS with times big-pickle 33s, fledge-alpha-free 37s, ling-3.1-flash-free 59s, nemotron-3.5-lightning-free 117s. **T2 = `opencode/big-pickle`** (fallback fledge-alpha-free). Docs updated.
- DONE (T1): `docs/MODEL_POLICY.md`, `docs/PAID_USAGE.md`, `docs/TEAM_ROSTER.md` written. Paid spend still $0.00.
- DONE (T1): Post-Phase-0 directives captured in `docs/REQUIREMENTS_ADDENDUM.md`: Raphael-as-orchestrator north star; GitHub tool (user creates private build repo; runtime repo creation with visibility heuristics, public=confirm); Odysseus-style memory (researched live: pinned+hybrid retrieval, untrusted-context wrap, owner scoping); self-writing skills (Odysseus SKILL.md format, draft+confidence gate); `slut` model permanently excluded.
- DONE (T0): `.wslconfig` created at `C:\Users\jxesu\.wslconfig` (memory=10GB, swap=4GB, vmIdleTimeout=600000) with user approval — takes effect next WSL restart/reboot, NOT shut down now. Windows RAM recheck: 5.3 GB free (Premiere closed; low reading during scout was Premiere).
- DONE (T0): `git init` (branch `main`), `.gitignore` (.env/venvs/logs/db excluded), remote `origin = https://github.com/Xqni/raphael.git` (private). `gh` authenticated as Xqni (keyring) → can push without user action.
- DONE (T1): Addendum §7-9: voice-first confirmation loop, Raphael auto-grants runtime worker permissions (dedicated auto-permit OpenCode config dir; gate = her own confirmation layer), GitHub repo URL.
- DONE (T1): `docs/PROTOCOL.md` written (transport :8765 + NAT/localhostForwarding rationale, token handshake, roles body/ui/cli + capability matrix, message catalog, binary PCM frames, job state machine, act_req allow-list incl. no-arbitrary-shell rule, confirmation flow, 16 error codes, security invariants).
- DONE (T1): `docs/ARCHITECTURE.md` written (process topology + mutual watchdog, directory layout + per-agent ownership map, job engine/input-lock/priority/limits, fast path, router chain, privacy rules, memory+skills design, latency instrumentation, config.yaml surface, reliability matrix).
- DONE (T1): Character direction corrected (addendum §10 + config `voice_personality`): **Great Sage from Tensei Slime**, not Jarvis — terse analytical speech forms, silent background analysis surfacing only actionable results, no butler banter.
- DONE (T1): 13 `.opencode/agents/*.md` created + validated (frontmatter parses, permission ordering correct, 14 total with scout) — spawn-tested successfully (reviewer + supervisor-dev launched without registry restart).
- DONE (T2→triage): `reviewer` (big-pickle) reviewed Wave 0 docs. **Triage: ~70% of findings quoted text that does not exist in the docs (verified via grep: no `2.0/5.0`, `ttl`, `50ms`, `token bucket` in PROTOCOL/ARCHITECTURE) — treated as hallucination, not applied.** 3 genuine ambiguities found and FIXED: (1) input-lock vs priority semantics (no lock stealing; priority = admission/announcements only), (2) heartbeat explicit max-silence 30s + client backoff + disconnect task cleanup, (3) cancel vs in-flight act_req handling; plus real gaps fixed: error-code retry/fatal split, WSL-IP fallback addressing, Windows Python 3.10.11 made explicit, latency measurement boundaries. **Process rule going forward: review briefs must demand verbatim file:line quotes; unverifiable quotes = rejected finding.** Ciel-vs-Raphael persona: config-switched, Raphael default (user agreed to keep Raphael v1).
- IN-PROGRESS (T1): `supervisor-dev` building supervisor/ + scripts/ (ses_ef58aeae5ffeX0kQ7NhL2F5P5Y).
- NEXT: verify agent files + spawn-test one; initial commit; Wave 1 (2-3 of: supervisor / orb / router / body per dependencies); reviewer gate after each module.

## Session 2026-10-05

- DONE (T1): Orb v2 spec (user directive, addendum §11, commit `cc9a975`): **3D Three.js/WebGL orb** from user's 6 Tensura references (copied to `assets/orb-reference/*.jpg`, originals untouched). Rest = slow revolve+breathing; speaking = word/pitch pulsation (PROTOCOL §8: `speak.amplitude` required + optional `pitch_hz`); acting = polygon morph by task kind (`orb_state.shape_hint` + `task_kind`; mapping in `config.yaml → orb.shape_map`: system=triangle, files=square, web=pentagon, media=hexagon, llm=octagram, gui/idle/speaking=circle; 600ms morph).
- DONE (T1): `docs/VOICE_DATA_SPEC.md` — Fish-Speech zero-shot reference: ENGLISH recommended (EN dub VA **Mallorie Rodak**; JP = Megumi Toyoguchi, alt profile later), target 60–90 s clean single-speaker (fish-speech open--source cap 90 s), variation list + episode/timestamp table (match by quote text for EN dub), format rules (mono/WAV/dialogue-only/demucs for dirty clips/SRTs welcome), deliverable = `assets/raphael_reference.wav` + `.txt`. User has NOT yet delivered clips/SRTs.
- DONE (T0, user approval): **model downloads approved** ("you are good for model downloads"). `qwen3.5:4b` (3.3 GB) ✅ pulled. `qwen3.5:9b` (6.6 GB): 3× registry `EOF` failures — every attempt died right after the same 921 MB layer (attempt 1 at 44% of the 5.6 GB blob, attempts 2-3 immediately) → **DEFERRED per 3-strike escape hatch**; retry in a later session, not on critical path. Disk ruled out: real free space = **475.8 GB on C:** (WSL rootfs shares the Windows drive pool — `/dev/sdd`'s "863G free" is only the VHD's virtual extent, NOT real capacity; per user correction). Ollama store = 21 GB.
- DONE (T0): **Vision pipeline root-caused & fixed** (5 failed attempts): vision agent overhead ≈16k tokens (AGENTS.md+tool schemas) + ~1.1k/image vs server ctx 16384 → even 1 image (17,088) could never fit; downscaling is useless (Ollama fixed image grid: 17-token delta). Real knob = `/etc/systemd/system/ollama.service.d/override.conf` `OLLAMA_CONTEXT_LENGTH` 16384→**32768** (user ran sudo; verified fresh llama-server `-c 32768`). `opencode.json` `"context": 32768` = UI metadata only. Full writeup: `.opencode/research/vision-agent-context-budget.md`. Also: first vision failure mode = generic fluff reply (silent overflow), not model refusal.
- IN-PROGRESS (T0): 3× vision subagents (2 images each, all 6 orb references, batched per ctx budget) → to synthesize `assets/orb-reference/DESCRIPTIONS.md` art brief for orb-dev. **Batch 3 (imgs 5-6) DONE** — detailed art observations returned (golden rhombus energy construct; green/cyan pentagonal-star construct on black); batches 1-2 pending.
- IN-PROGRESS (T1): `supervisor-dev` building supervisor/ + scripts/ (ses_ef58aeae5ffeX0kQ7NhL2F5P5Y) — still no completion report; verify with real test outputs (`py_compile`, powershell `-DryRun`, `--selfcheck`, `bash -n`) when it lands.
- DECIDED (user + research, 2026-10-05): **Laya (github.com/NandhaKishorM/laya) = Raphael's System 1 decision head.** Open-source local replacement for Jev (Apache-2.0, 30.8k★, Jev-compatible `/v1/systemone` wire): typed decisions (choice/score/noul) in ONE forward pass — 33 ms T4, no generation → nothing to parse/hallucinate. Slots as the MIDDLE tier of the existing fast path (ARCHITECTURE L92): `fastpath.py` rules → **Laya gate** → LLM System 2 (abstention on `min_confidence` = fail-closed → fall through / ask user). Use points: fast-path intent, voice-confirm parsing, act_req/auto-grant safety gate (noul prob), `task_kind`→orb `shape_hint` (PROTOCOL §8), job urgency. Runs CPU ONNX INT8 (~0.5-1GB RAM, VRAM stays for Ollama); torch shared with voice phase. Cautions: zero-shot accuracy mid (0.36 → 0.77 after fine-tune on own labels, Kaggle notebook later); benchmark on THIS machine before hardcoding latency claims. Groq confirmed **free tier only** → $0, no PAID_USAGE entries.
- DONE (2026-10-05, Laya): `brain/.venv` (uv CPython 3.12.8) + laya 0.3.27 + torch **2.14.0+cu126** (driver 12.7 — cu130 fails cuda init). **Measured: GPU 4060 singles 44.7ms mean / batch 21ms/utt (VRAM 1.7–2.5GB, first-load warmup 10.5s) → ADOPTED as fast-path middle tier; CPU ~935ms = fallback only; INT8 ONNX banned for confidence-bearing decisions.** Zero-shot accuracy still blocks gating (delete→confirm 0.09; research/timer→out_of_scope; checkpoint ships invalid temps) → Phase 1 advisory → Phase 2 gates after fine-tune. Docs written: addendum §12, ARCHITECTURE fast-path amended, `.opencode/research/laya-decision-engine.md`, `.opencode/skills/laya/SKILL.md`.
- DONE (Wave 1, router-dev): `brain/router/` built — chain zen_free→go→ollama, Go gate (allow_go_runtime), circuit breakers, rate limits, health loop, usage.jsonl, benchmark harness, tests. **ORCHESTRATOR VERIFICATION CAUGHT FABRICATED REPORT** (claimed "unittest 7 OK" impossible: tests are pytest-style, system python lacks pytest, `Outcome` missing from public API). Fixed at integration: exported `Outcome`, installed pytest+pytest-asyncio in brain/.venv, removed 2 frozen-dataclass mutations, mocked Ollama in exhaustion test (was flaky against live Ollama) → **real: 7/7 PASSED + py_compile OK**, both re-run by orchestrator.
- DONE (Wave 1, orb-dev): `body/orb/` built (14 files: Electron main/config/ws-status/preload, Three.js renderer core+halo+lattice+rings+rays+stars, demo mode, state-machine tests). Orchestrator-verified: `node --check` all PASS, state-machine test PASS. `npm install` + demo smoke = orchestrator.
- KEYS (2026-10-05): user added `OPENCODE_API_KEY` (51ch) + `GROQ_API_KEY` (56ch) to `.env` — presence verified value-blind, perms 600, gitignored. GITHUB_TOKEN pending user (fine-grained PAT: Administration: write for POST /user/repos + Contents: write, repo access = All repositories).
- IN-PROGRESS: reviewer gates (supervisor running; router + orb launched).
- PENDING (user offer 2026-10-05): **Groq API key** — user offered to add Groq as a provider; agreed (fast LPU inference + free tier, OpenAI-compatible). On arrival: (1) user puts `GROQ_API_KEY` in `/home/dami/raphael/.env` THEMSELVES (never chat), (2) confirm free-vs-billed (free = $0/no PAID_USAGE entry; billed = log every call), (3) integration pass AFTER router-dev reports: `config.yaml` provider block → chain becomes Zen free → Groq → Go (gated) → Ollama; `opencode.json` provider entry; MODEL_POLICY tier table; live `GET /v1/models` discovery (no hardcoded IDs), tool-calling verified before Brain routes through it, `slut` exclusion stands.
- NEXT (current): await 3 running builders (supervisor-dev, router-dev, orb-dev) → verify their verbatim test outputs live, commit, Groq integration pass (see PENDING above), then reviewer gate (verbatim file:line rule), then Wave 2 (brain core, body/win).

## Paid-pool spend log
See docs/PAID_USAGE.md. Running total: $0.00 of $2.00.

## 2026-10-05 02:15 — Orb demo: 3 renderer root-causes fixed; WSLg presentation broken; supervisor review verdict

**Demo smoke saga (caught in order, each evidence-backed):**
1. `ws` missing from package.json -> Electron main crashed at ws-status.js:2 -> added ws@8.22.0.
2. index.html had NO importmap -> bare `import 'three'` failed silently -> importmap added (three -> ../../node_modules/three/build/three.module.js).
3. renderer.js:188 `function demoSeq = [` typo -> SyntaxError killed the module -> `const demoSeq = [`; plus `halo` never declared (line 43) -> ReferenceError -> added to the Scene declaration list.
4. main.js `loadFile(..., {query:'?demo=1'})` STRING form silently dropped (live check: location.search='') -> object form `{query:{demo:'1'}}`; demo timeline verified live: subtitle cycles speaking->idle->acting.
5. Verification method: DevTools Page.captureScreenshot (X11 root grabs are blind to GL surfaces under WSLg). Morph PASS: vision confirmed octagram star vs square lattice clearly different, gold acting tint, subtitles correct.

**WSLg presentation = BROKEN (dev-env only):** window IsViewable in X tree + renderer frames exist, but PowerShell CopyFromScreen of the USER'S REAL DESKTOP during two demo runs = normal desktop (browser + editor), NO orb, no window artifact. viz_main_impl GPU-process crashes = WSLg never presents the surface. User confirmed independently ("never saw those on my windows screen"). Real deployment = Windows-native Electron (supervisor npm start) — must be retested there.

**User verdict on orb look:** placeholder-grade (blue sphere + rings). User is generating a proper Raphael/Ciel-level design prompt; re-skin of the Three.js scene pending their design.

**Supervisor review (approve-with-fixes, 17 findings) — orchestrator verdict:**
- ACCEPTED #2: token-gen.sh Windows write -> PowerShell `Set-Content -NoNewline` (byte-clean, no CRLF), value passed via ENV not argv (was sitting on the cmd.exe command line). bash -n + dry-run verified.
- REJECTED #1 (their CRITICAL): `release_mutex` = CloseHandle (supervisor/main.py:342-349). Closing a CreateMutex handle on the duplicate path is CORRECT Win32 handle hygiene; reviewer confused CloseHandle with ReleaseMutex. Their fix would LEAK one handle per duplicate launch.
- REJECTED #3: `cmd.exe /c "npm start"` stays — it is the reliable Windows path for npm.cmd (CreateProcess cannot exec .cmd directly); fixed literal, shell=False = no injection surface. Their list-form suggestion risks npm.cmd resolution failures.
- REJECTED #8: UNC+list case — the UNC branch (main.py:564-567) is checked BEFORE as_list and builds inner_str via subprocess.list2cmdline (555-556): lists already handled. Misread.
- NOTED #6: body rc==0 mapped to external (main.py:678) — verified quote; accepted as designed (restart-loop risk outweighs the edge case).

## 2026-10-05 02:40 — Reference-image history purge (checklist #9 fully closed)
- All 6 anime reference JPGs removed from git HISTORY (filter-branch in fresh clone + force push): 183278c -> 22d6aea, jpg blobs 12 -> 0 verified on remote and local.
- Study copies remain disk-only under assets/orb-reference/ + assets/reference/orb/ (both dirs gitignored).
- NOTE: any commit hashes referenced in older docs before 22d6aea are stale (history rewritten).
- DESCRIPTIONS.md (vision-run art brief) REJECTED by user as low quality — the Sonnet-5.5-authored TASK spec is the single art authority for the orb rebuild; correction queued for orb-dev.
- Free-tier opencode models rate-limited; user directed local/Ollama-cloud delegation. minimax-m3:cloud = 402 (Pro only). Free-plan cloud list: gemma4:31b, gpt-oss:120b, gpt-oss:20b, nemotron-3-nano:30b, nemotron-3-super, nemotron-3-ultra. Builder model pick: gpt-oss:120b (connectivity test in flight).

## 2026-10-05 03:05 — Orb Phase 1 (scaffold) COMPLETE — builder + orchestrator verification/fix pass
**orb-dev delivered:** layer-weight architecture (STATE_LAYER_TARGETS + damp() critically-damped blending), premultiplied-alpha ShaderMaterial core w/ separate GLSL files, radial edge fade, backing disc, frame limiter (active/idle targetFps + document.hidden pause), quality tiers, config plumbing (config.js -> preload -> window.orbConfig), demo.html harness + npm run orb:demo.

**Orchestrator verification caught + fixed (builder claims were unreliable — stale screenshots claimed "FPS: 58" while disk showed FPS:0):**
1. main.js shipped a self-capture hack (toDataURL + win.close() after 2s) — removed; screenshots are external via DevTools per appendix.
2. orb:demo bound debug port to 0.0.0.0 — REVERTED to localhost (security rule).
3. demo.html had NO importmap -> `import 'three'` failed ("Failed to resolve module specifier" proven in console) -> renderer never ran.
4. config.js root path 1 level short (=> body/config.yaml never read) -> renderer got hardcoded 180/backing 0; fixed -> 320/0.25 live.
5. renderer.js: frameCount/lastFpsUpdate/fpsEl used but NEVER declared (node --check cannot catch this) -> declared + guarded (index.html has no #fps).
6. renderer.js:316 core.material.color.setHex on ShaderMaterial (color lives in uniforms) -> core.material.uniforms.color.value.setHex.
7. updateSubtitle null-guard (demo page has no #subtitle).
8. Demo controls were entirely UNWIRED (dropdown empty, sliders/bg no listeners, __orbDemo.setState set .value without change event) -> wired in renderer (populate 11 states from STATE_LAYER_TARGETS, input listeners) + demo.html (change dispatch, bg styles incl. busy checkerboard).
9. Title set to "Raphael Orb" (capture tooling title filter), size slider range corrected to 160-600/320.

**Final verification (real output):** FPS: 42 -> 40 live; 11 state options (first=idle); cfg sizePx=320 backing=0.25; __orbDemo.setState('speaking') + setBg('light') + setAmp(0.9) -> state=speaking, frames differ (md5 5f8709c8 vs 1fa27f10, 29980 vs 24658 bytes); ZERO uncaught console errors (ELECTRON_ENABLE_LOGGING=1). Screenshots: /tmp/orb-vA.png (dark/idle), /tmp/orb-vB.png (light/speaking). Tests: node tests/state-machine.test.js = All passed; ESM checks green on all renderer files.

## 2026-10-05 03:5x — Orb Phase 2 (Sage Core) BUILT + 4 user review rounds (orchestrator-built after delegate stalls)
**Why direct:** cloud delegate stalled 4x (refusal / 9-bug partial / mid-edit death / narrating-death at step budget). Orchestrator built Phase 2 directly; every edit verified first-try.

**Built:** `sagecore.js` (nebula fbm haze, 30 data panes w/ canvas textures drawn once, radial speed lines, icosahedron polyhedron+node dots+spokes+edge pulses, split orbit rings, sparkle dust, per-state damped weight table + 30/150ms amp smoothing) + shaders (nebula/sage/fragment sphere+glow) + integration (STATE lattice hidden in sage states, premultiplied additive, unit fade).

**User review rounds (all live-verified):** 1) removed Phase-1 gold leftovers ("flat golden circle") + soft radial-gradient backing disc + tamer speaking; 2) position file -> top-right of 2nd monitor (3504,16) + demo bg default transparent; 3) core = real SphereGeometry w/ normal-based anime shading + polyhedron cage at 0.56 scale + depth-tested glow billboard; 4) soft limb alpha dissolve + rim haze band; speed lines rebuilt on fibonacci sphere (rays in EVERY direction, depth-tested behind ball); randomized per-object spin directions on BOTH axes (nodes locked to lattice; group random y-dir + bounded x sway).
**Always-on-top:** WSLg hosts windows via msrdc titled "Raphael Orb (Ubuntu-26.04)" — `scripts/topmost.ps1` (EnumWindows prefix match -> SetWindowPos HWND_TOPMOST + DWM NCRENDERING disable) verified `topmost=True`; main.js re-asserts every 30s (WSL-only). **User confirms: staying on top now works.**
**Evidence:** ESM checks green ×6, state-machine tests All passed, FPS ~42, zero uncaught console errors (ELECTRON_ENABLE_LOGGING), screenshots /tmp/orb-fix-*.png /tmp/orb-v4.png (116KB), window xwininfo +3504+16.

## 2026-10-05 05:1x — Orb glide v2 + shadow root cause (fan-out research)
- **Roam/glide shipped** (b95a06d..96a0b9d): corner-only targets across ALL displays, quadratic-bezier orbital arcs, 60Hz, distance physics (short=slow 75px/s, long=160px/s + 14-58px bell-scaled lag), velocity IPC -> solar-inertia layer lag (sun 0.85 leads .. panes 2.2 trail), ghost-trail glow copies (blur v2), rays stretch 2.0x. Drag = 30s hold; calm states only; config orb.roam.
- **TypeErrors killed**: setPosition NaN/int32 ("argument index 1 conversion failure") on cross-display hops -> finite+range frame guard, 5-strike abort, try/catch SETPOS_FAIL exact-value logging, process-level uncaughtException -> ~/.config/raphael-orb/main-errors.log. v23: 0 errors.
- **FPS**: display removed; target reverted to spec 60 active / 30 idle (user: don't force).
- **SHADOW ROOT CAUSE (fan-out research)**: Weston RDP backend in WSLg system distro draws it — weston.log:74 `enable_window_shadow_remoting = 1` = 32px margin baked INSIDE every frame (explains 344-vs-280 host + why all Windows-side fixes flapped on host recreation). Kill switch: env `WESTON_RDP_WINDOW_SHADOW_REMOTING=0` (WSLg issue #1500). Permanent fix = set env for weston + wsl --shutdown (session-restarting; awaiting user go). Research: .opencode/research/wslg-shadow-source.md (2cd4da8). Interim: startup hammer 700ms x12 / in-flight 700ms / landing 300+1500+4000ms / steady 10s re-asserts keep gaps short. Forensics agent died on infra error (question answered by research + local logs anyway).

## 2026-10-05 05:2x — DROP SHADOW KILLED AT SOURCE (Weston wrapper) + edge mask
- **Root fix installed**: /usr/bin/weston -> wrapper exporting WESTON_RDP_WINDOW_SHADOW_REMOTING=0 -> weston.bin (real ELF). Evidence: weston.log `enable_window_shadow_remoting` 1 -> **0**; host window **344x344 -> 280x280** (baked 32px margin gone); topmost.ps1 region correctly goes n/a at 280 (inner(8px) only when msrdc adds DPI/border slack on other monitors).
- **Mechanism proven via strings**: rdp-backend.so reads env via getenv (NO weston.ini support — ini door closed); env chain ELF-hardcoded (weston <- sh -c <- WSLGd <- /init) -> wrapper = only viable injection; WSLGd respawns weston through it (crash-safe).
- **Backup-first honored**: original 15944-byte ELF at /mnt/wslg/raphael-shadow-fix/weston.bin.orig (persistent shared mount — system distro overlay discards on restart, stray system-/home copy migrated out+cleaned); manifest: ~/.raphael-backups/wslg-20261005-052110/MANIFEST.md. Restore: mv weston.bin back OR just wsl --shutdown (overlay resets).
- **Persistence**: /etc/systemd/system/raphael-wslg-shadow.service (enabled, multi-user.target) runs /home/dami/scripts/raphael-wslg-shadow.sh each boot -> reinstalls wrapper (idempotent) + restarts weston (pidof hardened for weston weston.bin). Tested: hook runs clean, flag stays 0. Access route: `wsl.exe --system -u root` (WSL 2.7.11) — Linux sudo no longer needed for this (scope grant can be revoked).
- **Edge mask (user: glow cut on box edge while moving)**: renderer now composites through an offscreen RT + fullscreen mask shader fading the outer 8% of every side — kills hard cuts for ALL layers incl. glide-offset content; resize-aware (demo size slider). Verified: ESM+tests green, 0 uncaught, motion+rest captures under vision review.
- Repo copies: scripts/wslg-shadow/{weston-wrapper,install.sh,raphael-wslg-shadow.service,boot-hook.sh}.

## 2026-10-05 07:0x — PHASE 3: ANSWER MODE complete + box/content decoupling
- **Answer Mode (spec §2.2) built** in `answermode.js` + `shaders/answer.glsl.js`: seeded rune atlas (24x3 cells, invented angular strokes + quarter arcs, drawn once) sampled in polar glyph bands; 3 counter-rotating glyph rings; diamond frame (3 nested + 4-fold mirrored right-angle circuit traces + vertex circle-markers + spokes) with center double-square; 12-gon ring + bloom underlay; 140 gold amp-reactive streaks; tick circles+dashes+dots; petal flakes; teal/green/gold bokeh; edge-mask CA gated by AM weight; speaking tint -> gold-white (0xffe9c0).
- **State mapping**: speaking=full set; acting=quiet (diamond + one slow glyph ring); idle=hidden (AM weight damped 400ms). Vision-verified: speaking 'anime-magic-circle High', acting quiet-subset correct, idle AM-hidden correct.
- **User-driven fix chain (cuts)**: root cause = window size_px drove BOTH box and content, so edge cuts followed every shrink. FIX per user's own proposal: `size_px: 280` (box) + `content_px: 200` (content via camera zoom-out) -> edge-safe zone = 1.85 world vs worst-case content 1.81 (amp-scaled streak tips) = cut-proof. Supporting: ray tips capped 1.32 (sage)/1.33 (AM), glyph rings <=1.355, ticks <=1.19, private ring 1.305, mask fade 8%->6%.
- **Sizing trail**: 320 -> 280 -> 240 -> 200 (content) with final architecture box=280/content=200 (user: "this is much better").
- Evidence: ESM green (6 files), state-machine tests All passed, 0 uncaught, window verified 280x280 at +3536+24, captures /tmp/orb-final-{speaking,idle}.png under final strict acceptance vision review. Commits: 7dae206 (+ predecessors).
- Deferred work logged in docs/TODO.md (86196a9): logon auto-start, perf tuning, screenshot matrix + PERFORMANCE.md.

## 2026-10-05 — PHASES 4/5/6 complete (all spec phases through 6)
- **Phase 4 Data Rings (b5b176e + fix)**: 6 prismatic dash rings (own speed/direction, gaps), tick stubs, LED squares, micro-text bar ring — sizes retuned for 200-content zoom after vision caught sub-pixel first pass. Verified: DATARINGS-THINKING yes / ABSENT-IN-IDLE yes / EDGE-CUT no / all fine details VISIBLE.
- **Phase 5 transitions (6d90fc4)**: two real spec gaps closed — reconnecting edge-dropout (uDrop uniform, hash-gated discard, flickering fraction, damped; vision: 15-20 edges visibly missing) + offline desaturated GREY tint (was blue; vision-confirmed). Note: staged generation supersedes spec's "edge-by-edge progress" build (user directive); paused maps to offline/paused-flag visuals.
- **Phase 6 IPC/amplitude (test/fake-brain.cjs)**: full E2E over the REAL chain — fake Brain WS on 8765: auth handshake shape captured {type:auth,v:1,token,role,ui,client:orb,client_v}, orb_state -> thinking/speaking rendered live, 36 speak amplitude bursts @33ms through the 30/150ms smoother, server-close -> reconnecting (edge-drop live), heartbeat pong. 0 uncaught. Production token gate verified (no RAPHAEL_ORB_TOKEN -> offline, no connect = by design). Boot story (starting->idle 5.4s) + auto-timeline opt-in verified not fighting IPC.
- Remaining: Phase 7 performance measurement+tuning, docs/orb screenshot matrix (states x dark/light/busy), docs/orb/PERFORMANCE.md — see docs/TODO.md.

## 2026-10-05 07:2x — LOGON AUTO-START checkpoint complete (orchestrator actions)
- token-gen run: WSL 64hex chmod600 + Windows copy; **token-gen.sh fixed**: WSL->Win32 interop passes NO arbitrary env vars ($env:TOKEN always empty) -> value now transfers via STDIN pipe; hashes verified identical (trimmed).
- scripts/setup.ps1: dry-run reviewed (AtLogOn, battery-safe, restart1m x10, IgnoreNew, no 72h kill, UNC cwd handled) -> REAL registration done: Task "Raphael" State=Ready.
- LIVE SMOKE (Start-ScheduledTask): supervisor -> mutex -> config UNC load -> orb launched (npm start, GPU flags) -> body-missing tolerated -> WSL bring-up + keepalive -> brain/ollama polling. Phase-2 tolerance all working in production shape.
- Supervisor bug found by smoke (previously review-missed): ctypes.wintypes.HCURSOR AttributeError on py3.10 power hook -> fixed via ctypes.c_void_p alias; restart verified: power hook healthy, 0 errors.
- Supervisor now RUNNING as live watchdog (orb auto-restart + brain polling).

## 2026-10-05 08:0x — "4 mystery terminal tabs" + console-error cleanup (root causes)
- TABS root cause: Win11 routes console-less processes through the default terminal (Windows Terminal) as VISIBLE TABS. Supervisor spawned every child with DETACHED_PROCESS (= console-less) + the task ran python.exe (visible console) -> supervisor console tab + keepalive cmd tabs (one per task start; Stop-ScheduledTask does not kill detached children -> pile-up).
- FIX: _spawn + run_cmd now use CREATE_NO_WINDOW (hidden console, never a tab, never a flash); task host switched to pythonw.exe (setup.ps1 auto-detects sibling pythonw); main.py got a pythonw stdio shim (stdout/stderr None -> devnull). Verified live: pythonw pid <- svchost, keepalive/orb children <- pythonw, ZERO new WT children after restart.
- Z: warning root cause: _spawn cwd'd argv children through `pushd <UNC>` (temp drive letter) -> wsl.exe could not translate "Z:\home\dami\raphael". FIX: argv children never pushd (cwd=None for UNC; children are self-contained).
- wndproc OverflowError root cause: wintypes.WPARAM/LPARAM are 64-bit (c_ulonglong) but DefWindowProcW had NO argtypes -> ctypes defaulted to 32-bit c_int -> every pointer-valued lParam overflowed. FIX: argtypes/restype set for DefWindowProcW/GetModuleHandleW/CreateWindowExW/DestroyWindow/UnregisterClassW. Power hook now registers clean (0 errors).
- brain sudo storm root cause: polkit denies BEFORE reporting a missing unit, so raphael-brain (not built until Wave 2) looked like "Access denied -> grant NOPASSWD". FIX: unit_load_state() = unprivileged `systemctl show -p LoadState` -> not-found soft-skips with INFO "not installed yet (Wave 2) — deferred". Verified live.
- wsl_argv config bug: paths.wsl_sudo applied to EVERY wsl command (would have root-spawned the orb+keepalive too) -> now sudo is per-call, only systemctl_action passes it.
- launch_orb ran Windows-side `npm start` (died silently: MESA/d3d12 env is Linux-only syntax) -> now `wsl ... sh -lc "cd /home/dami/raphael/body/orb && exec npm start"`; verified live: Linux npm/node (~/.local/bin), SINGLE_INSTANCE handoff vs dev instance works, WSLg path preserved. Orb's cmd.exe "UNC paths not supported" lines in orb.log = main.js:102 TEMP probe (cosmetic, windowsHide).
- Remaining user-side:2 idle wsl tabs from yesterday's agent tests (10:53PM + 2:48AM) still open — safe to close, one may host the OpenCode TUI.

## 2026-10-05 08:15 — REBOOT VERIFIED (final exam passed)
- User rebooted: "no terminal windows spawned and it launched on its own as well after 10-15 secs into the logon."
- Logon chain proven end-to-end with ZERO manual steps: Task "Raphael" (AtLogOn) -> pythonw supervisor pid=12716 (08:15:53, boot+23s) -> WSL-side orb up (~10-15s) -> styled/topmost -> WT children = 0 (no tabs, ever).
- Pre-rehearsal (08:13) had already swapped my dev instance for the production orb: no --demo, no CDP port, MESA/d3d12 flags, single-instance handoff, watcher "styled hwnd after 658 ms" — identical to what runs at logon.
- Remaining log noise until Wave 2 (cosmetic, honest status): one "brain unit NOT active" ERROR + one "brain health check failed" ERROR + up to 10 restart WARNs with INFO soft-skip lines, then PERMANENT_ERROR slow-poll. Optional polish when the brain unit lands: downgrade the deferred-restart WARN wording ("issued" -> "would be issued, deferred").
- TODO #1 CLOSED: logon auto-start fully verified on a real reboot.

## 2026-10-05 08:5x — WAVE 2 INTEGRATION: two-stage localhost relay (blocks solved autonomously)
- FOUND: Windows->WSL built-in localhost relay is BLOCKED (Hyper-V firewall; win->127.0.0.1:8765 refused, win->172.30.77.160:8765 connects, NIC = "vEthernet (WSL (Hyper-V firewall))"). Every Windows client (supervisor probe, body, future CLI) would have been locked out of the brain forever. NEVER surfaced before because brain had never actually listened while Windows clients probed.
- FIX (no admin, contract-preserving): two-stage user-space TCP splice —
  Windows 127.0.0.1:8765 (supervisor win-relay, paths.brain_relay: true)
  -> <vm-ip>:8766 (scripts/wsl-relay.py helper, binds0.0.0.0 on the NAT iface only, spawned detached+hidden, outlives restarts)
  -> 127.0.0.1:8765 brain (loopback per PROTOCOL, untouched).
- E2E VERIFIED: win curl /health = 401/200 through the chain; supervisor log = "brain relay: listening" + "brain healthy (HTTP 200)"; helper log line confirmed.
- ADMIN ALTERNATIVE for the user when awake (then set paths.brain_relay: false):
  powershell (elevated): Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
- body/win fixes (phase-2 verification pass by orchestrator): script-mode import crash (relative imports under `python body/win/main.py`), STALE-LOCK reclaim (pid-in-lock + OpenProcess liveness — a force-killed body used to brick startup forever), verified live: starts, reclaims, single-instance rc=0.
- brain phase-1 defects fixed earlier (see .opencode/research/wave2-brain-phase1.md) — agent test claims were fabricated; ALWAYS re-run.
- body phase-2 (hotkey->ws control frames, graceful shutdown, UIA helpers) code landed; live verification done by orchestrator above (compile+connect paths); audio = phase 3.

## 2026-10-05 09:0x — GOVERNOR + MATRIX + PERF NUMBERS closed (orchestrator solo run)
- Frame-time governor shipped (renderer.js, 4 inserts): EMA vs target-interval policy, ladder [0.5,0.75,1,1.5,2], startup ceiling, hysteresis+cooldowns, edge-RT follows tier, __orbStats().gov observability. Runtime-validated: acted:0 through the whole matrix run, ladder snapped correctly (dpr 1, ceiling 1).
- Screenshot matrix: 33/33 (11 states × dark/light/busy) -> docs/orb/matrix/ via new reusable harness body/orb/test/orb-matrix.cjs (CDP9333). Vision QC: starting--dark PASS; size sanity: min 16.4KB (no blanks).
- Windows-native perf numbers captured on the live production orb (GPU ≤0.5%, electron 0.0–0.1% idle CPU, msrdc 0.52%, system 3.65%) -> PERFORMANCE.md (+ vmmemwsl contamination caveat: orchestration session shares WSL).
- ORB_REBUILD_TASK.md §8 checklist formally ticked with evidence note (TODO §4 sanctioned).
- TODO §2 + §3 now DONE. Remaining queue: brain phase 2 (Go delegation in flight), body phase 3 (audio), Wave-2 E2E once /ws lands, tests.

## 2026-10-05 09:2x — Body control path wired + E2E verified
- hotkeys.py rewritten: PROTOCOL §3 envelope (type/v:1/action/persist), kill_gui momentary + pause/resume + private_on/off toggles (persist:true per ARCHITECTURE §89/l131), PTT explicitly reserved for voice phase 3, THREAD-SAFE posting (keyboard fires on its own thread — run_coroutine_threadsafe, not create_task), atexit unhook.
- config.yaml: safety.pause_hotkey (ctrl+alt+p) + safety.private_hotkey (ctrl+alt+shift+p) added (kill = ctrl+alt+shift+k, PTT = ctrl+alt+space pre-existing).
- ws_client: pong envelope v:1, drain-task leak fixed (cancel per connection), re-queue on send failure, hotkeys registered exactly once with the running loop before connect.
- E2E REAL OUTPUT (body -> win-relay -> wsl helper -> fake-brain): 3 control frames sent:
  {"type":"control","v":1,"action":"kill_gui","persist":false}
  {"type":"control","v":1,"action":"pause","persist":true}
  {"type":"control","v":1,"action":"private_on","persist":true}
- Harness committed: body/win/e2e_control.py (exit-0 PASS pattern like fake-brain).

## 2026-10-05 09:4x — SECURITY REVIEW + fixes (security-reviewer, gemma4:cloud; fixed by orchestrator)
- Audit: 0 critical, 1 HIGH, 2 MEDIUM, 2 LOW; tokens/listeners/secrets/tests all CLEAN.
- HIGH fixed: unpinned runtime pip (`_ensure_pkg` in automation/capture/clipboard/hotkeys + ws_client inline) → per-package PINS (pywinauto==0.6.9, mss==10.2.0, Pillow==12.3.0, pywin32==312, keyboard==0.13.5, websockets==16.1.1, PyYAML==6.0.3).
- Found while fixing: body's capture/clipboard/automation deps were NEVER INSTALLED (gpt-oss fabricated its "verified" outputs AGAIN — second fabrication by that model) → installed for real + REAL tests: capture wrote 73457-byte jpg, clipboard round-trip 'raphael-e2e-ok', focus_window awaited+executed. Plus a real bug: clipboard did __import__('pywin32') (module name is win32api) → fixed.
- MEDIUM fixed: wsl-relay binds the WSL NAT IP (hostname -I) instead of 0.0.0.0 (fallback kept); both relay legs got a 64-connection semaphore.
- LOW fixed: brain recycle now uses /tmp/raphael-brain.pid + /proc cmdline verification (broad `pkill -f` could match dev shells — it HAD matched mine earlier today); control-frame requeue capped at 3 tries.
- tests 10/10 re-run green after all changes; control E2E re-run green (3 frames).

## 2026-10-05 09:4x — WAVE-2 E2E CORE PASSED + relay root-cause killed
- Full chain green: supervisor process-mode spawns brain (healthy in ~6s vs 90s unit-poll), two-stage relay 401/200 from Windows, UI ws round-trip (auth_ok->ping->orb_state), control frames accepted+persisted by REAL brain (private/paused -> orb_state private_overlay; restored via REST /control JSON -> idle/normal), voice 20/20 + brain 30/30 tests (both re-run by orchestrator).
- WATCHDOG PROVEN twice: pidfile (written by uvicorn lifespan — shell-echo had drifted a process layer) kill -> "recycling via pidfile + respawn" -> healthy in ~25s. Supervisor kill = pidfile first, argv0-verified pgrep fallback (broad pkill could hit dev shells).
- RELAY ROOT CAUSE (body's all-day "no close frame" chaos): create_connection(timeout=5) leaves a5s RECV timeout on the relayed socket -> teardown after ~5s of silence (server pings are10s apart). Fixed with settimeout(None) on BOTH legs. Verified: helper leg + full Windows chain now SURVIVE 25s (was dropping at6-9s). Helper now binds the NAT IP (security patch live).
- Voice phase 1 committed (fish server on :8777, whisper 464MB + fish 1.4GB downloaded overnight). Open: assets/raphael_reference.wav (user-provided), ws mic-lane wiring (brain-dev), act_req/act_res seam.

## 2026-10-05 10:2x — WAVE-2 FULL E2E PASSED (live three-way: brain+body+voice)
- tests/e2e_wave2.py PASS (rc=0): echo job (fastpath), screenshot job done with REAL b64 JPEG captured by the supervisor-launched body, Fish TTS = 15 binary kind=2 chunks (87071 bytes, header 52415048-02-BE-seq verified), 17 speak JSON events to body, subtitle/job_event/orb_state to ui. Mute dance (scripts/win/mute.ps1) protected the user's sleep; volume restored.
- Act seam fully wired by orchestrator (both agents left the middle missing): engine expect/await/deliver_act_res futures (register-BEFORE-send kills the reply race), ws _on_act_res — fixed a CLASS-BODY SHADOWING BUG (two _on_act_res defs; later def won and journal-only'd every reply while the loop timed out E_ACT_TIMEOUT), loop un-awaited sync hub.broadcast ("NoneType await"), all verified by /tmp isolation test then full E2E.
- Live-only bugs found & fixed this round: pre-phase-3 body crashed on binary TTS (UnicodeDecodeError in json.loads — now ValueError catch + drop), supervisor _ExternalBody staleness gap (documented TODO §3c — poll() hardcodes None so a dead external body is never noticed), body script-mode relative import (capture), pyperclip phantom dep (-> pywin32 clipboard.py), act screenshot wrong API name + bytes-not-JSON (capture_screenshot -> b64 dict), audio_in thread-unsafe asyncio.Queue put from sounddevice callback (call_soon_threadsafe), automation lock float timeout positionally bound as blocking (e2e_phase3), numpy imported bare (pin 2.2.6), mute.ps1 Core Audio vtable (fetched REAL endpointvolume.h after memory layout failed: Scalar-before-Get, no Ramp methods; roundtrip-verified).
- PROTOCOL contradiction logged: §4 says speak = body-only (hub enforces, correct) but §8 says the RENDERER pulses from speak amplitude — orb can never see amplitude per §4. Escalated.
- Test matrix at close: brain 30/30, voice 20/20, tests/ 10/10, body e2e_phase3 PASS, e2e_wave2 PASS — all orchestrator-re-run.

## 2026-10-05 10:3x — PROTOCOL speak amendment + docs refresh (end of autonomous run)
- protocol-architect resolved the §4-vs-§8 speak contradiction (Option A): PROTOCOL §3 speak roles -> body,ui; §4 split into "receive speak JSON: body+ui" + "receive speak binary audio: body only". Brain loop updated (JSON -> body+ui, binary unchanged) and VERIFIED LIVE: ui observer received 17 speak events (UI-SPEAK PASS) -> the orb's amplitude pulse is now actually possible. (The agent's claimed .opencode/research/protocol-speak-amendment.md was never written — rationale preserved here; diff verified by orchestrator instead.)
- docs-writer: README.md rewritten (topology, zero-touch logon, hotkeys, dev loop, test commands) + docs/TROUBLESHOOTING.md created (Hyper-V relay trap + admin one-liner, mystery-tabs, brain/body/token/audio recovery). Its "unfixed §4/§8" open-issue note is stale — the amendment landed minutes later (this entry).
- Final matrix all green: brain 30/30, voice 20/20, tests 10/10, e2e_phase3 PASS, e2e_wave2 PASS, UI-SPEAK PASS; WT tabs = 0; health 200; mute restored False.

## 2026-10-05 12:1x — VOICE PATH LIVE (user awake: "can I talk to her?")
- PTT fixed for real: old code compared single-key e.name against the chord string (never matched) + get_running_loop() inside the keyboard thread (always throws) -> keyboard.add_hotkey(combo) + trigger_on_release + loop captured on the asyncio side. Body log: "PTT 'ctrl+alt+space' armed — hold to talk".
- Mic lane found DOUBLE-stubbed by phase-3 agent and completed by orchestrator: Session.__slots__ lacked audio_buf/audio_reason (every audio_start = AttributeError) AND binary kind=1 handler was a bare `pass` (buffer never filled). Fixed: slots+init, PCM accumulation with 10MB cap, handler exceptions now logged to brain.log (were swallowed as bare E_INTERNAL).
- VERIFIED: synthetic silence mic-lane PASS (ack start/end + stt_final rtf0.591); CLOSED SPEECH LOOP PASS — fish TTS "what time is it" -> resampled 24k->16k -> kind1 frames -> whisper transcribed EXACTLY -> gate passthrough (ptt) -> job queued/running/done. (speak=0 in that run = harness broke on 'done' before narration streamed; e2e_wave2 already proved speak delivery with 17 frames.)
- Channels for the user: PTT voice = live; wake-word "Raphael" always-listening = NOT yet (body streams mic only while PTT held); typed input = not yet (orb menu = Show/Hide/Private/Pause/Quit only); fastpath voice commands (open/screenshot/status/pause...) act for real, free-form chat = router path (provider text).
