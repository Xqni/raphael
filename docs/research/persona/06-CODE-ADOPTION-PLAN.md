# 06 — CODE ADOPTION PLAN: Raphael/Ciel persona + companion takeaways

**Date:** 2026-10-09 · **Author:** integrator · **Status:** PROPOSED — lanes stay paused until the user says go; this is the packet for a **Wave 5P persona sprint** (inside wave 5, `current_wave` stays 5, same shape as wave-5H).
**Sources:** `persona/00-CONSOLIDATED-BRIEF.md` (canon, service model, autonomy rules, tone spec, debunk register), `../companions/00-COMPANION-TAKEAWAYS.md` (A1–A4 + rejections), `R1-ARCHITECTURE.md` (coupling findings), `R4-GAPS.md`/`R5-DECISIONS.md` (confirm batch overlaps).

**Design laws that bind every task below (from the research, non-negotiable):**
1. **Canon autonomy split:** act-first-and-report when intent is unambiguous; confirm-first for irreversible, destructive, or personal-domain acts; never destroy a resource silently; report every autonomous action afterward; honest about limits.
2. **Tiers are growth, not replacement** (great_sage → raphael → ciel = one continuous assistant; canon continuity).
3. **Debunk register is binding** — no refuted claim enters prompts, docs, or voice strings.
4. Ground rules preserved: text-free orb, Core Guard strength, cloud-only mandate, no-text-on-orb.

---

## Wave 5P packets

### P1 — Persona tiers as runtime state (brain-core + evolution-persona + config)
- `config.yaml` (integrator): `persona: {tier: raphael, locked: false}` + per-tier blocks carrying the P05 tone spec (pitch/warmth/pacing suggestions) and prompt identity lines.
- `brain/persona/` (evolution-persona): tier prompts authored FROM the canon brief — `great_sage` (system-voice, flat, no opinions, bracketed-style brevity), `raphael` (first-person, dry-warm, formal address, initiative within the autonomy split), `ciel` (expressive-warm, anticipatory; promotion still gated per CIEL-PROMOTION.md).
- `brain/loop.py` prompt assembly (brain-core): tier selects the persona block; tier is a session-settable field (`/control`), default from config.
- Tests: tier prompt selection, tier changes mid-session, debunk-register lint (a test asserting refuted strings never appear in persona assets).
- Acceptance: with tier=raphael, one live (when stack is up) answer shows first-person dry-warm register; tier=ciel shows warmth delta in a controlled A/B.

### P2 — Voice tier parameters (voice)
- Per-tier fish parameters from the P05 guide (flat/neutral → +slight warmth → +clear warmth; pacing; breath-before-emotive) as config, NOT hard-coded.
- A/B against `assets/raphael_reference_jp.wav` with the existing round-trip battery; no regression on the P0 drift fix (10/10 stays ≥9).
- Deliverable: measured per-tier samples in the vault (`vault/persona/` note) for the user to judge.

### P3 — Confirm policy = user-editable (A2 + R5 confirm-categories + R1 config-driven risk) (brain-core + integrator)
- `safety.confirm_policy` in config (Core-Guard-adjacent, integrator-owned): per-action-class `auto | confirm | never` with named classes (`gui_submission`, `open_arbitrary_file`, `files_write`, `web_publish`, `system_*`).
- `brain/confirm.py`: policy lookup before risk regex; regex stays as the fallback for unclassified tools (R1's externalize-risk-patterns finding folds in here).
- Spoken surface: "what requires your confirmation?" answers the policy; policy edits go through confirm (self-protecting).
- Tests: policy matrix, unclassified-tool fallback, confirm-gate xfail cluster stays green (qa's pinned tests).

### P4 — Clarify-on-ambiguity (A1) (brain-core + voice)
- Low-confidence intent path (fastpath miss + weak LLM intent): ONE clarifying question (spoken, tier-toned), max 1 repeat, then best-effort act with report or refusal — never N guesses.
- Config: `clarify: {enabled: true, max_questions: 1}`.
- Tests: ambiguous command fixtures, clarify→answer second-turn resolution, no-clarify when fastpath confident.

### P5 — Named context slots (A3) (tools-memory + brain-core)
- Slot = named short-term context ("work", "travel") selectable by voice ("switch to travel"); memory retrieval scoped to active slot; slots persist per session, optional save.
- `brain/memory` slot scoping + `brain/loop.py` per-turn injection slot awareness + a small confirm for slot creation? (no — creation is cheap/local: act-first).
- Tests: slot isolation of retrieval, switch mid-conversation, default-slot parity with today's behavior.

### P6 — Spoken memory privacy (A4) (tools-memory)
- Verify what wave-4 memory export/delete already shipped; add the spoken affordances: "what do you remember about X" (scoped recall answer), "forget X" (delete with confirm — destructive → P3 confirm), "memory report" summary.
- Tests: recall scoping (no cross-owner leakage), forget actually deletes (idempotent), private-mode interaction.

### P7 — Journal as a memory surface (integrator + tools-memory)
- A `journal` tool: append a dated entry to her vault journal (`vault/journal.md`, gitignored) — she logs milestones/decisions herself; reads back on "what did you do recently".
- Content rules: no secrets (scanner runs on it? it's gitignored — the tool enforces a redaction pass before write), append-only.
- Tests: append format, redaction of key-shaped strings, read-back.

### P8 — Proactive Notice tone per tier (voice + brain-core) [small]
- Notice phrasing per tier (P05/notice_spoken_text already tiers info/warn) — extend with persona register; no behavior change.
- The proactive-suggestion EXPANSION stays DEFERRED (AUD-06 human gate) — this packet only tones what already exists.

---

## Explicitly NOT in this sprint (on record)
- Cloud-VM execution, social/mobile/AR surfaces, mouth-anthropomorphism (companion takeaways §4).
- Background proactive suggestion engine (AUD-06 human gate).
- Cross-device sync (privacy stance; vault sync for docs only).
- Wave-6 local-model work (RAM gate).

## Merge/dependency order proposal
`P1 (persona+tier config) → P4 (clarify) + P3 (confirm policy) in either order → P5 slots → P6 memory-privacy → P7 journal → P2 voice tiers (can parallel P4+, needs P1 config) → P8`. P3's config block is integrator-authored first (Core Guard), then brain-core implements.

## Exit criteria (proposed)
1. All P-packets merged with green branch CI per lane (QA-4 as usual).
2. Debunk-register lint test green; tier prompts traceable to the canon brief.
3. qa's confirm/act pinned tests all green (no security regression; gates stronger, never weaker).
4. Voice: P0 drift battery still ≥9/10; per-tier A/B samples produced for the user.
5. User hears tier=raphael live and either approves ciel promotion criteria or adjusts tone.
