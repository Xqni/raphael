# computer-use — lane task list (owner: computer-use lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/computer-use.md. Requests to you: `ls docs/requests/*__to__computer-use__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Screenshot gate: downscale (vision.max_px/quality) + foreground blocklist + redaction BEFORE router.vision (PROTOCOL §7 conditions, cloud_temp only). — `brain/vision/{gate,image,redact,service}.py`
- [x] brain/tools/computer_use/ self-registered "see my screen" tool returning the vision() answer. — `see_screen` (+ strict `SPECS`)
- [x] Computer-use loop correctness under jobs.gui_steps_cap (act pipeline; structured errors, no free-form shell). — `computer_use` runner: UIA-first observe, allow-listed §7 actions, stuck/loop detection, per-step confirm, per-job cancel, input-lock via needs_lock
- [x] Privacy asserts: debug_capture stays false, no image bytes logged/persisted, Private Mode short-circuits to fastpath. — tests + service/runner short-circuits (note: shared `ws._on_act_res` journal leak filed as request → brain-core)
- [x] Mock vision tests (fake router). — `brain/vision/tests` + `brain/tools/computer_use/tests` (scripted gateway/chat/vision incl. injected "ignore previous instructions" screen)

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [x] [P0-BugF] `foreground_info` refuses vision on a NORMAL window: foreground = Windows Terminal titled "Ubuntu-26.04" (non-blocklisted, title query works) yet the answer was "I can't verify which window is in front" (docs/BUGS-WAVE2.md Bug F). Find the failing verification, fix it for non-blocklisted windows, keep blocklist refusal intact, test with a terminal foreground. — **Root cause (evidence-backed, dossier hypothesis disproven): `foreground_info` never ran. body.log shows `received 1012 (service restart)` between jobs 42/44; job 43's journal = instant refusal with NO `foreground_info` record in actions.log, while jobs 35/41 succeeded (16 ms, real titles). The body was disconnected mid-restart; my `capture_screen` swallowed the ActError into `title=None` and the gate spoke the privacy verdict for an availability failure. Fixed: `gate.unreachable()` + `gate.err_hint()` — probe failures now say "I can't reach the Body right now (detail)"; `{'window': None}`/missing title keeps "can't verify…" (fail closed); blocklist refusal intact. Also closed a gate hole found while fixing: the blocklist now gates EVERY observation (UIA text goes to cloud chat too), not just the vision path. Tests: terminal-foreground happy path (service + loop, exactly ONE fg probe = Rule 15), probe-failure verdict, missing-window verdict, blocklist-refuses-before-UIA.`
- [x] [SPEED] Screenshot→answer stays instant (Rule 15). — no new round trips: happy path = 1 `foreground_info` + 1 `screenshot` (asserted `foreground_calls == 1` in tests); no retries/sleeps added.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  (Wave 3: watch mode, help-with-error, summarize-page, window-aware context.
   Wave 4: failure recovery/strategy switch, dialog/UAC safety (never auto-click UAC).
   Wave 5: plan-preview "Simulation".)
