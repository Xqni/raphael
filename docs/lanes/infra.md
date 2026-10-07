# infra — lane task list (owner: infra lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/infra.md. Requests to you: `ls docs/requests/*__to__infra__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] Supervisor profile cloud_temp: skip Ollama/systemd bring-up, process-mode brain spawn (unit not installed), health/backoff unchanged.
- [ ] Spawn honors RAPHAEL_INSTANCE-derived port/pidfile (INTERFACES §d); main defaults unchanged.
- [ ] raphael CLI: bash+cmd wrappers + thin role=cli client (jobs list/get/cancel, control, typed command) — no new protocol frames.
- [ ] Task "Raphael" stays Disabled: no Task Scheduler changes; uninstall/setup scripts untouched except instance awareness.
- [ ] Synthetic tests only (existing supervisor test patterns); no live stack starts.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
