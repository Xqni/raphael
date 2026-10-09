# docs/requests Status Audit — integrator freshness pass (2026-10-09)

Scope: all 112 files in `docs/requests/*.md` on `main` (head 9e7c052).
Method: read each OPEN request's Status + "What" acceptance criteria; verified against
main with git grep/git log, exact file:line citations, and cheap pinned-test runs
(`brain/.venv/bin/python -m pytest -q`, ≤120s each). Conservative rule: flip only when
the exact file/flag/test the request demands demonstrably exists on main.

Counts: **31 flipped (category a)** · **20 genuine open (category b)** · **60 already fine (category c)**.
Personal scan: `python3 scripts/scan_personal.py` → 0 FAIL-severity across the tree;
the 31 touched files are the only modifications made (no commits, no staging).

Notes on method edge cases:
- 14 `brain-core__to__*` files carry the Status inline ("From: … Status: …"), not on a
  `^Status:` line; counted correctly.
- 11 files have NO Status field at all (mostly `brain-core__to__*` heads-up/review notes
  such as `brain-core__to__integrator__confirm-hardening.md`) — not OPEN, left untouched,
  listed under (c) as no-status-line.
- xfail tripwires were treated as ground truth ONLY when the test is client/state-based.
  `tests/test_dryrun_vocation…` counter-example: `test_dryrun_veto_is_clean_for_this_lane`
  XPASSED, but only because qa-security's branch currently has no diff touching its own
  lane docs (diff-dependent test, no carve-out code exists) → request kept OPEN.

---

## (a) Flipped: OPEN → status-update appended (31)

Each file got an appended `## Status update (integrator freshness pass 2026-10-09)`
section; the original Status line is intact.

| Request | Evidence |
|---|---|
| brain-core__to__integrator__arch5-profile-shape-design | design adopted: `config.yaml:183-199` `cloud` + `hybrid` presets, comment "ARCH-5 dormant presets (integrator-approved 2026-10-08 … brain-core co-share)"; `config.yaml:9` documents cloud_temp as CURRENT primary |
| brain-core__to__integrator__notice-events | `docs/PROTOCOL.md:56` `notice` row ("additive, 2026-10-07 integrator-approved"); `brain/notice.py` exists; boot emitter `brain/app.py:134-138`; merge record 7f0b6e8 |
| brain-core__to__integrator__output-formats-and-job-kinds | `docs/PROTOCOL.md:57` `answer` row, `:58` `report` row (caps as proposed), `:55` `job_event` kind+parent; `brain/jobs/engine.py:185` KINDS, `:213` `submit_fanout`; test `brain/tests/test_job_concurrency.py:346` |
| brain-core__to__voice__speak-feed-pipeline-coordination | in-file voice Answer (2026-10-08) + pre-roll landed `brain/voice/tts.py:5-7,730-742` (`RAPHAEL_TTS_PREROLL_S`); remaining half (streamed batching) also landed `brain/loop.py:294-306` |
| evolution-persona__to__brain-core__shadow-instance-row | `docs/INTERFACES.md:81` shadow row (8911/9411/`~/.raphael/shadow/`); sanctioned in `tests/ownership_exceptions.txt` |
| evolution-persona__to__integrator__sec7-core-guard-expansion | Part B: `tests/core_guard.py:25-41` cites this request, covers conductor/workflows/OWNERSHIP/boot scripts/act_powershell/evolution; Part C write-side: `tools/conductor/coord.py:293-312` MSG_MAX=4000 ("SEC-7 Part C rule 2"), DATA_MAX, `_REF_RE`, `_validate_event`. Prompt-side remainder tracked in coord-prompts-untrusted-framing (still OPEN) |
| infra__to__integrator__sec5-env-dev-and-docs | all 4 items: `.gitignore:3-5`; `docs/LAUNCH.md:88-93` SEC-5 paragraph; `docs/TROUBLESHOOTING.md:11-15` + `docs/TODO.md:34` narrow-rule-first; `config.yaml` supervisor `wsl_user` ARCH-4 comment |
| orb__to__brain-core__orb-state-transitions | `brain/orbstate.py` (`VALID_STATES` :33-34), `brain/ws.py:791-792` listening, `:939,955` + `app.py:97` error, `app.py:111` starting, `loop.py:606` acting, `:381-408,445-466` speaking; `test_orb_lifecycle.py::test_every_lifecycle_state_emitted` 1 passed (run 2026-10-09) |
| pc-control__to__integrator__core-guard-act-powershell-repin | `body/win/act_powershell.py:24,232` exact proposed offload diff; `tests/core_guard_manifest.json` pins `b0e580505281fc6a…` = proposed sha = file's current sha256 (verified 2026-10-09); re-pin reconfirmed by 48f74f3 |
| pc-control__to__integrator__ownership-grant-protocol-aud05 | `tests/ownership_exceptions.txt:25` `docs/PROTOCOL.md =pc-control,brain-core` citing this request; acceptance verified: `python3 tests/ownership_check.py --lane pc-control --files docs/PROTOCOL.md` → ownership OK, rc=0 |
| qa-security__to__brain-core__awaiting-confirm-status | `brain/loop.py:523` `store.transition(rowid, 'awaiting_confirm', ...)`; both pinned tests pass 2/2 (run 2026-10-09) |
| qa-security__to__brain-core__mock-tts-pidfile-guard | `brain/tests/conftest.py` autouse `_hermetic_tts` (VoiceStack.speak/warmup patched per test, path-guarded); `brain/app.py:37-45` `_pidfile_targets()` empty under PYTEST_CURRENT_TEST |
| qa-security__to__brain-core__orb-state-emission | same orbstate landing as orb-state-transitions; pinned `test_every_lifecycle_state_emitted` passes; xfail removed |
| qa-security__to__brain-core__risky-tool-confirm-gate | `brain/loop.py:576-587` `classify(text, tool=tool_name)` + registry `risky` → `tool_decision`; AUD-09 confirm.py hardening per coord [58] |
| qa-security__to__brain-core__tool-call-extraction | `brain/loop.py:67-100` balanced-brace `_extract_tool_call` (docstring names the old regex bug); pinned test now STRICT and passes: `tests/regression/test_act_pipeline.py:101-103` (run 2026-10-09) |
| qa-security__to__brain-core__untrusted-tool-results | `brain/tools/__init__.py:245-251` `as_untrusted()`; wrapped at `brain/loop.py:840` with `[:result_chars]` cap-before-wrap; extraction scoped to `assistant_text` (`loop.py:766`); commits a2cbe87/6ce1bac ("untrusted feedback/wrap") |
| router__to__brain-core__fastpath-open-search-mapping | `brain/fastpath.py:135` `_search`, `:194-198` registrations, `:116` youtube-and-search redirect — near-verbatim proposal |
| router__to__brain-core__surface-usage-in-status | `brain/app.py:292-300` `usage_status()` in try/except + `'router': router_block` |
| router__to__brain-core__wire-foreground-hook | `brain/app.py:79-87` `_set_fg(_fg.provider)`; `brain/foreground.py` push-cache provider (fail-closed) |
| router__to__integrator__interfaces-purpose-enum-analysis | `docs/INTERFACES.md:15-16` purpose enum extended with analysis\|simulation + purpose_roles tier note (as proposed) |
| router__to__integrator__vision-free-model-gap | option 2 landed: `config.yaml:48` `allow_vision_paid: true` (USER APPROVAL noted) + `:49` `vision_paid_daily_cap_usd: 1.00` hard stop; `config.d/router.yaml` go_vision rpm/tpm |
| tools-memory__to__brain-core__confirm-gate-tool-risky | same gate: `brain/loop.py:576-587` |
| tools-memory__to__brain-core__loop-memory-skills-injection | all 3 points: `brain/loop.py:165-207` `_external_context` (retrieve + build_untrusted_block + include_personal gate + active_skills), `brain/app.py:116-117` `arm_all()`, `brain/tools/schedule:295` `engine.submit(..., source='system')` |
| tools-memory__to__integrator__ownership-acquis-typo | `docs/OWNERSHIP.md:28` spells `ACQUISITION.md` correctly (3777788 "typo P->I") |
| tools-memory__to__integrator__ownership-audit-docs | `docs/OWNERSHIP.md:28` lists `docs/security/pat-scope.md` + `docs/skills/ACQUISITION.md` ("integrator grant 2026-10-08"); branch CI 37788108245 0 ownership violations; merged 0fc8a9f |
| tools-memory__to__integrator__progress-md-rebase-conflict | resolved option (a): rebase passed post-resolution (05320c8 "post-rebase … ownership_check --diff OK 25 files"); merged to main 0fc8a9f (position 9) |
| voice__to__brain-core__streamed-sentence-batching | `brain/loop.py:294-306` `_SentenceSpeaker` batch_size/batch_wait_s, comment cites "voice request APPROVED 2026-10-07" |
| voice__to__brain-core__stt-outage-subtitle | `brain/ws.py:874,947,958` `stt_outage_subtitle` broadcast in `_on_audio_end` error paths |
| voice__to__brain-core__test-isolation-hygiene | `brain/tests/test_config.py:66` `monkeypatch.setenv`; import-time patch replaced by `_hermetic_tts` fixture |
| voice__to__brain-core__utt-continuation-merge | `brain/ws.py:765-766` continuation append ("voice request ACCEPTED 2026-10-08"); body half `body/win/audio_in.py:87-114`; PROTOCOL row `docs/PROTOCOL.md:38` (continuation, granted 2026-10-08) |
| voice__to__router__turbo-stt-for-purpose-transcribe | `brain/router/roles.py:32-35` STT slot weights turbo/distil → whisper-large-v3-turbo; comment cites this request |

## (b) OPEN and genuinely not done (20) — left untouched

| Request | Why still open (verified) |
|---|---|
| evolution-persona__to__integrator__orb-state-minds-field | no `minds` key in `docs/PROTOCOL.md`/`docs/INTERFACES.md` (only "parallel-minds tag" wording on job_event kind) |
| evolution-persona__to__integrator__task-kind-analysis-simulation | PARTIAL: shape_map landed (`config.yaml:167-168` analysis:octagram/simulation:triangle, "approved 2026-10-07") and engine KINDS landed (`brain/jobs/engine.py:185`), but `docs/PROTOCOL.md:119` task_kind enum still `system\|files\|web\|media\|llm\|gui\|none` — the §8/§e vocabulary extension is missing |
| orb__to__brain-core__stt-source-in-status | no `stt_source` in brain code; `body/orb/src/main/main.js:651` still notes the brain "yet publish an stt_source flag" |
| orb__to__integrator__backing-disc-default-zero | `config.yaml:150` still `backing_disc_alpha: 0.25`; `docs/ORB_REBUILD_TASK.md:60` still documents 0.25 default (only the lane fragment `config.d/orb.yaml:14` is 0.0, as the request said) |
| pc-control__to__brain-core__activity-endpoint | no `/activity` routes anywhere in `brain/` (app.py has no activity handler) |
| pc-control__to__brain-core__aud11-open-path-mappings | no `open_path`/`uia` in `brain/confirm.py::TOOL_ACTION`; no path-routing in `brain/fastpath.py::_open` |
| pc-control__to__integrator__config-confirm-categories-aud11 | `config.yaml:105-113` safety.confirm_actions still the original 8 — no `open_arbitrary_file`/`gui_submission` |
| pc-control__to__integrator__protocol-activity-act | `activity` not in `docs/PROTOCOL.md` §7 allow-list (grep 0 hits) |
| qa-security__to__brain-core__disable-fastapi-docs | `brain/app.py:179` `FastAPI(lifespan=lifespan)` — docs still on; xfail remains `tests/security/test_core_guard_and_secrets.py:221` |
| qa-security__to__brain-core__lock-busy-code | no `E_LOCK_BUSY` mapping in `brain/loop.py`; xfail remains `tests/regression/test_act_pipeline.py:84` |
| qa-security__to__brain-core__rest-rate-limit | `token_auth` still bare; xfail remains `tests/contract/test_auth.py:156` `test_rest_auth_fail_rate_limited` |
| qa-security__to__brain-core__voice-confirm-wiring | wiring code exists (ws.py:540-547, confirm.py voice_safe/rejected_channel) BUT both pinned tests still FAIL: `test_spoken_yes_resolves_pending_confirmation` + `test_voice_channel_grant_is_refused_for_risky_job` → "2 xfailed" (run 2026-10-09) |
| qa-security__to__integrator__circuit-open-code | `E_CIRCUIT_OPEN` absent from `docs/PROTOCOL.md` §10; xfail remains `tests/contract/test_error_codes.py:130` |
| qa-security__to__integrator__coord-prompts-untrusted-framing | 0 "untrusted" hits in `tools/conductor/prompts/*.md` (write side landed; consumer side unfenced) |
| qa-security__to__integrator__handler-dryrun-lane-doc-carveout | no per-lane carve-outs in `tools/conductor/handler_dryrun.py` (`owners_of` unchanged); the pinned test only XPASSED because the lane diff currently touches no lane docs — diff-dependent, not the fix |
| qa-security__to__integrator__voice-confirm-channel | no `channel` field on `confirm_resp` in `docs/PROTOCOL.md`; enforcement test still xfails |
| qa-security__to__integrator__ws-query-token | `brain/ws.py:178` still accepts `ws.query_params.get('token')` |
| tools-memory__to__brain-core__wave5-feeding-report-cache | no call site for `build_context` (kind-aware feeding) or `reports.save_report` outside `brain/memory/**` tests — the hooks are unwired |
| voice__to__brain-core__speak-warn-notices | `brain/notice.py` has no speak/`notice_spoken_text`/`speak_notice` wiring — notices broadcast only |
| voice__to__brain-core__voice-confirm-wiring | same pinned xfails as qa's twin request — both still xfail (run 2026-10-09) |

## (c) Already fine — no action (60 + 11 no-status)

- 60 files already carrying a non-OPEN resolution (DONE / ANSWERED / ACCEPTED / APPROVED /
  CO-SIGNED / SUPERSEDED / FIXED+VERIFIED), incl. all `qa-security__to__infra__*` DONE
  slices, `infra__to__qa-security__ci-*`, the pc-control DONE batch, router ANSWERED
  batch, `tools-memory__to__qa-security__instance-count-12`, etc. — verified coherent
  with main, none re-verified line-by-line (out of flip scope).
- 11 files with NO Status field (brain-core heads-up/review notes: confirm-hardening,
  pidfile-out-of-timo→pidfile-out-of-tmp, rest-say-endpoint, aud09-confirm-manifest-repin
  (APPROVED-BY-DECISION inline), etc.) — not OPEN; left untouched.
- README.md (legend file) — untouched.

## Takeaways for the integrator

1. The heaviest genuine gaps are all in the confirm/security lane: voice-confirm wiring +
   channel contract (2 requests, pinned xfails red), REST rate limit, FastAPI docs,
   E_LOCK_BUSY mapping, ws query-token, E_CIRCUIT_OPEN catalog row.
2. Two partials worth a 10-minute close: PROTOCOL §8 task_kind enum (analysis/simulation)
   and the `minds[]` orb_state field — both code-complete on the brain side already.
3. `wave5-feeding-report-cache` is the only tools-memory wiring gap left (kind-aware
   `build_context` + `reports.save_report` call sites).
4. pc-control's F-3 chain (protocol-activity-act → activity-endpoint) is untouched end-to-end.
