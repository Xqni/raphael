# orb → brain-core: publish `stt_source` so the cloud-mic indicator is authoritative (SEC-3)

Status: OPEN
Asks: **brain-core** (one additive field). Orb-side indicator already shipped
and works **fail-safe** without it — see below.

## What

Add one key to `GET /status` (PROTOCOL §2 REST, same port/token as the WS):

```jsonc
{
  "ok": true,
  "stt_source": "cloud"        // "cloud" | "local" | "unknown"
}
```

Optionally also mirror it on `orb_state` (additive field, **not** a new frame)
so the indicator can update without an HTTP read.

## Why

Wave 5H / SEC-3 asks the orb for "a clear **'mic audio is going to cloud'**
indicator when the brain emits it". The orb shipped one — an on-orb badge shown
while `orb_state = listening` unless Private Mode, plus a menu row
(`src/renderer/renderer.js` `animate()`; `src/main/main.js` `micCloudRow()`) —
and it is deliberately **fail-safe**: Private Mode is the only thing that
provably stops cloud egress (PROTOCOL §7/§11), so anything else warns.

The gap: **the orb has no way to know which STT backend is in use.**

- profile `cloud_temp` → mic STT goes to **Groq Whisper (cloud)** → indicator
  correct.
- profile `local` (Wave 6 cutover) → **local faster-whisper** → the indicator
  would warn about egress that is not happening.

Silence is the dangerous direction for a privacy indicator, so the orb
over-warns today rather than staying quiet. `stt_source` lets it be exact, and
lets it **stop showing** the badge under `local` — which is the point of the
Wave 6 cutover.

`stt_source` also lets the badge appear *before* the first utterance (currently
it keys off `listening`, which is the capture window — correct timing, but the
backend is inferred rather than known).

## Proposed (brain-core owns `brain/app.py`)

```python
# alongside the existing router block in GET /status
'from brain.ws or voice: whether the active STT path is a cloud provider'
'stt_source': stt_source(),   # "cloud" | "local" | "unknown"; never raises
```

- Read from local state only — **no network, no keys, never raises**
  (same contract the `router` block already follows: an exception must degrade
  to `"unknown"`, never break `/status`).
- `"unknown"` must be a legal value: the orb treats it as `cloud` (fail-safe).

## Why REST and not a frame

Packet `docs/audit-tasks/orb.md` F-4 says **"no new frames"**, and the orb's
usage rows already read `/status` for that reason. One more key on the same
payload costs nothing and keeps `docs/PROTOCOL.md` §3 untouched.

Fallback if Brain-core prefers the WS: an additive `stt_source` field on the
existing `orb_state` frame (additive field, still not a new frame). Either is
accepted — say which.

## Impact

- Additive key in `/status` (or additive field on `orb_state`). Existing
  consumers read keys, so nothing breaks.
- Orb change after it lands: `micCloudRow()` and the badge switch from
  "warn unless Private Mode" to "warn iff `stt_source === 'cloud' or
  'unknown'`" — a 3-line edit in `src/main/main.js` + `src/renderer/renderer.js`,
  plus one added check in the `orb:trace` interaction phase.
- Until it lands, the current fail-safe behaviour stays (over-warns under a
  future `local` profile; never under-warns under `cloud_temp`).
