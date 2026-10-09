# voice → brain-core: batch streamed sentences before speaking (gapless cadence)
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: the batching landed exactly as proposed — `brain/loop.py:294-306` `_SentenceSpeaker` gained `batch_size` (default from `agent.speak_batch_sentences`, 2) and `batch_wait_s`, with the comment "streamed-sentence batching (voice request APPROVED 2026-10-07): hold speech until batch_size sentences OR batch_wait_s seconds, then ONE voice.speak() per batch". Subtitles remain per-sentence (queue push unchanged). Depends-on pre-roll verified at `brain/voice/tts.py:5-7`.

## What
The P0 gap fix (reply-level pre-roll) lives in `brain/voice/tts.py::
TTSEngine.speak()` — it guarantees gaplessness **for multi-sentence texts
passed as ONE speak() call** (narrate, POST /say, whole-reply paths).

The remaining cadence path is `_SentenceSpeaker` in `brain/loop.py`: it
pushes each streamed sentence as its own `voice.speak(sentence)` call, so each
call is single-sentence (pre-roll N/A) and the inter-sentence hole = fish gen
time for the NEXT sentence. Proposed change in `_SentenceSpeaker.push/_run`:

```python
# push(): queue the sentence; do NOT start a speak() per sentence immediately
# _run(): take sentences in BATCHES — hold until either
#   (a) 2 sentences are queued, or
#   (b) 1.5 s passed (end of stream / short reply),
# then call voice.speak(" ".join(batch), ...) ONCE per batch.
# voice.speak's pre-roll buffers the batch before the first chunk -> holes
# bounded by one batch boundary instead of every sentence boundary.
```

Subtitles keep flowing per-sentence exactly as today (UI unaffected); only the
speak() call granularity changes.

## Why
Measured on this box: fish runs ~RTF 0.5 with per-request wall time 2-9 s
(and up to 26 s when another client's request queues ahead — fish serializes).
With one speak() per sentence, a hole opens whenever gen(next) outlasts
play(current). The integrator's WS probe saw exactly that: one **12.23 s**
inter-chunk hole (fish log: a 145-token request taking 11.81 s). After the
pre-roll fix, the same-shape probe measures **max gap 1.0 ms / mean 0.0 ms /
zero holes > 350 ms** (`brain/voice/scripts/p0_gap_probe.py`), but only on
whole-text speak paths — hence this request for the streamed path.

## Impact
`brain/loop.py` `_SentenceSpeaker` only (brain-core-owned); no protocol
change, no frame-shape change, subtitles unchanged. Worst case if declined:
streamed LLM replies keep sentence-boundary pauses (the live gate's canned
replies and `/say` are already gapless). Tradeoff to note for UX: batching
delays the FIRST spoken sentence by up to 1.5 s (or until the 2nd arrives) —
set the hold to 0 to restore today's behavior.
