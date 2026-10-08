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
