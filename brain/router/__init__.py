"""`brain.router` — the ONLY way any lane talks to a model provider.

No lane may call a provider HTTP API directly (INTERFACES §a); keys come from
`.env` at call time, presence-checked value-blind and never logged.

Public API (INTERFACES §a)::

    await chat(messages, tools=None, purpose="chat")      -> dict
    async for ev in chat(messages, stream=True)           -> {"delta": …} …
                                                             final {"finish", "provider", "model", "tool_calls"?}
    await vision(image, question, purpose="vision")       -> {"text", "provider", "model"}
    await transcribe(audio, language=None)                -> {"text", "rtf"}
    await health()                                        -> {"ok", "providers": {name: {ok, models, last_error}}}
    rate_headroom()                                       -> compact RPM/TPM headroom + vision spend (F-4, orb menu)
    await usage_status()                                  -> 24 h usage + live rate/circuit state
                                                             (Wave 3: brain-core surfaces it in GET /status)

Every failure raises `RouterError(code=…)` with a PROTOCOL §10 code
(`E_PROVIDER_429`, `E_PROVIDER_5XX`, `E_PROVIDER_AUTH`, `E_LOCAL_DOWN`,
`E_OFFLINE`, …) — the brain loop maps these to job errors, never a crash.

Deterministic mock for other lanes' tests (no key, no network)::

    RAPHAEL_ROUTER_MOCK=1   # providers.chain becomes ["mock"]
    result = await brain.router.chat([{"role": "user", "content": "hi"}])
    # -> {"text": "Mock reply to: hi", "provider": "mock", "model": "mock-instant", …}

Privacy (PROTOCOL §7/§11) is enforced inside the router:
`set_private_mode(True)` disables every cloud call, `set_foreground_check(fn)`
wires the blocklist that forces vision refusal, and all outbound text is
secret-redacted first.
"""
from __future__ import annotations

from typing import Any

from .config import RouterConfig, load_config
from .core import (
    CallResult,
    CircuitBreaker,
    Outcome,
    ProviderStats,
    RateLimiter,
    Router,
    TokenBudget,
    UsageEvent,
    acquire_model,
    complete,
    get_router,
    init_router,
    report_usage,
    rate_headroom,
    reset_router,
    shutdown_router,
    usage_status,
)
from .errors import (
    RETRYABLE_CODES,
    SPOKEN_CODES,
    ProviderError,
    ProviderUnavailable,
    RouterError,
)
from .provider import ChatResult, Provider
from .privacy import is_private_mode, set_foreground_check, set_private_mode


# --------------------------------------------------------------------------- #
# facade (INTERFACES §a)
# --------------------------------------------------------------------------- #
def chat(messages: list[dict[str, Any]],
         tools: list[dict[str, Any]] | None = None,
         stream: bool = False,
         purpose: str = "chat"):
    """Chat completion.

    `stream=False` → await it for a dict; `stream=True` → iterate it
    (`async for`) for `{"delta": …}` chunks and one final frame with
    `finish`/`provider`/`model`/`tool_calls`.
    """
    return get_router().chat(messages, tools=tools, stream=stream, purpose=purpose)


def vision(image: Any, question: str, purpose: str = "vision"):
    """Screenshot Q&A. Caller MUST pre-downscale and run the PROTOCOL §7
    gates first; the router re-checks Private Mode + the blocklist anyway."""
    return get_router().vision(image, question, purpose=purpose)


def transcribe(audio: bytes, language: str | None = None):
    """Speech → text. cloud_temp: Groq Whisper; profile `local`: the voice
    lane's transcriber registered via `set_local_transcriber()`."""
    return get_router().transcribe(audio, language=language)


def health():
    """Provider reachability: {"ok", "providers": {name: {ok, models, last_error}}}."""
    return get_router().health()


def set_local_transcriber(fn) -> None:
    """Voice lane registers local STT behind the same `transcribe()` seam."""
    get_router().set_local_transcriber(fn)


__all__ = [
    # facade
    "chat", "vision", "transcribe", "health", "set_local_transcriber",
    # privacy gates
    "set_private_mode", "is_private_mode", "set_foreground_check",
    # errors
    "RouterError", "ProviderError", "ProviderUnavailable",
    "RETRYABLE_CODES", "SPOKEN_CODES",
    # lifecycle / legacy seam
    "Router", "RouterConfig", "load_config",
    "CallResult", "Outcome", "UsageEvent", "ChatResult", "Provider",
    "init_router", "get_router", "shutdown_router", "reset_router",
    "acquire_model", "complete", "report_usage", "usage_status",
    "rate_headroom",
    # resilience primitives (exposed for tests)
    "CircuitBreaker", "RateLimiter", "TokenBudget", "ProviderStats",
]
