# tools-memory — status

Updated: 2026-10-08 (Wave 5H audit packet: SEC-4 + F-2 done — handoff below)

## Wave 5H — audit packet (docs/audit-tasks/tools-memory.md), VERIFY-FIRST applied

**SEC-4: DONE (HUMAN applies the PAT) — report `CONFIRMED + ALREADY-DONE + NOT-APPLICABLE`:**
- **CONFIRMED (visibility tool forced Administration scope) — removed:**
  `brain/tools/github/__init__.py` (pre-fix, was line 194):
  `rc, out = _run(['gh', 'repo', 'edit', r, f'--visibility', v], timeout=60.0)`
  → `github_set_visibility` + `github_create_repo_public` (was line 136
  `argv.append('--public')`) **DELETED** — the namespace now registers exactly
  `github_status` + `github_push`.
- **CONFIRMED (creation) → human action:** register block was
  `reg.register('github_create_repo', github_create_repo, risky=False, ...)`;
  GitHub docs (*Permissions required for fine-grained PATs*): **`POST/user/repos`
  requires `Administration: write`** — impossible under the packet's NO-Administration
  token, so creation tools were removed = "user action" branch of SEC-4.
- **ALREADY-DONE (push confirm):** `reg.register('github_push', github_push, risky=True, category='local',`
  — every push confirm-gated in code.
- **ALREADY-DONE (tokens value-blind):** was line 119
  `token = 'set' if _have_token() else 'MISSING'` + line 91
  `return _TOKEN_RE.sub('***REDACTED***', str(text or ''))` — every gh/git
  output scrubbed; new test proves `github_status` with a real-shaped token in
  env never surfaces the value.
- **NOT-APPLICABLE (deletion/settings):** grep scan
  (`repo delete|repo archive|--allow-update|repo rename|gh api`) → only the
  visibility line matched; no deletion/settings tool ever existed.
- **DOC WRITTEN: `docs/security/pat-scope.md`** — fine-grained PAT, Selected
  repositories ONLY, Contents/Actions/PRs RW, NO Administration, NO org perms,
  expiry ≤90d, 6-step rotation, consequence table (creation/visibility =
  human), hygiene rules. Value-blind presence checker = existing `github_status`
  (quoted above). **ATTENTION post for the human to apply it.**
- Tests: `brain/memory/tests/test_tools_github.py` 9 tests (removal proofs,
  SPEC/registry sync, scrub, argv-no-shell).

**F-2: DONE (design + stubs, disabled) — report `CONFIRMED → BUILT`:**
- **CONFIRMED (missing):** `ls brain/memory/` → no `acquisition.py`; no
  `acquisition` string anywhere in `brain/memory/` or `config.d/` (grep = none).
  Existing infra verified live: `skills.py:324` `WHERE status = 'published' AND confidence >= ?`
  (the gate F-2 must feed).
- **BUILT:** `docs/skills/ACQUISITION.md` (5-stage design: observe → sandbox
  draft in `skills/.drafts/` → injected-runner test → human approval →
  `finalize_draft` move + human two-step publish; security invariants; config
  table). `brain/memory/acquisition.py` — every public fn gates on
  `skills.acquisition_enabled` (default **false**, config fragment) →
  `{'enabled': False}` + zero side effects; no execution primitives anywhere
  (`test_draft` without a runner = `'skipped'`, never auto-executes);
  inherits create_skill dedup/name validation; NO publish function by design.
- Tests: `brain/memory/tests/test_wave5_acquisition.py` **8 mock tests**
  (flag-off zero-effects, threshold counting + signature normalization,
  sandbox-not-live + gate exclusion + dedup bump, not-ready, no-runner skip,
  injected runner pass/fail, human two-step activation only, flag-off-midway).

**Packet scope note:** the earlier 4-item message's items 2 (injection fixture
battery) and 3 (memory privacy: retention/per-category/redaction) are NOT in
the packet table ("Scope = ONLY the IDs below") — not built in this pass;
existing coverage already includes shell-registry proofs
(`test_tools_shell.py`: argv-only/metacharacter-literal/unknown-script),
marker-neutralization probes, and token scrubbing. Say the word and I'll run
items 2/3 as a follow-up batch.

**Wave-5H verification runs (2026-10-08, one suite at a time per Rule 14):**
`brain/memory/tests` **165 passed** | `brain/tests` **194 passed** |
root `tests/` **214 passed, 7 xfailed, 0 failed** (instance-count red gone —
qa's fix landed). CI green reference for QA-4: run **37711404220**
(`completed success`, main, 2026-10-08T01:08).

## Wave 5 (MERGED — queued pos 9; call-site requests ride with it)

## Wave 5 (current_wave=5)

**DONE — lane checklist item, 10 new tests:**
1. **Kind-aware memory feeding:** `retrieval.kind_budget(kind)` (analysis `k=10/8000c`, simulation `k=4/3000c`, default `5/4000c`; config `memory.kind_budgets` overrides; unknown kind → default; `k=0` → inject nothing) + `build_context(query, kind=, include_personal=)` — the ONE call the loop needs: retrieve + untrusted framing + marker neutralization + personal gate, fail-silent `''`.
2. **Report cache:** `brain/memory/reports.py` — `save_report` (PROTOCOL §3 caps re-enforced: summary≤500, sections≤10, heading≤200, text≤2000 — truncate-into-shape, fail-silent `None`), `find_reports` (whitelist-token overlap, operator-proof, owner-scoped), `recent_reports`/`get_report`/`clear_reports`; `reports` table added additively (old DB without it degrades quietly, `init_db` re-migrates — tested).
3. **Injection probes extended:** report-shaped marker spoof (`[/UNTRUSTED` in title, fake header in summary) neutralized with exact framing intact + structure unbroken (extends the wave-4 probe family).
4. **Call sites requested** (brain-core owns formats.py/loop.py): `tools-memory__to__brain-core__wave5-feeding-report-cache.md` (feeding via `build_context` + `save_report` on emit; references the still-OPEN injection request).

**Verification (2026-10-07):** `brain/memory/tests` **155 passed** | `brain/tests` **184 passed** | root `tests/` **203 passed, 1 FAILED** — the failure is `regression/test_instance_isolation.py::..._collision_free` (asserts 11 instances; INTERFACES has 12 after the approved `shadow` row 8911). **Verified pre-existing on plain origin/main** (my branch byte-identical to main for INTERFACES+tests) → request `tools-memory__to__qa-security__instance-count-12.md` + `error` post on the bus.

**Wave 5 done → task_done/test_result posted; awaiting brain-core's two call sites + merge.**

## Wave 4 (MERGED, gate `wave-4-gate` 10/10)

## Wave 4 (current_wave=4, gate: lane checkbox in docs/lanes/tools-memory.md)

**DONE — two batches, both green:**

1. **Hardening checklist (lane wave-4 item)** — 19 new tests:
   - *sqlite crash-safety*: SIGKILL mid-write → `integrity_check ok`, only whole commits survive (count % 50 == 0), `get_conn`/`init_db` stay usable, WAL preserved; concurrent parent+child writers (100 parent rows all survive); locked-DB `_persist` drops fast (~500 ms, <3 s asserted) then recovers — no hang, no corruption.
   - *FTS corruption recovery*: new `fts.integrity_check()` (external-content check) + `fts.rebuild()`; ghost-row and missing-entry probes detected+cured; retrieval now DEGRADES (FTS exception → keyword fallback + one-shot self-heal rebuild) and pinned rows ship even if both match paths die.
   - *Injection probes (7)*: memory smuggle stays one neutralized framed line (**framing-escape FIXED**: record text can no longer spoof `[UNTRUSTED`/`[/UNTRUSTED` markers), personal-split not bypassable, fake-frontmatter skill body stays body (draft, gate-closed), status strings strict, **bool confidence fail-open FIXED** (`confidence: true` was coercing to 1.0), plugin stringly-bool + path-name manifests fail closed.
   - *MCP failure modes (5)*: dead handshake reaped (no zombie, no cached client), death-after-initialize recorded, **wedged timeout child evicted+KILLED (fix)**, killed child transparently respawned next call, failed servers leak no dynamic tools.
2. **Session-brief wave-4 scope** — 10 new tests:
   - *skill aging*: `audit_skills()` demotes published+never-used+older-than-`audit_grace_days` (30) back to draft (file AND index updated, gate closes, nothing deleted); `find_duplicates()` detects on-disk duplicates at ≥0.82 (report-only — never auto-merges user-visible files); failed audit returns `{}` (never a clean-looking empty report).
   - *export/delete controls*: `export_all()` → typed JSONL (memory/turn/summary), owner-scoped, mode **0600**, local-only; `wipe(scope)` surgical (`memories` vs `conversations` vs `all`), owner-filtered for memories (PR #2404), invalid scope raises; **deliberately NOT registered as model tools** — destructive power stays with the user (CLI/UI wiring = infra/integrator).

**Post-rebase/verification runs (2026-10-07):** `brain/memory/tests` **145 passed** | `brain/tests` **164 passed** | root `tests/` **197 passed, 9 xfailed** — all after the pc-control wave-4 merge base.

**Wave 4 done → `wave_done` posted; awaiting merge / next wave.**

## Wave 3 (MERGED 9355dd5, gate PASSED `wave-3-gate`)

## Done

**(Wave 2)** plan written; 2 seam requests filed; WAIT state.

**Wave-3 start:** inbox handled, rebased (lane-doc + request-file conflicts resolved — both mine), AGENT_RULES 13/14/15 read, BUGS-WAVE2 reviewed (**no P0s assigned to this lane**).

**Task 0 — prep ✅:** seam audit (confirm-gate request #1 LANDED in loop.py:430-431 — verified on origin/main too), registry mechanism learned (`register(schema=)`, `SPECS`, `as_untrusted`, `validate_args`, discovery skips tests), `config.d/tools-memory.yaml` created (own namespaces only).

**Task 1 — memory core ✅:** `brain/memory/{schema,fts,store,retrieval,block,profile,summary,conversation}.py`:
- `conversation_turns` + the ACCEPTED brain-core producer seam (`on_turn` — exact signature, O(1) job path, bounded buffer + daemon flusher, fail-silent everywhere);
- `memories` + FTS5 (external content, sync triggers, availability DETECTED not assumed → keyword fallback same API);
- retrieval: pinned-always + BM25 + category boost + recency tiebreak (verified: boost actually re-orders, not just labels) + use counters + owner-scoped (PR #2404 discipline);
- `build_untrusted_block` (§9 DATA-ONLY framing, personal-category split for the privacy gate, exact `max_chars` budget incl. footer);
- profile view (identity|preference over `memories`, no second table) + conversation summaries (covers keyed on turn IDs — same-second turns can never be skipped; router facade only).

**Task 2 — skills/plugins ✅:** SKILL.md loader (frontmatter validation loud, `skills_index` sidecar counters, **confidence gate**: drafts/low-confidence NEVER in `active_skills()`, Jaccard ≥0.82 dedup bumps instead of duplicating, publish flow updates file+index with zero drift, review/delete); plugin manifest loader (scan NEVER imports, `enabled` fail-closed, refuses to shadow core tools, risky-default-true, user-authored authority only).

**Task 3 — tools ✅:** files (roots-confined, secret-refusing, **TRASH+restore roundtrip — no delete tool exists**), shell (fixed script registry REPLACES the wave-2 `shell=True` placeholder, `risky` kept, argv-only → no injection surface), schedule (timers/reminders/recurring persisted in `schedules`, pump thread → `engine.submit(priority='user_facing', source='system')`, failed fires retry → visible `error` rows), github (create-private **physically cannot go public** — separate risky tool; BLOCKED advisory on missing gh/token; token value-blind; output scrubbed), web (SSRF guard on every host + every redirect hop + final URL, content-type allow-list, size caps, DDG parse with uddg decode, summarize via `brain.router.chat` only, injection-hardened prompt).

**Task 4 — MCP ✅:** `brain/tools/mcp/{__init__,client}.py` — stdio JSON-RPC client (handshake/list/call, per-request deadlines, stderr tail, orphan-free close), config-only servers (model can NEVER add/configure one — `mcp_list`/`mcp_refresh` have ZERO params), allow-list fail-closed, risky default with USER-only confirm override, server schemas **TIGHTENED** to §b (never loosened; un-tightenable → skipped loudly), fake stdio server fixture drives e2e tests.

**Step 5 — integration check:** request #1 verified landed on origin/main (`classify(text, tool=tool_name)` + registry `risky`); conversation hook landed on main (brain-core side). **Request #2 (memory/skills injection + `arm_all` startup) still OPEN — brain-core's remaining work; the API it needs is built, tested, and on this branch.**

**Chrome/CDP:** NOT this lane — `docs/lanes/pc-control.md` wave-3 claims "browser/CDP"; no `brain/tools/browser/` namespace in tools-memory's OWNERSHIP. (Coordinator's generic wave-3 echo; my lane list is the 4 tasks above.)

**Rule-4 stop (rebase): RESOLVED per integrator decision 2026-10-07** — option (a) taken: the `6d174f0` PROGRESS bullet was confirmed a cwd-drift mistake (content landed on main at `ff8a4c7`). Rebase REDONE onto `origin/main` (tip `3fab0a6`; merge-base == origin/main; tree clean): only the conversation-hook request file conflicted (my decision to own → kept `Status: ACCEPTED`), `6d174f0` replayed empty → `--skip`ped as instructed (nothing lost — verified on main first). Request file kept as audit trail.

## In progress
- —

## Blocked
- `docs/requests/tools-memory__to__brain-core__loop-memory-skills-injection.md` (Status OPEN) — loop-side injection of memory/skills as untrusted context + `schedule.arm_all(loop)` startup call + `plugins.load_enabled()` wiring. My side ships the exact API; integration needs brain-core. Until then memory is build-verified but not injected end-to-end.
- ~~Rebase blocked on the PROGRESS.md request~~ → RESOLVED 2026-10-07 (decision option a; rebase redone, `6d174f0` skipped, see Done section).

## Next
- `wave_done` POSTED and rebase now clean → wave_done **stands** for merge position 9 (integrator's answer: "once synced+clean"); idle until pinged; flip request statuses when owners do (request #1 code-verified as landed, awaiting brain-core's formal flip).
- Wave 4 (skill aging/audit, memory export/delete) and Wave 5 (predator-style acquisition) — only when WAVES.md says so.

## Test output (real runs only — never claim unrun tests)
- **Post-rebase (2026-10-07, onto origin/main `3fab0a6` with voice/computer-use/orb/infra/qa merges):**
  - `./brain/.venv/bin/python -m pytest -q brain/memory/tests` → **116 passed in 2.95s**
  - `./brain/.venv/bin/python -m pytest -q brain/tests` → **152 passed, 1 warning in 12.00s** (= merged main baseline)
  - `cd tests && ./.venv/bin/python -m pytest -q .` → **197 passed, 9 xfailed, 1 warning in 35.58s** (= post-qa-merge baseline)
- In-wave runs (each after the task that produced them): memory 10 → 31 → 41 → 58 → 86 → 106 → 116; brain 134 and root 187 re-verified green after every shared-schema/registry change (pre-merge baselines).
