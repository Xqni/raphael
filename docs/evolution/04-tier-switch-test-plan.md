# 04 — persona tier switch: deep-merge test plan (executed)

Status: **IMPLEMENTED & PASSING 2026-10-07** (lane task: "persona tier switch deep-merge test
plan"). Test code: `brain/persona/tests/test_tier_switch.py` (+ guard-rail helpers in
`brain/persona/tiers.py`, lane fragment `config.d/evolution-persona.yaml`).

## Mechanism under test

`persona.tier` lives in **our** lane fragment `config.d/evolution-persona.yaml` (AGENT_RULES
§3). Per-tier `voice_personality` overlays ride the standard loader order (INTERFACES §c:
`config.yaml` → `config.d/*.yaml` sorted deep-merge → profile overlay): mappings merge,
lists/scalars replace. The integrator-owned `config.yaml` is never edited, and **`great_sage`
is by definition the tier that changes nothing** (no overlay keys). Design:
`02-persona-tiers.md` §1.

## Layer A — real repo (fragment must be safe by construction)

| # | Case | Assertion |
|---|---|---|
| A1 | default tier | effective `persona.tier == great_sage`, in `tiers.TIERS` |
| A2 | great_sage = identity | effective `voice_personality` **byte-equals** base `config.yaml`'s block |
| A3 | authority untouched | effective `safety` / `privacy` / `providers` == base config.yaml (a lane fragment can never alter Core Guard switches) |
| A4 | safe evolution defaults | `evolution.mode == propose`, `evolution.idle_only == true` |

## Layer B — tmp config tree (merge semantics per future tier)

| # | Case | Assertion |
|---|---|---|
| B1 | `raphael` overlay | only overlay keys change (`character`, `style`, `speech_forms`); `banned`, `spoken_reply_max_sentences`, `proactive_warnings` inherited |
| B2 | lists replace | `speech_forms` replaced wholesale, never appended |
| B3 | `great_sage` fragment | `voice_personality` == base (identity) |
| B4 | `ciel` overlay | overlay applies; unspecified keys inherited from base |

## Layer C — guard rails (`brain/persona/tiers.py`)

| # | Case | Assertion |
|---|---|---|
| C1 | fail closed | unknown/missing/empty tier (`GOD`, `""`, `None`) → `great_sage` |
| C2 | unlock check | `is_unlocked` requires exact match; never partial/near tier names |

Everything not covered here is **by design out of scope** for a config switch: actual
unlock *criteria evaluation* and the proposal plumbing (user approval required) are Wave 5
work per `02-persona-tiers.md` §2.1; self-grant impossibility is proven in the evolution
controller's tests (design 01 §6 rule 1 — a diff touching `persona.tier` is always a
proposal), not in the loader.

## Test output (real, 2026-10-07)

```
$ tests/.venv/bin/python -m pytest brain/persona/tests -q
14 passed in 0.10s
```

No servers, no network, no provider calls — config-loader only (AGENT_RULES §5/§14).
