# pc-control — lane task list (owner: pc-control lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/pc-control.md. Requests to you: `ls docs/requests/*__to__pc-control__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] brain/tools/pc/ namespace + self-registered tools (open_app, launch_url, volume, media, window, clipboard, notify) per INTERFACES §b.
- [ ] Body act_req coverage for those tools (body/win minus audio_*), incl. queue/busy semantics (E_LOCK_BUSY).
- [ ] Hotkeys (pause/private/kill) contract-tested WITHOUT registering real hotkeys (instance rule).
- [ ] Lock names derive from RAPHAEL_INSTANCE (INTERFACES §d) — main defaults unchanged.
- [ ] Mock/unit tests only; never inject real input outside mocks.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
