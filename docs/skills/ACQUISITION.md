# ACQUISITION — Predator-style skill acquisition (F-2 design, NOT enabled)

Status: **DESIGN + STUBS ONLY — `skills.acquisition_enabled: false` (never flip
it without the user's explicit go).** Source: audit packet
`docs/audit-tasks/tools-memory.md` F-2 ("observe failed task → draft skill →
confidence gate → publish; mock tests only") + the wave-5 self-writing-skills
directive (addendum §4). Implementation: `brain/memory/acquisition.py`;
mock tests: `brain/memory/tests/test_wave5_acquisition.py`.

## Why (the predator loop)

Raphael currently *writes down* skills when asked (or by manual orchestration).
A predator-style loop notices repetition **on its own**: the same task failed
N times → the fix is already known → capture it ONCE so the next attempt is
first-try. Nothing here invents knowledge — it distills what already happened.

## The loop (all five stages are gated)

```
observe_failure() ──(signature hits skills.acquisition_min_repeats)──▶ READY
      │                                                                │
      └────────────────────────────────────────────────────────────────┘
                               maybe_draft()                       [2]
   skills.create_skill(status='draft', confidence=0.0,               │
                       directory=skills/.drafts/)   ← SANDBOX
                               │
                        test_draft(name, runner)        [3] — runner is
                               │                          INJECTED; with no
                               │                          runner: 'skipped'
                               │                          (never auto-exec)
                        submit_for_approval(name)       [4] — forces
                               │                          draft + below-gate;
                               │                          pings the user
                               ▼
                 HUMAN review (git diff on skills/) ──▶ set_status('published')
                                                    + set_confidence(≥0.6)
                                                          [5] PROMOTED
                               │
                               ▼
                active_skills() sees it (EXISTING wave-5 gate)
```

1. **Observe** — `observe_failure(task, error=...)` normalizes the task text to
   a signature (lowercased token set). In-memory counters (design-stage stub;
   Wave-6+ may journal them). Disabled flag → immediate `{'enabled': False}`,
   zero side effects.
2. **Sandbox draft** — only when the signature reaches
   `skills.acquisition_min_repeats` (default 3): a SKILL.md is written under
   **`skills/.drafts/<name>/`** (NOT the live `skills/` tree), always
   `status: draft`, `confidence: 0.0`, `source: learned`, full section
   skeleton (`When to Use / Procedure / Pitfalls / Verification`). Existing
   **Jaccard dedup** still applies — repeated failures of the same task bump
   `dedup_hits` instead of stacking drafts.
3. **Test gate** — `test_draft(name, runner=...)` runs the Verification section
   through a **caller-injected runner only**. No runner configured →
   `{'status': 'skipped'}` — acquisition NEVER executes code by itself
   (the untrusted-output and shell-registry rules apply to whatever a runner
   returns).
4. **User approval** — `submit_for_approval(name)` re-asserts draft + sub-gate
   confidence and returns the review prompt. After the human approves:
   `finalize_draft(name)` MOVES the sandbox draft into the live `skills/` tree
   (still `draft` + below-gate — moving activates nothing). Promotion is a
   HUMAN two-step on the existing API (`skills.set_status('published')` +
   `skills.set_confidence(≥ skills.gate_confidence)`); there is deliberately
   **no publish function in this module**.
5. **Publish** — only after both human steps does `active_skills()` include it
   (wave-5 confidence gate — unchanged).

## Security invariants (why this is safe to design now, enable later)

- **Disabled flag everywhere**: every public function checks
  `skills.acquisition_enabled` first; default `false` in
  `config.d/tools-memory.yaml`; flipping it is a USER config edit (the model
  cannot enable acquisition — same fail-closed pattern as plugins/MCP).
- No code execution anywhere in the module (test runner is injected, never
  discovered; no shell, no subprocess imports).
- Drafts are TEXT in a sandboxed directory; they can't reach prompts until the
  human publishes them through the existing gate (drafts are never injected —
  wave-3/4 tests already prove the gate).
- Dedup + caps inherited from `skills.create_skill` (no draft spam, no path
  traversal — name regex enforced).
- Everything is reviewable: `skills/.drafts/` is inside the git-tracked
  `skills/` tree, so every draft shows up in `git status` / `git diff`.

## Config (all in `config.d/tools-memory.yaml`)

| key | default | meaning |
|---|---|---|
| `skills.acquisition_enabled` | **false** | master switch — stays off until the user says go |
| `skills.acquisition_min_repeats` | 3 | failures of one signature before a draft is proposed |

## Future work (explicitly NOT built)

- persistence of observation counters (journal-backed), failure-taxonomy
  clustering beyond token signatures, auto-runners for Verification (would
  need a Core-Guard-style confirmation design first), confidence scoring from
  test outcomes (today: humans set it).
