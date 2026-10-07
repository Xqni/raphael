"""Provider abstraction shared by every cloud/local client.

A `Provider` owns: live model discovery (NEVER hardcoded IDs), role mapping,
one single-attempt call of each kind, and a health probe. Resilience —
backoff, retries, rate budgets, circuit breakers, chain failover — lives in
`core.py` and wraps these single attempts (Wave 2 task 3).

No lane outside `brain/router/**` may call a provider HTTP API directly
(INTERFACES §a); everything goes through `brain.router.chat/vision/transcribe`.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Sequence

from .config import RouterConfig
from .errors import RouterError
from .privacy import secret_present
from .roles import DEFAULT_ROLE_HINTS, ModelInfo, pick

# normalized non-streaming result (provider-internal; core adds provider/model
# and shapes it into the INTERFACES §a dict)
@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish: str = "stop"
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})
    rate_limit: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None    # provider-reported actual cost, if any

    def estimated_tokens(self) -> int:
        return int(self.usage.get("input", 0)) + int(self.usage.get("output", 0))


class Provider:
    """Base class — subclasses implement `_fetch_models` + the call methods."""

    name: str = "?"
    caps: frozenset[str] = frozenset({"chat"})
    key_env: str | None = None
    gated: bool = False               # money gate applies (go/paid pool)
    paid_selection_ok: bool = False   # vision-only paid slot: paid ids allowed
                                      # (gated by chain membership + daily cap)

    def __init__(self, config: RouterConfig) -> None:
        self.config = config
        self._models: list[ModelInfo] = []
        self._expires_at = 0.0
        self._discover_lock = asyncio.Lock()
        self.last_error: str | None = None

    # ------------------------------------------------------------------ #
    # discovery / role mapping
    # ------------------------------------------------------------------ #
    async def _fetch_models(self) -> list[ModelInfo]:  # pragma: no cover - abstract
        raise NotImplementedError

    async def discover(self, force: bool = False) -> list[ModelInfo]:
        """Live GET /models (cached for `discovery_interval_s`)."""
        now = time.monotonic()
        async with self._discover_lock:
            if not force and self._models and now < self._expires_at:
                return list(self._models)
            ttl = max(5.0, float(self.config.providers.discovery_interval_s))
            try:
                models = await self._fetch_models()
                if models:
                    self._models = models
                    self.last_error = None
                elif not self._models:
                    self._models = []
                    self.last_error = "no models returned"
            except RouterError as e:
                # keep the cached list if the endpoint blips (ARCHITECTURE §4:
                # vanishing model = re-select, not error)
                self.last_error = str(e)[:200]
                if not self._models:
                    self._expires_at = now  # retry next call
                    raise
            self._expires_at = now + ttl
            return list(self._models)

    def invalidate(self) -> None:
        """Force re-discovery on the next call (model vanished → re-select)."""
        self._expires_at = 0.0

    async def pick(
        self,
        role: str,
        *,
        require_capability: str | None = None,
        force: bool = False,
    ) -> ModelInfo | None:
        models = await self.discover(force=force)
        # money gate (§7): paid-pool models never enter selection unless
        # `providers.allow_paid_runtime` is on — or this provider IS the
        # user-approved vision-only paid slot (gated by chain + daily cap)
        if not self.paid_models_allowed:
            models = [m for m in models if not m.paid]
        return pick(
            models,
            role,
            self.config.providers.role_hints or DEFAULT_ROLE_HINTS,
            require_capability=require_capability,
            deny_hints=self.config.providers.deny_hints,
        )

    def supports(self, capability: str) -> bool:
        return capability in self.caps

    @property
    def paid_models_allowed(self) -> bool:
        """May this provider put a PAID model into selection?

        Default follows `providers.allow_paid_runtime`; the user-approved
        vision-only paid slot sets `paid_selection_ok = True` and is gated
        elsewhere (only present in the vision chain, plus the daily cap).
        """
        return self.paid_selection_ok or self.config.providers.allow_paid_runtime

    @property
    def cached_models(self) -> list[ModelInfo]:
        """Last discovery result (no network) — used by Private-Mode health()."""
        return list(self._models)

    def has_key(self) -> bool:
        return not self.key_env or secret_present(self.key_env)

    # ------------------------------------------------------------------ #
    # calls (single attempt — core.py adds retry/backoff/failover)
    # ------------------------------------------------------------------ #
    async def chat(
        self,
        model: ModelInfo,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float,
    ) -> ChatResult:
        raise NotImplementedError

    async def chat_stream(
        self,
        model: ModelInfo,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError
        yield {}  # pragma: no cover — makes this an async generator

    async def vision(
        self,
        model: ModelInfo,
        image_b64: str,
        mime: str,
        question: str,
        *,
        timeout: float,
    ) -> ChatResult:
        raise NotImplementedError

    async def transcribe(
        self,
        model: ModelInfo,
        audio: bytes,
        filename: str,
        mime: str,
        language: str | None,
        prompt: str | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # meta
    # ------------------------------------------------------------------ #
    async def health(self) -> dict[str, Any]:
        if self.key_env and not self.has_key():
            return {"ok": False, "models": 0, "last_error": "E_PROVIDER_AUTH: missing key"}
        try:
            models = await asyncio.wait_for(
                self.discover(force=True),
                timeout=max(2.0, self.config.providers.discovery_timeout_s),
            )
        except asyncio.TimeoutError:
            return {"ok": False, "models": len(self._models), "last_error": "E_TIMEOUT: discovery"}
        except RouterError as e:
            return {"ok": False, "models": len(self._models), "last_error": str(e)[:200]}
        except Exception as e:  # noqa: BLE001 — health must never raise
            return {"ok": False, "models": len(self._models), "last_error": str(e)[:200]}
        return {
            "ok": bool(models),
            "models": len(models),
            "last_error": None if models else (self.last_error or "no models"),
        }


def estimate_input_tokens(messages: Sequence[dict[str, Any]],
                           tools: Sequence[dict[str, Any]] | None = None) -> int:
    """Cheap token estimate for TPM budgeting (chars/4, never exact)."""
    chars = 0
    for msg in messages or ():
        content = msg.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    chars += len(str(part.get("text", "")))
        if msg.get("name"):
            chars += len(str(msg["name"]))
    if tools:
        chars += len(str(list(tools)))
    return max(1, chars // 4)
