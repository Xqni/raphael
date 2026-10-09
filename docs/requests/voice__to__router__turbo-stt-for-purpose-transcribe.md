# voice → router: fastest Groq STT model for the transcribe seam (latency Cut B)
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: router-side selection landed — `brain/router/roles.py:32-35` the STT slot weights `[turbo, whisper, distil-whisper, speech-to-text]` with the comment "'turbo'/'distil' weight the FAST variants so the slot resolves to whisper-large-v3-turbo regardless of provider list order (voice Cut B, request voice__to__router__turbo-stt-for-purpose-transcribe)". No signature change; discovery still never hardcodes model IDs.

## What
Measured baseline for `segment-close → subtitle` (probe
`brain/voice/scripts/stt_reply_latency.py`, 5 live runs, real Groq):
**S2 = 576 ms median (493–621 ms)**, `rtf ≈ 0.23` on a 3.7 s clip — S2 is the
whole non-VAD part of the wait (gate 0.1 ms, submit 2.5 ms, fastpath→subtitle
0 ms). Ask: make `brain.router.transcribe()` (INTERFACES §a seam, no signature
change needed) target **Groq's fastest Whisper-class model** (e.g.
`whisper-large-v3-turbo`, or whatever discovery currently ranks fastest for
`purpose="transcribe"`) instead of the default one — or expose a
`providers.stt_model`/`stt_fast_model` config key if you want it tunable.

## Why
- Rule 15 (speed) + the user's ask ("can we not make the STT real time"):
  the body hangover is being cut separately (Cut A,
  `voice__to__brain-core__utt-continuation-merge.md`); this is the other half.
- Expected: S2 576 → ~300–400 ms ⇒ close→subtitle ≈ **0.3–0.4 s**, perceived
  stop-speaking→subtitle ≈ 1.5–1.6 s with Cut A (from ≈3.1 s).
- Accuracy floor: the wake gate needs 'Raphael' spelled/tolerated (its phonetic
  fold handles rafael/raphael) and `stt_language: en` is pinned, so a faster
  model must keep both — verify with the 10-sentence battery
  (`p0_drift_ab.py` fixtures) before flipping.

## Impact
Router's file only (`brain/router/**` — model selection/discovery is yours by
INTERFACES §a: "Chain order = providers.chain … discovery never hardcodes
model IDs" — hence this request rather than me hardcoding anything). Voice-side
re-measurement after the change: `brain/voice/scripts/stt_reply_latency.py`
(numbers above are the pre-change baseline). No contract change either way.
