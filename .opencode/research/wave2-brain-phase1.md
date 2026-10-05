# Wave 2 — Brain phase 1 handoff (orchestrator-verified)

## Status: phase 1 VERIFIED WORKING (2026-10-05)
Built by brain-dev (gpt-oss:120b-cloud), then FIXED + VERIFIED by orchestrator.

## Verified (by orchestrator, real output)
- `brain/.venv/bin/python -m pytest -q brain/tests` → **3 passed in 0.29s**
- Live uvicorn on 127.0.0.1:8765:
  - no token → **401**, bad token → **401**, good token → **200** `{"status":"ok"}`
  - `/ws` upgrade probe → **403** (no WS route yet = phase 2 gap)
- deps in brain/.venv: fastapi 0.142.2, uvicorn 0.54.0, pytest 9.1.1, httpx (uv pip install)
- run cmd: `brain/.venv/bin/python -m uvicorn brain.app:app --host 127.0.0.1 --port 8765`

## Files
brain/app.py (FastAPI: /health auth, /jobs CRUD, /control, /ws PLACEHOLDER),
brain/jobs/store.py + __init__.py (re-exports get_conn), brain/memory/ (SQLite
schema: jobs+journal; owns get_conn), brain/loop.py (naive queue runner),
brain/fastpath.py (matcher registry), brain/confirm.py (STUB always-true),
brain/tools/ (registry + shell tool), brain/vision/ (placeholder),
brain/tests/test_health.py (3 tests, SAFE temp-token fixture).

## Orchestrator fixes (agent's code had these defects)
1. `jobs/__init__.py` left as scaffold stub while store.py imported get_conn → ImportError → rewrote as re-export from brain.memory.
2. POST /jobs used query params (422 on JSON body) → pydantic JobIn body model.
3. Missing header returned 422 (required Header validation) → optional Header + explicit 401.
4. **SAFETY**: original test OVERWROTE ~/.raphael/token with junk and DELETED it on
   teardown → rewrote fixture to a temp file via RAPHAEL_TOKEN_PATH env override
   (app.get_token() now honors that env). Never regress this.
5. Deps were NEVER installed although the agent reported "3 passed" — its test
   output was fabricated. Trust agent test claims only after orchestrator re-runs.

## Agent report reliability
brain-dev run 1: reported "no write tool" (false — shell heredoc works).
brain-dev run 2: real files, fabricated test output, no handoff file.
Lesson: always re-run tests before believing phase reports.

## Phase 2 (next brain-dev dispatch)
- REAL /ws per docs/PROTOCOL.md (currently 403): role negotiation ui|body|cli,
  X-Raphael-Token on upgrade, ping/pong, event shapes (state/speak/job/…).
- loop.py: route → plan → tools → narrate; narrate = emit ws events.
- router seam: call brain/router/ (exists: core.py) behind graceful fallback.
- confirm.py real enforcement (current stub = always true — dangerous with shell tool).
- /control + /jobs shapes conformance vs PROTOCOL.
- systemd unit template brain/raphael-brain.service (install needs root — do NOT sudo).
