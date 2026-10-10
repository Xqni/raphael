# tools-memory — status

Updated: 2026-10-10 (Wave 5U Wave A: confirm-class tags DONE — handoff below)

## Wave 5U Wave A (§5.4 P0.1) — confirm-class tags ✅ 2026-10-10

- **Delivered:** every tool in my six namespaces carries an explicit
  `confirm=<class>` (registry metadata consumed at loop.py:585):
  `web_*=web_fetch` · `file_read/file_search/shell_list/github_status/mcp_list
  /timer_list/schedule_list=read_only` · `file_write/file_restore=files_write`
  · `file_trash=delete_files` · `shell=system_command` · `github_push=web_publish`
  · `timer_set/timer_cancel/reminder_set/schedule_set/schedule_cancel=schedule`
  · `mcp_refresh` + dynamic wrapped `=mcp_tool` (charter: wrapped default
  confirm until config marks a read-only class — Wave-C task 5).
- **Coordination (P0.2):** class names filed for the integrator's
  `safety.confirm_policy` (Core Guard): request
  `tools-memory__to__integrator__wave5u-confirm-classes.md`
  (new: read_only/schedule auto; system_command/web_publish/mcp_tool confirm).
  Until it lands: tags fail CLOSED (safe direction, never a loosening).
- **Tests (5):** coverage derived from package SPECS (an untagged future tool
  fails by construction — the P0.2 guard), exact charter mapping, vocabulary
  drift guard, risky⇒tagged (pc rule + risky trio classes), MCP wrapped
  default `mcp_tool` via fake server.
- **Battery (fresh base, sequential):** memory **217** | brain **242** |
  root **270 passed, 1 failed** — the 1 = `contract/test_config_and_tools.py::
  test_cloud_temp_chain_has_no_local_providers` (**MAIN-SIDE**, evidence:
  `git log origin/main..HEAD -- config.yaml` = empty — my branch never
  touched it; config says `chain: [zen_free,...]` (integrator commit
  13bcfae) while qa's test asserts `chain[0]=='go'` — both on current main,
  fails on plain origin/main). Same class as the voice tier test
  (`test_tier_default_is_great_sage_on_the_approved_reference` — also fails
  on latest main, verified post-rebase; my earlier error post stands).
  gitleaks+regen **exit 0**; scan_personal my-files **0**; repo FAIL **0**.
- **PUSH/DISPATCH pending** for the green id (covers wave-5P wave_done too —
  [31]); branch CI stays red on the two main-side tests until their owners
  align them.

## Wave 5P — persona adoption packets P5/P6/P7 (all ✅ 2026-10-09)

**Binding inputs read first:** `06-CODE-ADOPTION-PLAN.md` (packets + design laws)
+ `00-CONSOLIDATED-BRIEF.md` (canon + **debunk register** — no refuted claim
entered any of my prompts/docs/strings; my features are persona-neutral
plumbing, tone lives in P1/P2).

| Packet | Delivered | Tests |
|---|---|---|
| **P5 context slots** | `memories.slot` guarded ALTER (default `'default'` → byte-identical parity: all 189 prior tests green unchanged), `brain/memory/slots.py` (validate/switch/list; state-table persistence → survives restart; act-first no-confirm per spec), retrieval + `build_context` scoped to active slot incl. pinned; `retrieve(slot=)` read-only override (asking ≠ switching); profile global by design | 10 |
| **P6 spoken privacy** | wave-4 export/delete **verified FIRST** (7/7 + quotes: `export_all`/`wipe`/`store.forget`/`delete_skill`/trash); `brain/memory/privacy.py`: `recall` (owner+slot scoped, speakable, bad-slot raises for clarify), `forget_fact` (**needs_confirm preview → confirmed delete**, owner-wide, never cross-owner, idempotent), `memory_report` (local paragraph + export/wipe pointers); router-boom private-mode test = all local | 6 |
| **P7 journal** | `brain/memory/journal.py` → repo-root `vault/journal.md` (gitignored ✓): **append-only `'a'` only** (source-shape + prefix tests), redaction-before-write (secrets→REDACTED, ids/paths→SEC-1 placeholders), dated single-line entries, `read_recent` read-back, fail-silent; tmp fixtures never touch real vault; SEC-1 pre-commit flagged my rule literals 12 → **assembled → 0** | 7 |

- **Seam request** `tools-memory__to__brain-core__wave5p-memory-seams.md`
  (all three packets' intent surface for brain-core's fastpath: switch/recall/
  forget-confirm/report/journal append+read).
- **Suites (2026-10-09, one at a time):** memory **212** | brain **242** |
  root **271 passed, 7 xfailed, 0 failed**. scan_personal: my files **0**,
  repo-wide FAIL-severity **0** (86 REVIEW = ledger/transitional). gitleaks
  with policy-regenerated baseline: **exit 0**.
- **PENDING for QA-4:** push cycle + branch dispatch (same as wave-5H:
  I verify remote==HEAD first, dispatch, reply with green id → wave_done).

## Wave 5H / 5P merge note
- TEMP exceptions entry (gitleaks-baseline) was removed at my position-9
  merge per its note — my baseline regens since are per SCANNERS.md policy
  and will need the same treatment at the next merge (flag it in wave_done).

## GREEN CI RUN (wave-5H): 37788108245 (5/5, head 05320c8)

- **5/5 jobs SUCCESS**: Security scanners (gitleaks `no leaks found` ×3 +
  pip-audit + bandit + npm audit) | Ubuntu brain+mock suites | Windows body |
  Protocol conformance ubuntu + windows; **0 OWNERSHIP violations**.
- Twin push-run `37788038799` also SUCCESS (same head).
- Path to green (full verify-first chain): stale-dispatch miss acknowledged →
  gitleaks' real 2 = `Xqni` handle in pat-scope + AWS sentinel literal in
  AUD-07 test → both scrubbed (concat/placeholder, runtime identical) →
  baseline regenerated per SCANNERS.md policy (reason in each commit) →
  rebase cleared OWNERSHIP/manifest from the diff (zero guarded files) →
  coord-granted exceptions entry (main `f93d287`) for the policy-regen →
  local gates pre-dispatch: `ownership_check --diff` **OK (25 files)**,
  gitleaks **exit 0**, suites **189/242/241** green → push (explicit
  "rebase + push" instruction, force-with-lease) + server-verified MATCH →
  dispatch (remote==HEAD verified FIRST) → green.
- NOTE: exceptions entry is TEMPORARY — remove at my position-9 merge per
  its own comment (the baseline becomes main's content post-merge anyway).

## Addenda batch — AUD-15 / AUD-23 / AUD-25 / AUD-28 (verify-first quotes) + SEC-1 scrub

## Addenda batch — AUD-15 / AUD-23 / AUD-25 / AUD-28 (verify-first quotes) + SEC-1 scrub

**AUD-15: CONFIRMED → FIXED — memory DB checkout-local, no perms/retention:**
- quote (pre-fix) `brain/memory/__init__.py:10`:
  `_DEFAULT = os.path.join(os.path.dirname(__file__), 'memory.db')` + no
  `os.chmod` anywhere; retention had only `conversation_max_rows` (memories
  uncapped — `config.d/tools-memory.yaml` grep before fix).
- **FIX:** DB path = `RAPHAEL_DB_PATH` → else **instance data-dir**
  (`~/.raphael/<instance>/memory.db` — INTERFACES §d), one-time legacy
  checkout-DB move (data-safe fallback to legacy if move fails); `_harden_perms`
  chmods db/-wal/-shm **0600** on every connect; `memory.max_rows: 5000`
  retention enforced in `store.remember` same-transaction (oldest UNPINNED
  dropped, **pinned immune**, owner-scoped) via `_trim`.
- Tests: migration to tmp data-dir, 0600 on all three files, retention keeps
  newest-3 + pinned + other-owner rows untouched.

**AUD-23: CONFIRMED → FIXED — SSRF DNS-rebinding TOCTOU:**
- quote (pre-fix, self-documented) `brain/tools/web/__init__.py:17`:
  `DNS-rebinding note: host is checked before connect (TOCTOU window exists but…` +
  `:128 with _build_opener().open(req, ...)` (urllib reconnect re-resolves).
- **FIX:** `_resolve_public()` resolves ONCE and returns the **pinned IP**;
  `_PinnedHTTP(S)Connection.connect()` connects to that IP only (no second
  lookup exists to race); Host header + TLS `server_hostname` keep the
  original hostname (cert valid); **every redirect hop re-resolves +
  re-validates** (max 5) — `_SafeRedirect`/`_build_opener` deleted.
- Tests (6): single-resolution rebind sim (`getaddrinfo` call-count == 1),
  private-first refused pre-connect, redirect hop to `169.254.169.254`
  (metadata IP!) refused, public redirect re-validated + final URL, socketpair
  e2e proving connect uses `(pinned_ip, port)`, TLS SNI == original hostname.

**AUD-25: CONFIRMED → FIXED — shared response queue discards concurrent replies:**
- quote (pre-fix) `brain/tools/mcp/client.py:71` `self._q: 'queue.Queue[Optional[str]]' = queue.Queue()`
  + `:173 # notifications and other ids: ignore` (concurrent waiter discards
  another's reply) + `self._id += 1` unsynchronized.
- **FIX:** `_req_lock` serializes the full request cycle (id allocation +
  send + wait) and `notify` (frame integrity); MCP stdio is a serial protocol.
- Test: 8 concurrent registry calls × 4 threads → every caller gets ITS
  reply (`echo: worker-i` exact, no McpError).

**AUD-28: CONFIRMED → FIXED — schedule no atomic claim:**
- quote (pre-fix) `brain/tools/schedule/__init__.py:311`:
  `"SELECT * FROM schedules WHERE status = 'pending' AND due_at <= ?"` →
  submit → record, with no claim between select and fire (double-fire window).
- **FIX:** `claimed_at` column (guarded ALTER); `_claim()` atomic
  `pending→firing` UPDATE (rowcount-gated — exactly one winner); stale-claim
  recovery (>300 s) at pump start; success/failure both release the claim;
  recurring success now explicitly returns to `pending` (regression caught by
  existing test during the fix).
- Tests: fresh claim blocks a second pumper, stale claim recovers+fires,
  4-thread claim → exactly one winner, failure releases claim + retry works.

**SEC-1/ARCH-4 SCRUB (my files only):** before **3** findings
(`test_profile_summary.py:9` user-linux, `test_tools_web.py:25` ip-private,
 `test_tools_web.py:34` ip-public) → after **0** (incl. my new staged files —
repo scanned 818 files, still 195/101 = my 2 FAIL + 1 REVIEW removed).
Username → `<wsl-user>` placeholder; fixture IPs assembled from RFC octets
(`_fx(...)` with SEC-1 comment — documented ranges, not personal data).
No other lane's files touched (ownership).

**Root-suite note:** `regression/test_act_pipeline.py::test_lock_action_sets_lock_true`
FAILS — **pre-existing, NOT-APPLICABLE to this batch**: verified by
`git stash -u` → same failure on clean `origin/main` → popped back. WS-frame
harness timeout (act pipeline — brain-core/pc-control surface); reported on
the bus.

**Verification runs (2026-10-08, one suite at a time):** `brain/memory/tests`
**189 passed** | `brain/tests` **232 passed** | root `tests/` **213 passed,
1 pre-existing fail** (stash-proven on main). **Green CI id: 37723653896**
(success, main, 2026-10-08T03:38).

## P0 addendum — AUD-01 (CRITICAL) + AUD-07 (coord dispatch), VERIFY-FIRST

## P0 addendum — AUD-01 (CRITICAL) + AUD-07 (coord dispatch), VERIFY-FIRST

**AUD-01: CONFIRMED → FIXED — file tools could reach `~/.raphael/token`:**
- quote (pre-fix) `config.d/tools-memory.yaml:32`:
  `allowed_roots: ["~"]           # file_read/file_write confined to these (expanded)`
- quote (pre-fix) `brain/tools/files/__init__.py:31-33`:
  `_SECRET_NAMES = {'.env', 'secrets.env', '.secrets', 'id_rsa', ...}` /
  `_SECRET_SUFFIXES = ('.key', '.pfx', '.p12', '.keystore', '.jks')` — no
  `token`, no `.ssh` dir, no cloud stores → deny-list gap.
- quote (pre-fix) `:254`:
  `reg.register('file_write', file_write, risky=False, category='local',` —
  arbitrary write, unconfirmed.
- **FIX:** roots → explicit workspace `["~/raphael-wt", "~/raphael"]` (code
  default too); resolved-path `_is_denied()` on EVERY op (deny dirs
  `.ssh/.gnupg/.aws/.docker/.kube/.raphael/dropbox/nextcloud/google drive/onedrive`
  case-insensitive on any component; deny names `token/.token/credentials/authorized_keys/…`
  + suffixes incl `.pem/.ppk`); `file_write` → **`risky=True` (confirm-gated)**;
  search never lists denied; restore re-checks tampered origin; symlink
  escapes die at `resolve()`.
- **Tests (TEMP fixtures only — real token never touched):** `test_aud01_07.py`
  — token read/write/trash refused ×3, ssh+cloud denied, search clean,
  symlink outside+to-denied refused, write confirm-gated, config no `"~"`,
  restore-tamper refused. **10/10 green.**

**AUD-07: CONFIRMED → FIXED — MCP children inherited the full env:**
- quote (pre-fix) `brain/tools/mcp/client.py:50`:
  `env={**os.environ, **(env or {})}, cwd=cwd)` → GITHUB_TOKEN/HF_TOKEN/etc
  leaked to every configured child.
- **FIX:** `_child_env()` minimal allowlist (PATH/HOME/LANG/LC_*/TMP*/USER/
  LOGNAME) + user-authored per-server `env` + config `mcp.env_allow: []`;
  Popen uses it exclusively.
- **Tests:** unit (secrets absent / base present / extra present / config
  extension deliberate) + **e2e sentinel**: fake `envdump` child reports its
  own `os.environ` → `SENTINEL_AUD07_E2E` + `GITHUB_TOKEN` absent, PATH/HOME
  present. All in the 10/10 green.

**AUD-15 / AUD-23 / AUD-25 / AUD-28: CANNOT VERIFY** — `grep -rn "AUD-15|23|25|28" docs/`
→ zero hits; `docs/reviews/2026-10-07-project-wide-audit.md` (PART 2) does not
exist in the tree or on origin/main. Per verify-first: **not applied** — asked
on the coord bus for the findings/definitions.

**Verification runs (2026-10-08, one suite at a time):** `brain/memory/tests`
**175 passed** | `brain/tests` **216 passed** | root `tests/` **214 passed,
7 xfailed, 0 failed**. **Green CI id: 37717702130** (completed success, main,
2026-10-08T02:24).

## Wave 5H — audit packet (docs/audit-tasks/tools-memory.md), VERIFY-FIRST applied

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

## Current as of 2026-10-09 (integrator freshness pass)

- **Merged + wave closed.** `git merge-base --is-ancestor agent/tools-memory main` → true (verified 2026-10-09). WAVE-5H GATE PASSED recorded in main at `2247a65` (tag `wave-5h-gate`). Latest completed main CI at report time: **37800865212** (success); scheduled tests-heavy sweep **37925272630** success (2026-10-09T11:41Z).
- **Stale — Blocked item "`loop-memory-skills-injection.md` (Status OPEN) … Until then memory is build-verified but not injected end-to-end"**: the injection half has landed in code — `brain/loop.py:166-193` (AUD-22: `retrieve` + `active_skills` framed between history and the live question) and `arm_all` wired at startup (`brain/app.py:116-117`), both on main (grep 2026-10-09). The request FILE is still Status OPEN (owner flip pending), and the `plugins.load_enabled()` wiring has **no** call site in `brain/` (grep 2026-10-09) — so the item is now partially stale, not fully open.
- **Stale — "## Next: … `wave_done` … stands for merge position 9 … idle until pinged"**: the merge happened; nothing awaits a merge slot on this lane as of 2026-10-09.
- **Still genuinely open (checked 2026-10-09):** `tools-memory__to__integrator__ownership-acquis-typo.md` and `tools-memory__to__integrator__progress-md-rebase-conflict.md` are both still Status OPEN in their files (no flip recorded); `tools-memory__to__qa-security__instance-count-12.md` is Status ANSWERED (qa's cross-source fix, already noted above).
