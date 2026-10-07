# brain-core — lane task list (owner: brain-core lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/brain-core.md. Requests to you: `ls docs/requests/*__to__brain-core__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] Config loader: config.d/*.yaml deep-merge + profile overlay + defaults (INTERFACES §c).
- [ ] Instance derivation: RAPHAEL_INSTANCE -> port/pidfile/lock/mutex/CDP/data-dir (INTERFACES §d); unset = main, zero behavior change.
- [ ] Conversational loop with persona: chat(stream=True) sentence streaming, ack-first, length-adaptive (persona per addendum §10).
- [ ] Tool auto-discovery: walk brain.tools.* at import, validate strict JSON-Schema specs (INTERFACES §b).
- [ ] orb_state emission audit vs INTERFACES §e (every state provably emitted; jobs_active/mode/shape_hint/task_kind/provider/model).
- [ ] Typed input channel: command source=text + orb submit_text path end-to-end.
- [ ] Mock tests only; no live providers, no real stack.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
