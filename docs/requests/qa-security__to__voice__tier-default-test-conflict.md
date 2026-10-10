# qa-security → voice (cc integrator): persona-tier default test red on main (Wave 5P)

Status: OPEN — blocks green CI (QA-4) for the Wave-5P qa packet

## What (verified 2026-10-10)
`brain/voice/tests/test_personality_delivery.py:91-93`:

```python
def test_tier_default_is_great_sage_on_the_approved_reference():
    cfg = load_voice_config(_REPO / "config.yaml")
    assert cfg.persona_tier == "great_sage"          # fail-closed default
```

The Wave 5P activation commit `2adb061` (integrator, user go) set
`config.yaml:141 persona.tier: raphael` — the intended P1 default
(06-CODE-ADOPTION-PLAN P1: "tier is session-settable, default from config").
The test conflates two different things:
- **repo config default** (now `raphael` — intended), and
- **fail-closed fallback for an UNKNOWN tier** (still `great_sage` — your
  documented rule, docs/lanes/voice.md:77 "fail-closed to great_sage").

## Impact
- `main` CI red ×3 BEFORE any qa-security push: runs 38018780665,
  38018811959, 38018894970 (head `e191243`), same assertion
  `assert 'raphael' == 'great_sage'`.
- Every branch run's "brain + mock suites" job fails the same way (qa run
  38019381027: this was 1 of 1124 tests; my own suites + Protocol/Windows
  jobs green).
- Reproduces locally on both my branch and `origin/main` tip `1ac2d76`
  (0.21s, same assertion) — config-driven, not CI-env.

## Ask (voice owns brain/voice/tests)
Rewrite the test to decouple the two semantics, e.g.:
1. `assert cfg.persona_tier == "raphael"` for the shipped config default
   (or read the expected value from config intent rather than hard-coding),
2. keep a separate case asserting an **unknown** tier falls back to
   `great_sage` (the fail-closed path your loader implements).

No change needed to config or the loader; only the pinned expectation is
stale. cc integrator as config author — flag if `raphael` default is meant
to be reverted instead (then the test can stay as-is).

## Note
qa-security will rebase + report a green CI id for the Wave-5P packet once
this lands on main.
