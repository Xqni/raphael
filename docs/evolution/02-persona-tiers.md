# 02 — Persona tiers and Ciel (Wave 5 design notes)

Status: **DESIGN ONLY — not implemented.** Do not start before `current_wave: 5` (AGENT_RULES §11).
Owner: evolution-persona lane (`brain/persona/**`, `docs/evolution/**`).
Basis: REQUIREMENTS_ADDENDUM §10 (Great Sage character), §14 (persona profiles = tier 3, crown
user-placed), WAVES.md Wave 5, PROTOCOL.md §3/§5/§8.

## 1. Module layout (planned)

```
brain/persona/
├─ tiers.py        # tier definitions, unlock criteria evaluation, enforcement
├─ formats.py      # Answer / Notice / Report reply-format shaping
├─ voice_slot.py   # Ciel voice reference slot resolution (falls back to Raphael reference)
├─ palette.py      # per-tier palette payload for the orb (gold-leaning for Ciel)
└─ tests/
config.d/evolution-persona.yaml  # persona.tier + format/palette tunables (lane fragment)
```

Tier is a **config switch, not a model decision**: `persona.tier` in config; the model never
self-grants a tier (addendum §14 — "the crown stays user-placed").

## 2. Tiers

| Tier | Character | Autonomy | Persona surface |
|---|---|---|---|
| `great_sage` (default) | calm, precise, analytical, devoted (§10) | **proposes only** — never acts on its own | current Raphael voice/acks, current palette |
| `raphael` | same core character, more proactive | **small safe autonomy zone**: proactive `Notice` events, unprompted checks, background scheduling of *non-risky* jobs — everything still confirm-gated, allow-listed, budgeted | Notice-style proactive speech; slight warmth delta, no role change |
| `ciel` | personable, warmer, more expressive (still she/her, still uncensored per §16a) | **broader EARNED autonomy**: a wider set of auto-start background classes (file/web/read-only analysis, reminders, summaries) — still never Core Guard, never money, never secrets, never network-write/public | Ciel voice reference slot, gold-leaning palette, warmer reply style |

### 2.1 Unlock criteria (explicit, machine-checkable, user-approved)

Every unlock is **evaluated but not applied** by the system: the criteria produce a
`tier_unlock_available` proposal; the user flips `persona.tier` (voice/text: "switch to raphael"),
and only that flips it. Never self-granted, never auto-promoted by the evolution pipeline
(the evolution controller's own hard rule: persona tier is Core Guard-adjacent — a tier change is
always a proposal).

| From → To | Criteria (all must hold) | Evidence source |
|---|---|---|
| `great_sage` → `raphael` | ≥7 days uptime without a severity-1 failure; full test suite green at last LKG; ≥95% job success over the window; zero unhandled confirm-timeouts; user says go | task journal, test results, evolution journal |
| `raphael` → `ciel` | previous tier stable ≥30 days; probation of every auto-promoted change passed; zero rollbacks in the window; explicit user approval recorded in the journal | evolution journal + user record |

Criteria are reported with the proposal ("you are 4 of 5 days in") — the system never nudges,
never guilts, and stops asking once declined for the day.

## 3. Reply formats: Answer / Notice / Report

A per-reply shaping rule applied *after* the loop produces content (never a new source of truth):

| Format | When | Spoken | On screen |
|---|---|---|---|
| **Answer** | direct question | ≤2 sentences, direct answer first, then nothing (§10) | full detail + provenance/source flags (addendum §15b) |
| **Notice** | proactive/unprompted surfacing (battery, deadline, "two tasks remain") | ≤1 sentence + the actionable item | context, why it matters, suggested action |
| **Report** | job/analysis completion, weekly evolution summary | ≤2-sentence summary line ("Analysis complete. Two risks found.") | structured body: findings, evidence (`file:line`), confidence, next steps |

Format is chosen by a deterministic classifier (event kind: question → Answer; proactive event →
Notice; terminal `job_event(done)` for analysis/report jobs → Report) with LLM-only fallback;
misclassification degrades to Answer (never fabricates a proactive Notice). Private mode still
suppresses subtitles; paused mode still queues.

**Contract note:** `speak`/`subtitle`/`job_event` frames already carry text — formats are shaping
rules inside the Brain, so no PROTOCOL change is needed for §3 itself. (Proactive Notices do need
the Wave 3 `Notice` event from brain-core — dependency, see §6.)

## 4. Job types: `Analysis` and `Simulation`

Additions to the job engine's `task_kind` vocabulary (job engine = brain-core's `brain/jobs/**`):

- **Analysis** — read-only deep pass over inputs (files/logs/memory/web): long-running,
  `priority: background`, `lock: false`, output = Report format, results persisted to memory with
  provenance. No side effects outside the memory store.
- **Simulation** — sandboxed "what would happen" dry run: replays a plan against the **mock Body /
  shadow harness** (reuses Wave 4's shadow instance, §01) and reports the predicted `act_req`
  stream without executing anything on the machine. `lock: false` always; never touches the real
  input path.

Both are **announceable** to the orb via the existing `job_event` states (`thinking`/`acting`), so
the state machine in PROTOCOL §8/INTERFACES (e) is unchanged; only the `task_kind` enum grows
(`analysis`, `simulation`) — which is a shared contract value consumed by `orb.shape_map`.

## 5. Orb/voice surfaces for Ciel (three sub-items)

1. **Parallel-minds status events** — when several worker jobs run concurrently, the orb gets a
   parallel-minds visualization driven by status events. Design: reuse `jobs_active` + per-job
   `job_event`/`shape_hint` already in the contract; add an optional `minds[]` summary
   (`[{job, task_kind, stage}]`, capped) on `orb_state`. **Protocol change → request to the
   integrator/protocol-architect; orb renders it only if present (backward compatible).**
2. **Ciel voice reference slot** — `voice.tts_voice_ciel: assets/ciel_reference.wav` (missing ⇒
   falls back to `assets/raphael_reference.wav` + spoken notice, exactly like the existing §10
   fallback). Asset + voice lane code are voice-lane owned → **request**, we only own the config
   key and the tier→slot mapping.
3. **Gold-leaning Ciel palette** — `persona.palette.ciel` (gold/amber-leaning; Raphael's palette
   untouched) delivered as a small payload on `state_req`/auth snapshot. Renderer = orb lane →
   **request** with exact swatches; we own the values and the tier switch.

## 6. Dependencies to resolve at Wave 5 start (write requests, keep working)

| Gap | Owner | When |
|---|---|---|
| Wave 3 proactive `Notice` event (basis for the Notice format) | brain-core | at Wave 5 start |
| `task_kind` enum + `orb.shape_map` entries for `analysis`/`simulation` | brain-core + orb | at Wave 5 start |
| `minds[]` field on `orb_state` (parallel-minds) | integrator (PROTOCOL) + orb | at Wave 5 start |
| Ciel voice reference slot behavior | voice | at Wave 5 start |
| Gold palette swatches + delivery payload | orb | at Wave 5 start |
| `persona.tier` unlock evaluation + proposal plumbing | evolution-persona (us) | own work |

## 7. Test plan (lane tests, `brain/persona/tests/`)

- Tier enforcement: `great_sage` emits zero proactive Notice jobs; `raphael` emits only
  allow-listed non-risky proactive jobs; `ciel` never gets money/secrets/network-write classes
  (table-driven negative tests).
- Self-grant impossible: code path that attempts `persona.tier` write outside an approved
  proposal ⇒ rejected (evolution pipeline integration test).
- Format shaping: each format respects its spoken length cap; misclassification degrades to
  Answer; private mode still suppresses subtitles.
- Voice slot: Ciel tier + missing `ciel_reference.wav` ⇒ fallback + spoken notice.
- Palette: tier switch changes payload; Raphael palette byte-identical to baseline.
- Job types: Analysis runs read-only (mock fs) with Report output; Simulation's `act_req` stream
  targets the mock Body only — assert zero real input-path calls.
