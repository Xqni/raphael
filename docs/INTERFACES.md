# INTERFACES.md — shared contracts between lanes (integrator-owned)

Status: **authoritative** together with `docs/PROTOCOL.md` + `docs/ARCHITECTURE.md`. Lanes code against this file; changing it = a `docs/requests/` request to the integrator. Last updated: 2026-10-05.

## (a) Router API — `brain/router/` (owner: router lane; consumers: everyone)

Single facade, exported from `brain.router`. **No lane may call a provider HTTP API directly.** All keys come from `.env` at call time; presence checked value-blind, never logged.

```python
chat(messages, tools=None, stream=False, purpose="chat")
#  messages: OpenAI-style [{"role": "system|user|assistant|tool", "content": ...}]
#  tools:    None or OpenAI function-tool list (JSON Schema params)
#  stream:   False -> dict result; True -> async iterator of delta dicts
#  purpose:  "chat" | "tool" | "plan" | "ack" | "analysis" | "simulation"
#            (usage/latency tag + model-tier hint; tier map =
#             config.d/router.yaml -> router.purpose_roles; unknown purpose -> fast)
#  returns:  {"text": str, "tool_calls": list, "finish": "stop"|"tool_calls"|"length",
#             "provider": str, "model": str, "usage": {"input": int, "output": int}}
#  stream:   yields {"delta": str} ... final {"finish", "provider", "model", "tool_calls"?}
#  errors:   raises RouterError(code=<PROTOCOL §10 code>) — E_PROVIDER_429/5XX/AUTH, E_OFFLINE,
#            E_LOCAL_DOWN; the loop maps these to job errors, never crashes.

vision(image, question, purpose="vision")
#  image: bytes or path — caller MUST pre-downscale (config vision.max_px/quality) and pass the
#         PROTOCOL §7 gates FIRST (profile cloud_temp, blocklist, redaction, no logging, not private)
#  returns: {"text": str, "provider": str, "model": str}

transcribe(audio, language=None)
#  audio: bytes (webm/wav/pcm). cloud_temp -> Groq Whisper; profile local -> local faster-whisper
#         (voice lane registers the local implementation behind this same seam)
#  returns: {"text": str, "rtf": float | None}

health()
#  returns: {"ok": bool, "providers": {name: {"ok": bool, "models": int, "last_error": str|None}}}
```

Chain order = `providers.chain` from config (cloud_temp: `[groq, zen_free]`). Discovery never hardcodes model IDs. Circuit breakers/rate limits/discovery live inside the router; callers just get `RouterError` with a PROTOCOL code. Go/paid gates (`allow_go_runtime`, `allow_paid_runtime`) are enforced inside `complete()` — a lane cannot bypass them.

## (b) Tool registration — self-registration, no central registries

- **Where:** each tool lives in its owner's folder: `brain/tools/<namespace>/*.py`
  (`pc` → pc-control, `computer_use` → computer-use, `web|files|shell|github|schedule|mcp` → tools-memory).
- **How:** the module exposes its specs via the registry decorator/declaration from
  `brain/tools/__init__.py` (brain-core owns that file; **nobody else edits it** — AGENT_RULES §3).
  brain-core's loader auto-discovers every `brain.tools.*` subpackage at import (pkgutil walk) — new tools appear without touching shared files.
- **Spec:** strict JSON Schema — `type: "object"` params, every property typed, `required` listed,
  `additionalProperties: false`. The registry **rejects** non-conforming specs at load time (loudly, in tests).
- **Metadata:** each tool declares `risky` (confirm-gated — `brain/confirm.py` enforces in code) and `needs_lock` (input-lock arbitration). Never left to a model's judgment.
- **Output:** tools return strings (or JSON-serialized data). Their output is **untrusted text** — the loop wraps it as untrusted context before any model sees it (AGENT_RULES §9).

## (c) Configuration — `config.yaml` + `config.d/*.yaml` + profile overlays (loader: brain-core)

Load order, later wins:

1. `config.yaml` (base — integrator-owned; current base values already reflect profile `cloud_temp`)
2. `config.d/*.yaml` fragments, **sorted by filename**, each **deep-merged** over the accumulated config:
   mappings merge recursively; lists and scalars **replace**. (No null-deletion magic.)
3. The active profile overlay: `profiles.<profile>` from the merged tree. Profile source:
   `RAPHAEL_PROFILE` env var (wins) → top-level `profile:` key → default `cloud_temp`.
4. Explicit env overrides for instance values (`RAPHAEL_INSTANCE`, `RAPHAEL_PORT`, `RAPHAEL_BIND`, `RAPHAEL_LOG_LEVEL` — `brain/run.py` already honors these).

Rules: `config.d/<lane>.yaml` belongs to that lane (create yours; never edit another's). Secrets never appear in any yaml — `.env` only. `config.yaml` base + `profiles:` block are integrator-only.

## (d) Instance isolation — `RAPHAEL_INSTANCE` and derived values

Set `RAPHAEL_INSTANCE=<lane>` for every lane process/test run. **Unset = `main` = today's exact behavior (zero change for the real stack).** All values derive from the instance name; code must read the derivation, never hardcode a port/lock/path.

| instance | WS/REST port | brain pidfile | body lock | supervisor mutex | orb single-instance | CDP | data-dir |
|---|---|---|---|---|---|---|---|
| `main` (unset) | 8765 | `~/.raphael/brain.pid` (+ legacy `/tmp/raphael-brain.pid` dual-write until infra cutover) | `%TMP%\raphael_body.lock` | `Raphael_Supervisor` | Electron per-userData lock (default userData) | 9333 | `~/.raphael/` |
| `router` | 8901 | `~/.raphael/router/brain.pid` | `%TMP%\raphael_body_router.lock` | `Raphael_Supervisor_router` | userData `~/.raphael/router/orb/` | 9401 | `~/.raphael/router/` |
| `brain-core` | 8902 | `~/.raphael/brain-core/brain.pid` | `…_brain-core.lock` | `…_brain-core` | `~/.raphael/brain-core/orb/` | 9402 | `~/.raphael/brain-core/` |
| `pc-control` | 8903 | `~/.raphael/pc-control/brain.pid` | `…_pc-control.lock` | `…_pc-control` | `~/.raphael/pc-control/orb/` | 9403 | `~/.raphael/pc-control/` |
| `voice` | 8904 | `~/.raphael/voice/brain.pid` | `…_voice.lock` | `…_voice` | `~/.raphael/voice/orb/` | 9404 | `~/.raphael/voice/` |
| `computer-use` | 8905 | `~/.raphael/computer-use/brain.pid` | `…_computer-use.lock` | `…_computer-use` | `~/.raphael/computer-use/orb/` | 9405 | `~/.raphael/computer-use/` |
| `orb` | 8906 | `~/.raphael/orb/brain.pid` | `…_orb.lock` | `…_orb` | `~/.raphael/orb/orb/` | 9406 | `~/.raphael/orb/` |
| `infra` | 8907 | `~/.raphael/infra/brain.pid` | `…_infra.lock` | `…_infra` | `~/.raphael/infra/orb/` | 9407 | `~/.raphael/infra/` |
| `qa-security` | 8908 | `~/.raphael/qa-security/brain.pid` | `…_qa-security.lock` | `…_qa-security` | `~/.raphael/qa-security/orb/` | 9408 | `~/.raphael/qa-security/` |
| `tools-memory` | 8909 | `~/.raphael/tools-memory/brain.pid` | `…_tools-memory.lock` | `…_tools-memory` | `~/.raphael/tools-memory/orb/` | 9409 | `~/.raphael/tools-memory/` |
| `evolution-persona` | 8910 | `~/.raphael/evolution-persona/brain.pid` | `…_evolution-persona.lock` | `…_evolution-persona` | `~/.raphael/evolution-persona/orb/` | 9410 | `~/.raphael/evolution-persona/` |
| `shadow` | 8911 | `~/.raphael/shadow/brain.pid` | `…_shadow.lock` | `…_shadow` | `~/.raphael/shadow/orb/` | 9411 | `~/.raphael/shadow/` |

Format for derived names: **brain pidfile = `<data-dir>/brain.pid`** (moved out of world-writable `/tmp` — `brain/config.py::pidfile()` is the single source, **implemented on `agent/brain-core`, lands at its merge**; `main` keeps dual-writing the legacy `/tmp/raphael-brain.pid` as supervisor's read/remove fallback; integrator decision 2026-10-06 on `infra__to__integrator__pidfile-location.md` + `brain-core__to__integrator__pidfile-out-of-tmp.md`, both branches: agent/infra and agent/brain-core, not yet in main), `<main-name>_<instance>` (body lock / supervisor mutex), `9400 + lane index` (CDP), `~/.raphael/<instance>/` (data-dir: memory DB, orb userData, logs, `brain.pid`, token).

Hard restrictions for lanes (AGENT_RULES §5):
- **Never** spawn Fish TTS (port 8777 reserved for main; voice tests mock TTS).
- **Never** register global hotkeys or open the real microphone; never send input (input-lock is main-only).
- Never start Ollama (cloud_temp has no local models).
- Prefer mocks; the only sanctioned live runs are the integrator's.

## (e) `orb_state` emission contract — who emits what

`orb_state` frames (PROTOCOL §8) are **server-authoritative** except three connection states the orb client owns. Every frame carries: `state`, `jobs_active`, `mode: normal|private|paused` (private/paused render as overlays — they are NOT states), and when a foreground job exists: `shape_hint`, `task_kind`; plus `provider`, `model` (router's current/last target).

| state | emitted by | trigger (code) |
|---|---|---|
| `starting` | orb client at process start (pre-WS); brain-core in the boot snapshot while engine not ready | launch / `state_req` before hub ready |
| `reconnecting` | **orb client** (documented exception) | WS dropped, backoff retry in progress |
| `offline` | **orb client** (documented exception) | retries exhausted / server unreachable |
| `idle` | brain-core | initial snapshot after `auth_ok` with `jobs_active==0`; last job terminal (after its `speak` end) |
| `listening` | brain-core | mic lane `audio_start` (reason `wake`\|`ptt`); back to `idle` on `audio_end` with no job yet |
| `thinking` | brain-core | job_event `running` with stage `routing`\|`llm` (plan in flight) |
| `acting` | brain-core | first `act_req` sent (stage `tool`); while any input-lock job holds the lock |
| `speaking` | brain-core | first `speak` `start` event; returns to `thinking`/`idle` per pending jobs after `speak` `end` |
| `confirm` | brain-core | `needs_confirm` emitted (confirm.py gate) |
| `error` | brain-core (+router codes) | job `failed`, auth failure, provider chain exhausted → transient, then `idle` |

- `shape_hint` mapping = `config.yaml → orb.shape_map` (`task_kind` from fastpath/loop; the Laya advisory tier is NOT wired yet — TODO §5).
- The orb only renders (crossfade ~300 ms, morph ~600 ms); it never invents states beyond the three client-owned connection states above.
- Wave 2 exit evidence (per-state screenshots) is produced against this table.

## (Wave 5U addendum, 2026-10-10) — Browser CDP ports (owner: pc-control)

Her dedicated browser profile listens on a loopback-only CDP port:
main instance **9500**; lane instances **9500 + lane index**; the ORB's test CDP stays
**9333** (do not collide). Body launches Chrome/Edge with
`--remote-debugging-port=<cdp port>` bound to 127.0.0.1 and `--user-data-dir` under the
instance data dir. Nothing else may hard-code a CDP port.

