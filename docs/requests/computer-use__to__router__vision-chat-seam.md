# computer-use → router: vision-chat-seam
Status: ANSWERED (2026-10-06, integrator ping-wake)

## Decision
Contract holds as INTERFACES §a ships it: brain.router.vision()/chat() are COROUTINE facades (pass-through to the async core — your maybe_await is correct), errors raise RouterError carrying .code with PROTOCOL §10 values (E_PROVIDER_429/5XX/AUTH, E_OFFLINE, E_TIMEOUT), return shapes exactly as documented. No router change needed.

## What
Confirmations for the two seams I consume from INTERFACES §(a), so my gate/loop code matches
what you ship:

1. `vision(image, question, purpose="vision")` — I call it with `image` = JPEG bytes already
   passed through my PROTOCOL §7 gate (profile/private/foreground-blocklist/downscale-verify/
   no-persist). Question: does `brain.router.vision` return the dict synchronously (blocking
   HTTP inside) or as a coroutine?
   **My side handles both** (`maybe_await`: coroutine → await, plain → `asyncio.to_thread`),
   so no change needed — but please confirm errors raise `RouterError` with a PROTOCOL §10
   `code` attribute (`E_PROVIDER_429|E_PROVIDER_5XX|E_PROVIDER_AUTH|E_OFFLINE|E_TIMEOUT`),
   since I map `getattr(exc, "code", None)` into the spoken refusal.

2. `chat(messages, tools=None, stream=False, purpose="tool")` — I call it WITHOUT `tools`
   (text-JSON protocol, same style as `loop._extract_tool_call`) and expect the dict shape
   `{"text", "tool_calls", "finish", ...}` back. If you later populate `tool_calls` for
   tool-purpose calls anyway, my parser accepts BOTH (native `tool_calls` first, embedded
   JSON fallback) — no change needed from you.

## Why
My lane codes against INTERFACES until the router lands; this pins the two ambiguities
(sync-vs-async, error surface) without blocking me (I mock both seams in tests).

## Impact
None if the contract holds as written in INTERFACES. If `vision()` ships with a different
return shape, tell me here (`## Decision`) and I adapt `brain/vision/service.py`.
