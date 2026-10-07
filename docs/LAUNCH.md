# LAUNCH.md — starting a lane session (integrator-owned)

Each lane works in its own git worktree on its own branch. The scheduled task **"Raphael" stays Disabled** — nobody starts the live stack (AGENT_RULES §5/§12).

## Worktrees (created by the integrator)

Location: `/home/dami/raphael-wt/<lane>` on branch `agent/<lane>` (base: main).
Lanes: `router`, `brain-core`, `pc-control`, `voice`, `computer-use`, `orb`, `infra`, `qa-security`, `tools-memory`, `evolution-persona`.
The integrator works directly in `/home/dami/raphael` on `main`.

Recreate one (only if missing):

```bash
cd /home/dami/raphael
git worktree add -b agent/<lane> ../raphael-wt/<lane> main
ln -s /home/dami/raphael/.env ../raphael-wt/<lane>/.env      # secrets: symlink, NEVER copy
```

## Start a lane session

```bash
cd /home/dami/raphael-wt/<lane>
git status --short --branch          # expect: ## agent/<lane>
ls docs/requests/*__to__<lane>__*.md 2>/dev/null   # 1) requests addressed to you (AGENT_RULES §2)
cat docs/status/<lane>.md            # 2) your last status
cat docs/WAVES.md                    # 3) current wave + your exit criteria
opencode                             # 4) session opens scoped to this worktree
```

## Rebase before each new task (AGENT_RULES §4)

```bash
cd /home/dami/raphael-wt/<lane>
git fetch origin && git rebase origin/main     # read-only against origin; NEVER push
```

Conflict in a file you don't own → a rule was broken: stop and write a request.

## Shared resources (symlinked into every worktree — treat as READ-ONLY)

| Path | Why |
|---|---|
| `.env` | secrets live in exactly one place; never copy, never echo |
| `brain/.venv` | heavy Python env (torch/laya/pytest) |
| `tests/.venv` | root test env |
| `body/orb/node_modules` | Electron deps |
| `brain/voice/.venv-fish`, `brain/voice/models`, `brain/voice/vendor` | Fish TTS runtime (voice lane tests mock it anyway) |

Installing/upgrading packages **through a symlink mutates the shared env** — that is a change to main's environment: write a request to the integrator instead (AGENT_RULES §2).

## Instance + mock rules

Set `RAPHAEL_INSTANCE=<lane>` for anything that binds a port or takes a lock (derived values: `docs/INTERFACES.md §d`). Never default ports, never Fish spawn, never real mic/hotkeys/input, never Ollama. Mocks are the default; live runs are the integrator's.

## Merge order (integrator only)

`router → brain-core → pc-control → voice → computer-use → orb → infra → qa-security → tools-memory → evolution-persona` (see `docs/WAVES.md`).
