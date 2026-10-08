# brain-core → integrator: ARCH-5 design note — cloud_temp as primary profile + `hybrid`

From: brain-core lane. Date: 2026-10-07. Status: OPEN (DESIGN ONLY — Wave-5H packet:
"Design only, no code". The `profiles:` block + config.yaml docs are integrator-owned
(INTERFACES §c), so this ships as a proposal.)

## Current state (verified file:line)
- `config.yaml:174-180` — `profiles:` holds exactly two entries: `cloud_temp: {}`
  (the TEMPORARY-PIVOT overlay, effectively a no-op) and `local` (Wave-6 cutover).
- `config.yaml:11` `profile: cloud_temp`; the header comments still call it a
  "TEMPORARY PIVOT (2026-10-05 …)" — i.e. cloud_temp is functionally primary but
  documented as temporary; there is no `hybrid` profile and no alias mechanism.

## Proposed shape (no code from me until approved)
1. **cloud_temp becomes first-class**: keep the NAME `cloud_temp` as the canonical
   primary (zero migration for supervisors/tests), update the config.yaml header +
   ARCHITECTURE §6 to document it as THE primary cloud profile; add
   `profiles.cloud_temp:` content only if/when it must override anything (today `{}`).
2. **Old-name alias**: if you prefer a cleaner canonical (e.g. `cloud`), add a
   top-level `profile_aliases: {cloud: cloud_temp}` map — my loader
   (`brain/config.py::load_config`) will resolve `RAPHAEL_PROFILE=cloud` (and the
   file `profile:` key) through it, reporting the CANONICAL name in `cfg['profile']`.
   (Loader change is ~5 lines + tests — I'll implement in the same batch you confirm
   the direction: keep-name-canonical vs rename-with-alias.)
3. **`hybrid` profile** (new, your block):
   ```yaml
   hybrid:
     profile: hybrid
     # cloud chat/tools stay as in cloud_temp (paid-fast per Rule 15)
     local_model: { enabled: false }          # no local LLM/VLM
     voice: { stt_engine: groq }              # cloud STT as today
     # tiny CPU-only LOCAL helpers that must stay on even in hybrid:
     #   - wake word + VAD/segmentation (body-side, config voice.always_listen)
     #   - playback-echo guard + activation gate (brain/voice/activation.py)
     #   - TTS stays LOCAL Fish-Speech in EVERY profile (user directive)
   ```
   Hybrid = cloud models + the always-on local helper set; it differs from
   `cloud_temp` mainly in documentation/intent (helpers explicitly protected) and
   from `local` (no local LLM).
4. **Tests I own once landed** (loader-level, already sketched in
   `brain/tests/test_config.py`): `RAPHAEL_PROFILE=hybrid` selects the overlay;
   alias resolution (if adopted) reports the canonical; unknown profile still
   raises loudly (existing test).

## Impact
Integrator-only edits to config.yaml + docs; my loader work is additive and
backward-compatible (unknown names keep today's behavior). No Core Guard surface.
