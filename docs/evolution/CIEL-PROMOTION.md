# CIEL-PROMOTION.md — Ciel promotion checklist (F-6, Wave-5H audit)

**STATUS: CHECKLIST ONLY — NOT PROMOTED.** `persona.tier` is `great_sage` (default).
Promotion happens only when every box below is checked **and the user says yes** —
tiers are never self-granted (addendum §14: "the crown stays user-placed"; design
`02-persona-tiers.md` §2.1; controller hard rule 01 §6.1).

Run the checks in order; a failed box stops the run. Record the result as a journal
entry (`docs/evolution/journal/`) whatever the outcome.

## 1. Unlock criteria — machine-evaluated (never auto-applied)

- [ ] `brain.persona.tiers.evaluate_unlock(stats, "ciel")` returns `ready: True`
      with **`unmet == ["user approval"]` only** (all three auto-criteria met):
  - [ ] `days_stable >= 30` on the current tier (source: journal + git log dates),
  - [ ] `failed_probations == 0` (every auto-promoted change's probation passed —
        `docs/evolution/journal/` entries with `decision: promoted` + no
        `rolled_back` during the window),
  - [ ] `rollbacks == 0` in the window.
- [ ] Current tier is `raphael` (a jump `great_sage → ciel` is not offered;
      `tiers.is_demotion` ordering is `great_sage < raphael < ciel`).

**Evidence required:** the literal `evaluate_unlock` output (met/unmet lists) pasted
into the journal entry — not a summary, the output.

## 2. System evidence at the time of request

- [ ] Full mock suite green **with a linked CI run** (QA-4: `gh run list
      --workflow=ci.yml` → run id; wave_done is bounced without it).
- [ ] `python tests/core_guard.py` → `Core Guard OK` (byte-stable).
- [ ] Shadow pipeline green for the last promotion: `brain/evolution/shadow.py`
      `run_tests()` `ok: True` + `baseline.compare()` `ok: True`.
- [ ] No open `blocked`/`error` events for this lane in the coord bus.

**Evidence required:** CI run id + the four command outputs in the journal entry.

## 3. User approval step (the only step that can flip the tier)

- [ ] The proposal is SPOKEN/SHOWN to the user with the criteria summary from §1
      ("30 days stable, no rollbacks, no failed probations — approve Ciel?").
- [ ] User answers yes **explicitly** (voice `confirm_resp`, text, or direct
      instruction). Silence, timeout, or an unprompted internal "ready" is **no**
      (confirm timeout = abort, PROTOCOL §9).
- [ ] Approval recorded verbatim in the journal entry
      (`decision: promoted`, `zone: mutable`, `reason:` quoting the user).
- [ ] Only then: flip `persona.tier: raphael` → `ciel` in
      `config.d/evolution-persona.yaml` (either by hand or
      `brain.persona.probation.apply_tier(text, "ciel", write_to=...)` — the
      line-scoped edit preserves every other key; round-trip tested).
- [ ] The flip commit is a normal commit on the lane branch → integrator merge
      (never pushed public, never auto-merged by the controller).

## 4. Voice reference slot (already implemented — verify at promotion time)

Status: **DONE** — `evolution-persona__to__voice__ciel-voice-reference-slot.md`
(commits `b2aea73`/`86140dd` + config.d consumption fix).

- [ ] `voice.tts_voice_ciel` resolves (`brain/voice/config.py` deep-merges lane
      fragments; `VoiceConfig.tier_voice_path()` reads `persona.tier`).
- [ ] `assets/ciel_reference.wav` present and the user confirms it is the voice
      they want (**check before flipping**; missing ⇒ loud one-time fallback
      notice to the current approved reference + phrase cache re-namespaced live —
      `test_tier_ciel_missing_slot_falls_back_loudly`,
      `test_tier_flip_renamespaces_the_cache_live`).
- [ ] Smoke: one spoken reply after the flip is in the Ciel voice, no stale
      cached phrases from the old tier.

## 5. Orb theme (already implemented — verify at promotion time)

Status: **DONE** — `evolution-persona__to__orb__ciel-gold-palette.md`.

- [ ] `persona.tier == "ciel"` → `orb.theme: auto` → `THEMES.ciel`
      (`body/orb/src/renderer/palette.js → CIEL`, gold-leaning: haze `#E8B84B`,
      ring `#FFE9B8`, glyph `#FFC247`, warm-white core `#FFF6E3`).
- [ ] Palette switches **live** on the next `orb_state` (config stat ≥1 s
      throttle, no restart).
- [ ] Regression: `tests/palette.test.mjs` still asserts
      `great_sage and raphael are BYTE-IDENTICAL palettes`.

## 6. Probation window after the flip (automatic; demotion only ever LOWERS)

- [ ] `brain.persona.probation.start("raphael", "ciel", {"jobs": 20, "hours": 24})`
      — starts ONLY after the approved unlock (an upward start without approval
      raises `ValueError`; test `test_start_refuses_non_unlocks`).
- [ ] Window passes only with **both** 20 clean jobs **and** 24 hours
      (`evaluate()`); a fatal event (severity-1, rollback, confirm-timeout
      regression) fails it instantly and it is sticky.
- [ ] Failure ⇒ `demotion_target("ciel") == "raphael"` + `apply_tier(...)` —
      automatic demotion is permitted (it lowers autonomy); a RE-promotion to
      ciel again requires §3 approval.
- [ ] Journal entry for the probation outcome (passed/failed) with the reason
      string.

## Do-nots (standing)

- Never flip the tier without §3's explicit yes — not for demos, not for tests.
- Never let the evolution controller auto-promote a diff touching
  `persona.tier` (it classifies as CORE-adjacent → always a proposal).
- Never skip the CI-link (QA-4) or the core-guard check at §2.
- Never synthesize a Ciel voice from a non-approved reference (Bug D rule).

## Two open Ciel requests — STATUS (verified 2026-10-07)

| Request | Status | Evidence |
|---|---|---|
| `evolution-persona__to__voice__ciel-voice-reference-slot.md` | **DONE** | Decision section: "ACCEPTED, IMPLEMENTED, DONE — All three items shipped (commits `b2aea73` / `86140dd` …)" — key + tier resolution/fallback + live cache namespacing, 4 tests |
| `evolution-persona__to__orb__ciel-gold-palette.md` | **DONE** | Decision section: "ACCEPTED, all three requirements" — `palette.js → CIEL` swatches, live switch via config stat, `tests/palette.test.mjs` byte-identical guard |

Nothing external blocks §4/§5 today; the only gates are §1–§3 (criteria + evidence +
the user's yes).
