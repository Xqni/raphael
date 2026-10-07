# tools-memory → brain-core: loop-memory-skills-injection
Status: OPEN

## What
Three integration points in `brain/loop.py` / startup (brain-core owns both) that only brain-core can wire, for tools-memory Wave 3:

1. **Per-turn memory injection.** When assembling LLM messages (non-private path), call the new memory API and inject the result as untrusted context — NOT as a system instruction:

   ```python
   from brain.memory import retrieve, build_untrusted_block
   rows = retrieve(user_text, k=cfg.memory.top_k)          # pinned always + BM25 top-k
   block = build_untrusted_block(rows)                      # "<untrusted_context> ... DATA ONLY ..." framing
   # appended as a user/assistant-context message, bounded by cfg.memory.max_context_chars
   ```
   Private mode / fastpath-only turns: no injection (no LLM call happens anyway). Personal categories (`identity`, `contact`) are flagged by `build_untrusted_block(rows, personal=...)` so the privacy gate can hold them back from free cloud providers (`allow_free_models_for_personal_data: false` — decide: exclude/redact those rows under cloud_temp; tools-memory has no authority over that gate).

2. **Skills injection.** Same turn, only skills that pass the gate:

   ```python
   from brain.memory.skills import active_skills            # status='published' AND confidence >= gate; drafts NEVER included
   ```
   Wrapped via `build_untrusted_block`-style framing as well (skill bodies are text, addendum §4: injection-gate defense).

3. **Schedule fire path + startup re-arm.** `brain/tools/schedule/` persists timers/reminders in the `schedules` table. On fire it calls the existing public seam `await engine.submit(text="Timer done: <label>" | "Reminder: <text>", priority='user_facing', source='system')` (verified: `brain/app.py:123` uses the same call) so the normal loop narrates/subtitles it — no new speak API requested. Plus: call `brain.tools.schedule.arm_all()` once at loop/app startup (after `start_loop`) so pending timers survive a restart; if startup wiring is awkward, say so and schedule will arm lazily on first tool call as a fallback.

## Why
- Addendum §3/§4 (Odysseus semantics): pinned memories + gated skills are injected **per turn by the loop**; the memory module can only return data — wrapping/injection is the loop's job (AGENT_RULES §9).
- Wave 3 lane task 1 deliverable ("results wrapped as untrusted context") cannot be demonstrated end-to-end without this wiring.
- Timers that fire but never reach the user are useless; `engine.submit` is already the sanctioned intake (post_job path).

## Impact
- Prompt shape grows by ≤ `memory.max_context_chars` (4000 chars default) per turn — config-bounded.
- New imports from `brain.memory` (owned by tools-memory — stable API as specified in docs/lanes/tools-memory.md §2.2; any signature change goes through docs/requests/).
- Privacy gate decision on personal categories is a Core Guard-adjacent choice (§8) — integrator/brain-core decides; tools-memory only exposes the flag.
- No shared-contract edits; works entirely through existing router/loop/job-engine seams.
