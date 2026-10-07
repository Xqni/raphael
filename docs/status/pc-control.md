# pc-control — status

Updated: 2026-10-06 (Wave 2 complete — handoff below)

## Done (Wave 2, all committed on agent/pc-control)

1. **Instance isolation (task 0 / lane task 4).** `body/win/instance.py`
   derives body lock, WS port, token candidates, data dir, action-log path and
   supervisor mutex from `RAPHAEL_INSTANCE` (INTERFACES §d table). Unset/`main`
   = today's exact values (8765, `%TMP%\raphael_body.lock`,
   `%APPDATA%\Raphael\token` → `~/.raphael/token`). Unknown instance without
   `RAPHAEL_PORT` raises — never defaults a port (AGENT_RULES §5).
   `main.py` (lock) and `ws_client.py` (URL + token) consume it.
   Brain-side token derivation + supervisor mutex/env → 2 open requests.
2. **Full PROTOCOL §7 act_req coverage (task 1).** `body/win/actions.py`
   dispatcher + one module per group (`act_launch/act_powershell/act_capture/
   act_uia/act_input/act_window/act_system`) = 17 actions: launch_url,
   search_youtube, open_app (PATH → Start Menu → App Paths → UWP staged
   resolution), open_path (local-only, no UNC/shell:), powershell (fixed
   script registry, env-var args — no injection), screenshot, uia
   find/click/type/read/tree (structured selectors), input (atomic
   chords/text/mouse units, modifier-release guarantees, mouse failsafe),
   window list/focus/min/max/restore/snap, clipboard, media, volume,
   brightness, notify, plus list_windows / foreground_info /
   list_running_apps (§7 enum additions requested from the integrator).
   Semantics: allow-list → strict validation (no value echo) → input-lock
   (`E_LOCK_BUSY` + `queued:true`, lock acquired even if the sender forgets,
   released in `finally`) → timeout `E_TIMEOUT` (atomic input exempt so a
   chord is never cut in half) → redacted JSONL action log
   (`logs/actions[_<instance>].log`: args summarized w/ secret keys + content
   text reduced to lengths, results structural only, 5 MB rotation).
   All OS calls sit behind `body/win/winlayer.py` (lazy Windows imports,
   ctypes keyboard/mouse/window/process, pywinauto UIA, NullBackend off-Windows)
   with `body/win/fakewin.py` as the mock.
3. **LLM-facing tools (task 2).** `brain/tools/pc/` — one file per group
   (launch/system/window/automation/powershell) + `_spec.py`; 17 ToolSpecs
   with strict JSON schemas (typed + described properties, required ⊆ props,
   `additionalProperties:false`, provider-portable keywords only), loud
   import-time validation, self-registration into `brain.tools` with
   `category='gui'`, `needs_lock` parity with the body action (asserted),
   and confirm categories (`powershell` risky → `system_settings_change`,
   everything else None). Exports `openai_tools()` + `prompt_block()` for the
   router. Live-Brain discovery/LLM wiring is brain-core's half → open request.
4. **Tests + e2e (task 3).** `body/win/tests/` (78 tests) and
   `brain/tools/pc/tests/` (10 tests), all mocked — no real input, no
   sockets, no hotkey registration anywhere. `body/win/e2e_control.py`
   extended: default **mock mode** drives the whole §7 matrix through
   `ws_client.handle_message` (FakeWS+FakeWin, action-log checks, exit 0/1);
   `--live` keeps the original control-frame flow but **refuses to run**
   unless `RAPHAEL_INSTANCE` is set and ≠ `main`.
5. **Hotkeys (lane task 3).** `hotkeys.py` refactored: pure
   `build_bindings(config)` + `register_hotkeys()` as the only `keyboard`
   touchpoint; contract tests run registration against a stub `keyboard`
   module and check every frame against the PROTOCOL §3 control enum parsed
   from the doc.
6. **Cross-lane requests (AGENT_RULES §2).** 4 written:
   - `pc-control__to__integrator__protocol-act-req-enum.md` (§7 additions)
   - `pc-control__to__integrator__instance-token-path.md` (auth token path)
   - `pc-control__to__brain-core__tool-discovery-and-llm-tools.md`
     (auto-discovery, feed tool specs to the model, risky/confirm enforcement)
   - `pc-control__to__infra__instance-env-supervisor.md` (mutex + env)

## In progress
- — (Wave 2 lane tasks complete)

## Blocked
- Live-Brain use of `brain/tools/pc` awaits the brain-core auto-discovery
  request (tools are registered + tested; the Brain must import the package).

## Next
- Per AGENT_RULES §11: handoff written, lane STOPS here. Waves 3-5
  (browser/CDP, recycle-bin+activity viewer, dry-run) start only when
  `docs/WAVES.md current_wave` advances.

## Test output (real runs, 2026-10-06, on this worktree)

```
$ tests/.venv/bin/python -m pytest -q tests
10 passed in 0.33s                      # qa-security's root suite — unchanged baseline

$ tests/.venv/bin/python -m pytest -q body/win/tests brain/tools/pc/tests
88 passed in 0.67s                      # 78 body + 10 tool-spec tests

$ /home/dami/raphael/brain/.venv/bin/python -m pytest -q brain
70 passed, 3 warnings in 18.98s         # baseline 60 + 10 new pc spec tests

$ python3 body/win/e2e_control.py
... 54 PASS lines, 0 FAIL ...
E2E-MOCK: PASS (0 checks failed)
exit=0

$ cd body/win && python3 -c "import ws_client, actions; print(len(actions.action_names()), 'actions')"
17 actions                              # script-mode (supervisor) import path
```

Honest note: ONE earlier run of the brain suite reported `1 failed, 69 passed`
before any name could be captured (the `.pytest_cache/lastfailed` was cleared
by the next green run). The identical sequence was then repeated 9 times — all
`70 passed`, `lastfailed = {}`. The pc-control tests (88) were green in every
single run; the transient sits in the pre-existing brain suite (timing-class),
not in this lane's tests. Re-run `pytest brain` if it reappears and report the
name to the owning lane.


## Handoff (for the integrator / next pc-control session)

- **Ownership respected:** only `body/win/**` (except `audio_*`),
  `brain/tools/pc/**`, `docs/lanes|status/pc-control.md`, `docs/requests/*`
  were touched. `docs/PROTOCOL.md`, `brain/auth.py`, `brain/tools/__init__.py`,
  `supervisor/` are NOT edited — changes proposed via the 4 request files.
- **What the next session needs to know:**
  - The act_req action registry is `body/win/actions.py::ACTIONS`;
    conformance test parses §7 from the doc + `PENDING_PROTO_ADDITIONS`.
    When the integrator accepts the enum request, delete the tuple (the test
    keeps passing either way).
  - `body/win/fakewin.py` ships in the body (test support, documented) —
    never bind it outside tests/e2e; `winlayer.get_backend()` only auto-selects
    the real backend on `os.name == 'nt'`.
  - Live Windows verification NOT run here (Linux worktree, AGENT_RULES §5):
    `e2e_control.py --live` (with `RAPHAEL_INSTANCE`), `e2e_phase3.py` and a
    real screenshot/clipboard/volume pass still need an integrator go on the
    Windows host — expected to pass unchanged: legacy response shapes
    (`result.b64/bytes`, clipboard string result, exact `E_LOCK_BUSY`) were
    kept for them.
  - Test invocations that work on this machine: `tests/.venv` for
    `tests` + `body/win/tests` + `brain/tools/pc/tests`; `brain/.venv` for
    `brain/**` (no PyYAML in tests/.venv).
