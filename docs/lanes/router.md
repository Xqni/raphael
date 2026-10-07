# router — lane task list (owner: router lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/router.md. Requests to you: `ls docs/requests/*__to__router__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] Groq client behind chat() — OpenAI-compatible https://api.groq.com/openai/v1, key from .env (presence-only checks).
- [ ] Chain wiring: providers.chain=[groq, zen_free]; Go/paid gates stay enforced; discovery never hardcodes model IDs.
- [ ] transcribe() = Groq Whisper for voice.stt_engine=groq (keep local faster-whisper seam behind profile local).
- [ ] vision() cloud seam (config vision.provider) — caller passes pre-gated, downscaled images (PROTOCOL §7).
- [ ] RouterError -> PROTOCOL §10 codes for every failure class; health() covers groq+zen.
- [ ] Unit tests with mocked HTTP only (no network, no keys in output).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
