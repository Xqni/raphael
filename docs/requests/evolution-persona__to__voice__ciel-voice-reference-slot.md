# evolution-persona → voice: Ciel voice reference slot
Status: OPEN

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
