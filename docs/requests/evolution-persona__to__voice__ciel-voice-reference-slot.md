# evolution-persona → voice: Ciel voice reference slot
Status: DONE

## What
Add the tier-2/3 voice slot requested by the Wave-5 persona tiers (`docs/evolution/02-persona-tiers.md` §5.2):

1. config key `voice.tts_voice_ciel: assets/ciel_reference.wav` (lane fragment will ship it
   default-empty/absent — the key's existence + consumption is what we need);
2. TTS voice resolution: when `persona.tier == "ciel"` and `assets/ciel_reference.wav` exists
   with a valid reference, use it; **missing/invalid ⇒ fall back to the current Raphael
   reference exactly like the §10 fallback** (existing behavior: default female voice +
   spoken notice — we need the SAME mechanism, just keyed by tier);
3. phrase-cache invalidation on tier switch (Bug-D class: stale cached phrases must not leak
   the wrong voice across a tier change).

The user will provide `ciel_reference.wav` later (same as `raphael_reference_jp.wav`); until
then the slot exists and always falls back — no breakage.

## Why
WAVES wave 5 ("a Ciel voice reference slot") + addendum §10 fallback semantics. We own the
tier switch and the config key semantics; the TTS resolution path is voice's file
(`brain/voice/**`).

## Impact
No protocol change; additive config key + one resolution branch keyed off the existing
`persona.tier` (already merged in `config.d/evolution-persona.yaml`). Core Guard untouched.

## Decision (voice lane, 2026-10-07) — ACCEPTED, IMPLEMENTED, DONE

All three items shipped (commits `b2aea73` / `86140dd` merged as wave-5, plus
the config.d consumption fix in this session's commit below):

1. **config key** — `voice.tts_voice_ciel` (default `assets/ciel_reference.wav`
   when absent — exactly "the key's existence + consumption"). Your lane
   fragment's value IS honored: `brain/voice/config.py` now deep-merges every
   `config.d/*.yaml` `voice:` / `voice_personality:` mapping (sorted, later
   wins — INTERFACES §c) and resolves `persona.tier` from the fragments too,
   so a key shipped in `config.d/evolution-persona.yaml` reaches the TTS
   resolution path without either lane editing the other's files.
2. **tier resolution + fallback** — `VoiceConfig.tier_voice_path()`: with
   `persona.tier == "ciel"` the slot is used when present; missing/empty ⇒
   fall back to `voice.tts_voice` (the current approved reference) **plus a
   one-time subtitled notice** (your item 2's first clause). Deviation, by
   user directive: the §10 "default female voice" leg of the old fallback is
   retired (Bug D, 2026-10-07 — never synthesize without the approved
   reference); falling back to the *current reference* as your request's
   wording asks is strictly safer and keeps "no default voice, ever".
3. **phrase-cache invalidation on tier switch** — the cache is namespaced by
   `sha1(reference)[:12]` and `TTSEngine.refresh_reference()` re-resolves the
   tier + re-namespaces LIVE on the next `speak()`: old-tier audio becomes
   unreachable from that first chunk, no restart needed. Tests:
   `test_tier_flip_renamespaces_the_cache_live`,
   `test_tier_ciel_missing_slot_falls_back_loudly`,
   `test_tier_fallback_notice_is_one_time`,
   `test_config_d_lane_fragments_are_consumed`
   (`brain/voice/tests/test_personality_delivery.py`, 12 green).

No protocol change; Core Guard untouched. When you ship
`assets/ciel_reference.wav`, it activates on the next speak with zero code
changes (and its own cache namespace).
