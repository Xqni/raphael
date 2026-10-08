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

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Observation hardening: UIA crash recovery, blocklist bypass attempt suite (privacy audit), foreground-probe failure matrix (locked/hidden/vanished windows), screenshot redaction re-verify. — `test_hardening.py` ×2 (19 tests): UIA crash → gated-vision recovery (+ debug-capture/body-gone variants); **process-field bypass closed** (`foreground_window()` now returns `title | process` composite, zero-identity window = fail-closed None); probe matrix (timeout/no-session/malformed/vanished → E_UNREACHABLE vs E_NO_FOREGROUND at runner AND service level); redaction re-verify (all 6 kinds in vision answers, UIA trees, action feedback). Plus qa-security vision-gate item 4: `gate.check_debug_capture()` (§7(4) enforced in code) — request flipped DONE with evidence.

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Analysis-mode context gathering (screen + foreground + window history for deep-dive requests), redaction discipline extended to Simulation/Analysis payloads. — **`gather_context` tool** (self-registered, strict SPECS, offered via tool_specs): foreground (`foreground_info`, 1 probe) + open windows (`list_windows`, top-10, **blocklist entries filtered — sensitive titles never reach a model**) + in-process window-history ring (32-row memory, 12 emitted, dedup; fed by every production `BodyGateway.foreground_window()` probe; nothing persisted) + optional gated screen pass (blocklist/profile/debug_capture/image gates, vision). Private Mode = ZERO probes; fg probe failure = honest unreachable; ALL output through `gate.redact` + bounded 3000 chars + blocklist-generic wording (app names withheld from cloud payloads; see_screen's spoken naming stays user-facing). Simulation/Analysis payload discipline = same redact path (`brain/vision/context.py::gather_context`).

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [ ] Read `docs/audit-tasks/computer-use.md` → your IDs: **SEC-3 egress co, SEC-3 context, QA-2 fixtures, ARCH-6 vision report** — VERIFY-FIRST (file:line → CONFIRMED/NOT-APPLICABLE/ALREADY-DONE), QA-4: link green CI run with wave_done. Register/dedupe: `docs/AUDIT-2026-10-07.md`.

## Wave 5H — hardening sprint packet (2026-10-08, inside wave 5)

Verify-first done with file:line quotes → docs/status/computer-use.md (Wave 5H section).

- [x] 1. Screenshot egress tripwire: fails if image bytes hit disk/log/send while blocklisted (composite `title | process`), Private Mode, or no cloud-vision policy. — `brain/vision/tests/test_egress_tripwire.py` (+ runner twin): marker bytes after EOI, disk guard (open/os.open/Path writers), capsys marker+b64 checks, vision spy, control happy-path (send still works). Hardening found & fixed: unknown `vision.provider` slipped `check_profile` → now E_PROFILE fail-closed (`gate.check_profile`).
- [x] 2. Sensitive contexts beyond the static blocklist: focused password fields (UIA IsPassword), UAC/secure desktop, configurable bank/wallet/2FA patterns — refuse with a short spoken reason. — `gate.check_foreground` + `matched_sensitive_pattern` (regex w/ literal fallback, defaults UNION config), `config.d/computer-use.yaml` (`computer_use.sensitive_title_patterns`), `password_focus` consumption in gateway/service/runner/gather_context; body-side flags requested: `docs/requests/computer-use__to__pc-control__focused-password-flag.md`.
- [x] 3. Untrusted wrapping + injection fixtures (hidden text, ignore-previous, fake system dialogs). — wrapping verified (runner `wrap_observation` + loop `as_untrusted`); `strip_invisible` now scrubs Cc/Cf at `redact_text` + `render_tree` chokepoints; `test_injection_fixtures.py` (3 fixtures × wrap/strip/never-dispatch + compromised-model allow-list check).
- [x] 4. Vision latency + cost per call reported to router (paid-slot budgeting). — observed from `brain/router/usage.jsonl` (14 vision calls: 2 ok @ 1544/3187 ms, $0.000167 + $0.000708 = $0.000875 via `spend.estimate_cost_usd`; 12 failed @1.4–2.1 s E_OFFLINE/E_INTERNAL during the outage window) → coord `test_result` + status doc.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
  (Wave 3: watch mode, help-with-error, summarize-page, window-aware context.
   Wave 4: failure recovery/strategy switch, dialog/UAC safety (never auto-click UAC).
   Wave 5: plan-preview "Simulation".)
