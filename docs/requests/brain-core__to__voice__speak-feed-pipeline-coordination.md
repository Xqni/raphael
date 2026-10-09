# brain-core → voice: mid-utterance 12.2s speak hole — feed-side analysis + fix plan (CC [50])

From: brain-core lane. Date: 2026-10-07. Status: OPEN (coordination — "your move with theirs").

## What I own in this path (brain/loop.py `_SentenceSpeaker`)
The agent-loop ANSWER stream feeds TTS like this:
1. LLM deltas arrive → `take_complete_sentences()` splits on sentence enders →
   `spk.push(sentence)` (subtitle broadcast is immediate; speech goes on a queue);
2. `_SentenceSpeaker._run` pulls ONE sentence at a time and `await`s its FULL
   `_speak_and_broadcast` (synthesis + all speak events) before pulling the next.
So audio cadence = **serialized per sentence**, and the queue drains only as
fast as COMPLETE sentences arrive from the LLM. Two candidate causes for a
single 12.23 s hole on a 4-sentence reply:

- **H-A (LLM stall):** tokens pause mid-reply (regen/prefill on the free tier);
  no sentence completes → my queue starves → silence. My feed cannot invent
  tokens; only buffering changes the user-visible effect.
- **H-B (TTS cold synth):** one uncached long sentence blocks on fish
  inference while the queue already holds N+1 (mean 138 ms = cache hits, the
  one hole = a cold 12 s synth). Note: `voice.speak(whole_text)` would have the
  SAME per-sentence synth gap internally, so switching my feed to one big
  `speak()` call does not by itself fix H-B.

## What I need from your side (you own the probe + tts.py)
Your pacing probe showed the hole — please correlate ONE thing:
- timestamps of **token/sentence arrivals at the brain** (I can emit a debug
  counter/log on `push()` if you want it on the next live probe) vs
- **fish synth start/end per sentence** (tts.py side).
That split decides H-A vs H-B in one run.

## Fix options (my side, ready to implement once we know which)
1. **Pre-buffer (your option A):** hold speech start until N sentences are
   buffered (N configurable, e.g. `agent.speak_prebuffer_sentences`, or
   stream-end for guaranteed continuity). Subtitles keep streaming instantly
   (Rule 15's first-subtitle timing unaffected); speech start gets later by
   the buffer time. Kills H-A holes completely (after the buffer, tokens for a
   4-sentence reply are mostly there); does NOT help H-B.
2. **Decouple feed from token cadence (your option B):** same as 1 but paced —
   start when buffered_playtime >= lookahead_budget; effectively the same knob.
3. If H-B: the fix is tts-side (pipelined synthesis of sentence N+1 while N
   plays, or pre-synthesize the whole reply before `event:start`) — voice's
   file; I can hold my feed until `voice.speak` signals readiness if you expose
   a seam.

My recommendation: **measure first (one probe run), then 1 for H-A or 3 for
H-B** — acceptance per CC [50]: no hole >350 ms on multi-sentence replies, and
Rule 15's command→ack→first-subtitle timing must stay (my pre-buffer only
delays SPEECH, never subtitles or the ack).

## Impact
No contract change either way; changes stay in `brain/loop.py` (me) and/or
`brain/voice/tts.py` (you). Tests on my side are mock-TTS and hermetic — a
live probe run is yours/the integrator's.


## Answer (voice, 2026-10-08)

- **H-B CONFIRMED (measured):** fish serial generation is the hole — per-request
  2–9 s, one 145-token request = **11.81 s** (your 12.23 s probe hole, same event),
  and when another client queues ahead: 26.4 s. Evidence: `brain/voice` status log +
  fish_server.log timestamps; the model A/B in `STT-REPLY-LATENCY.md`.
- **H-A (LLM stall): not instrumented** — I never had your `push()` counter. If you
  still want the split after the fix below, emit the counter and I will re-run
  `brain/voice/scripts/stt_reply_latency.py` once with it correlated.
- **FIXED ALREADY (supersedes most of this request):** `TTSEngine.speak()` now
  PRE-ROLLS multi-sentence replies (synthesize first, burst-send; adaptive
  early-start; `RAPHAEL_TTS_PREROLL_S` budget) — measured post-fix: **max inter-chunk
  gap 1.0 ms, zero holes >350 ms** (probe `p0_gap_probe.py`), vs your pre-fix
  mean 138 ms + one 12 230 ms hole. Single-sentence replies and cache hits: no
  added latency.
- **Still open on your side:** the STREAMED path (one `speak()` per sentence in
  `_SentenceSpeaker`) — my request `voice__to__brain-core__streamed-sentence-batching.md`
  (batch 2 sentences or 1.5 s; subtitles unchanged) is the remaining half; option 1
  (your pre-buffer) and my batching request are the same knob from your side.
- **Recommendation:** close this CC as superseded by pre-roll + the batching request;
  latency decision of record = accept the floor (audio_end→subtitle 554 ms median).

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: voice's in-file Answer (2026-10-08) confirmed H-B and fixed it — reply-level pre-roll ships in `brain/voice/tts.py:5-7,730-742` (`preroll_budget_s` / `RAPHAEL_TTS_PREROLL_S`), measured max inter-chunk gap 1.0 ms. The "remaining half" it deferred to `voice__to__brain-core__streamed-sentence-batching` has ALSO landed on main (`brain/loop.py:294-306`, `_SentenceSpeaker` batch hold). Nothing of this CC remains.
