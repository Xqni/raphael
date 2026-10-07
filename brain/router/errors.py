"""RouterError + PROTOCOL §10 error-code mapping.

Every failure that escapes the router facade is a `RouterError` carrying a
PROTOCOL §10 code (docs/PROTOCOL.md §10). The brain loop maps these to job
errors — the loop never crashes on a provider (INTERFACES §a).

Codes used here (all from §10, never invented):
  E_PROVIDER_AUTH   401/403 from a provider        (fatal)
  E_PROVIDER_429    provider rate limit            (retryable)
  E_PROVIDER_5XX    provider 5xx / garbage body    (retryable)
  E_LOCAL_DOWN      local Ollama unreachable       (retryable)
  E_OFFLINE         no network / chain exhausted /
                    cloud disabled by a gate       (retryable)
  E_TIMEOUT         our own per-call timeout       (retryable)
  E_BAD_MSG         caller passed a bad payload    (fatal)
  E_INTERNAL        anything unexpected            (fatal)

`reason` is a machine-readable supplement (private_mode, blocked_window,
local_rpm_budget, …) so callers can distinguish gates that share a code.
`detail` is a SHORT human line — only surfaced as a subtitle for the §10
spoken-code set (§10 "Retry semantics"/communication rules).
"""
from __future__ import annotations

from typing import Any, Iterable

# PROTOCOL §10 — retryable (client/Brain may retry after backoff)
RETRYABLE_CODES = frozenset({
    "E_RATE_LIMIT",
    "E_LOCK_BUSY",
    "E_TIMEOUT",
    "E_PROVIDER_429",
    "E_PROVIDER_5XX",
    "E_LOCAL_DOWN",
    "E_OFFLINE",
})

# PROTOCOL §10 — detail may be surfaced as subtitle text ONLY for these
SPOKEN_CODES = frozenset({
    "E_LOCK_BUSY",
    "E_TIMEOUT",
    "E_CONFIRM_TIMEOUT",
    "E_PROVIDER_429",
    "E_LOCAL_OOM",
    "E_LOCAL_DOWN",
    "E_OFFLINE",
})

# PROTOCOL §10 — fatal (never auto-retried)
FATAL_CODES = frozenset({
    "E_AUTH",
    "E_AUTH_RATE",
    "E_PROTO",
    "E_PROVIDER_AUTH",
    "E_CANCELLED",
    "E_CONFIRM_TIMEOUT",
    "E_BAD_MSG",
    "E_UNSUPPORTED",
    "E_LOCAL_OOM",
    "E_INTERNAL",
})

# precedence used when the whole chain failed with mixed codes:
# most actionable first (auth needs a key fix; offline is the least specific)
_AGGREGATE_PRECEDENCE = (
    "E_PROVIDER_AUTH",
    "E_PROVIDER_429",
    "E_TIMEOUT",
    "E_PROVIDER_5XX",
    "E_LOCAL_DOWN",
    "E_OFFLINE",
    "E_BAD_MSG",
    "E_INTERNAL",
)

# short, spoken-friendly lines for the subtitle-capable codes
_SPOKEN_DETAIL = {
    "E_PROVIDER_429": "Rate limited by the model service. Retrying shortly.",
    "E_LOCAL_DOWN":   "Local model service is not responding.",
    "E_OFFLINE":      "No model service is reachable right now.",
    "E_TIMEOUT":      "The model service timed out.",
}


class RouterError(Exception):
    """Single error type out of `brain.router` (INTERFACES §a)."""

    def __init__(
        self,
        message: str = "",
        *,
        code: str = "E_INTERNAL",
        provider: str | None = None,
        model: str | None = None,
        reason: str | None = None,
        status: int | None = None,
        retry_after: float | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.provider = provider
        self.model = model
        self.reason = reason
        self.status = status
        self.retry_after = retry_after
        # detail = caller-safe short line; fall back to a generic spoken line
        self.detail = detail or (_SPOKEN_DETAIL.get(code) if code in SPOKEN_CODES else None)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES

    @property
    def spoken(self) -> str | None:
        """Subtitle-safe text (None when §10 forbids surfacing detail)."""
        return self.detail if self.code in SPOKEN_CODES else None

    def __str__(self) -> str:  # never carries secrets — callers scrub first
        bits = [self.code]
        if self.provider:
            bits.append(self.provider)
        if self.reason:
            bits.append(self.reason)
        msg = super().__str__()
        if msg and msg != self.code:
            return f"{'/'.join(bits)}: {msg}"
        return "/".join(bits)


class ProviderError(RouterError):
    """Legacy name kept for callers that caught `ProviderError` pre-Wave 2."""


class ProviderUnavailable(RouterError):
    """Chain exhausted (legacy name — `brain/llm.py` maps it to E_OFFLINE)."""

    def __init__(self, message: str = "all providers unavailable", **kw: Any) -> None:
        kw.setdefault("code", "E_OFFLINE")
        kw.setdefault("reason", "chain_exhausted")
        super().__init__(message, **kw)


def code_for_status(status: int) -> str:
    """Map an HTTP status to a PROTOCOL §10 provider code."""
    if status in (401, 403):
        return "E_PROVIDER_AUTH"
    if status == 429:
        return "E_PROVIDER_429"
    if 500 <= status <= 599:
        return "E_PROVIDER_5XX"
    if status in (408,):
        return "E_TIMEOUT"
    # 400/404/other 4xx: our request or a vanished model — surfaced as internal
    # (404 is additionally retried once after re-discovery, see core.py)
    return "E_INTERNAL"


def aggregate_code(codes: Iterable[str]) -> str:
    """Best single code for 'every provider failed' (see _AGGREGATE_PRECEDENCE)."""
    seen = [c for c in codes if c]
    if not seen:
        return "E_INTERNAL"
    for code in _AGGREGATE_PRECEDENCE:
        if code in seen:
            return code
    return seen[0]
