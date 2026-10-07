# computer-use — lane task list (owner: computer-use lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/computer-use.md. Requests to you: `ls docs/requests/*__to__computer-use__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Screenshot gate: downscale (vision.max_px/quality) + foreground blocklist + redaction BEFORE router.vision (PROTOCOL §7 conditions, cloud_temp only). — `brain/vision/{gate,image,redact,service}.py`
- [x] brain/tools/computer_use/ self-registered "see my screen" tool returning the vision() answer. — `see_screen` (+ strict `SPECS`)
- [x] Computer-use loop correctness under jobs.gui_steps_cap (act pipeline; structured errors, no free-form shell). — `computer_use` runner: UIA-first observe, allow-listed §7 actions, stuck/loop detection, per-step confirm, per-job cancel, input-lock via needs_lock
- [x] Privacy asserts: debug_capture stays false, no image bytes logged/persisted, Private Mode short-circuits to fastpath. — tests + service/runner short-circuits (note: shared `ws._on_act_res` journal leak filed as request → brain-core)
- [x] Mock vision tests (fake router). — `brain/vision/tests` + `brain/tools/computer_use/tests` (scripted gateway/chat/vision incl. injected "ignore previous instructions" screen)

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  (Wave 3: watch mode, help-with-error, summarize-page, window-aware context.
   Wave 4: failure recovery/strategy switch, dialog/UAC safety (never auto-click UAC).
   Wave 5: plan-preview "Simulation".)
