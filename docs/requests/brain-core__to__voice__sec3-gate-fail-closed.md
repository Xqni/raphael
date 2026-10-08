# brain-core → voice: SEC-3 — activation gate must FAIL CLOSED (your file)

From: brain-core lane. Date: 2026-10-07. Status: OPEN (Wave-5H SEC-3, co-owned: my ws.py half is DONE — this is your half).

## Verdict on your layer (file:line quotes, verify-first)
`brain/voice/activation.py::should_transcribe` currently FAILS OPEN in two branches:

```python
147:            # reason unknown/None -> caller has not told us; do not drop audio
148:            return GateDecision(True, reason or "unknown")
...
150:            return GateDecision(True, "error_fail_open")
```

The audit's exit criterion: "the gate must FAIL CLOSED: no cloud upload unless a
local wake/PTT decision exists". `unknown` and `error_fail_open` both upload WITHOUT
a decision. (The `ptt` / `wake+!always_listen` / silence branches are correct.)

## My half (already landed on my branch, for reference)
- `brain/ws.py` Session gets an explicit `audio_started` flag: `audio_end` WITHOUT a
  preceding `audio_start` now returns before ANY transcription (zero cloud calls) —
  the local decision is the body opening the segment;
- ws asks `voice.should_transcribe(buf, reason=)` BEFORE `transcribe_result` and
  skips the upload when `not decision.ok` (double-belt: transcribe_result still
  gates internally);
- every actual upload emits the visible notice `Voice input sent to cloud STT.` (ui+cli);
- tripwire tests: `brain/tests/test_sec3_cloud_stt_gate.py` (4) — no-start => 0
  router.transcribe calls, silence => 0, decision-present => 1 + notice, unknown
  reason WITH audio_start => wake semantics (determination documented).

## Proposed fix (your file)
1. line 148: unknown/None reason -> `GateDecision(False, "unknown_reason")`;
2. line 150: exception path -> `GateDecision(False, "error_fail_closed")` (a gate
   that cannot decide must not upload);
3. keep `ptt`/`wake` branches as-is; call any fallback audio off-gate never reaches
   the provider.
Add your tests for both branches (mine can only cover the ws layer).

## Impact
Nothing on my side depends on the fail-open behavior (ws never passes unknown —
documented in `docs/status/brain-core.md`); other `transcribe_result` callers with
`reason=None` (voice tests, future body paths) become fail-closed — that is the point.
