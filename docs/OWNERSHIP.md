# OWNERSHIP.md — lane → owned paths (integrator-owned; verified against the real tree 2026-10-05)

**Default rule: anything unlisted is the integrator's.** A lane may only create/edit files under its own paths (plus its `docs/lanes/<lane>.md` + `docs/status/<lane>.md`). Ownership = write authority; Core Guard semantics (AGENT_RULES §8) need an integrator-approved request even for the owning lane.

## Corrections vs the original bootstrap map (verified against the real tree)

- `brain/llm.py` (router seam, docstring says "brain-dev's side") → **brain-core**.
- `brain/ws.py` (the `/ws` hub behind `app.py`), `brain/orbstate.py` (INTERFACES §e frame builder) and `brain/config.py` (config loader/instance derivation) → **brain-core** (added 2026-10-06 during wave_done verification: brain-core's branch edits them inside its own brief — `/ws` + REST endpoints, server-authoritative `orb_state`, config loading — and no other lane touches them).
- `brain/auth.py`, `brain/control.py`, `brain/mode.py` → **integrator** (Core Guard: auth, kill/pause/private/watch).
- `brain/run.py` + `brain/raphael-brain.service` → **infra** (entry point / unit).
- Tests-inside-your-folder belong to the lane (`brain/tests` → brain-core, `brain/router/tests` → router, `brain/voice/tests` → voice); root `tests/**` → qa-security.
- `assets/`: `acks/**` + `raphael_reference.*` → voice; `orb-reference/**` → orb; anything else → integrator.
- Planned dirs are pre-assigned below even though they do not exist yet — creating your own is expected; creating someone else's is a violation.

## Lane table

| Lane | Owns | Notes |
|---|---|---|
| **integrator** | `docs/{PROTOCOL,ARCHITECTURE,INTERFACES,WAVES,OWNERSHIP,AGENT_RULES,COORD_PROTOCOL,LAUNCH}.md`, `docs/{TODO,MODEL_POLICY,PAID_USAGE,REQUIREMENTS_ADDENDUM,TEAM_ROSTER,TROUBLESHOOTING,VOICE_DATA_SPEC,ORB_REBUILD_TASK}.md`, `config.yaml`, `config.d/README.md`, `PROGRESS.md`, `README.md`, `SYSTEM_REPORT.md`, `.env.example`, `.opencode/**`, `tools/conductor/**` (coord CLI + conductor + its tests/prompts), `brain/{auth,control,mode}.py`, all merges | `confirm.py` semantics guarded by AGENT_RULES §8 even though brain-core owns the file; `~/.raphael-coord/` is outside git and integrator/conductor-owned |
| **orb** | `body/orb/**`, `docs/orb/**`, `assets/orb-reference/**` | renderer + demo/matrix harness |
| **brain-core** | `brain/app.py`, `brain/loop.py`, `brain/fastpath.py`, `brain/orbstate.py`, `brain/notice.py`, `brain/llm.py`, `brain/jobs/**`, `brain/confirm.py`, `brain/tools/__init__.py` (central registry — **nobody else edits it**), config loading + `config.d` loader + profile overlay + instance-env derivation, tool auto-discovery, runtime workers, `brain/tests/**` | `brain/tools/__init__.py` is a central registry (AGENT_RULES §3); `brain/orbstate.py` added 2026-10-07 (file header: INTERFACES §e 'brain-core emits every state' — was an unlisted-path gap, Bug E assignment made it explicit) |
| **router** | `brain/router/**` (incl. `brain/router/tests/**`) — all cloud API clients: Groq, Zen free, legacy Ollama client (kept, profile-gated), `chat/vision/transcribe/health` seams, discovery, circuit breakers, usage log | Groq + Zen keys read from `.env`, never logged |
| **voice** | `brain/voice/**` (incl. tests), `body/win/audio_in.py`, `body/win/audio_out.py`, `assets/acks/**`, `assets/raphael_reference.wav/.txt` | Fish TTS stays local; local faster-whisper kept behind profile `local` |
| **pc-control** | `body/win/**` **except** `audio_*`, `brain/tools/pc/**`, `body/win/PROGRESS.md` | hotkeys, UIA, input-lock etiquette, launch/clipboard/system tools |
| **computer-use** | `brain/vision/**`, `brain/tools/computer_use/**` | cloud-vision gate lives here (blocklist/redaction before `router.vision`) |
| **infra** | `supervisor/**`, `scripts/**`, `brain/raphael-brain.service`, `brain/run.py`, the `raphael` CLI (bash + cmd + thin client) | never touches Task Scheduler/`.wslconfig` without telling the user |
| **qa-security** | `tests/**` (root, incl. `.venv`), `.github/workflows/**`, `docs/reviews/**` | mock harness, contract tests, security regressions |
| **tools-memory** | `brain/memory/**`, `brain/tools/{web,files,shell,github,schedule,mcp}/**`, `skills/**`, `plugins/**` | Wave 3 bulk; folders pre-assigned |
| **evolution-persona** | `brain/evolution/**`, `brain/persona/**`, `docs/evolution/**` | Wave 4/5 bulk; folders pre-assigned |

Every lane additionally owns `docs/lanes/<lane>.md` (its task list) and `docs/status/<lane>.md` (its status log).

## Not owned by anyone (runtime data — gitignored)

`logs/**`, `*.sqlite*`, `*.db`, `brain/router/usage.jsonl`, `memory.db`, `run/`, `*.pid`, `screenshot_test.jpg`. Lanes must not depend on another instance's runtime data.

## Shared-contract change protocol

Contracts = `docs/PROTOCOL.md`, `docs/ARCHITECTURE.md`, `docs/INTERFACES.md`, `config.yaml` (base), `brain/tools/__init__.py`, Core Guard files. Lanes never edit them directly — write `docs/requests/<from>__to__<owner>__<slug>.md` (see `docs/requests/README.md`) and keep working.
