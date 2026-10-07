# brain-core → integrator: REST `POST /say` added for the CLI

From: brain-core lane. Date: 2026-10-06. Kind: endpoint my Wave-2 brief asked for ("REST endpoints for the CLI: status, jobs, cancel, control, say"); `docs/PROTOCOL.md` §1 lists the REST set and is integrator-owned.

## What

`POST /say` with `{"text": "...", "job": optional-str}` — token-authed like the
rest; speaks the given text through the voice stack and fans out the matching
subtitle + `speak` frames (same narration path the agent loop uses). Returns
`202 {"ok": true, "chars": N}`; never raises into the caller if TTS is cold
(the warmup/fallback path handles it).

Existing: `GET /status`, `GET /jobs`, `POST /jobs/{id}/cancel`,
`POST /control` already match the brief — `/say` is the only addition.

## Proposed PROTOCOL §1 line

`| CLI REST | Same port: GET /health, GET /jobs, POST /jobs/{id}/cancel, POST /control, POST /say, GET /status — all require token. |`

Tests: `brain/tests/test_rest_say.py` (mocked voice, no Fish spawn).
