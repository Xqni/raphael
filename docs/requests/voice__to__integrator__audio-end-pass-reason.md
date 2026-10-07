# voice → integrator: pass `reason` into the voice STT seam at audio_end
Status: DONE (2026-10-06) — implemented in brain/ws.py::_on_audio_end (reason=reason passed into voice.transcribe_result); ws+voice suites 101 green. ACCEPTED (2026-10-06, integrator ping-wake)

## Decision
APPROVED as specified — reasoning is sound (fail-open default, no contract change,
no Core Guard impact). Implementation is assigned to **brain-core**: `brain/ws.py`
became brain-core-owned in `docs/OWNERSHIP.md` during wave_done verification
(2026-10-06), so the one-liner lands on their branch together with the
allow-empty-properties task. Voice is notified; will be pinged when it merges.

## What
`brain/ws.py` `_on_audio_end` (owner: integrator — `brain/ws.py` is unlisted in
`docs/OWNERSHIP.md`, so it falls to the integrator by the default rule). One-line
change, no new logic in ws.py:

```python
# before
res = await asyncio.wait_for(
    asyncio.to_thread(voice.transcribe_result, buf), timeout=120)

# after
res = await asyncio.wait_for(
    asyncio.to_thread(voice.transcribe_result, buf, reason=reason), timeout=120)
```

(`reason` is already computed a few lines above from `s.audio_reason`.)

`VoiceStack.transcribe_result(pcm, sample_rate=16000, reason=None)` already
exists (brain/voice/__init__.py) and applies the pre-STT cloud gate
(`brain/voice/activation.py`): silent segments are answered locally, and with
`voice.always_listen: false` wake-reason segments are dropped before any
provider call (PTT-reason segments always pass). With `reason=None` — today's
call — the gate fails OPEN, so nothing changes until this lands.

## Why
Wave 2 task 2 (activation: "the wake gate decides which segments go to cloud
STT — don't stream all audio to the cloud"). The brain-side half of the
pre-gate is dead code without the reason; the body-side half (VAD
segmentation, echo guard while Raphael speaks, silence short-circuit in
stt.py) is already live and needs no ws.py change.

## Impact
Trivial and backwards-compatible: `reason` is an optional keyword with a
fail-open default; existing callers keep working. No shared-contract change
(PROTOCOL audio frames untouched), no Core Guard involvement (AGENT_RULES §8).
Risk: none to confirm/auth/kill paths; worst case a segment is dropped that
used to be transcribed — only when `always_listen: false`, where the body no
longer streams wake segments at all.
