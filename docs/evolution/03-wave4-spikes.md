# 03 — Wave 4 implementation spikes: journal + rollback

Status: **SPIKES BUILT & TESTED 2026-10-07** (lane task: "rollback design + journal design
notes → implementation spikes"). These are the first executable pieces of
`01-self-evolution-infra.md`; the full controller (`controller.py`, `worktree.py`, `shadow.py`,
`baseline.py`, `promote.py`) is deliberately NOT built yet — it depends on two OPEN requests
(§ Dependencies).

## What landed (all under `brain/evolution/**`, lane-owned)

| Module | Design section | What it does |
|---|---|---|
| `zones.py` | 01 §1 | Fail-closed zone classifier: `CORE_EXACT` + `CORE_GLOBS` + `MUTABLE_GLOBS`, authority-key **content check** (a `safety:`/`kill_switch`/`allow_go_runtime`/`0.0.0.0`-touched file re-guards itself), `classify()` (CORE wins), `is_auto_promotable()`. Unknown path ⇒ CORE. |
| `journal.py` | 01 §4 | `make_entry()` (schema-validated: decision/mode enums raise; a `promoted` entry auto-fills `rollback`), `write_entry()` (markdown + YAML frontmatter in `docs/evolution/journal/` + `INDEX.md` line, idempotent), `load_entry()`, `iter_entries()`, `weekly_summary()` (spoken, ≤2 sentences per item per `voice_personality.spoken_reply_max_sentences`). |
| `rollback.py` | 01 §1.1, §2.6–2.7 | `verify_core_guard()` **delegates to qa-security's `tests/core_guard.py`** (single source of truth — no second manifest; tool or manifest missing ⇒ `(False, …)` = refuse to run), `tag_last_known_good()` / `last_known_good()` (annotated `last-known-good` tag, moves with `-f` after a passed promote), `rollback_command()` / `retag_command()` — these only **generate strings** for the journal / infra's out-of-band rollback; they never execute `git reset`/`revert` against the real repo. |

Shared test conventions honored: no servers spawned, git exercised only in throwaway `tmp_path`
repos, real-repo access is read-only (the core-guard verify), AGENT_RULES §14 (smallest target,
one suite at a time).

## Test output (real, 2026-10-07)

```
$ tests/.venv/bin/python -m pytest brain/evolution/tests -q
49 passed in 0.14s
$ python3 tests/core_guard.py
Core Guard OK (4 files byte-stable)
$ tests/.venv/bin/python tests/ownership_check.py --lane evolution-persona --files <11 new files>
ownership OK for lane 'evolution-persona' (11 file(s) checked)
```

Notable cases proven: fail-closed classification (unknown ⇒ CORE), authority-content
re-guarding, journal schema rejection of bad decisions/modes, promoted-entry rollback
auto-fill, weekly summary pending-proposal wording, `verify_core_guard` failing closed when
the tool is missing, LKG tag creation + forward move, and that the recorded
`git revert --no-edit <sha>` command **actually reverts** (verified in a tmp repo).

## Dependencies still blocking the full controller

1. **shadow instance row** (OPEN, brain-core — `evolution-persona__to__brain-core__shadow-instance-row.md`):
   blocks `shadow.py`/`baseline.py` entirely (`config.py::_instance_index` raises for unknown instances).
2. **Rollback hook seam** (infra): what command/endpoint supervisor executes for the LKG
   re-point — `retag_command()` is ready to hand over once defined.
3. **Golden harness seam** (qa-security): reuse `tests/{run_all,harness,conformance,contract}`
   rather than inventing a runner.
4. **CORE_GUARD_FILES extension** (qa-security): today's manifest = 4 files; design 01 §1.1
   wants `supervisor/**`, `brain/evolution/**`, PROTOCOL §7 allow-list artifact, `tests/**`.
   `zones.py` already classifies all of them as CORE; the *hash* coverage grows via their tool.
5. **Router weights ownership** (router): mutable-zone path for benchmark-derived ranking.

## Next spike (when 1 lands)

`worktree.py` + `controller.py` skeleton: detect → classify → worktree → verify → journal,
with `evolution.mode: off|propose` gating (config.d fragment already ships the safe defaults:
`mode: propose`, `idle_only: true`, free-tier budget).
