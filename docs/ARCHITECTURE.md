# ARCHITECTURE.md — Raphael module boundaries & ownership (v1)

Status: **authoritative** (with PROTOCOL.md). Orchestrator-owned. Last updated: 2026-10-05.

## 1. Process topology

```
Windows (logon)
 └─ supervisor/raphael-supervisor.exe|pyw  (entry: Task Scheduler "Raphael" @ logon; Startup-folder fallback)
     ├─ 1) launches body/orb (Electron) FIRST → orb shows "starting" immediately, even before WSL is up
     ├─ 2) spawns WSL:  wsl.exe -d Ubuntu-26.04 -u dami -- (systemd bring-up check, ollama, raphael-brain)
     │     └─ WSL (systemd)
     │          ├─ raphael-brain.service  (Restart=always)  ← FastAPI :8765, agent loop, jobs, router, STT/TTS
     │          └─ ollama.service         (already exists, Restart=always)
     ├─ 3) body/win (Python, Windows-native) → WS client role=body → ws://127.0.0.1:8765/ws
     │     (mic capture, playback, screenshot, UIA, input, hotkeys, clipboard)
     └─ 4) health loop: HTTP /health + WS ping every 5 s → exponential-backoff restarts (cap → orb error, no thrash)
Electron orb ← role=ui WS client (direct to Brain) + local IPC to Body for menus that need Windows ops (open logs/settings)
CLI: raphael (WSL bash) + raphael.cmd (Windows) → role=cli (REST/WS on 127.0.0.1:8765)
```

**Mutual watchdog:** Supervisor restarts dead Brain (via `wsl.exe … systemctl restart raphael-brain`); Brain restarts dead Body via `powershell.exe` interop (relaunch Body exe/script). Neither is a single point of failure. Orb reconnects independently (`reconnecting` state).

**Keep-WSL-alive:** supervisor holds an attached lightweight WSL process + `.wslconfig` `vmIdleTimeout=600000` (created 2026-10-04).

## 2. Directory layout & ownership (build-time, disjoint — see docs/TEAM_ROSTER.md)

```
raphael/
├─ brain/                    # WSL, Python 3.12 venv (.venv)
│  ├─ app.py                 # FastAPI entry: /ws, /health, /jobs, /control      [brain-dev]
│  ├─ jobs/                  # job engine: store, scheduler, priorities,
│  │  │                      #   input-lock arbiter, cancellation, journal hooks [brain-dev]
│  ├─ loop.py                # agent loop: route → plan → tools → narrate        [brain-dev]
│  ├─ fastpath.py            # deterministic intent matcher (NO LLM)             [brain-dev]
│  ├─ tools/                 # tool registry + implementations (app control,
│  │  │                      #   shell registry, files, system, web, memory,
│  │  │                      #   github, computer-use, vision)                   [brain-dev]
│  ├─ router/                # provider chain, discovery, circuit breakers,     [router-dev]
│  │  │                      #   benchmark (raphael benchmark), usage log
│  ├─ voice/                 # STT (faster-whisper), TTS (Fish-Speech),         [voice-dev]
│  │  │                      #   wake word, PTT, phrase cache, amplitude
│  ├─ vision/                # screenshot Q&A via LOCAL ollama only              [brain-dev]
│  ├─ memory/                # SQLite: memories, skills index, task journal     [brain-dev]
│  └─ confirm.py             # confirmation enforcement (code, per-job)          [brain-dev]
├─ body/
│  ├─ win/                   # Windows Body (Python, pywinauto)                 [body-dev]
│  │  ├─ main.py (entry, single-instance mutex), ws_client.py, audio_{in,out}.py,
│  │  ├─ capture.py (screenshot+downscale), automation.py (UIA/hotkeys/input-lock),
│  │  ├─ apps.py (launch/URL/paths), clipboard.py, system.py (volume/brightness/media),
│  │  └─ hotkeys.py (kill switch, PTT, private, pause)
│  └─ orb/                   # Electron overlay                                 [orb-dev]
│     └─ src/ (main: frameless/always-on-top/tray/mutex; renderer: GLSL orb,
│              states, job dots, subtitle, context menu, WS client role=ui)
├─ supervisor/               # Windows bring-up + watchdog (Python/PS1)          [supervisor-dev]
├─ scripts/                  # setup.sh/.cmd, uninstall, task-register,          [supervisor-dev]
│                             #   venv build, token gen, selftest entry
├─ skills/                   # Raphael's RUNTIME self-written skills (SKILL.md)  [brain-dev runtime; user-reviewable]
├─ plugins/                  # drop-in code skills (Python modules, manifest)    [brain-dev loader; user-authored]
├─ assets/                   # raphael_reference.wav/.txt (user-provided), acks  [voice-dev]
├─ tests/                    # selftest, concurrency, resilience, latency        [test-engineer]
├─ docs/                     # PROTOCOL, ARCHITECTURE, MODEL_POLICY, PAID_USAGE, [see roster]
│                             #   REQUIREMENTS_ADDENDUM, TEAM_ROSTER, troubleshooting
├─ config.yaml               # all runtime config (providers, flags, lists)      [orchestrator + brain-dev]
├─ .env.example / .env       # OPENCODE_API_KEY, GITHUB_TOKEN, token paths       [orchestrator]
├─ PROGRESS.md, SYSTEM_REPORT.md, README.md
└─ .opencode/                # BUILD team agents + build skills (not Raphael's)
```

## 3. Ownership rules (parallel-safe)

- Two agents never edit the same file (verified: `brain/**` excludes `brain/router/**` + `brain/voice/**` in brain-dev's permissions).
- Orchestrator integrates: `git add/commit/push` (subagents have commit/push denied), resolves conflicts, runs integration tests.
- Waves + review gates: build wave → independent `reviewer` (T2) → `security-reviewer` for anything auth/privacy/shell/screen → orchestrator integration tests → PROGRESS.md updated → next wave.
- Runtime-written dirs (`skills/`, `logs/`, `memory/*.sqlite`) are data, not code — tests must not depend on them.

## 4. Brain internals (the orchestrator core — brief §3B)

- **asyncio, single event loop.** Blocking work (STT, TTS, vision, disk I/O, subprocess) in `asyncio.to_thread`/process pool. No blocking calls on the loop (enforced by a latency watchdog test).
- **Job engine:** SQLite-backed (`jobs` table = journal for crash recovery) + in-memory asyncio tasks. Fields: id, status, priority, owner_tools, input_lock:bool, pending_confirm, created/updated, parent (for worker-subagent jobs). Features: per-job cancellation (asyncio.Event), priority queue (user_facing preempts background), progress events, terminal-state immutability.
- **Worker subagents (runtime):** the Brain spawns *its own* lightweight asyncio workers (research/file/vision/shell lanes) — NOT OpenCode — for parallel subtasks; optional escalation to a spawned OpenCode worker (`opencode run`, dedicated auto-permit config per addendum §8) when general reasoning is needed. All inherit the untrusted-text rule.
- **Input lock:** Brain-arbitrated mutex; exactly one GUI job holds it; `lock:true` tool calls from others queue FIFO. Non-GUI tools (URL, shell, files, timers, API) never touch it.
- **Limits:** per-provider semaphore (from router rate headers + config), local-model concurrency = 1 (8 GB VRAM), tts semaphore = 1, wake/STT lane always reserved so background jobs can't starve voice (user_facing priority floor).
- **Fast path:** `fastpath.py` regex/keyword rules run BEFORE any LLM: open app/URL, YouTube search, volume/brightness/media, timers/reminders, window ops, "what's running", job status/cancel, mode toggles → instant `act_req`. Target: action dispatch < 300 ms from end-of-utterance. Miss → LLM path with instant cached ack ("Understood.") + streamed sentences → Fish-Speech.
- **Router chain:** `zen_free` (discover via GET `https://opencode.ai/zen/v1/models`, filter free — never hardcode IDs; benchmark ranks them) → `go` (only if `allow_go_runtime:true`) → `ollama` local. Health checks, per-provider circuit breaker (open after N failures → cooldown with jitter), 401/429/5xx handling, rate-limit header honoring, model-vanished → re-select (normal, not an error). Offline → local, brief spoken notice, automatic switch-back.
- **Privacy:** `private_on` disables all cloud calls (persisted flag); foreground-window blocklist (password managers/banking/messengers) forces local models for that interaction; `allow_free_models_for_personal_data:false` default → personal-flagged content → local only; redaction of keys/tokens/cards/emails before any cloud call; screenshots → local vision only, ever.
- **Memory + self-written skills:** SQLite tables mirroring Odysseus semantics (pinned + hybrid-retrieved memories wrapped as untrusted context; skills as `skills/<name>/SKILL.md` with draft/confidence gate + usage counters + dedup). See REQUIREMENTS_ADDENDUM §3/§4.

## 5. Latency instrumentation (brief §3B)

Every stage timestamped into `logs/latency.jsonl`: `stt_final`, `route`, `llm_first_token`, `tool_start`, `tts_first_audio`. `raphael latency` computes report vs targets: fast-path action ≤300 ms, ack ≤500 ms, LLM first spoken word ≤1.5 s (provider permitting). `raphael selftest` runs the full matrix (WSL/auth/mic/speaker/screenshot/orb/providers/local models/TTS/YouTube demo/latency/concurrency).

## 6. Config surface (`config.yaml`)

```yaml
providers: { chain: [zen_free, go, ollama], allow_go_runtime: false, allow_paid_runtime: false,
             allow_free_models_for_personal_data: false, model: auto, benchmark_ranking_path: ... }
local_model: { candidates: [qwen3.5:4b, qwen3.5:9b, qwen3:1.7b, huihui_ai/qwen3-vl-abliterated:4b-instruct],
               text: auto, vision: auto, keep_alive: "5m", vision_keep_alive: "0" }   # slut: EXCLUDED permanently
voice: { stt_model: small, tts_voice: assets/raphael_reference.wav, wake_word: "raphael", ptt_hotkey: ... }
jobs: { max_concurrent: 8, gui_steps_cap: 25, local_concurrency: 1 }
safety: { confirm_actions: [delete, send_message, purchase, password, system_settings, install, make_public_repo],
          failsafe_corner: true, kill_switch_hotkey: ..., pause_persist: true }
privacy: { blocklist_apps: [...], watch_mode: false, debug_capture: false }
github: { default_visibility: private, auto_public: false }
runtime_opencode: { auto_permit: true, config_dir: ~/.raphael/runtime-opencode }
```
Secrets ONLY in `.env` (`OPENCODE_API_KEY`, `GITHUB_TOKEN`, token paths) — chmod 600, git-ignored, never logged.

## 7. Reliability matrix (brief §6 — every row gets a test)

| Failure | Recovery owner | Behavior |
|---|---|---|
| Brain crash | Supervisor (backoff, cap→orb error) | task journal replay → report interrupted jobs, **ask before resume** |
| Ollama crash/hang | Brain (`systemctl restart ollama` via interop) + router failover to cloud | spoken notice; OOM → unload vision → smaller model/context → report |
| Body crash | Brain via `powershell.exe` relaunch | orb unaffected; Body reconnects |
| WSL VM idle-stop / `wsl --shutdown` | Supervisor keep-alive + wake; restart chain | orb `reconnecting` → `starting` → normal |
| Sleep/resume, network change | Brain resume hook: re-verify WSL/Ollama/audio/providers/WS, re-warm TTS+router, reconnect | cloud unreachable = normal state (failover + brief notice) |
| Windows Update reboot | logon task → full bring-up | journal reports interrupted jobs |
| Cloud 401/429/5xx/offline | router circuit breaker + chain failover | never crash; recover automatically |
| Duplicate launch | mutex (supervisor) / single-instance (Body, Orb) | second instance exits silently |

Pause (persisted), Private (persisted), kill switch (momentary) survive restarts; hotkeys distinct and configurable.
