# tools-memory — status

Updated: 2026-10-07 (wave 3 started)

## Done
- (bootstrap) shared contracts read (AGENT_RULES/WAVES/OWNERSHIP/INTERFACES).
- **Wave 2**: plan written into docs/lanes/tools-memory.md; 2 seam requests filed to brain-core; status WAITING.
- **Wave-3 start (2026-10-07):** inbox read (`wave_open` + conversation-hook decision), rebased on origin/main (lane-doc conflict resolved — integrator intro + my plan both kept), AGENT_RULES 13/14/15 read, BUGS-WAVE2 reviewed (**no P0s assigned to this lane**; A–G belong to router/pc-control/orb/voice/brain-core/computer-use/infra).
- **Seam audit:** my request `confirm-gate-tool-risky` **LANDED** (brain/loop.py:430-431: `classify(text, tool=tool_name)` + registry `risky` → `tool_decision`); registry fully landed (`register(schema=)`, `SPECS`, `as_untrusted()`, `validate_args`, discovery skips tests). Request `loop-memory-skills-injection` still OPEN. brain-core's producer hook is on their branch (merge order brain-core → tools-memory lands first).
- **Conversation-hook request ACCEPTED** as-is (Status+Decision flipped in `docs/requests/brain-core__to__tools-memory__conversation-hook.md`, answer posted to brain-core's coord inbox).
- **Task 0 prep complete:** `config.d/tools-memory.yaml` created (memory/skills/plugins/files/shell/web/schedule/mcp keys only; base `github.*`/`safety.*` untouched).
- **Task 1 started — conversation-turn capture landed:** `brain/memory/schema.py` (additive `conversation_turns` + index, called from `init_db`), `brain/memory/conversation.py` (exact accepted signature; O(1) job path = bounded in-memory buffer + ONE lazily-started daemon flusher; fail-silent everywhere incl. flush/thread-start; trim at `memory.conversation_max_rows`; readers `recent_turns/turn_count/clear_turns`; `shutdown()` for Rule-14 cleanup), `brain/memory/tests/` (NO `__init__.py` on purpose — conftest must set `RAPHAEL_DB_PATH` before `brain.memory` import).

## In progress
- Task 1 remainder: memories schema (FTS5 + sync triggers + keyword fallback), `store.py`, `retrieval.py` (pinned+BM25+boost+recency+counters), `block.py` (untrusted framing), `profile.py`, `summary.py` + tests.

## Blocked
- — (request #2 open with brain-core, not blocking my build order — integration check is wave-3 step 5)

## Next
- Finish task 1 → task 2 skills/plugins → task 3 tools → task 4 MCP → step 5 integration check → handoff.

## Test output (real runs only — never claim unrun tests)
- `./brain/.venv/bin/python -m pytest -q brain/memory/tests` → **10 passed in 0.11s** (2026-10-07)
- `./brain/.venv/bin/python -m pytest -q brain/tests` → **134 passed, 1 warning in 10.16s** (init_db hook = no regression)
- `cd tests && ./.venv/bin/python -m pytest -q .` → **187 passed, 9 xfailed, 2 xpassed, 1 warning in 34.12s** (matches qa baseline exactly)
