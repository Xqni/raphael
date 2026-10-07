# tools-memory — lane task list (owner: tools-memory lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/tools-memory.md. Requests to you: `ls docs/requests/*__to__tools-memory__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Wave 2 has no exit-criteria tasks for this lane: write the Wave 3 plan into docs/lanes/tools-memory.md (tool specs, folder skeletons, memory schema). → **PLAN IS §"Wave 3 plan" BELOW** (written 2026-10-06, verified against real tree: brain/tools/__init__.py, brain/loop.py:113-240, brain/confirm.py, config.yaml, addendum §2/§3/§4).
- [ ] Then: WAIT for current_wave to bump (AGENT_RULES §11) — check requests addressed to tools-memory meanwhile. **(current state: WAITING — current_wave: 2; two seam requests filed to brain-core, see docs/requests/)**

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [CONTEXT] Wave 2 merged; live gate 3/5 — gate bugs assigned in docs/BUGS-WAVE2.md (P0s belong to other lanes). Your wave-3 goals below stand.
- [SPEED] Remembered/derived answers come back near-instant (Rule 15).

## Wave 3 tasks (start ONLY when WAVES.md current_wave >= 3)

Execution order (each = implement → test → commit → update docs/status/tools-memory.md; stop after 2 failed attempts on one problem, §11):

0. **Prep:** ✅ DONE 2026-10-07 — rebased on origin/main (lane-doc conflict resolved: integrator Wave-3 intro + my plan both kept); registry/loop/confirm re-read (confirm-gate request LANDED at loop.py:430-431; `register(schema=)`+SPECS+`as_untrusted`+`validate_args` all landed; discovery skips tests); `config.d/tools-memory.yaml` created; conversation-hook request ACCEPTED + answered on the bus; no BUGS-WAVE2 P0s assigned to this lane (all A–G belong to others). Seam request #2 (memory/skills injection) still OPEN with brain-core.
1. **Memory core** (task 1): store + FTS5/BM25 retrieval + untrusted block wrapper + user-profile view + conversation summaries → §4 schema, §5 tests. **✅ DONE 2026-10-07**
2. **Skills/plugins** (task 2): SKILL.md loader (draft + confidence gate + usage counters + dedup) + plugin manifest loader → §7, tests in §5. **✅ DONE 2026-10-07** — `skills.py` (parse/gate/dedup/publish no-drift/delete), `plugins.py` (scan-never-imports, fail-closed, no shadowing), index tables, 25 tests.
3. **Tools** (task 3): files → shell → schedule → github → web (smallest-risk first, MCP last because it is the largest) → §3 specs, §5 tests. **✅ DONE 2026-10-07**
4. **MCP adapter** (task 4): allow-list fail-closed, confirm categories, untrusted-output → §3.6, tests. **✅ DONE 2026-10-07**
5. **Integration:** verify brain-core landed the two seam requests (confirm gate + memory/skills injection). If still open at wave end → status `blocked` on those items only, handoff, STOP. Never edit loop.py / confirm.py myself (§8). **✅ DONE 2026-10-07 — #1 verified landed (origin/main loop.py:450 + conversation hook :187); #2 STILL OPEN → recorded as the one blocked item in docs/status. Chrome/CDP = pc-control's wave-3 list (not this lane's paths). Rebase stopped by rule 4 (PROGRESS.md) → request filed → **RESOLVED (option a): rebase redone onto `3fab0a6`, `6d174f0` skipped as instructed, suites 116/152/197 green.****
6. **Wave end:** handoff in docs/status/tools-memory.md, STOP (§11). **✅ handoff written 2026-10-07 → wave_done posted → STOP.**

Wave 4 items (skill dedup aging, memory export/delete) and Wave 5 (predator-style acquisition) live in plan §8 — do not start early.

---

# Wave 3 plan (tools-memory)

Contracts honored: INTERFACES §b (tool registration), AGENT_RULES §9 (all tool/memory/web/skill text = untrusted data, never instructions), §7 (no keys in logs; presence checks only), §5 (RAPHAEL_INSTANCE=tools-memory, mocks over live).

## 0. Seams I depend on (others' files — via docs/requests/, never direct edits)

| Seam | Owner | Status |
|---|---|---|
| Auto-discovery of `brain.tools.*` + strict JSON-Schema spec validation (INTERFACES §b) | brain-core | planned in their Wave 2 list; verify after merge, else request |
| Confirm gate honors tool name + registry `risky` metadata (loop.py:114 calls `classify(text)` with no tool; `meta` fetched only later at :206) | brain-core | **request filed** `tools-memory__to__brain-core__confirm-gate-tool-risky.md` |
| Per-turn injection of memory/skills as untrusted context in loop message assembly; schedule-fire → user-facing output | brain-core | **request filed** `tools-memory__to__brain-core__loop-memory-skills-injection.md` |
| `engine.submit(text, priority, source)` as the timer/reminder fire path | brain-core | verified present (brain/app.py:123); re-verify after merge |

Interim risk (documented, not silent): until the confirm-gate request lands, risky tools rely on `confirm.py` text patterns only. Tools are therefore also NAMED to hit existing patterns (`shell`; delete/push/public-repo words) and always declare `risky=True` in the registry.

## 1. Folder skeleton (create as tasks start — planned dirs are pre-assigned by OWNERSHIP)

```
brain/memory/
  __init__.py      # EXISTS: get_conn/init_db — extend ADDITIVELY only; never touch jobs/journal/state
  store.py         # memories CRUD: remember/forget/list/pin, owner discipline on every query
  fts.py           # FTS5 virtual table + sync triggers; keyword-score fallback if FTS5 unavailable
  retrieval.py     # pinned + BM25 + category boost + recency tiebreak + use counters
  block.py         # build_untrusted_block(records) -> str  (DATA-ONLY framing; loop injects)
  profile.py       # user_profile() — identity|preference facts view over memories
  summary.py       # conversation_summaries: add_summary / covers-range / recent
  skills.py        # SKILL.md loader: frontmatter, draft+confidence gate, counters, dedup, active_skills()
  plugins.py       # plugin manifest loader (disabled-by-default, risky-by-default tools)
  tests/           # LANE TEST ROOT (see §5 — every other tests/ location is owned elsewhere)
brain/tools/
  web/__init__.py      # web_fetch, web_search, web_summarize
  files/__init__.py    # file_search, file_read, file_write, file_trash, file_restore
  shell/__init__.py    # shell — fixed script registry only (re-registers name 'shell', risky stays True)
  github/__init__.py   # github_create_repo, github_create_repo_public, github_push, github_set_visibility, github_status
  schedule/__init__.py # timer_set/list/cancel, reminder_set, schedule_set/list/cancel
  mcp/__init__.py      # mcp_list + dynamic mcp_<server>_<tool> wrappers
  mcp/client.py        # stdlib JSON-RPC 2.0 MCP client (stdio; HTTP transport = stretch)
skills/<name>/SKILL.md  # runtime-writable, git-tracked (first write creates dirs)
plugins/<name>/manifest.yaml   # user-authored; enabled only by user
config.d/tools-memory.yaml     # §6 keys (mine; deep-merged per INTERFACES §c)
docs/requests/tools-memory__to__brain-core__*.md
```

No tests inside `brain/tools/**` — the pkgutil walker would import them at runtime.

## 2. Memory (task 1)

### 2.1 Schema — additive on `memory.db` (same additive-migration pattern as the jobs columns)

```sql
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source TEXT NOT NULL DEFAULT 'observed',   -- user | observed | imported
  category TEXT NOT NULL DEFAULT 'fact',     -- identity | contact | preference | fact | task
  pinned INTEGER NOT NULL DEFAULT 0,
  owner TEXT NOT NULL DEFAULT 'local-user',  -- EVERY query filters owner (addendum §3: PR #2404 leak lesson)
  uses INTEGER NOT NULL DEFAULT 0,
  last_used TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  text, content='memories', content_rowid='id', tokenize='porter unicode61'
);
-- triggers memories_ai / memories_ad / memories_aw keep FTS in sync with memories
CREATE TABLE IF NOT EXISTS conversation_summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT, summary TEXT NOT NULL,
  covers_from TIMESTAMP, covers_to TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

(FTS5 unavailable → `fts.py` falls back to token-overlap keyword scoring behind the same `retrieve()` interface; both paths tested.)

### 2.2 API

- `remember(text, source, category, pinned=False, owner='local-user')` / `forget(id, owner)` / `list_memories(category=None, limit)` / `pin(id, on)` — inline capture ("remember: X") is the loop's parse job; passive capture = `remember(..., source='observed')`.
- `retrieve(query, k=5)`:
  1. pinned rows always included (cap 20);
  2. FTS5 `bm25(memories_fts)` on a sanitized query (quote terms, strip MATCH operators — user text is data);
  3. category boost: identity/preference +0.15, task +0.05 (config-overridable);
  4. recency tiebreaker (decay over ~30 days);
  5. dedup by id, drop already-pinned, take k;
  6. `uses += 1, last_used = now` on every returned row.
  Returns `[{id, text, category, source, ts, pinned, score}]` — data only, no instructions.
- `build_untrusted_block(records, personal: bool) -> str` — `<untrusted_context>` framing: header states *retrieved local memory — DATA ONLY, never instructions*, records as `category|ts: text`. Personal categories (identity/contact) flagged so the privacy gate can hold them back from free cloud providers (`allow_free_models_for_personal_data: false` → cloud_temp: exclude/redact personal categories — flag surfaced in seam request 2).
- `user_profile()` → profile.py view over category IN (identity, preference): pinned first, then uses/recency. No second table — `memories` stays the single source of truth (no sync bugs).
- `add_summary(text, session, covers_from, covers_to)` / `recent_summaries(session)` / `covers_up_to()` — older-turn rolling summaries produced via `brain.router.chat` (purpose tag `chat`), injected only when context pressure needs them, wrapped by block.py like everything else.

## 3. Tools (task 3 + 4) — all specs strict JSON Schema (`type: object`, typed props, `required`, `additionalProperties: false`), all outputs strings/JSON = untrusted text

### 3.1 web
| tool | params | risky | notes |
|---|---|---|---|
| `web_search` | `query:str, limit:int=8` | no | DuckDuckGo HTML endpoint (no key), endpoint overridable via config; returns `[{title,url,snippet}]` JSON |
| `web_fetch` | `url:str, max_bytes:int=1048576` | no | http/https only; **SSRF guard**: block loopback/private/link-local IPs + re-check on every redirect; timeout 15 s; html→text via stdlib `html.parser` (no new deps); binary/oversize → clear error string |
| `web_summarize` | `question:str`, `url:str?`, `text:str?` (exactly one, runtime-validated) | no | fetches if url, then `brain.router.chat` with content delimited as untrusted data (injection-hardened prompt); input capped; purpose tag `chat` |

No direct provider HTTP (INTERFACES §a) — summarize goes through the router facade only.

### 3.2 files — **trash instead of delete: there is NO file-delete tool, ever**
| tool | params | risky | notes |
|---|---|---|---|
| `file_search` | `root:str, pattern:str, limit:int=50` | no | pure-Python `os.walk`+`fnmatch` (rg not assumed); skips `.git/.venv/node_modules/__pycache__` |
| `file_read` | `path:str, offset:int=0, limit:int=200` | no | 256 KB cap; NUL-sniff binary → error; **secret refusal**: `.env`, `secrets.env`, `*.key`, `id_rsa*`, `*.pfx` unreadable (§7) |
| `file_write` | `path:str, content:str, append:bool=false` | no | confined to `files.allowed_roots`; secret paths refused; returns bytes written |
| `file_trash` | `path:str` | **yes** | moves to `<data-dir>/trash/<ts>_<name>/`, returns trash id (maps to confirm action `delete_files`) |
| `file_restore` | `trash_id:str` | no | moves back; refuses to clobber an existing destination |

### 3.3 shell — fixed script registry (task: "shell via the fixed script registry")
- Tool `shell(script:str, args:list[str]=[])`, **risky=True** (name in `confirm.RISKY_TOOLS` too).
- Registry = `shell.scripts` in config.d/tools-memory.yaml: `{name: {cmd: [argv...], cwd?, desc?}}`. `args` are APPENDED as raw argv elements — `subprocess.run(shell=False)`, **never** `shell=True`, no string interpolation → no injection surface.
- Unknown script → error (allow-list is the point); timeout 30 s; output capped 64 KB; non-zero exit → RuntimeError like the built-in shell.
- This re-registers the name `shell`, replacing the placeholder `shell_tool` in the central registry via sanctioned self-registration (metadata `risky=True` unchanged — strengthening, never weakening).

### 3.4 github (addendum §2 — `gh` CLI, token presence-checked value-blind, never logged)
| tool | params | risky | notes |
|---|---|---|---|
| `github_create_repo` | `name:str, description:str=""` | no | ALWAYS private (`private` param does not exist — the safe default cannot be overridden) |
| `github_create_repo_public` | `name:str, description:str=""` | **yes** | `make_public_repo` confirm category |
| `github_push` | `remote:str="origin", branch:str?` | **yes** | text pattern `push` also matches |
| `github_set_visibility` | `repo:str, visibility:enum[private,public]` | **yes** | any visibility change confirms |
| `github_status` | — | no | auth presence only; sanitizes any token-like output |

`github.default_visibility: private`, `auto_public: false` read from base config — never loosened (Core Guard §8 spirit; auto_public:true remains a user config decision).

### 3.5 schedule — timers / reminders / schedules
- `timer_set(seconds:int?, at:str?, label:str="")`, `timer_list()`, `timer_cancel(id)`
- `reminder_set(at:str ISO, text:str)`
- `schedule_set(pattern:str, task_text:str)` — tiny parser only: `every Nm|Nh|Nd`, `daily HH:MM` (no cron lib); `schedule_list()`, `schedule_cancel(id)`.
- Store: `schedules` table (§4.3) — survives restart; re-arm on startup (startup hook per seam request 2; fallback: arm on first tool call + `arm_all()` exposed).
- Fire path: `await engine.submit(text="Timer done: <label>" | "Reminder: <text>", priority='user_facing', source='system')` → existing job loop narrates + subtitles it (no new speak API needed). Recurring fires re-arm after submit.
- All params `risky=False` (non-GUI, non-sensitive per ARCH §4); fired text still flows as untrusted like any tool output.

### 3.6 mcp — client adapter (task 4)
- Config-only server definitions (user-authored; the MODEL cannot add servers — that would be arbitrary code execution): `mcp.servers: [{name, transport: stdio, command: [argv], allow: [...], confirm: {tool: bool}?}]`.
- **Allow-list fail-closed**: `allow: []` (default) = server visible via `mcp_list` but zero callable tools; `"*"` = all explicitly opted in by the user's config.
- `mcp_list()` returns server+tool inventory; allow-listed tools register dynamically as `mcp_<server>_<tool>` with the MCP `inputSchema` as their JSON Schema (skipped + warned if schema is non-conforming).
- **Confirm categories**: wrapped tools default `risky=True` (unknown external behavior); `confirm: false` per tool only in user config — never model-settable.
- Client: stdlib JSON-RPC 2.0 over stdio (`initialize` → `notifications/initialized` → `tools/list` → `tools/call`), timeout + output caps; HTTP transport = stretch if time allows.
- **Untrusted-output rule**: every MCP result is untrusted text wrapped by block.py before any model sees it (MCP servers are a known prompt-injection vector).
- Startup of stdio servers happens only from config load (user-approved by authoring the config), never from a tool call.

## 4. Skills / plugins (task 2 — addendum §4)

### 4.1 SKILL.md format (disk: `skills/<name>/SKILL.md`)
YAML frontmatter `name, description, version, category, tags, status: draft|published, confidence, source: learned|taught|created, created` + body `## When to Use`, `## Procedure`, `## Pitfalls`, `## Verification` (PyYAML already a dep via config loader → `yaml.safe_load`). Malformed file → recorded as invalid, never a crash.

### 4.2 Index table + gate semantics
```sql
CREATE TABLE IF NOT EXISTS skills_index (
  name TEXT PRIMARY KEY, path TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'general',
  tags TEXT NOT NULL DEFAULT '[]',            -- JSON array
  status TEXT NOT NULL DEFAULT 'draft',        -- draft | published
  confidence REAL NOT NULL DEFAULT 0.0,        -- 0.0..1.0
  source TEXT NOT NULL DEFAULT 'learned',      -- learned | taught | created
  content_hash TEXT NOT NULL DEFAULT '',
  dedup_hits INTEGER NOT NULL DEFAULT 0,
  uses INTEGER NOT NULL DEFAULT 0, last_used TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
);
```
- **Dedup at creation**: Jaccard ≥ 0.82 over normalized token sets of `description + body` → do NOT create; bump `dedup_hits` + `uses` on the match instead.
- **Confidence gate**: `active_skills()` returns ONLY `status='published' AND confidence >= skills.gate_confidence (0.6)` — drafts and low-confidence skills are never injected (prompt-injection defense); they're listable on demand (`skills_list` view for the user/orchestrator, not auto-injected).
- Usage counters increment whenever a skill is actually included in a prompt or re-read by a task. Periodic audit/demote = Wave 4.
- Injection seam: `active_skills()` → block.py untrusted framing → loop (seam request 2).

### 4.3 plugins (user-authored code; `plugins/<name>/manifest.yaml`)
`{name, version, description, entry: python module path, tools: [{name, spec, risky?}], enabled: bool}` — loader validates schema, mirrors into `plugins_index`, imports/registers declared tools **only when `enabled: true`** (user flips it; `plugins.auto_enable: false` default; NO model-facing enable tool). Declared tools default `risky=True`. Bad manifest → error string, never a crash, never a partial import.

### 4.4 schedules table (§3.5 store)
```sql
CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                    -- timer | reminder | recurring
  due_at TIMESTAMP NOT NULL, label TEXT NOT NULL DEFAULT '',
  pattern TEXT,                          -- recurring: 'every 30m' / 'daily 08:00'
  payload TEXT,                          -- JSON (task text)
  status TEXT NOT NULL DEFAULT 'pending',-- pending | fired | cancelled
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, fired_at TIMESTAMP
);
```

## 5. Tests (lane test root: `brain/memory/tests/` — `brain/tests` = brain-core, root `tests/` = qa-security, nothing inside `brain/tools/**` so pkgutil discovery never imports tests)

All hermetic: `RAPHAEL_INSTANCE=tools-memory`, `RAPHAEL_DB_PATH=<temp>`, HTTP/router/gh/engine mocked, zero network, zero ports, no real `.env`.

- `test_memory_store.py` — CRUD, owner isolation on every query, pin, additive migration leaves `jobs/journal/state` untouched.
- `test_memory_retrieval.py` — FTS5 build + trigger sync, BM25 ordering, boost/recency, forced no-FTS fallback path, use-counter increments, sanitized MATCH input, untrusted-block framing (header + no instruction-looking markup).
- `test_memory_profile_summary.py` — profile view ordering, summary cover-range, recent-summaries retrieval.
- `test_skills.py` — frontmatter parse, draft/low-confidence excluded from `active_skills()`, Jaccard dedup → `dedup_hits`, counters, malformed SKILL.md rejected safely.
- `test_plugins.py` — manifest validation, disabled default, risky-by-default, bad manifest no-crash no-import.
- `test_tools_files.py` — search caps/skip-dirs, read limits, binary + `.env` refusal, trash→restore roundtrip, **no delete path exists**.
- `test_tools_shell.py` — unknown script rejected, argv list (shell=False), timeout, output cap, `risky=True` metadata.
- `test_tools_github.py` — gh subprocess mocked: private-only creation, public tool risky, visibility risky, missing token → `BLOCKED: GITHUB_TOKEN` (presence only, no value).
- `test_tools_web.py` — mocked HTTP: fetch caps, SSRF private-IP/redirect block, scheme refusal; summarize via mocked `brain.router.chat`.
- `test_tools_schedule.py` — set/list/cancel, persistence + re-arm, fire → `engine.submit` called with `priority='user_facing'` (mock), recurring pattern parse.
- `test_tools_mcp.py` — fake stdio MCP server (child python): initialize/list/call, allow-list fail-closed, non-conforming schema skipped, default risky.
- `test_specs.py` — every registered spec passes strict JSON-Schema validation (brain-core validator post-merge; local assert as fallback).

## 6. Planned `config.d/tools-memory.yaml` keys (mine; created at task 0)

```yaml
memory:   { top_k: 5, max_context_chars: 4000, category_boost: {identity: 0.15, preference: 0.15, task: 0.05} }
skills:   { dir: skills, gate_confidence: 0.6, dedup_jaccard: 0.82, inject_drafts: false }
plugins:  { dir: plugins, auto_enable: false }
files:    { allowed_roots: ["~"], trash_subdir: trash, read_max_bytes: 262144 }
shell:    { scripts: {}, timeout_s: 30, max_output_bytes: 65536 }
web:      { fetch_max_bytes: 1048576, timeout_s: 15, block_private_ips: true, search_endpoint: <ddg html> }
schedule: { tick_s: 1 }
mcp:      { servers: [] }     # allow: [] = fail-closed; enabling = user config edit, never model
```
Base `github.*` and `safety.confirm_actions` are read-only for me (never redeclared/loosened).

## 7. Constraints checklist (re-verified at every commit)

- Untrusted rule: memory blocks, skill bodies, web/MCP/file/shell output all framed DATA-ONLY by block.py or returned as plain strings for the loop's wrapper (AGENT_RULES §9).
- Secrets: `.env` never read by tools; token presence checks value-blind; gh output sanitized (§7).
- No `shell=True`, no delete tool, no model-authored MCP server/command, no public-repo path without confirm, no direct provider HTTP.
- Instance isolation in tests; `config.d` only; central registries untouched; Core Guard untouched (requests instead).

## 8. Later-wave scope (do NOT start early)

- **Wave 4:** skill aging/audit/demote cycle, dedup hardening; memory export + delete controls (user-facing wipe/export).
- **Wave 5:** predator-style acquisition — notice repeated-task signals (journal + usage counters), draft a skill in a sandbox (isolated write to `skills/.drafts/`), test it, keep `status=draft` below the confidence gate, promote only after gate pass + user approval. Build ONLY on the loader/gate/counters shipped in Wave 3.

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Memory/plugin hardening: sqlite crash-safety (kill-during-write), FTS corruption recovery, skills/plugins sandbox audit (prompt-injection probes through memory retrieval), MCP stdio orphan/failure modes. **✅ DONE 2026-10-07** — 19 tests (crash 3 / FTS 4 / injection 7 / MCP 5), real fixes: untrusted-block marker neutralization (framing escape), bool-confidence fail-open, MCP wedged-child evict+kill, FTS keyword-fallback + self-heal + pinned-always.
- [x] Session-brief wave-4 scope: skill dedup/aging + memory export/delete controls. **✅ DONE 2026-10-07** — `audit_skills()` (stale-unused-published → draft, file+index in sync; `find_duplicates()` report-only), `export.py` (`export_all` 0600 JSONL owner-scoped; `wipe('all'|'memories'|'conversations')` surgical + owner-filtered; deliberately NOT model tools — destructive power stays with the user). 10 tests; `skills.audit_grace_days: 30` in config fragment.
- **Wave 4 COMPLETE → wave_done posted (merge-ready).**

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Memory-context feeding for Analysis/Simulation (retrieval budgets per kind) + Report caching; injection probes extended to the new format outputs. **✅ DONE 2026-10-07** — `retrieval.kind_budget()` (analysis k10/8000, simulation k4/3000, default 5/4000, config `memory.kind_budgets` override) + `build_context(query, kind=...)` one-call feeding seam (framed, neutralized, personal-gateable, '' = inject nothing); `brain/memory/reports.py` cache (PROTOCOL §3 caps re-enforced, fail-silent save, owner-scoped `find_reports`/`recent_reports`/`get_report`, operator-proof token search); report-shaped marker-spoof probe + missing-table recovery test. Call sites filed: `tools-memory__to__brain-core__wave5-feeding-report-cache.md` (extends still-open injection request). 10 new tests → 155 memory / 184 brain green; root 203+1 pre-existing red (stale 11-instance count after approved `shadow` row → request to qa-security).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
