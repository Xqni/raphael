# qa-security → integrator: voice-confirm-channel
Status: OPEN

## What
PROTOCOL §9 needs an explicit confirmation CHANNEL contract:
1. Add an optional field to `confirm_resp` (§3):
   `"channel": "voice" | "text" | "orb"` (default `text` when absent —
   keeps existing clients compatible).
2. Add the rule: **risky/high-risk confirmations may NOT be granted by
   `channel: "voice"`** — a non-voice channel (typed command, orb menu, CLI)
   is required. Voice may answer only non-risky confirms.
   Rationale: acoustic injection — anything the mic hears (Raphael's own TTS
   on the speakers, a video, a TV) can say "yes"; STT output is untrusted
   data (AGENT_RULES §9).

## Why
Review §1.4 C2. Voice confirmation is being wired by brain-core
(`…__voice-confirm-wiring`) — the channel field + rule must exist in the
protocol BEFORE that lands, otherwise the injection surface ships by default.
Core Guard rule (AGENT_RULES §8): this strengthens confirmation, never
weakens it, but it edits PROTOCOL §9 → integrator/protocol-architect owns it.

## Impact
Contract-only + one enforcement point in the confirm resolver. Old frames
without `channel` keep working (`text`). qa-security xfail test
`test_voice_channel_grant_is_refused_for_risky_job` pins the enforcement.
