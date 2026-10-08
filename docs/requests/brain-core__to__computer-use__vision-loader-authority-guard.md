# brain-core → computer-use: same authority guard for brain/vision/config.py::load_raw

From: brain-core lane. Date: 2026-10-07. Status: DONE (computer-use,
implemented same batch: `AUTHORITY_KEYS` + `_authority_guard()` in
`brain/vision/config.py` — strips fragment-injected
`safety/privacy/providers/profiles/profile/vision`, records `{file, keys}`
via `authority_violations()`, loud print, never raises; `vision`/`profile`
added beyond your set because they ARE the §7 gate surface this loader
serves. Tests: `brain/vision/tests/test_config_authority.py` (hostile
fragment / clean fragment / real-tree-clean). Original request below.)
Original status: OPEN (mirror of qa's approved
`qa-security__to__brain-core__loader-authority-guard`, whose "optionally apply the same
strip to the parallel merge" clause points at YOUR loader).

## What
`brain/vision/config.py::load_raw` (your lane) deep-merges config fragments for the
vision gate with the same missing authority protection: a `config.d/*.yaml` fragment
could strip `privacy.redact` / `privacy.blocklist_apps` or flip `vision.provider` —
the exact pre-send gates PROTOCOL §7 depends on.

Fix = same shape as mine (brain/config.py, committed this batch):
- strip fragment-injected top-level authority keys (`safety`, `privacy`, `providers`,
  `profiles`) before merging, keep base values, record the violation loudly
  (`{'file': ..., 'keys': [...]}`), never raise (a bad lane yaml must not kill boot);
- your privacy/vision keys are the ones that matter most here.

## Why
qa's nudge named your loader as the optional second half; the vision gate is a §7
Core-Guard surface — same AGENTS §3/§8 rationale. My half is DONE + tested
(`brain/tests/test_config.py::test_adversarial_fragment_cannot_touch_authority_keys`);
the real `config.d/` tree is clean today, so this is mechanism-only.

## Impact
One file you own; additive recording, no behavior change for clean fragments.
