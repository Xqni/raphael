# voice → brain-core: subtitle the STT-outage notice in `_on_audio_end`
Status: OPEN

## What
Wave 4 (voice lane) delivers `brain.voice.stt_outage_subtitle(code, detail) ->
str | None` — a brief, secret-free subtitle for STT failures, restricted to the
PROTOCOL §10 surfaceable code set (`E_LOCK_BUSY`, `E_TIMEOUT`,
`E_CONFIRM_TIMEOUT`, `E_PROVIDER_429`, `E_LOCAL_OOM`, `E_LOCAL_DOWN`,
`E_OFFLINE`); fatal/internal codes return None so raw detail never reaches
the screen.

Proposed 4-line addition in `brain/ws.py` `_on_audio_end` (this file is
brain-core-owned per OWNERSHIP 2026-10-06):

```python
except VoiceSTTError as e:
    orbstate.mark_error()
    self.broadcast(error_frame(e.code, e.detail), roles={'body', 'ui'})
+   notice = stt_outage_subtitle(e.code, e.detail)   # from brain.voice
+   if notice:
+       self.broadcast({'type': 'subtitle', 'v': 1, 'job': None,
+                       'text': notice, 'fade_ms': 6000},
+                      roles={'ui', 'cli'})
except Exception as e:
    orbstate.mark_error()
    self.broadcast(error_frame('E_INTERNAL', str(e)), roles={'body', 'ui'})
+   ... same optional subtitle via stt_outage_subtitle('E_INTERNAL', ...) -> None
```

(and add `stt_outage_subtitle` to the existing `from brain.voice import ...`
line.)

## Why
Wave-4 task "STT outage path (cloud gate → subtitle notice, no silent drop)".
Today a Groq Whisper outage broadcasts `error_frame` + flips the orb to
`error`, but nothing TEXT reaches the user — the utterance they just spoke
vanishes silently. `error_frame.detail` also carries raw provider text, which
§10 says may only be surfaced for the code set above; the helper encodes that
rule once, so neither lane re-derives it.

## Impact
Additive, no shared-contract change (no new frame type; `subtitle` is an
existing PROTOCOL §3 frame with `job: None` already used elsewhere in ws.py),
no Core Guard involvement. If the helper is missing/import fails, keep
current behavior (the `if notice:` guard makes it a no-op).
