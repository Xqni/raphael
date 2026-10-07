# tools-memory — status

Updated: 2026-10-06 (Wave 2 complete — WAITING for current_wave >= 3)

## Done
- (bootstrap) shared contracts read (AGENT_RULES/WAVES/OWNERSHIP/INTERFACES).
- **Wave 2 plan task**: Wave 3 plan written into docs/lanes/tools-memory.md — tool specs (web/files/shell/github/schedule/mcp), folder skeletons, memory schema (memories + FTS5 + summaries + skills_index + schedules), skills/plugins gate semantics, test matrix, config keys, execution order.
  - Verified against the real tree first: `brain/tools/__init__.py` (registry shape, placeholder `shell` tool), `brain/loop.py:113-240` (confirm gate at :114 passes NO tool name; `meta['risky']` unused; tool output path), `brain/confirm.py` (RISKY_TOOLS/RISKY_PATTERNS), `brain/app.py:123` (`engine.submit` seam), `config.yaml`, addendum §2/§3/§4, brain-core's lane list (auto-discovery is their Wave 2 task).
- Requests addressed to tools-memory: **none** (`ls docs/requests/*__to__tools-memory__*` → empty).
- Two seam requests FILED to brain-core (AGENT_RULES §2):
  - `tools-memory__to__brain-core__confirm-gate-tool-risky.md` — loop.py must pass tool name to `confirm.classify` + honor registry `risky` metadata (currently pattern-only; blocks file_trash / github visibility / mcp confirm gates).
  - `tools-memory__to__brain-core__loop-memory-skills-injection.md` — per-turn memory+skills injection as untrusted block, personal-category privacy flag, schedule fire via `engine.submit` + `arm_all()` at startup.

## In progress
- — (waiting; AGENT_RULES §11)

## Blocked
- Not blocked yet (Wave 3 not started). Watch items once it starts: the two brain-core requests above; exact spec/registration mechanism from the merged `brain/tools/__init__.py`.

## Next
- WAIT for docs/WAVES.md `current_wave >= 3`, then execute docs/lanes/tools-memory.md §"Wave 3 tasks" in order: 0 prep → 1 memory → 2 skills/plugins → 3 tools → 4 MCP → 5 integration check → handoff.

## Test output (real runs only — never claim unrun tests)
- (none — Wave 2 task was docs-only; no code changed)
