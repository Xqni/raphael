# Wave 2 integration E2E — runbook (execute when brain phase 2 notification arrives)

## Pre-flight
1. `git status` — clean? stage any in-flight agent files first.
2. Re-run: `PYTHONPATH=$(pwd) tests/.venv/bin/pytest -q tests/` (want 10+ passed) AND `brain/.venv/bin/python -m pytest -q brain/tests` (want all green after phase-2 rewrite).
3. Check brain/voice status: voice phase-1 handoff `.opencode/research/wave2-voice-phase1.md`.

## Full-chain bring-up (all autonomous, no root)
4. `node body/orb/test/fake-brain.cjs` NOT needed — real brain.
5. Restart supervisor: `powershell -c "Stop-ScheduledTask -TaskName Raphael; Start-Sleep 2; Start-ScheduledTask -TaskName Raphael"`.
6. Expect in logs/supervisor.log (grep):
   - `brain process mode — unit ... spawning brain directly under wsl`
   - `brain relay: listening 127.0.0.1:8765` + `backend wsl <ip>:8766 (helper leg)`
   - within ~15s: `brain healthy (HTTP 200)`  (process mode skips the old 60s unit poll)
   - `orb launched ... sh -lc "cd .../body/orb && exec npm start"`
   - body: `body not ready` UNTIL supervisor phase-1b sees body/win/main.py — it EXISTS now, so body should launch; body stdout in logs/body.log should show auth + ping/pong (no more "connection refused").
7. From Windows: `curl.exe -s -H "X-Raphael-Token: <tok>" http://127.0.0.1:8765/health` -> 200 (two-stage relay chain).

## /ws E2E (the real contract)
8. WS probe through relay from Windows (python websockets script): auth frame role=ui -> expect auth_ok/state; role=body -> auth_ok; wrong token -> error/close per PROTOCOL.
9. `python body/win/e2e_control.py` with real brain up -> control frames accepted (brain logs control receipt; no E_UNSUPPORTED).
10. Orb: goes from `offline` to `idle` (no Brain = offline visuals) -> NOW with brain up the orb should reach `idle` bright state. User's eyes final-gate.

## Watchdog proof
11. `wsl -d Ubuntu-26.04 -u <wsl-user> -- sh -c "kill $(cat /tmp/raphael-brain.pid)"` (pidfile kill, NOT broad pkill) -> supervisor logs `recycling via pidfile + respawn` + `brain healthy` again.
12. Kill orb electron -> supervisor relaunches (procs["orb"]) -> single-instance handoff clean.
13. Body: kill body python -> supervisor relaunch (body watchdog) -> rc0 single-instance if duplicate.

## After E2E
14. PROGRESS entry + TODO updates (Wave 2 core = integrated).
15. Remaining dispatches: body phase 3 (audio real), voice phase 2 (wake/PTT), test-engineer extension for brain/ws, docs-writer README refresh.
16. USER report when awake: relay admin one-liner option (TODO §3b), hotkey bindings added, everything green.

## Wave-2 core: PASSED 2026-10-05 09:40 (evidence in PROGRESS)
- brain tests 30/30 + voice 20/20 (orchestrator re-runs), process-mode healthy ~6s, watchdog x2, relay 401/200, UI+body ws round-trips, control frames persisted+restored, relay5s-timeout bug killed (25s survival both legs), body stable.

## Phase-3 verification: PASSED 2026-10-05 (e2e_wave2.py rc=0; see PROGRESS)
- §17 all suites green (30/20/10 + e2e_phase3), §18 speak+binary live (15 chunks BE-verified), §19 act live (real body screenshot -> b64), §20 body respawn path exercised via task restarts. Remaining: §21 wake report + docs-writer.
17. Re-run: brain tests (30+new), voice tests (20), tests/ suite (10).
18. Mic lane E2E: body PTT simulation → audio_start + kind=1 binary (seq BE) → brain transcribe (monkeypatched or real whisper) → loop command → speak frames to ui session.
19. Act E2E: GUI job → act_req → body → act_res → job_event done; plus no-body-session → job fails with clean error event.
20. Kill-body test: supervisor relaunches body (body watchdog), single-instance rc=0.
21. Final: PROGRESS milestone + docs-writer README refresh + USER WAKE REPORT (relay firewall one-liner TODO §3b, hotkeys ctrl+alt+p / ctrl+alt+shift+p / kill ctrl+alt+shift+k, raphael_reference.wav missing — voice needs it, all-wave-2 status).
