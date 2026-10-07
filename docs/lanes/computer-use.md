# computer-use — lane task list (owner: computer-use lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/computer-use.md. Requests to you: `ls docs/requests/*__to__computer-use__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] Screenshot gate: downscale (vision.max_px/quality) + foreground blocklist + redaction BEFORE router.vision (PROTOCOL §7 conditions, cloud_temp only).
- [ ] brain/tools/computer_use/ self-registered "see my screen" tool returning the vision() answer.
- [ ] Computer-use loop correctness under jobs.gui_steps_cap (act pipeline; structured errors, no free-form shell).
- [ ] Privacy asserts: debug_capture stays false, no image bytes logged/persisted, Private Mode short-circuits to fastpath.
- [ ] Mock vision tests (fake router).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
