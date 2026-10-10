# brain-core → integrator: needs-confirm-frame-fields (Wave 5U P0.3)
Status: OPEN — awaiting integrator/PROTOCOL merge (code ships additive per charter owner pre-approval; PROTOCOL.md §9 is integrator-owned)

## What

`needs_confirm` frame (PROTOCOL §9) gains three ADDITIVE fields so orb and
CLI confirm cards can show what is being approved (charter rule 16 permits
confirm cards; the orb stays text-free except in the confirm state):

```jsonc
{"type": "needs_confirm", "v": 1, "job": "j_…",
 "question": "About to …: “…” Confirm?",
 "actions": ["yes", "no"],
 "risk": "high",                       // unchanged (voice-yes gate)
 "action": "delete_files",             // NEW: normalized action id
 "target": "old logs folder",          // NEW: what is acted on (<=200)
 "detail": "delete files or data",     // NEW: reason, redacted, <=200
 "expires_at": 1791620000000}          // unchanged
```

Compatibility: pure superset — `v` unchanged, no existing field altered or
removed; old clients that read `question`/`actions`/`risk`/`expires_at`
behave exactly as before. `detail` passes through `logjson.redact_value`
(config `privacy.redact` categories) and is hard-capped at 200 chars;
`target` is capped at 200. Emitted from `brain/loop.py:_ask_confirm`;
decision source `brain/confirm.py:RiskDecision{action,target}`.

## Asks

1. Integrator: fold the field list into docs/PROTOCOL.md §9.
2. orb/pc/voice lanes: cards may surface `action`/`target`/`risk`/`detail`
   (they can ignore them until then).
