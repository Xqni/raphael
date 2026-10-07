# tools-memory — status

Updated: 2026-10-07 (wave 3 COMPLETE — handoff, awaiting merge pos 9)

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

**Rule-4 stop (rebase):** rebasing onto current origin/main conflicts in `PROGRESS.md` (integrator-owned; their commit `6d174f0` sits on my branch, content not on main). Rebase ABORTED untouched, request filed: `tools-memory__to__integrator__progress-md-rebase-conflict.md` (union resolution proposed). Branch intact at the handoff commit; no re-rebase attempts until answered.

## In progress
- —

## Blocked
- `docs/requests/tools-memory__to__brain-core__loop-memory-skills-injection.md` (Status OPEN) — loop-side injection of memory/skills as untrusted context + `schedule.arm_all(loop)` startup call + `plugins.load_enabled()` wiring. My side ships the exact API; integration needs brain-core. Until then memory is build-verified but not injected end-to-end.
- Rebase blocked on the PROGRESS.md request above (work itself unblocked).

## Next
- Post `wave_done` → idle (coord mode); merge at position 9; flip request statuses when owners do (request #1 code-verified as landed, awaiting brain-core's formal flip).
- Wave 4 (skill aging/audit, memory export/delete) and Wave 5 (predator-style acquisition) — only when WAVES.md says so.

## Test output (real runs only — never claim unrun tests)
- `./brain/.venv/bin/python -m pytest -q brain/memory/tests` → **116 passed in 2.74s** (2026-10-07, task 4 final)
- `./brain/.venv/bin/python -m pytest -q brain/tests` → **134 passed, 1 warning in 10.09s**
- `cd tests && ./.venv/bin/python -m pytest -q .` → **187 passed, 9 xfailed, 2 xpassed, 1 warning in 34.04s** (= qa baseline)
- Earlier in-wave runs (each after the task that produced them): 10 → 31 → 41 → 58 → 86 → 106 → 116 memory tests; brain 134 + root 187 re-verified green after every shared-schema/registry change.
