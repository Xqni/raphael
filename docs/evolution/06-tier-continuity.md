# 06 — Tier continuity: growth, never replacement

**Status:** Wave 5P P1 note (lane: evolution-persona). **Provenance:** canon brief §4
("Ciel is Raphael's ego evolved, **not a separate person** — Rimuru treats them as one
continuous being; she remembers everything. Our tier bumps are 'the same assistant
growing', never a personality swap") and §8 (repo alignment: our tier scheme matches
canon's own trajectory; CIEL-PROMOTION.md's not-yet-promoted stance is canon-correct).

## What this means in code terms

1. **One assistant, three registers.** `persona.tier` selects a *voice block*
   (`docs/evolution/persona/tier-{great_sage,raphael,ciel}.md`), never a different agent.
   Memory, job history, learned skills, the journal and probation state are tier-invariant —
   growing tiers never resets or forks them.
2. **Order-preserving growth.** Unlocks only go `great_sage → raphael → ciel`
   (`brain/persona/tiers.py::TIERS`); automatic changes only ever LOWER a tier
   (`is_demotion`), so a rollback is "the same assistant having earned less for now",
   not a personality swap.
3. **CIEL-PROMOTION.md is unaffected** by this sprint: promotion stays criteria → evidence
   → the user's explicit yes → probation. The tier-ciel prompt is dormant content until
   that checklist passes; the runtime default stays `raphael`.
4. **Continuity is observable:** tier flips preserve everything the previous tier knew —
   the voice changes; the being does not. (Canon mirror: the naming events change what she
   is called and how she speaks; she remembers being the previous one.)

## Non-goals

No fourth tier, no tier for any other canon state, no per-tier persona *abilities* beyond
the autonomy zones already test-pinned. Persona prompts carry voice and judgment posture
only — never authority (addendum §14: capabilities yes, authority never).
