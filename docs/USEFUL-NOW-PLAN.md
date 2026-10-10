# USEFUL-NOW PLAN — Raphael upgrade plan + paste-ready lane prompts

Date: 2026-10-09 (written read-only against `main`; nothing in the repo was changed).
Audience: the integrator opencode session, which dispatches lanes. Each prompt is self-contained.
Framing: she is Raphael doing everything for Rimuru — in code, on the owner's laptop first, a home server later.

**Owner pre-approvals (treat as APPROVED; the integrator does not re-ask):**
1. Lift the cloud-only and no-latency-work rules (`docs/WAVES.md` global constraints, `docs/AGENT_RULES.md` cloud-only mandate + "no performance/latency optimization") for local Kokoro TTS and local faster-whisper STT on the laptop, within RAM rule 14.
2. The Japanese clone voice becomes an optional tier (`voice.tts_engine: fish`); Kokoro is the default voice.
3. Confirm cards are allowed — in the chat UI and on the orb (orb only while in the confirm state; the no-text rule holds otherwise).

---

## 1. Summary

The repo is solid scaffolding: a hardened job engine, a real confirm gate, Core Guard, scanners, CI on two OSes, a tool registry with 19 pc tools, memory/FTS, MCP client, schedule, web, computer-use. Wave 5H closed green (`wave-5h-gate`). What she lacks is the feeling of a partner who is *with* the owner right now:

1. **She cannot continue what she just did.** `launch_url` / `search_youtube` (`brain/tools/pc/launch.py`, `body/win/act_launch.py`) hand a URL to the default browser via `backend.open_url`. "Open YouTube" then "search pewdiepie" opens a second tab. There is no world-state model and no in-page control.
2. **Her voice is slow.** Fish-Speech: 2.5–9.8 s to first audio for a fresh sentence (`docs/voice/TTS-DECISION.md`), 2.88 GB VRAM; plus `agent.speak_batch_sentences: 2` / `speak_batch_wait_s: 1.5` in `config.d/brain-core.yaml` holds the first sentence up to 1.5 s.
3. **Her loop blocks.** A multi-step task runs inside the conversational job; background jobs speak into the same voice pipeline; GUI lock waits occupy one of 8 workers (design review #4).
4. **Her mind is thin.** `loop.persona_system_prompt()` builds a generic prompt from `voice_personality`; it ignores `persona.tiers`, and tells the model "the UI shows your full reply as text" — false since the orb went text-free (orb lane Amendment 3). Personal memory categories are always stripped from prompts (`loop._external_context`). History is an in-process list lost on restart.
5. **The safety layer has two doc-vs-code lies** (design review #1–2) that must be fixed before email/accounts.
6. **There is no place to see her.** The orb is text-free by design and the CLI prints JSON-ish lines. A local web chat (P1) becomes the screen for conversation, tasks and confirm cards.

This plan fixes those in order, keeps every existing gate, and moves toward a private, fully local deployment on a mini-PC without rewrites.

**Owner decisions:** the three big ones are pre-approved above. The integrator asks the remaining short list once, at minute one, and proceeds on the recommended defaults (section 4, minute 0).

---

## 2. Phases

Rationale is one line each. "Demo" = the daily-use check the integrator runs on the live stack (with the owner's go) to call a phase done. Tests alone do not close a phase.

### P0 — Foundations and safety (must land first)

| # | Item | Why | Lane |
|---|---|---|---|
| P0.1 | Wire `safety.confirm_policy` (config.yaml:118-136) into `brain/confirm.py` (design review #1) | Dead safety config is a trap for every future edit | brain-core (+integrator Core Guard approval) |
| P0.2 | Reconcile `default: confirm` vs `classify()` default-allow (review #2): tool calls with no policy class fail closed to confirm; tools carry an explicit class via registry `confirm=` metadata; plain chat with no tool needs nothing | Email/account tools must never slip through a deny-list gap | brain-core, pc-control, tools-memory (class tags) |
| P0.3 | New high-risk classes `send_email`, `account_login`, `enter_password`, `purchase`, `delete_files` require **typed or on-screen click** confirm with the action + target visible; voice yes stays rejected (already enforced in `Confirmer.resolve_ex`) | Open-mic injection; owner must see what she approves | brain-core, orb, infra |
| P0.4 | Confirm card on the orb (confirm state only, pre-approved) + `raphael confirm <job> yes|no` CLI; the chat UI (P1) shows the same card | Today the orb receives `needs_confirm` (`ws-status.js`) but shows no text, and the CLI has no confirm verb; high-risk actions can only be approved by a blind click or time out | orb, infra |
| P0.5 | `scripts/wsl-relay.py` accept-loop guard (review #3) + supervisor health probe of the helper | Same zombie-listener class that already bit once | infra |
| P0.6 | Input-lock acquired at admission, not inside a worker (review #4; `brain/loop.py:598-599`, `brain/jobs/engine.py`) | Prerequisite for background workers | brain-core |
| P0.7 | `foreground_unknown` surfaced as its own Notice + `/status` field, still fail-closed (review #5) | "Offline" vs "can't verify window" must be distinguishable | brain-core, router |
| P0.8 | End-to-end latency: add `audio_end → tts_first_audio` and `command → tts_first_audio` to `brain/latency.py` (stages already exist: stt/routing/llm_first_token/tool_start/tts_first_audio) + `raphael latency` CLI report | Judge P1 voice work with numbers | brain-core, infra |

Demo: ask "delete the file notes.txt" by voice → she asks, voice "yes" is refused, the orb shows the card, a click approves. `raphael latency` prints p50/p95 per stage.

### P1 — Live, stateful PC control (headline)

- **Her own browser profile driven over CDP.** A dedicated Chrome/Edge profile launched by the Body with `--remote-debugging-port` bound to 127.0.0.1 and `--user-data-dir` under her data dir. Driver lives **in the Body** (Windows side, where the browser runs; WSL cannot reliably reach Windows localhost through the Hyper-V firewall). Default implementation: raw CDP over the already hash-pinned `websockets` dependency (`body/win/requirements.txt`) — no new heavy dependency, lowest RAM. Playwright `connect_over_cdp` only if raw CDP fails twice (then add hash pins per SEC-9).
- **Act in the current tab.** New body actions: `browser{op: status|tabs|activate|navigate|back|forward|reload|find|click|type|press|scroll|read}`. `navigate` reuses the active tab. `search_youtube` and `launch_url` route through the browser worker when it is up (same tab if the active tab is the same site; new tab only when asked), falling back to `open_url`.
- **Read pages as text.** `read` returns `Accessibility.getFullAXTree` / DOM text, capped and wrapped untrusted — no screenshot, no cloud vision for web pages.
- **Desktop apps:** existing `uia{op: find|click|type|read|tree}` (`body/win/act_uia.py`) acts inside the focused app; `computer_use` vision stays the fallback for apps with no UIA tree.
- **World state.** A small model in the brain: focused app/window (already pushed by `body/win/foreground.py`), active tab {url, title, site}, last action {tool, args, result, ts}, last search box used. Follow-ups ("now search X", "scroll down", "go back", "open the second result") resolve against it in the fast path before the LLM.
- **Safety:** typing into a field where `focused_is_password` is true is refused (never type passwords); form submits on non-allowlisted sites = `gui_submission` class (confirm); `privacy.blocklist_apps` and `computer_use.sensitive_title_patterns` gate reads.

Acceptance: "open YouTube" then "search pewdiepie" → one tab, results for pewdiepie in it; "scroll down", "go back", "open the first video" all act in that tab. Works by voice and by `raphael say`.

### P1 — Non-blocking brain with background workers (owner requirement)

Her conversational loop never waits on long work. Anything longer than a few seconds (multi-step computer use, research, email triage, file work) becomes a **task** handed to a worker with its own id; she acknowledges at once, keeps talking, accepts new requests, and answers status/cancel/redirect.

Build on what exists — `brain/jobs/engine.py` already has persisted jobs, priorities (`user_facing|normal|background`), per-job cancel, job events, `parent` links and an unused `submit_fanout()` seam:

- **Task = job with `kind: task`** (new kind) and a structured packet `{goal, specialist, inputs, budget, deadline, allow_tools}`; the conversational turn that created it ends immediately with a one-sentence ack.
- **Concurrency:** `workers.max_background` (default 2 on the laptop, RAM rule 14); `jobs.max_concurrent` stays the global cap; exactly **one** task may hold the input lock (mouse/keyboard/foreground) — acquired at admission (P0.6); all others must be non-GUI. A GUI task queued behind another waits in `waiting_lock` status outside a worker slot.
- **Progress events** (`job_event` with `stage`, `progress`, short `note`) feed the orb's existing job dots and a new fast-path intent: "how's that task going?", "what are you working on?", "cancel the email task", "change it to only last week" (redirect = cancel + resubmit with amended packet, same parent).
- **Surfacing policy:** workers never speak. They emit results; the brain decides: spoken one-sentence summary at the next idle moment (never mid-sentence, never while the owner is talking — reuse the `speaking`/`listening` state in `brain/orbstate.py`), or a Notice if it is minor. Full detail goes to the report store (`brain/memory/reports.py`) and is readable via CLI.
- **Watchdog:** per-task heartbeat; no progress event for `workers.stall_s` (default 90 s) → mark `stalled`, notify, offer cancel; hard deadline → cancel. The same pattern covers the dev conductor SPOF (review #8) on the integrator/infra side.
- **Persistence:** tasks are rows already; add a checkpoint column (last completed step + packet). On brain restart they surface as `interrupted` with checkpoint, and she says so. **Resume is explicit** ("resume the research task") — PROTOCOL §5 forbids auto-resume; keep that law unless the owner amends it.
- **Boundary for later relocation:** a worker talks to the brain only through the packet + event interface (in-process asyncio first, then a local process over the existing WS protocol with a new `worker` role, then a remote host/VM). No worker imports brain internals beyond the tool registry and router facade.

Acceptance: start a 60-second background task (e.g. "research the best budget mini-PC for a home server"); while it runs, ask "what time is it in Tokyo?" and get an answer at normal latency; then "how's that task going?" returns a real stage/progress from the job row; "cancel it" cancels it.

### P1 — Fast, private voice

- **TTS:** add a pluggable synthesizer interface in `brain/voice/tts.py` (today `TTSEngine` is hard-wired to `FishSpeechServer`). Add **Kokoro-82M** (Apache-2.0, local, CPU-capable, ~0.3–0.5 GB RAM — verify locally) as the default engine with a calm female English preset; stream sentence by sentence. Keep Fish as `voice.tts_engine: fish` (voice-clone tier); GPT-SoVITS optional later. Engine choice is config; phrase cache stays namespaced per engine+voice.
- **Speak sooner:** set `speak_batch_sentences: 1`, `speak_batch_wait_s: 0` once Kokoro is live (Fish needed the batching; Kokoro does not). Speak the first sentence as soon as it completes.
- **STT:** local faster-whisper (`small` or `base`, GPU, int8_float16) becomes the privacy default; Groq Whisper is the optional fallback. Requires letting `voice.stt_engine: local` run outside profile `local` (today `SttEngine.local` refuses under `cloud_temp`).
- **Laya** (TODO §5): not wired, 1.7–2.5 GB VRAM. Do **not** load it on the laptop. Park it for the server.
- **Target:** command → first audio p50 ≤ 2.5 s for a fresh LLM answer; fast-path acks ≤ 0.5 s.
- Heavy local models (LLMs, Laya, big Whisper) go to the future server, not the laptop.

Acceptance: `raphael latency` shows p50 ask→first-audio ≤ 2.5 s over 20 mixed turns; Fish removed from the default bring-up frees ~2.9 GB VRAM; no audio gaps > 350 ms (`brain/voice/scripts/p0_gap_probe.py`).

### P1 — Raphael Chat (local web chat UI)

**What "Odysseus" is (verified 2026-10-10):** a self-hosted AI workspace — chat + agents, deep research, documents, email (IMAP/SMTP), notes/tasks/calendar (CalDAV), model "Cookbook", MCP, memory, themes, 2FA. Public on GitHub at `odysseus-dev/odysseus` (first published under PewDiePie's account on 2026-05-31, moved to the `odysseus-dev` org in July 2026; old links redirect). License: **AGPL-3.0** (GitHub API; started MIT, changed to AGPL in launch week per a third-party history page). Stack: Python FastAPI backend (`app.py`, `routes/`, `services/`, its own `src/agent_loop`), vanilla-JS front end (`static/index.html`, `app.js`), Docker Compose, UI bound to 127.0.0.1 by default. Sources: github.com/odysseus-dev/odysseus (README, docs/setup.md), api.github.com/repos/odysseus-dev/odysseus, odysseusai.dev/odysseus-ai-github.

**Decision: build a lean custom chat ("Raphael Chat") served by the brain; borrow Odysseus's UX ideas, not its code.** Why:
- AGPL is copyleft, not permissive. Fine for private use, but copying its code into this repo makes the result AGPL whenever it is distributed or served to others; the repo has no LICENSE file today, so that would be a licensing decision the owner has not made.
- Odysseus is a whole second assistant: its own agent loop, LLM calls, memory, email and shell tool. Wiring it to Raphael means ripping those out so persona, memory, tools and confirm gates stay in the brain — more work than a focused client, and a second "admin console" with shell access on a RAM-tight laptop.
- Alternatives checked: Open WebUI (custom BSD-3-style license with a branding clause; it expects an OpenAI-compatible model endpoint) and LibreChat (MIT, but Node + MongoDB + Meilisearch — too heavy for ~4.5 GB free RAM). Both assume they talk to an LLM; neither renders Raphael's job events, background tasks or `needs_confirm` without deep changes.
- If the owner later wants Odysseus itself, run it unmodified as a separate app and point its MCP or OpenAI-compatible slot at Raphael — never vendor its code here.

**Requirements:**
- Served locally: static files under `web/chat/` mounted by `brain/app.py` at `/chat` (same origin as `/ws`, no new server); reachable from the laptop now (loopback through the existing relay) and from the mini-PC over LAN later (same TLS + token rule as the brain).
- Talks to the brain ONLY via the existing protocol: WS `/ws` with a new `chat` role (same caps as `ui` for command/confirm_resp/control/cancel; never `act_res`/audio), `command{source:'text'}` for messages. No direct LLM calls, so persona, memory, tools, privacy and confirm gates all apply.
- Streaming replies (sentence/token frames already emitted by the loop), markdown rendering, copy button.
- History: last N turns from `conversation_turns` (new read-only `GET /history?limit=` in brain-core) plus the live session.
- Tasks panel: background tasks with stage/progress, cancel, "redirect" (opens a prefilled message).
- Confirm cards: action, target, risk, detail, Approve/Deny (`confirm_resp` from the `chat` role = channel `click`). This satisfies the confirm-card need; the orb card stays as the at-a-glance mirror.
- Voice toggle: "speak replies" on/off for chat-originated turns (per-command `speak:false` flag) + push-to-talk button that sends `control` to the body's existing PTT path (no browser audio capture in P1).
- Raphael/Ciel theming from the orb palette (`body/orb/src/renderer/palette.js`; the ciel-gold request exists); tier switch changes theme.
- Mobile-friendly: single column under 640 px, large tap targets, works in a phone browser on the LAN later.
- Auth: token typed once and stored in sessionStorage; never in the URL (qa request `ws-query-token` precedent); no third-party CDNs (vendor small libs, pinned).

**Lane:** orb, upgraded to the "UI lane" for this sprint. Reasons: it already owns the only front-end code, the palette/theme system, the confirm-state work and a CDP test harness; it was going to be in burst mode anyway; a new lane would add another session to a thin budget. brain-core does the server half (static mount, `chat` role, `/history`, `speak` flag). Ownership grant needed: `web/chat/**` → orb.

Acceptance: open `http://127.0.0.1:8765/chat`, enter the token, type "open YouTube" then "search pewdiepie" (same tab), see streamed replies, reload and see history, start a background task and watch progress, cancel it, trigger a high-risk action and approve it from the card; layout passes at 390 px width; zero direct LLM calls from the page (network log shows only `/chat` assets and `/ws`).

### P1 — Typed input (mostly done — finish it)

Already shipped: orb double-click text box sends `command{source:'orb'}` (orb lane W2.3) and `raphael say <text>` posts `/jobs` with `source:text` (`scripts/raphael_cli.py`). Missing: `raphael confirm`, `raphael tasks` (list/status/cancel background tasks), and an interactive `raphael chat` loop that prints her replies (the orb shows no text). TODO §3e is stale — integrator should update it.

### P2 — Mind and memory

- **Model routing:** opencode Go as the primary conversation model. Select the existing `profiles.cloud` preset (`chain: [go, zen_free, groq]`) rather than inventing a new one. Free models for background chores (consolidation, summaries). Add a runtime chat daily spend cap (router; today only vision has one) because Go overflow bills the same thin credit.
- **Personal data:** replace the blanket strip in `loop._external_context` with a provider-aware decision: personal categories are included only when the provider that will answer is in a `providers.personal_ok` list (Go / local), never for `zen_free`. Redaction (`brain/router/privacy.py`) stays on for everything.
- **Private Mode:** today = fast path only (no LLM). Add optional `private_mode.local_llm` (Ollama endpoint, small model) — off on the laptop by default, on once the server exists. She answers instead of going silent.
- **Memory that learns:** model-callable `remember` / `recall` / `forget` tools (forget = `delete_files`-class confirm), persistent conversation history (reload last N turns from `conversation_turns` at boot), and an idle/nightly **memory curator** that extracts facts, preferences, projects, people, commitments from `conversation_turns` into `memories` (local SQLite, owner-scoped, deduped, confidence-scored, source='observed').
- **Persona:** author `docs/evolution/persona/tier-great-sage.md`, `tier-raphael.md`, `tier-ciel.md` (they were never created — Wave 5P P1 is unchecked) from `docs/research/persona/00-CONSOLIDATED-BRIEF.md`; wire them in `persona_system_prompt()`; fix the false "UI shows your text" line; fix the effective tier (config.d/evolution-persona.yaml `tier: great_sage` silently overrides config.yaml `tier: raphael`). One solid prompt: calm, precise, devoted; addresses the owner per tier; states uncertainty plainly; pushes back on unsafe or self-defeating requests; reports every autonomous action; never claims a success she did not observe.

Acceptance: "remember that my sister's birthday is 3 March" → next day "when is my sister's birthday?" answers from memory with Go, and refuses to send it to a free model (test). Restart the brain → she still knows the last conversation topic.

### P2 — Life integrations via MCP

MCP client exists (`brain/tools/mcp/`, stdio only, allow-list fail-closed, results untrusted, children get a minimal env) but `mcp.servers: []`. Use existing open-source MCP servers instead of hand-building: an Obsidian/markdown vault server (or the filesystem server scoped to the vault), Google Calendar, Gmail or a generic IMAP/SMTP server. Rules:

- Server definitions with personal paths/accounts go in a **gitignored** overlay `config.d/zz-local.yaml` (loads last; integrator adds it to `.gitignore`), never in tracked `config.d/tools-memory.yaml`.
- Read tools may be `auto`; every outbound tool (send, reply, create event with invitees, delete, archive-all) maps to a high-risk class → typed/click confirm with the draft visible.
- Accounts: OAuth where offered (tokens in her data dir, 0600, never in git); otherwise her logged-in browser profile; passwords only via the owner's password manager autofill. Raphael never stores or types raw passwords. `privacy.blocklist_apps` stays (password managers, banking).
- Finances: read-only, ever. No purchase tools in this plan.

### P2/P3 — Agent fleet ("her skills")

Raphael is the single conductor the owner talks to. Specialists are her skills (in-universe, like Raphael's sub-skills); she speaks for them, they never talk to the owner directly. Each specialist has: a tool allowlist, a permission class ceiling, a model choice per `docs/MODEL_POLICY.md` / router roles, a task packet in and a result packet out, progress events, a budget cap (tokens, wall time, spend), and **no direct outbound action** — anything in a high-risk class returns a proposed action that goes through her confirm gate.

Build on existing runtime pieces (review in section 6): the job engine + `submit_fanout`, `computer_use` runner, Analysis kind (read-only tool filter), web tools, schedule, memory, MCP adapter, reports cache.

| Skill | Wraps (existing) | Allowed | Never |
|---|---|---|---|
| Browser/computer | P1 browser worker, `uia`, `computer_use` runner | navigate, read, click, type in non-password fields | submit forms on new sites, login, purchase (proposes instead) |
| Research | `web_search`, `web_fetch`, `web_summarize`, Analysis read-only filter | read-only web + memory recall | any write outside reports |
| Life manager (email, calendar, accounts, reminders, errands, finances read-only) | MCP mail/calendar servers, `schedule` tools, browser skill for account pages | read, triage, draft, propose events/reminders | send, accept invites, pay, change account settings without confirm |
| Tutor | vault MCP, memory, schedule | Socratic dialogue, flashcards in the vault, review schedule, learning tracker | grading claims it cannot verify |
| Coding | `opencode run` in a sandboxed worktree (the `runtime_opencode` config block exists but has no code) | edit/run tests inside its worktree | push, publish, touch Raphael's own repo or Core Guard files |
| Memory curator | `brain/memory/*`, `conversation_turns` | extract/dedupe/demote memories | export, wipe, send anything out |

Deployment path: in-process asyncio workers on the laptop → separate processes speaking the worker protocol → one container/VM per skill on the mini-PC(s). `runtime_opencode.auto_permit: true` in config.yaml must become a per-skill allowlist before the coding skill ships.

### P3 — Partner behaviour

- Morning briefing + evening check-in: schedule entries (`brain/tools/schedule`) that create a background task: calendar today, unread mail triage, reminders, tutor reviews due, unfinished tasks. Spoken in two sentences, details on request.
- Tutor mode: Socratic questioning, spaced repetition (SM-2 style) with cards as markdown in the Obsidian vault (`vault/` is already gitignored), a learning tracker of topics/strengths/gaps in memory.
- Opt-in proactive suggestions only after watch mode is reliable and AUD-06 (wake/consent) is decided by the owner.

### P3 — Server readiness (mini-PC)

Service boundaries, each with a configurable endpoint:

| Service | Today | On the server | What changes |
|---|---|---|---|
| Brain (FastAPI + jobs + memory) | WSL2, 127.0.0.1:8765 | server, LAN bind behind TLS + token | `RAPHAEL_BIND`, TLS, review #10/#11 (unauthed session cap, ban pruning) done first |
| Body (mic, audio, UIA, browser worker) | Windows laptop | stays on the laptop (it is the hands) | connects to `brain.url` over LAN instead of the relay |
| Orb | Windows | stays on the laptop | same |
| STT | Groq / local whisper in brain | server GPU | `voice.stt_url` (HTTP) seam |
| TTS | Fish in brain | server (Kokoro or clone tier) | `voice.tts_url` seam; audio already streams as binary WS frames |
| Local LLM / Laya | none | server (Ollama) | `local_model.ollama_url` already configurable |
| Specialists | in-process | one container/VM each | worker protocol + per-skill credentials |
| Memory DB | brain data dir | server disk, backed up | `RAPHAEL_DB_PATH`; `scripts/backup-raphael.sh` exists |

Second mini-PC: run specialists + heavy models there; brain stays on the first. Nothing in P1–P2 may hard-code 127.0.0.1 for a service-to-service call except the existing loopback-only defaults.

---

## 3. Lane mapping (real lane names) and what pauses

Real lanes (docs/lanes/, docs/OWNERSHIP.md): router, brain-core, pc-control, voice, computer-use, orb, infra, qa-security, tools-memory, evolution-persona, plus integrator. Dev lanes are opencode sessions that BUILD her; they are not her runtime skills.

| Lane | Status in this plan | Theme |
|---|---|---|
| **pc-control** | ACTIVE (feature) | Control: CDP browser worker, world-state inputs, uia follow-ups |
| **brain-core** | ACTIVE (feature) | Mind core: confirm policy, admission lock, world state, task workers, fleet runtime, persona wiring, latency |
| **voice** | ACTIVE (feature) | Kokoro + local STT + streaming |
| **tools-memory** | ACTIVE (feature, from Wave C; P0 tagging only before) | Memory learning + curator, MCP integrations, life/tutor/research skills' tools |
| qa-security | ACTIVE (guard) | tests for every new gate, scanners, CI |
| **orb (UI lane)** | ACTIVE through P1 (confirm card, Raphael Chat, task progress), then pause | |
| infra | BURST (P0.5 relay, CLI confirm/tasks/chat/latency, startup watchdog), then pause | |
| router | BURST in P2 (provider-aware personal data, spend cap, private local LLM), else paused | |
| evolution-persona | BURST in P2 (three tier prompts + lint), then paused | |
| computer-use | PAUSED (fallback path stays as is; one small task in P1 if needed) | |

Pause all doc-only/audit work (new audits, status-doc refreshes, research notes) until P0 and P1 demos pass. Wave 5P packets are folded in: P1 tiers → P2 persona, P3 confirm policy → P0.1–P0.3, P6 memory privacy → P2 memory, rest deferred.

---

## 4. Integrator prompt

```text
ROLE: integrator for Raphael. Plan: docs/USEFUL-NOW-PLAN.md (copy of /workspace/raphael/USEFUL-NOW-PLAN.md — commit it as your first act). Rules: docs/AGENT_RULES.md, docs/OWNERSHIP.md, docs/MODEL_POLICY.md. Start NOW; do not wait for anything that is pre-approved.

OWNER PRE-APPROVALS (already given — do not re-ask): (1) lift the cloud-only and no-latency-work rules for local Kokoro + faster-whisper on the laptop within RAM rule 14; (2) the Japanese clone voice becomes an optional tier, Kokoro is default; (3) confirm cards allowed in the chat UI and on the orb (orb only in confirm state).

MINUTE 0-15 (one turn, short):
 A. Send the owner ONE message with this short list; proceed on the [default] for anything unanswered and record answers in PROGRESS.md:
   1. Chat profile: Go first (profiles.cloud) [default: yes] — and runtime chat spend cap per day [default: $0.50].
   2. Opening Wave 5U inside wave 5, folding Wave 5P [default: yes].
   3. Kokoro voice preset: pick from 3 samples when voice sends them [default: the calmest female preset].
   4. Live demos: may I start the stack for each wave's demo (one stack, stopped after) [default: ask each time].
   Owner-only reminders (no answer needed now): repo private, PAT rotation, history rewrite, branch protection, OAuth credentials for mail/calendar.
 B. Commit (one commit, your files only): docs/WAVES.md "Wave 5U — useful-now sprint (inside wave 5)" with the per-wave usable-demo checklists and the Definition of Usable (plan section 4b) + the pre-approvals replacing the conflicting global constraints; docs/AGENT_RULES.md rule 15 / standing constraints amended to match; docs/TODO.md §3e and §6 one-line pointers to the plan; .gitignore += config.d/zz-local.yaml.
 C. Dispatch Wave A to every lane that has Wave A work IN THE SAME TURN (parallel from minute one). Paused lanes get WAIT.

WORKING RULES:
 - Parallel by default: independent lanes run at once; only real dependencies (below) serialize.
 - Timebox every lane task: small = 1 lane session turn-batch (~2 h wall), medium = ~4 h, large = split before dispatch. A task that misses its timebox or fails twice → the lane posts blocked, you cut scope or re-split; never let a lane spin.
 - No new docs beyond what a task needs: status updates in docs/status/<lane>.md only; no research notes, audits or summaries during 5U unless a task names one.
 - Contracts first, fast: answer requests within one integrator turn; approve or reject, never "discuss".
 - Keep ≤ 5 feature lanes + qa active at once (RAM: lanes never run the stack; only you do, for demos).

CONTRACT WORK YOU OWN (do in Wave A, before lanes need it):
 - config.yaml safety: classes send_email, account_login, enter_password, purchase, gui_submission, delete_files + `typed_confirm` list; comment that confirm_policy is enforced once brain-core P0.1 merges. providers: personal_ok [go, ollama], chat_daily_cap_usd; private_mode.local_llm (off); runtime_opencode.auto_permit → per-skill allowlist (with brain-core).
 - Core Guard (brain/confirm.py, supervisor/**, docs/OWNERSHIP.md, ci.yml, brain/raphael-brain.service are pinned): approve request → `python3 tests/core_guard.py --update --approval <request-doc>` from a CLEAN worktree.
 - docs/PROTOCOL.md: §7 `browser` act; §3 `chat` role + `worker` role + task events; needs_confirm fields {action, target, risk, detail}; command `speak` flag.
 - docs/INTERFACES.md §d: browser CDP port column (main 9500, lanes 9500+index; 9333 is the orb's).
 - docs/OWNERSHIP.md: brain-core gets brain/worldstate.py + brain/agents/**; orb gets web/chat/**.

WAVES (each ends with a usable demo the OWNER can run from the checklist; you run it first, live, one stack):
 Wave A — P0 safety + reliability (parallel): brain-core P0.1/0.2/0.3/0.6/0.7/0.8; infra P0.5 + CLI confirm + one-command start; orb confirm card; qa gate tests; pc-control + tools-memory class tags; voice starts Kokoro interface (independent).
   Usable demo A: `raphael start` brings everything up; voice "delete notes.txt" → voice "yes" refused, card click approves; `raphael latency` prints stages.
 Wave B — P1 control, workers, voice, chat (parallel; brain-core world state/tasks start after P0.6 merges): pc-control browser worker; brain-core world state + background tasks + chat server half; voice Kokoro + local STT; orb Raphael Chat; infra `raphael tasks|chat`.
   Usable demo B: in Raphael Chat or by voice — YouTube then "search pewdiepie" in the same tab, scroll, back; a 60-second background task runs while an unrelated question is answered normally, "how's that task going?" gives real status, cancel works; set a reminder that fires; ask→first audio p50 ≤ 2.5 s.
 Wave C — P2 mind, memory, integrations: tools-memory memory tools + curator + MCP configs; router personal-data routing + spend cap + private local LLM hook; evolution-persona tier prompts; brain-core persona wiring + persistent history.
   Usable demo C: "remember X" today → recalled after a brain restart (and next day); calendar today read via MCP; an email reply draft that cannot send without a typed/card confirm; persona speaks in the chosen tier.
 Wave D — P2/P3 fleet + partner: brain-core fleet runtime; tools-memory research/life-manager/tutor tools; pc-control browser skill batch ops; brain-core + tools-memory morning briefing / evening check-in schedules; infra + voice + brain-core endpoint seams for the mini-PC.
   Usable demo D: morning briefing at the set time (calendar, inbox summary, reminders, due flashcards) in two spoken sentences + details in chat; a tutor session with 3 flashcards graded and rescheduled; a research task run by her research skill while chatting.

DEPENDENCIES: confirm policy (P0.1/0.2) before any outbound MCP tool, browser form submit or email skill · admission lock (P0.6) before background tasks · PROTOCOL browser act before pc-control merges the worker · `chat` role + needs_confirm fields before orb merges Raphael Chat · world state consumes pc-control browser status (agree the frame first) · Kokoro merge before brain-core drops speak batching · fleet runtime before any specialist ships.

MERGING: fixed order router → brain-core → pc-control → voice → computer-use → orb → infra → qa-security → tools-memory → evolution-persona. Per merge: tests/ownership_check.py; battery (pytest brain -k "not fish_real"; tests/regression tests/contract tests/security tests/resilience; tests/conformance; python3 tests/core_guard.py → Core Guard OK; python3 scripts/scan_personal.py --strict → STRICT PASS; gitleaks vs baseline); linked green branch CI id (QA-4). CI runs scan_personal advisory only — the strict run is yours until qa moves it into CI. Merge as soon as a lane is green; do not batch merges to wave end.

BUDGET (docs/MODEL_POLICY.md): you stay on opencode/mimo-v2.6-flash-free; lanes on opencode-go/mimo-v2.5; haiku only for small debugging after 2 failed cheaper attempts; flagships never. Short turns, file-based handoffs. Log paid delegations in docs/PAID_USAGE.md; below $2.00 credit paid delegation stops. Runtime chat spend is capped separately (router task).

DEV CONDUCTOR SPOF (design review #8): ensure-running guard for tools/conductor (yours) + startup hook via infra; stall alarm when active lanes post nothing for 30 min.

DONE = the Definition of Usable (plan section 4b) passes live, run by you and then by the owner. Not before. Report after each wave: demo result (pass/fail per line), credit used, next wave.
```

### 4b. Definition of Usable (final acceptance — all lines must pass live)

Run on the laptop from a cold boot, one stack, owner present:

1. `raphael start` (one command) brings up brain, body, orb, relay and TTS; `raphael status` all green within 60 s.
2. Talk ("Raphael, …") or type in Raphael Chat (`/chat`) — both get a streamed answer in her voice; ask→first audio p50 ≤ 2.5 s over 10 turns.
3. "Open YouTube" → "search pewdiepie" → results in the same tab; "scroll down", "go back" act in that tab.
4. "Remind me in 2 minutes to stretch" → reminder fires as speech + chat notice.
5. "Remember that my favourite tea is genmaicha" → after a brain restart and the next day, "what tea do I like?" answers correctly.
6. Start a background task ("research a quiet mini-PC under $300"), ask an unrelated question meanwhile (normal latency), ask "how's that task going?" (real stage), get the result surfaced without being interrupted mid-sentence; cancel another task from the chat Tasks panel.
7. Morning briefing fires at the configured time: calendar, inbox summary, reminders, due flashcards.
8. Inbox summary on request once MCP email is connected; drafting a reply works; sending it requires a typed or card confirm, and a voice "yes" is refused.
9. A delete/purchase/login attempt is always stopped at a confirm card; Private Mode on → no cloud calls (router usage log shows none).
10. Battery green on main (Core Guard OK, scan_personal --strict PASS, CI green both OSes).

## 5. Lane prompts

Common to every lane prompt (already inside each block): work only in `agent/<lane>`, own paths only, requests for others' files, config in `config.d/<lane>.yaml` (fragments cannot set safety/privacy/providers/profiles — `brain/config.py` AUTHORITY_KEYS strips them), mocks first, RAM rule 14 (smallest test, one suite, kill what you spawn), heavy suites via `gh workflow run tests-heavy.yml`, no personal identifiers in tracked files (use `<win-user>`, `<wsl-user>`, `<repo-root>`).

### 5.1 brain-core (ACTIVE)

```text
LANE: brain-core. Branch agent/brain-core. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), docs/USEFUL-NOW-PLAN.md (or the copy the integrator gives you), docs/research/design-review-2026-10-09.md, then this packet.

GOAL: make her mind safe and non-blocking: config-driven confirm policy, admission-stage input lock, world state for follow-ups, background tasks with status/cancel, and the specialist (fleet) runtime. Later: persona wiring and persistent history.

OWNED: brain/app.py, brain/loop.py, brain/fastpath.py, brain/orbstate.py, brain/notice.py, brain/llm.py, brain/jobs/**, brain/confirm.py (Core Guard pinned — needs an integrator-approved request + manifest update), brain/latency.py, brain/tests/**, config.d/brain-core.yaml. After OWNERSHIP grant: brain/worldstate.py, brain/agents/**.

TASKS — P0 (do first, in order):
1. Confirm policy (design review #1/#2): in brain/confirm.py read safety.confirm_policy {default, classes}. Decision order: registry tool meta `confirm=<class>` → class policy (auto|confirm); tool with no class → confirm (fail closed); text regex RISKY_PATTERNS stays as an additional trigger, never a loosener. HIGH risk = class in safety.confirm_actions OR typed_confirm list. Write docs/requests/brain-core__to__integrator__confirm-policy-coreguard.md first (Core Guard). Keep voice-yes rejection for high risk exactly as today.
2. needs_confirm frame gains `action`, `target`, `risk`, `detail` (≤200 chars, redacted) so orb and CLI can show what is being approved (PROTOCOL request to integrator).
3. Admission-stage input lock (review #4): acquire InputLock before a needs_lock job takes a worker slot; park waiters in a `waiting_lock` status. brain/loop.py:598-599 + brain/jobs/engine.py.
4. Foreground-unknown legibility (review #5): when the router refuses with reason foreground_unknown, emit a Notice (reason=foreground_unknown, rate-limited) and expose `/status.foreground` {state: ok|unknown|stale, age_s}. Keep fail-closed.
5. Latency: add derived metrics command→tts_first_audio and audio_end→tts_first_audio to brain/latency.py; expose in /status.latency.

TASKS — P1:
6. World state (brain/worldstate.py): focused window (from the existing foreground push), active browser tab {url, title, site, tab_id} (from pc-control's browser status events), last action {tool, args, ok, ts}, last search surface. Fast-path follow-ups in brain/fastpath.py: "search X" when active tab is a site with a search box → browser type+submit in that tab (YouTube first); "scroll down/up", "go back/forward", "open the first/second result", "read this page" → browser ops on the active tab. Falls back to today's search_youtube/launch_url when no browser worker is connected.
7. Background tasks (owner requirement): new job kind `task` with packet {goal, specialist, inputs, budget, deadline_s, allow_tools}; conversational turn acks in one sentence and ends; config workers.max_background (2), workers.stall_s (90). Only one task may hold the input lock; others are offered non-GUI tool specs only (reuse analysis.readonly_specs pattern). Progress via job_event (stage, progress, note). Workers never call voice; results go to a surfacing queue: speak a one-sentence summary only when orbstate is idle (not speaking/listening), else hold; minor results become a Notice. Persist checkpoint (last step + packet) on the job row; on boot interrupted tasks are announced and resumable only on explicit "resume" (PROTOCOL §5 unchanged). Fast-path intents: "how's that task going", "what are you working on", "cancel the <x> task", "change it to <y>" (redirect = cancel + resubmit with same parent). Watchdog: no event for stall_s → status stalled + Notice; deadline → cancel.
7b. Raphael Chat server half (timebox ~4 h): mount web/chat/ as static files at /chat in brain/app.py (same origin as /ws; no new server, no new port); add WS role `chat` (caps = ui for command/confirm_resp/control/cancel; never act_res/audio) — PROTOCOL request to integrator first; command frames accept `speak: bool` (false → no TTS for that turn, text frames still stream); read-only `GET /history?limit=50` from brain.memory.conversation.recent_turns() (redacted, token-auth like /status); task list/progress already on job_event — make sure chat clients receive them. confirm_resp from role chat = channel click.
8. Fix the stale persona line in persona_system_prompt() ("the UI shows your full reply as text" is false — orb is text-free); say details are available on request via CLI/report instead.

TASKS — P2/P3:
9. Persona wiring (Wave 5P P1): read persona.tier (env RAPHAEL_PERSONA_TIER → config) and load docs/evolution/persona/tier-<tier>.md into the system prompt; missing file → great_sage + warn Notice. Note config.d/evolution-persona.yaml currently overrides config.yaml's tier — raise with integrator.
10. Persistent history: on boot reload the last history_max_messages turns from brain.memory.conversation.recent_turns().
11. Fleet runtime (brain/agents/**): SPECIALISTS registry {name, persona_label ("her skill"), allow_tools, max_risk_class, model_role, budget{tokens, wall_s, usd}, lock_ok}. A specialist runs as a task worker with ONLY its allowlisted tool specs; any tool whose class is high-risk returns a proposed_action that the conductor turns into a normal needs_confirm on the owner's side — specialists can never resolve confirms. Worker interface = packet in / events + result out, serializable JSON, so the worker can later be a separate process (new WS role `worker`, request to integrator) or a remote VM. Coding skill: `opencode run` in a throwaway worktree under the data dir, no push, no access to the Raphael repo; replace runtime_opencode.auto_permit:true with a per-skill allowlist (integrator config request).

ACCEPTANCE / TESTS (brain/tests/**, mocks only):
- policy matrix: unclassified tool → confirm; class auto → no confirm; high class + voice yes → rejected_channel; text/click yes → ok; qa's pinned confirm tests stay green.
- lock: 8 needs_lock jobs + 1 chat job → chat completes without waiting.
- world state: open youtube → "search pewdiepie" dispatches browser navigate/type on the SAME tab id (fake body).
- background: a fake 60 s task runs; a chat turn submitted meanwhile finishes within its normal mock latency; "how's that task going" returns the job's stage/progress; cancel works; restart → task shows interrupted with checkpoint, not resumed.
- chat role: command → streamed answer frames; speak:false → no TTS call; /history returns last N turns without secrets; chat confirm_resp counts as click (high-risk approve OK, never voice).
- specialist with a send_email tool proposes; the owner-side needs_confirm is created; the specialist cannot approve it.

CONSTRAINTS: Core Guard never weakened (AGENT_RULES §8); confirm.py edit only via approved request + clean-tree manifest update; all tool/web/screen text untrusted; no personal data in tests; budget per MODEL_POLICY (mimo-v2.5 session).

REPORT BACK: coord task_done per task with test counts; docs/status/brain-core.md updated; branch CI run id; battery (Core Guard OK, scan_personal --strict PASS, gitleaks clean) before wave_done.
```

### 5.2 pc-control (ACTIVE)

```text
LANE: pc-control. Branch agent/pc-control. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), the plan, docs/lanes/pc-control.md.

GOAL: she controls the PC live and statefully. Baseline: "open YouTube" then "search pewdiepie" searches in the SAME tab.

OWNED: body/win/** except audio_*, brain/tools/pc/**, body/win/tests/**, body/win/requirements.txt.

TASKS — P0:
1. Tag every pc tool spec with a confirm class (brain/tools/pc/_spec.py `confirm=`): read-only (list_running_apps, foreground_info, screenshot, uia read/find/tree) = auto; launch_url/search_youtube/open_app/window/volume/media = auto (reversible); open_path = open_arbitrary_file (exists); powershell = system_settings_change (exists); input/uia click+type = gui_input (new class, auto unless the focused element is a password field or a submit control on a non-allowlisted site → gui_submission).

TASKS — P1 (browser worker, Body side):
2. File the PROTOCOL §7 request first: docs/requests/pc-control__to__integrator__protocol-browser-act.md (act `browser{op, ...}`; add 'browser' to PENDING_PROTO_ADDITIONS in body/win/actions.py like 'activity'/'report').
3. body/win/act_browser.py: launch (or attach to) her dedicated Chrome or Edge profile: `--user-data-dir=<data-dir>\browser-profile`, `--remote-debugging-port=<browser cdp port>` bound to 127.0.0.1 only, `--no-first-run`. Raw CDP over the pinned `websockets` package: /json/list, Target.activateTarget, Page.navigate, Runtime.evaluate (bounded, no arbitrary model-supplied JS — only fixed helper scripts), Accessibility.getFullAXTree, Input.dispatchKeyEvent/MouseEvent, DOM.scrollIntoViewIfNeeded. Ops: status, tabs, activate, navigate(url, new_tab=false), back, forward, reload, find(text|role|name), click(ref), type(ref, text, submit=false), press(key), scroll(dy), read(max_chars). Refs are AX node ids from the last read/find.
4. Push browser status to the brain after every op and on tab change (active tab id/url/title) — frame shape agreed with brain-core via request.
5. search_youtube / launch_url: when the browser worker is up, reuse the active tab if it is already YouTube (type into the search box via find role=searchbox/combobox, submit) else navigate the active tab; open_url fallback when the worker is down. Keep act_res always truthful (wave-4 failure matrix applies).
6. Safety in the Body: refuse `type` when the target is a password field (reuse winlayer.uia_flags / AX `protected`); refuse navigation to file:, javascript:, data:; obey privacy.blocklist_apps; page text returned as data only, capped.
7. uia follow-ups: ensure uia type/click target the focused window by default so "type hello" acts in the app she just opened.

TASKS — P2/P3:
8. Browser skill packet support: an op batch mode (list of ops, stop on first failure) so the browser specialist can run multi-step flows with one lock hold.

ACCEPTANCE / TESTS (FakeWin + a fake CDP server, never real input outside mocks; body/win/tests/**):
- open youtube → search pewdiepie → exactly one Page.navigate or search-box submit on the same target id; zero new targets.
- scroll/back/first-result ops hit the active target.
- type into a protected field → E_REFUSED, no key events sent.
- worker down → falls back to open_url, act_res ok.
- failure matrix rows added for `browser` (invalid args, lock busy, crash+recovery).
- live check (integrator, owner's go): the YouTube same-tab demo.

CONSTRAINTS: CDP bound to 127.0.0.1 only; profile dir under the data dir (no user paths in git); no new dependency without hash pins (SEC-9); act_powershell.py is Core Guard pinned — do not touch; RAM rule 14; mocks only in tests; MODEL_POLICY budget.

REPORT BACK: coord task_done with test counts, docs/status/pc-control.md, branch CI id, battery before wave_done.
```

### 5.3 voice (ACTIVE)

```text
LANE: voice. Branch agent/voice. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U — owner lifted the cloud-only/no-latency constraints for local STT/TTS; confirm this is recorded before starting), the plan, docs/voice/TTS-DECISION.md, brain/voice/README.md.

GOAL: fast, private voice. Ask→first audio p50 ≤ 2.5 s for fresh LLM replies; local STT by default.

OWNED: brain/voice/** (incl. tests), body/win/audio_in.py, body/win/audio_out.py, assets/acks/**, assets/*.wav + transcript sidecar, config.d/voice.yaml (create it — your lane fragment).

TASKS — P1:
1. Synthesizer interface in brain/voice/tts.py: `Synth.synthesize(text) -> pcm/wav` + `stream(text)`; FishSpeechServer becomes one implementation; TTSEngine picks via voice.tts_engine (kokoro|fish|fallback). Phrase cache namespaced by engine+voice id (keep timbre gate for fish only).
2. Kokoro-82M engine: local, CPU by default (GPU optional), calm female English preset chosen by the owner from 3 samples you render; lazy load, single instance (RAM rule: pgrep/port check before any server), 24 kHz output resampled to voice.tts_sample_rate. Pinned, hashed requirements; weights outside git (brain/voice/models is gitignored).
3. Streaming: synthesize and send sentence 1 as soon as it exists; disable pre-roll for kokoro (pre-roll existed for fish's slower-than-realtime RTF). Request brain-core set speak_batch_sentences: 1 / speak_batch_wait_s: 0 for kokoro.
4. Local STT default: allow stt_engine: local under any profile when voice.local_stt_allowed: true (new key); faster-whisper small (fallback base) on GPU int8_float16, CPU fallback; Groq stays optional fallback on local failure (SEC-3 gate unchanged: pre-STT gate fail-closed, cloud upload notice only when cloud is used).
5. Measure with brain/voice/scripts/stt_reply_latency.py and the gap probe: report RAM/VRAM before/after (fish off by default frees ~2.9 GB VRAM).
6. Keep the JP clone voice as voice.tts_engine: fish (optional tier). Do not delete fish code or references.

TASKS — P3:
7. Server seams: voice.tts_url and voice.stt_url (HTTP) so TTS/STT can run on the mini-PC; same frames to the body.

ACCEPTANCE / TESTS (brain/voice/tests/**, mocks; a real-kokoro test marked like fish_real and skipped in CI):
- engine selection matrix (kokoro/fish/fallback), missing kokoro weights → loud one-time notice + subtitle-only, never silent.
- first speak frame emitted before sentence 2 is synthesized (fake synth with delays).
- local STT path used when allowed; zero cloud calls (spy) in that mode.
- live (integrator): p50 ask→first audio ≤ 2.5 s over 20 turns; no gap > 350 ms.

CONSTRAINTS: no paid/cloud TTS; one TTS server max; RAM rule 14; SEC-3/SEC-9 tests stay green; P0 drift battery only applies to fish; no personal data in samples committed (samples stay in gitignored dirs).

REPORT BACK: coord task_done + test counts, measured numbers, docs/status/voice.md, branch CI id, battery.
```

### 5.4 tools-memory (ACTIVE)

```text
LANE: tools-memory. Branch agent/tools-memory. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), the plan, docs/lanes/tools-memory.md (Wave 3 plan sections are still the architecture).

GOAL: memory that learns, life integrations through existing MCP servers, and the tool sets for her research, life-manager, tutor and memory-curator skills.

OWNED: brain/memory/**, brain/tools/{web,files,shell,github,schedule,mcp}/**, skills/**, plugins/**, config.d/tools-memory.yaml, docs/security/pat-scope.md, docs/skills/ACQUISITION.md.

TASKS — P0:
1. Tag every tool you own with a confirm class: web_* auto; file_read/search auto; file_write files_write (auto, reversible); file_trash delete_files; shell system_command; github_* per existing risk; schedule auto; mcp wrapped tools default confirm unless config marks a read-only class.

TASKS — P2 memory:
2. Model-callable tools: remember(text, category), recall(query), forget(id|query) (forget = delete_files class → confirm). Owner-scoped, untrusted-wrapped output.
3. Memory curator (idle/nightly, background task via brain-core's task kind once merged; until then a schedule entry): read new conversation_turns since the last run, extract facts/preferences/projects/people/commitments with a free model (purpose chat, background priority) using an injection-hardened prompt, dedupe against memories (Jaccard + FTS), set source='observed' and a confidence; never store secrets (reuse redaction); demote stale observed memories. Report a short "memory report".
4. Provide brain-core a helper personal_allowed(provider_name) -> bool using providers.personal_ok (integrator adds the key) so personal categories can be included for Go/local only.

TASKS — P2 integrations (MCP):
5. Document and test configs for existing open-source MCP servers: vault (Obsidian/markdown or filesystem scoped to the vault), calendar, mail (Gmail or IMAP/SMTP). Personal server entries live in the gitignored config.d/zz-local.yaml; tracked config keeps servers: []. Add per-tool class mapping in mcp config: `classes: {tool: auto|<high class>}`; any send/reply/delete/accept/invite tool must map to a high-risk class.
6. Optional HTTP transport for MCP (streamable HTTP) behind the same allow-list, for servers hosted on the future mini-PC.

TASKS — P2/P3 skill tool sets (runtime skills = her sub-skills; brain-core owns the runtime):
7. Research skill: web_search → web_fetch → summarize pipeline as one tool `research_brief(question, depth)` writing a report via brain/memory/reports.py.
8. Life manager skill: mail triage (read, classify, draft reply text — never send), calendar read + propose_event (returns a proposal; creation needs confirm), reminders/errands via schedule tools, finances read-only (no write tools at all).
9. Tutor skill: flashcards as markdown in vault/ (one file per deck, front/back/next_due/interval/ease), SM-2 scheduling, `tutor_due()`, `tutor_grade(card, quality)`, learning tracker memories (topic, level, gaps); Socratic prompting lives in the persona/skill prompt.
10. Journal (Wave 5P P7): append-only vault/journal.md with redaction.

ACCEPTANCE / TESTS (brain/memory/tests/**, fake MCP server, no network):
- curator extracts a preference from a fake turn, dedupes on second run, never stores a key-shaped string.
- forget requires confirm; recall is owner-scoped.
- MCP send tool without a class → confirm required; with read class → auto.
- tutor: SM-2 intervals for quality 0..5 match the reference table; due list correct.
- life manager has zero tools that send/pay (test enumerates registry).

CONSTRAINTS: no raw passwords anywhere; OAuth tokens only in the data dir (0600); MCP children keep the minimal env (AUD-07); all MCP/web output untrusted; finances read-only; no personal data in tracked config or tests.

REPORT BACK: coord task_done + counts, docs/status/tools-memory.md, branch CI id, battery.
```

### 5.5 qa-security (ACTIVE — guard)

```text
LANE: qa-security. Branch agent/qa-security. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), the plan.

GOAL: every new capability lands behind a test that fails if the gate weakens.

OWNED: tests/**, .github/workflows/**, docs/reviews/**, .gitleaks.toml, .github/dependabot.yml.

TASKS:
1. Confirm policy matrix tests in tests/regression/ (unclassified tool → confirm; high-risk + voice yes → rejected; typed/click ok; policy cannot be loosened by a config.d fragment — AUTHORITY_KEYS).
2. Browser safety tripwires: password-field typing refused; javascript:/file:/data: navigation refused; CDP port bound to loopback (fake socket audit).
3. Background-task tests: chat latency unaffected by a running task (mock clock); only one lock holder; tasks never auto-resume after restart; workers cannot emit speak frames.
4. Fleet tripwire: a specialist cannot resolve a confirm and cannot call a tool outside its allowlist.
5. Personal-data routing: personal memory never in a payload to zen_free (mock router spy).
6. Move `scan_personal.py --strict` into CI (tests-heavy.yml or ci.yml) — ci.yml is Core Guard pinned: request + integrator approval + manifest update.
7. Golden transcript for the YouTube same-tab flow (tests/golden/).
8. Chat UI tripwires: role `chat` cannot send act_res/audio; chat page has no innerHTML sinks fed by frames (static grep test) and no external origins; token never appears in a URL or log.
9. Definition-of-Usable script (tests/e2e/usable_checklist.md + mock-backed checks where possible) so the integrator's final run is repeatable.

ACCEPTANCE: each test fails on a deliberately weakened build (mutation check noted in docs/reviews/); CI green both OSes.

CONSTRAINTS: mocks only; no secrets; Core Guard procedure for workflow edits.

REPORT BACK: coord test_result with counts, docs/status/qa-security.md, CI ids.
```

### 5.6 orb — UI lane (ACTIVE through P1)

Why the orb lane gets the chat UI: it owns the only front-end code, the palette/theme system and the confirm-state work, and has a CDP test harness; a new lane would cost another session on a thin budget. brain-core builds the server half.

```text
LANE: orb (UI lane for Wave 5U). Branch agent/orb. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), the plan sections "P1 — Raphael Chat" and P0.4, docs/lanes/orb.md, docs/PROTOCOL.md.

GOAL: the owner can SEE her: a local web chat (Raphael Chat) for conversation, tasks and confirm cards, plus a confirm card on the orb. Pre-approved by the owner: confirm card in chat UI and on the orb (orb card only in confirm state; no-text rule otherwise unchanged).

OWNED: body/orb/**, docs/orb/**, and after the OWNERSHIP grant web/chat/**.

TASKS (timebox each; post blocked rather than overrun):
1. [~2 h] Orb confirm card: shown ONLY while orb state is confirm; content from needs_confirm {action, target, risk, detail, job}; Approve / Deny send orb_input{kind:'confirm', value:'yes'|'no'} (existing ws.py path, channel=click); hides on resolve/timeout. ORB_TEXT_ENABLED stays false for everything else.
2. [~4 h] Raphael Chat MVP in web/chat/ (plain HTML/CSS/JS, no build step, no CDN; vendor any tiny lib pinned with its license file): token prompt (sessionStorage, never in the URL) → WS /ws role chat → message list with streamed assistant text, markdown (safe renderer, no raw HTML), copy button; input box sends command{source:'text', text, speak}; history from GET /history on load.
3. [~3 h] Tasks panel: live list from job_event (kind, stage, progress, age), Cancel (cancel frame), Redirect (prefills "change the <task> to …"); interrupted tasks shown with a Resume hint.
4. [~2 h] Confirm cards in chat: render needs_confirm inline and pinned at top until resolved; Approve/Deny → confirm_resp; show high-risk badge; never auto-approve; expire visibly on timeout.
5. [~2 h] Voice toggle ("speak replies" sets speak flag) + push-to-talk button (control frame to the existing PTT path; no browser mic in P1). Theme: Raphael/Ciel palettes from body/orb/src/renderer/palette.js (implement the ciel-gold request), switch follows persona tier from /status.
6. [~2 h] Mobile: single column < 640 px, 44 px tap targets, safe-area insets, no hover-only controls; works over LAN later with the same token + TLS.
7. [~1 h] Orb job dots reflect background task stage (no labels); orb right-click menu "Open chat" opens /chat in the default browser.

ACCEPTANCE / TESTS:
- npm run test:unit; npm run orb:trace -- --only=interaction PASS (card only in confirm state; text length back to 0 after resolve); distinctness gate unchanged.
- Chat e2e against the mock brain (extend the existing CDP/Playwright harness or a node test with a fake WS): streamed reply renders; reload shows history; fake 60 s task shows progress and cancels; needs_confirm card Approve sends confirm_resp; speak toggle sets speak:false; viewport 390×844 has no horizontal scroll.
- Network log: page loads only /chat/* and /ws — no LLM or third-party calls.
- npm audit high gate green; scan_personal --strict PASS (no personal strings in fixtures).

CONSTRAINTS: never call an LLM or the body directly — everything through /ws; treat all message text as untrusted (escape, no innerHTML from frames); mock brain only (RAM rule 14); no new docs beyond docs/status/orb.md and a short web/chat/README.md.

REPORT BACK: coord task_done per task, docs/status/orb.md, CI id, screenshots at 1280 px and 390 px. Then WAIT.
```

### 5.7 infra (BURST)

```text
LANE: infra. Branch agent/infra. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), the plan, docs/research/design-review-2026-10-09.md #3, #8, #12.

GOAL: reliability fixes and a CLI the owner can actually drive her with.

OWNED: supervisor/** (Core Guard pinned), scripts/**, brain/run.py, brain/raphael-brain.service (pinned), the raphael CLI.

TASKS:
1. scripts/wsl-relay.py: port the supervisor's accept-loop guard (transient OSError → log + continue; exit only when srv.fileno() == -1). Not Core Guard pinned.
2. Supervisor health loop probes the WSL relay helper and respawns it on failure (supervisor/** is pinned: request + integrator approval + manifest update from a clean tree). Then review #12 (helper re-resolves its bind address).
3a. [~3 h] One-command start: `raphael start` / `raphael stop` / `raphael status` wrapping the existing start path (verify locally which script the owner uses today — supervisor + scripts/setup-startup.ps1) so brain, body, orb, relay and TTS come up together; prints the chat URL. Required by the Definition of Usable line 1.
3. CLI (scripts/raphael_cli.py): `raphael confirm <job> yes|no` (WS confirm_resp as role cli → channel text), `raphael tasks [id] [--cancel]`, `raphael chat` (interactive terminal chat; `--web` opens /chat in the browser), `raphael latency` (prints /status.latency p50/p95 per stage).
4. Dev conductor watchdog hook in scripts/setup-startup.ps1 (ensure-running guard), coordinated with the integrator (tools/conductor is integrator-owned). Never re-enable the scheduled task or touch .wslconfig without telling the owner.
5. P3: document service endpoints for the mini-PC move (brain.url for body/orb, TLS + token, RAPHAEL_BIND) in scripts/NETWORK-SECURITY.md; no LAN bind by default.

ACCEPTANCE / TESTS (supervisor/tests/**, mock server): `raphael start` dry-run lists every component and exits 0; relay accept survives an injected OSError; CLI confirm sends the right frame and prints result; chat loop prints answer frames; zero orphans.

CONSTRAINTS: Core Guard procedure for pinned files; loopback defaults unchanged; RAM rule 14.

REPORT BACK: coord task_done + counts, docs/status/infra.md, CI id. Then idle.
```

### 5.8 router (BURST in P2)

```text
LANE: router. Branch agent/router. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), the plan, docs/MODEL_POLICY.md (runtime chain is config.yaml's, not the build policy).

GOAL: private-by-construction routing and a runtime spend cap.

OWNED: brain/router/**, config.d/router.yaml.

TASKS:
1. Expose which provider/model will answer before the call (router.plan(purpose) → provider) so brain-core can decide whether personal memory may be included (providers.personal_ok, integrator key).
2. Runtime chat daily cap (providers.chat_daily_cap_usd, integrator key): append-only ledger like the vision SEC-8 ledger; over cap → fall back to zen_free/local, Notice once.
3. Review #9: pre-filter the chain by capability so groq (stt-only) never appears in chat failover.
4. Private Mode local LLM: when private_mode.local_llm.enabled and an Ollama endpoint answers, route chat there (no cloud egress, foreground gate still applies); otherwise today's fast-path-only behavior.
5. foreground_unknown refusal carries reason through to brain-core's Notice (review #5).

ACCEPTANCE / TESTS (brain/router/tests/**, mocked HTTP): personal payload never sent to zen_free; cap trips and falls back; groq absent from chat chains; private mode with no Ollama = zero calls.

CONSTRAINTS: keys never logged; no hardcoded model ids; profiles/providers are integrator keys — request changes.

REPORT BACK: coord task_done, docs/status/router.md, CI id. Then idle.
```

### 5.9 evolution-persona (BURST in P2)

```text
LANE: evolution-persona. Branch agent/evolution-persona. Read docs/AGENT_RULES.md, docs/WAVES.md (Wave 5U), docs/research/persona/00-CONSOLIDATED-BRIEF.md (§7 debunk register is binding), docs/evolution/02-persona-tiers.md.

GOAL: one solid persona, in three growth tiers, that brain-core loads.

OWNED: brain/persona/**, brain/evolution/** (Core Guard pinned — do not touch in this sprint), docs/evolution/**, config.d/evolution-persona.yaml.

TASKS:
1. Write docs/evolution/persona/tier-great-sage.md, tier-raphael.md, tier-ciel.md (paths referenced by config.yaml persona.tiers; they do not exist yet). Each ≤ 400 words: voice, values, how she addresses the owner, when she pushes back, honesty about uncertainty, act-first-and-report vs confirm-first split, "my skills" framing for specialists (she speaks for them), spoken replies ≤ 2 sentences, no claim of on-screen text.
2. Lint test: none of the debunked strings in persona assets/config (Wave 5P P1 list); mutation-check it.
3. Reconcile tier source: config.d/evolution-persona.yaml `tier: great_sage` overrides config.yaml `tier: raphael`; propose the owner's chosen default to the integrator.

ACCEPTANCE: brain/persona/tests green; brain-core's loader test reads your files.

CONSTRAINTS: canon brief only; no refuted claims; no personal identifiers.

REPORT BACK: coord task_done, docs/status/evolution-persona.md, CI id. Then idle.
```

### 5.10 computer-use (PAUSED)

```text
LANE: computer-use. Status: PAUSED for Wave 5U. Reply WAIT to the conductor.
Only if the integrator assigns it in P1: make computer_use (brain/tools/computer_use/runner.py) prefer the new browser act for browser windows (DOM/AX text, no screenshot) and keep vision as the fallback for non-browser apps; tests in brain/tools/computer_use/tests with the existing harness; privacy gates unchanged (brain/vision/gate.py). Report via coord + docs/status/computer-use.md.
```

---

## 6. Existing runtime subagents vs dev lanes (review)

Dev lanes (opencode sessions that build her): the 10 lanes + integrator above, plus `.opencode/agents/*.md` dev subagents (architect-pro, body-dev, brain-dev, brain-dev-pro, docs-writer, orb-dev, protocol-architect, reviewer, router-dev, scout, security-reviewer, supervisor-dev, test-engineer, voice-dev) and the coord bus (`tools/conductor/`). They are not her runtime skills.

Runtime pieces Raphael already delegates to, and how the fleet builds on them:

| Piece | Path | What it does | Quality | Fleet use / gap |
|---|---|---|---|---|
| Job engine | `brain/jobs/engine.py`, `store.py`, `lock.py` | persisted jobs, priorities, cancel, events, interrupted-at-boot, InputLock FIFO | solid | base of tasks; needs admission lock (#4), `task` kind, checkpoints, watchdog |
| Parallel-minds fan-out | `JobEngine.submit_fanout` | N child jobs under one parent | stub seam (no production caller) | becomes specialist dispatch |
| Analysis kind | `brain/analysis.py` | read-only tool filter, background priority, privacy gates | solid | pattern for specialist tool allowlists |
| Simulation kind | `brain/simulation.py` | tools off, hypothetical plan | solid, niche | plan preview before risky tasks |
| Computer-use runner | `brain/tools/computer_use/runner.py` | UIA-first observe/act loop, step cap, per-step confirm | solid but vision-heavy | browser/computer skill fallback |
| Web tools | `brain/tools/web/` | search/fetch/summarize with SSRF guard | solid | research skill |
| Schedule | `brain/tools/schedule/` | timers/reminders/recurring, fire via engine.submit | solid | briefings, reminders, tutor reviews |
| Memory + skills | `brain/memory/*` | FTS memory, skills gate, reports, conversation turns | solid storage; no learning loop | memory curator |
| MCP adapter | `brain/tools/mcp/` | stdio client, allow-list | solid, unused (no servers), no HTTP | life manager, tutor vault |
| Runtime opencode worker | `config.yaml runtime_opencode` + ARCHITECTURE §4 | promised `opencode run` worker | not implemented (config only; auto_permit:true is unsafe) | coding skill, with allowlist |
| Evolution controller | `brain/evolution/*` | propose-mode self-patching | solid, Core-Guard-pinned, out of scope | leave alone |
| Skill acquisition | `docs/skills/ACQUISITION.md` | design only, flag off | stub | later |

Gaps vs the fleet design: no packet/result schema, no per-specialist tool allowlist or budget, workers can speak (they share the voice pipeline), no status intents, no worker process boundary.

---

## 7. Owner-only actions

1. Make the GitHub repo private. It is public and contains voice-reference wavs under `assets/`, a WSL username value in `config.yaml` (`supervisor.wsl_user`, allowlisted in the scanner as a functional key), and name-revealing paths in history.
2. Rotate/narrow the GitHub PAT (`docs/security/pat-scope.md`).
3. Decide the history rewrite (`scripts/GIT-SCRUB-PLAN.md`), needs force-push approval; enable branch protection.
4. DONE (pre-approved in this doc): lift cloud-only/no-latency rules for local Kokoro + Whisper; JP clone voice becomes an optional tier; confirm cards in the chat UI and on the orb.
5. Answer the integrator's one minute-zero question list (chat profile + spend cap, open Wave 5U, Kokoro preset, demo permission) — defaults apply if you don't.
6. Run each wave's usable-demo checklist and the final Definition of Usable (section 4b).
7. Licensing: the repo has no LICENSE file; do not vendor AGPL code (e.g. Odysseus) unless you decide the project is AGPL.
8. Decide AUD-06 (always-listening consent vs push-to-talk) before proactive features.
9. Create OAuth credentials for calendar/mail MCP servers yourself; keep them out of git.
10. Approve each Core Guard manifest update (confirm.py, supervisor/**, OWNERSHIP.md, ci.yml).

---

## 8. Corrections to the brief this plan was built from

- Typed input already exists (orb double-click text box; `raphael say`). Missing pieces are `raphael confirm`, `raphael chat`, `raphael tasks`.
- Persona tier files were never created (Wave 5P P1 unchecked), not deleted. The effective tier is `great_sage` because `config.d/evolution-persona.yaml` overrides `config.yaml`; `loop.persona_system_prompt()` ignores tiers entirely.
- Fish numbers: 13.4 s/phrase at 1.95 GB was the 2026-10-05 measurement (TODO §6); the later record (`docs/voice/TTS-DECISION.md`) is 2.5–9.8 s to first audio and 2.88 GB VRAM. A 1.5 s speak-batch wait adds to it.
- Latency instrumentation exists (`brain/latency.py`, ARCH-6); only the end-to-end metric and report are missing.
- `allow_free_models_for_personal_data: false` does not make personal memory "rarely" reach the model: the loop strips identity/contact categories from every prompt, whatever provider answers.
- The chain is `[zen_free, go, groq]`; groq is STT-only. A `cloud` profile with Go first already exists.
- CI runs `scan_personal.py` advisory (no `--strict`); strict is the pre-push battery.
- No `AGENTS.md` in the repo (the design review refers to one outside the repo).
- `scripts/wsl-relay.py` is not Core Guard pinned; `supervisor/**`, `brain/confirm.py`, `docs/OWNERSHIP.md` and `ci.yml` are.
- MCP client is stdio-only; server definitions sit in a tracked config file, so personal entries need a gitignored overlay.
- The orb can already send a click confirm (`orb_input` kind confirm → `ws.py`), but shows nothing about what is being confirmed.
