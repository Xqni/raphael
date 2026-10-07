# 01 — Self-evolution infrastructure (Wave 4 design notes)

Status: **DESIGN ONLY — not implemented.** `current_wave: 3`; per AGENT_RULES §11 no Wave 4 code
starts until WAVES.md says so. Written as the Wave 2 lane task, refreshed for Wave 3 (2026-10-07):
aligned with what the Wave 2 merge actually shipped (qa-security's Core Guard manifest tool,
brain-core's instance-derivation enforcement).
Owner: evolution-persona lane (`brain/evolution/**`, `docs/evolution/**`).

Authority basis: REQUIREMENTS_ADDENDUM §13 (three-tier self-evolution) and §14 (capability growth).
This document is the concrete design those tiers map onto. Hard rules below override everything.

## 0. Module layout (planned)

```
brain/evolution/
├─ controller.py        # orchestrates one evolution cycle (detect→patch→test→compare→promote/propose)
├─ zones.py             # Core Guard manifest + mutable-zone classification (fail-closed)
├─ manifest.py          # loads/verifies the EXISTING manifest (tests/core_guard_manifest.json)
├─ worktree.py          # isolated git worktree + branch creation (never touches main checkout)
├─ shadow.py            # RAPHAEL_INSTANCE=shadow run harness (tests + golden transcripts)
├─ baseline.py          # baseline capture + diff/compare of shadow run vs baseline
├─ promote.py           # promote/tag/probation/rollback bookkeeping
├─ journal.py           # evolution journal entries + weekly spoken-summary builder
├─ config.py            # mode (off|propose|auto_safe), budget counters, idle-only gate
├─ golden/              # golden transcripts (inputs + expected outputs, deterministic mocks)
└─ tests/               # unit tests for everything above (lane-owned, mirrors brain/tests pattern)
docs/evolution/
├─ 01-self-evolution-infra.md   # this file
├─ 02-persona-tiers.md          # Wave 5 design
└─ journal/                     # evolution journal entries (git-tracked, reviewable)
```

## 1. Zone model: Core Guard manifest vs mutable zone

Classification is **path-glob based and fail-closed**: a path that matches no zone rule is
treated as **Core Guard** (never auto-promoted). Unknown ⇒ most restrictive.

### 1.1 Core Guard set (hash-locked; changes = PROPOSAL, user/integrator approval only)

**The hash manifest already exists (shipped by qa-security in the Wave 2 merge):**
`tests/core_guard.py` verifies sha256 against `tests/core_guard_manifest.json`
(`brain/auth.py`, `brain/confirm.py`, `brain/control.py`, `brain/mode.py`), exit 1 on drift;
`--update` is only legitimate with an integrator-approved request. **That is THE manifest** —
the evolution controller calls it (never maintains a second copy), and the controller refuses
to run when verification fails. Widening `CORE_GUARD_FILES` is a change to `tests/**`
(qa-security's file) → request, see §7.

| Path / semantic | Why guarded |
|---|---|
| `brain/confirm.py` | confirmation enforcement (AGENT_RULES §8) |
| `brain/auth.py` | token handshake / auth |
| `brain/control.py` | kill switch, pause, private, watch |
| `brain/mode.py` | mode semantics (private/pause persistence) |
| `docs/PROTOCOL.md` `§7 act_req` allow-list + the PowerShell script registry | what can touch the machine |
| `supervisor/**`, `scripts/**` (incl. rollback + Task Scheduler registration) | out-of-band recovery path — if this breaks, rollback breaks |
| `brain/evolution/**` **including its tests** | the controller itself must not rewrite its own judge |
| `brain/tools/__init__.py` | central registry (AGENT_RULES §3) |
| `config.yaml` base + `profiles:` block | global safety switches (`safety.*`, `providers.allow_*`) |
| `tests/**` (root suite), `.github/workflows/**` | the gate itself |
| `.env`, `.env.example`, any `secrets`/`token` path | secrets — see §6 |

Raphael may **propose** changes to any of these (that is the whole point of `propose` mode);
she may never auto-apply them, and she may never edit them on a branch that gets merged without
the user's yes. Note AGENT_RULES §8: even the owning lane cannot weaken Core Guard semantics —
requests go through `docs/requests/` + integrator.

### 1.2 Mutable zone (eligible for auto-promote in `auto_safe` after all gates pass)

| Path / semantic | Notes |
|---|---|
| `skills/**` | runtime self-written skills — existing draft + confidence gate still applies |
| `plugins/**` | drop-in code plugins, deny-by-default permissions |
| prompts | prompt text held in evolution-mutable prompt files / config keys — **not** the system-prompt literals embedded inside Core Guard code files (those are guarded with their file) |
| tunable config | non-safety keys in `config.d/evolution-persona.yaml` and other lanes' *tunable* keys; **never** `safety.*`, `privacy.*`, `providers.allow_*`, ports, bind, auth, or instance derivation |
| router weights | model ranking / benchmark-derived selection weights (router-owned files, see §7 requests) — never the Go/paid gates, which live in router `complete()` code and stay guarded |
| UI polish | `body/orb/**` visuals (colors, easing, glow) — no protocol/state-machine files |

Anything in the mutable zone that would *indirectly* change authority (e.g. a "prompt" that adds
a tool, a "tunable" that widens an allow-list, a "UI polish" file that also contains protocol
logic) is reclassified to Core Guard by the classifier's content checks, not just its path.

## 2. The pipeline (one evolution cycle)

```
detect ──► plan ──► patch (worktree branch) ──► verify (shadow) ──► compare (baseline)
   │                                                            │
   │                                          pass + mutable ───┴──► promote + tag LKG + probation
   │                                          pass + core ─────────► PROPOSAL (journal entry, waits for user)
   └─ fail/over budget/blocked ────────────────────────────────► journal "no change" + stop
```

1. **Detect** — sources: `logs/**` errors, failed jobs from the task journal, user feedback
   ("that broke"), reviewer/security findings backlog, self-audit outputs (addendum §13 tier 1).
   Detection produces a *finding* record; findings never mutate anything by themselves.
2. **Plan** — classify the target path(s) → zone. Core Guard target ⇒ this cycle is pre-flagged
   `proposal_only`. Budget check (§6): if over cap, emit proposal/journal and stop.
3. **Patch** — create an **isolated git worktree** on branch `evo/<slug>` from the current HEAD of
   the lane/integration branch; all edits happen there, never in the running checkout.
   Who patches: the **runtime worker** (Raphael's own worker path, addendum §13/§14) using
   **free models only** (Go/paid off — `allow_go_runtime`/`allow_paid_runtime` stay false), bounded
   step budget, **one attempt per finding** (never loops; second failure ⇒ journal + proposal).
4. **Verify (shadow instance)** — run the full test suite **plus** the golden transcripts under
   `RAPHAEL_INSTANCE=shadow` with a **mock Body** (no mic, no hotkeys, no input — INTERFACES (d)
   restrictions apply to this lane's runs). Shadow derives its own port/pidfile/lock/datadir from
   the instance name; it never binds main's 8765.
5. **Compare (baseline)** — baseline = captured transcript/behavior snapshot of the last-known-good
   tag, run through the same shadow harness. Compare = structured diff of job events, act_req
   sequences (must be byte-identical unless the change *intends* to alter them), speak text classes,
   and test results. Any unintended delta ⇒ fail ⇒ no promote.
6. **Promote** — auto-promote **only** mutable-zone changes that pass 4+5. Promote = merge the work
   branch, then **tag `last-known-good`** (annotated tag carrying the manifest hash + journal id).
7. **Probation** — after promote, the change watches N cycles / T time (config
   `evolution.probation: {jobs: 20, hours: 24}`); failures during probation ⇒ **automatic rollback**
   via infra's out-of-band rollback (supervisor-side, works even if the Brain is broken — that is
   why `supervisor/**` is Core Guard, not mutable). Rollback re-points the LKG tag and writes a
   journal entry with the rollback command.
8. **Proposal path** — anything Core Guard, over-budget, or failed-compare-but-still-worth-doing
   becomes a journal **proposal**: diff + reason + test evidence + risk + rollback command, spoken
   summary offered to the user, applied only after an explicit yes.

## 3. Shadow instance

- `RAPHAEL_INSTANCE=shadow` for every shadow run (AGENT_RULES §5: never default ports, prefer mocks).
- Mock Body: no real mic/speaker/hotkeys/input; `act_req` answered by a scripted mock Body that
  records calls (that recording *is* the golden transcript's action stream).
- Golden transcripts live in `brain/evolution/golden/`: input commands → expected `job_event` /
  `act_req` / `speak`-class sequences, with router mocked deterministically (no live provider calls
  in the gate — cloud_temp keys are not spent by tests).
- **Known contract gap:** INTERFACES (d) has no `shadow` row (only lane instances + `main`).
  Instance derivation must produce a real port/pidfile/lock/datadir for `shadow` — request written:
  `docs/requests/evolution-persona__to__brain-core__shadow-instance-row.md` (**Status: OPEN**).
  Enforcement now exists: `brain/config.py::_instance_index` raises loudly for any instance
  name not in the §d table ("ask the integrator to add it") — so shadow runs are hard-blocked
  until the row lands. This is exactly the fail-closed behavior we want; no workarounds
  (never hardcode a port, INTERFACES (d)).

## 4. Journal

- Location: `docs/evolution/journal/<YYYY-MM-DD>-<slug>.md` (+ `docs/evolution/journal/INDEX.md`).
  Git-tracked so every change is reviewable and `git revert` is always the human escape hatch.
- Every entry carries, at minimum:
  `id`, `timestamp`, `mode`, `finding` (source: logs/jobs/feedback), `zone`, `paths[]`,
  `diff` (unified, or pointer to the merge commit), `reason`, `tests` (real command + real output
  summary — never claimed, never invented), `baseline_compare` (pass/fail + delta summary),
  `decision` (promoted | proposal | rejected | rolled_back), `rollback` (exact command), `budget`
  (steps/tokens used vs cap).
- **Weekly spoken summary:** a job that reads the last 7 days of the journal and produces a short
  spoken report (Great-Sage voice: "Two changes promoted. One proposal awaiting your approval.
  One rollback after a failed probation.") — long detail goes to screen, spoken stays ≤2 sentences
  per item (REQUIREMENTS_ADDENDUM §10 speech rules).

## 5. Modes

`config.d/evolution-persona.yaml` (lane-owned fragment, AGENT_RULES §3):

```yaml
evolution:
  mode: propose          # off | propose | auto_safe   (DEFAULT: propose)
  budget: {max_patches_per_day: 3, max_steps_per_patch: 40, max_tokens_tier: free}
  idle_only: true        # cycles run only when no user-facing job is active
  probation: {jobs: 20, hours: 24}
  journal_dir: docs/evolution/journal
```

- `off` — detection still journals findings, no patching.
- `propose` — everything through step 5 runs, **zero** merges; all outcomes are proposals.
- `auto_safe` — the full pipeline including auto-promote, but **only** for mutable-zone changes
  passing every gate; Core Guard always stays proposal. `off`/`propose` cannot be changed by a
  self-proposal that raises autonomy — mode escalation itself is a proposal (§6 hard rules).

## 6. Hard rules (enforced in code + tested, not conventions)

1. **Never expand own permissions** — no new tools, allow-list entries, capabilities, or mode
   escalation via an auto-promoted change (addendum §14 self-escalation boundary).
2. **Never disable/weaken** kill switch, pause, private mode, confirm gate, auth.
3. **Never touch secrets** — `.env`/token paths are read-never-written by the controller; a diff
   touching them aborts the cycle and journals a security finding.
4. **Never change network exposure** — bind, port, listeners, protocol auth stay put.
5. **Never push public** — no `git push` at all from the controller (repo remote stays integrator's).
6. **Bounded budget** — daily patch cap + per-patch step cap; over cap ⇒ stop and journal.
7. **Idle-only** — never runs while a user-facing job holds attention/input lock.
8. **Free models only** — no Go/paid dispatches; router gates are not bypassable anyway.
9. **Never loops** — one attempt per finding; the same failure 3× ⇒ blocker + proposal (AGENT_RULES §11 escape hatch).
10. **Fail closed** — unclassifiable path = Core Guard; missing manifest = controller refuses to run.

## 7. Dependencies / contract gaps to resolve at Wave 4 start (write requests, keep working)

| Gap | Owner | Status / next step |
|---|---|---|
| `shadow` row missing from instance-derivation table | brain-core | **OPEN** — `evolution-persona__to__brain-core__shadow-instance-row.md` (2026-10-05); `brain/config.py` now raises loudly for unknown instances, so this hard-blocks shadow runs until done |
| Extend `tests/core_guard.py → CORE_GUARD_FILES` to the full §1.1 set (supervisor/**, brain/evolution/**, PROTOCOL §7 allow-list artifact, tests/**) | qa-security | to write at Wave 4 start (today's manifest covers only the 4 core files — keep it as the single source of truth and grow it, do not fork one) |
| Out-of-band rollback hook: what exactly does supervisor expose (command/endpoint) for LKG re-point? | infra | to write at Wave 4 start |
| Test-suite entry point + golden-transcript harness seam (mock router fixture) — root `tests/` now has `run_all`, `harness/`, `conformance/`, `contract/` to reuse | qa-security | to write at Wave 4 start |
| Router "weights" (benchmark ranking) file path ownership for the mutable zone | router | to write at Wave 4 start |

## 8. Test plan (lane tests, `brain/evolution/tests/`)

- Manifest verify: intact ⇒ pass; single-byte flip of a guarded file ⇒ refuse (with file name).
- Classifier: every Core Guard path ⇒ guarded; every mutable path ⇒ mutable; unknown path ⇒ guarded (fail-closed); safety-tunable inside a mutable file ⇒ guarded.
- Budget: cap hit ⇒ cycle stops, journal written, zero worktree created.
- Idle-only: user-facing job active ⇒ cycle skipped.
- Shadow run with mock Body: golden transcript replay is deterministic (two runs identical).
- Compare: injected unintended delta ⇒ no promote.
- Promotion: mutable+pass ⇒ merged+tagged; core+pass ⇒ proposal only (assert no merge).
- Probation rollback: simulated failure ⇒ automatic rollback invoked + journal `rolled_back`.
- Mode gating: `off`/`propose` never merge; mode escalation proposal cannot self-approve.
