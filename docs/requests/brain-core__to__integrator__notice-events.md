# brain-core → integrator: PROTOCOL `notice` frame for proactive events

From: brain-core lane. Date: 2026-10-07. Status: OPEN (Wave-3 goal "proactive Notice
events" — needs a PROTOCOL §3 row before brain-core may emit anything).

## What

Add a Brain→Client frame (additive):

```json
{"type": "notice", "v": 1, "text": "Recovered from restart — 2 interrupted tasks.",
 "level": "info" | "warn", "ts": 1791350000000, "job": null}
```

- broadcast roles `ui` + `cli` (the orb may render it as a subtitle/banner; the CLI
  prints it); `job` present only when the notice is tied to one;
- `level` is advisory for styling; **no state change** — `orb_state` stays the single
  authority for state (NOTICE is not an orb state, INTERFACES §e untouched).

Proposed emitters (brain-core side, implemented only after approval):

1. **Restart recovery** — right after boot, when `_mark_interrupted` actually marked
   jobs: text from `voice_personality.greeting_recovered` + count (config already has
   the greeting).
2. **Provider outage / recovery** — first `E_OFFLINE` of an outage burst while idle:
   "Cloud providers unreachable — retrying." and one notice on recovery. (Ratelimited:
   at most one pair per 10 min; no key/log data, presence only.)
3. *(optional, only if you want it)* confirm expiry warning at T-10s.

Emitter would live in a new brain-core file `brain/notice.py`
(`notice.emit(text, level="info", job=None)`), ratelimited and fail-silent, wired at
the three points above.

## Why

WAVES.md Wave-3 goal "proactive Notice events" + `voice_personality.proactive_warnings:
actionable_only` (addendum): Raphael may speak up ONLY when something needs the user —
today there is no frame to carry that, so the goal cannot ship without a contract row.

## Impact

Purely additive frame type; qa-security's conformance whitelist needs the new row
(`tests/conformance` enumerates Brain→Client types — that's their file, flagged here so
the decision lands once). Core Guard untouched; no provider/key data ever in a notice.

## Decisions needed

- frame name/fields as proposed (or your preferred spelling);
- which of the emitter sources (1/2/3) are in scope;
- whether `body` role should also receive it.
