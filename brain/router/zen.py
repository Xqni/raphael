"""Zen free + Go providers (OpenCode Zen).

- `zen_free` (profile cloud_temp chain #2): base `https://opencode.ai/zen/v1`,
  free models discovered live via `GET /v1/models`, filtered by the `free`
  flag and the permanent model exclusion list (policy.py). Paid-pool models
  never enter selection unless `providers.allow_paid_runtime` is on.
- `go` (kept in code, gated OFF by `providers.allow_go_runtime=false`).

`ZenDiscovery` keeps its original shape (older tests and callers patch its
`_models` / `_expires_at` and call `get_free_model_ids()`).
"""
from __future__ import annotations

import os
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from .config import RouterConfig
from .errors import RouterError
from .openai_compat import OpenAICompatProvider
from .policy import is_excluded
from .privacy import redact_secrets, secret
from .roles import ModelInfo

DEFAULT_ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"

# Zen's live `GET /models` (verified 2026-10-06) returns a bare OpenAI-style
# list — NO `free` field and no capability metadata. Free tier is therefore
# detected from the id (`…-free`), overridable via `router.zen_free_hints`.
# Anything not positively identified as free is treated as PAID (money gate
# AGENT_RULES §7 — better to lose a slot than to spend the balance).
DEFAULT_FREE_HINTS = ("free",)


def _looks_free(model_id: str, hints: tuple[str, ...] = DEFAULT_FREE_HINTS) -> bool:
    low = str(model_id).lower()
    return any(h and h.lower() in low for h in hints)


@dataclass(frozen=True)
class ZenModel:
    id: str
    free: bool


class ZenDiscoveryError(Exception):
    pass


class ZenDiscovery:
    """Live free-model discovery for Zen (original class, API preserved)."""

    def __init__(self, base_url: str, ttl_s: int = 3600,
                 free_hints: tuple[str, ...] | list[str] = DEFAULT_FREE_HINTS) -> None:
        self.base_url = base_url.rstrip("/")
        self.models_url = f"{self.base_url}/models"
        self.ttl_s = ttl_s
        self.free_hints = tuple(str(h) for h in free_hints if str(h).strip())
        self._models: list[ZenModel] = []
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _parse_models(data: Any) -> list[ZenModel]:
        return ZenDiscovery._parse_models_with(data, DEFAULT_FREE_HINTS)

    @classmethod
    def _parse_models_with(cls, data: Any, free_hints: tuple[str, ...]) -> list[ZenModel]:
        models: list[ZenModel] = []
        if not isinstance(data, dict):
            return models
        for key in ("data", "models"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = item.get("id") or item.get("model") or ""
            if not mid:
                continue
            raw_free = item.get("free")
            if raw_free is None:
                # no metadata (Zen today) → id must positively say so
                free = _looks_free(str(mid), free_hints)
            elif isinstance(raw_free, str):
                free = raw_free.lower() == "true"
            else:
                free = bool(raw_free)
            models.append(ZenModel(id=str(mid), free=bool(free)))
        return models

    async def _fetch_sync(self) -> list[ZenModel]:
        def _do() -> list[ZenModel]:
            headers = {"Accept": "application/json",
                       "User-Agent": "raphael-router/1.0 (OpenAI-compatible client; local)"}
            key = secret("OPENCODE_API_KEY") or secret("ZEN_API_KEY")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            try:
                req = request.Request(self.models_url, headers=headers)
                with request.urlopen(req, timeout=5) as resp:
                    body = resp.read()
                data = json.loads(body.decode("utf-8", errors="replace"))
                return self._parse_models_with(data, self.free_hints)
            except (error.URLError, error.HTTPError,
                    json.JSONDecodeError, TimeoutError) as e:
                raise ZenDiscoveryError(str(e)) from e

        return await asyncio.to_thread(_do)

    async def get_models(self, force_refresh: bool = False) -> list[ZenModel]:
        now = time.monotonic()
        async with self._lock:
            if force_refresh or now >= self._expires_at or not self._models:
                try:
                    self._models = await self._fetch_sync()
                except ZenDiscoveryError:
                    # tolerate endpoint down; keep cached if any, else empty
                    if not self._models:
                        self._models = []
                self._expires_at = now + self.ttl_s
            return list(self._models)

    async def get_free_model_ids(self) -> list[str]:
        models = await self.get_models()
        return [m.id for m in models if m.free and not is_excluded(m.id)]

    async def select_free_model(self, candidates: list[str] | None = None) -> str | None:
        free_ids = set(await self.get_free_model_ids())
        if candidates:
            for c in candidates:
                if c in free_ids:
                    return c
            return next((c for c in candidates if not is_excluded(c)), None)
        ids = await self.get_free_model_ids()
        return ids[0] if ids else None


class ZenProvider(OpenAICompatProvider):
    """Zen free chat/vision provider — free models only (money gate §7)."""

    def __init__(self, config: RouterConfig) -> None:
        super().__init__(
            config,
            name="zen_free",
            base_url=config.providers.zen_base_url,
            key_env=config.providers.zen_key_env,
            caps=frozenset({"chat", "tools", "vision"}),
            free_only=True,
        )
        self.discovery = ZenDiscovery(
            base_url=config.providers.zen_base_url,
            ttl_s=config.providers.discovery_interval_s,
            free_hints=tuple(config.providers.zen_free_hints) or DEFAULT_FREE_HINTS,
        )

    async def _fetch_models(self) -> list[ModelInfo]:
        try:
            models = await self.discovery.get_models(force_refresh=True)
        except ZenDiscoveryError as e:
            raise RouterError(redact_secrets(str(e)), code="E_OFFLINE",
                              provider=self.name, reason="network") from e
        if not models:
            # surface the real reason instead of an empty success
            raise RouterError("no models returned", code="E_OFFLINE",
                              provider=self.name, reason="empty_models")
        return [
            ModelInfo(id=m.id, provider=self.name, free=m.free, paid=not m.free)
            for m in models
            if not is_excluded(m.id)
        ]
    def has_key(self) -> bool:
        # Zen's /models works unauthenticated for discovery; chat needs a key.
        return bool(secret(self.key_env)) if self.key_env else True


class GoProvider(OpenAICompatProvider):
    """Go endpoint — paid, gated by `providers.allow_go_runtime` (user-approved true 2026-10-07)."""

    def __init__(self, config: RouterConfig) -> None:
        super().__init__(
            config,
            name="go",
            base_url=config.providers.go_base_url,
            key_env=config.providers.zen_key_env,
            caps=frozenset({"chat", "tools"}),
            gated=True,
            assume_billed=True,
            # Same mandatory header as GoVisionProvider: the Go endpoint rejects
            # requests without x-opencode-session (HTTP 400 MissingSessionID),
            # which silently failed over chat to slow zen_free (user report:
            # "zen_free taking a long time"). Stable id per process.
            extra_headers={"x-opencode-session": f"raphael-brain-{os.getpid()}"},
        )


class GoVisionProvider(OpenAICompatProvider):
    """User-approved vision-ONLY paid slot (docs/PAID_USAGE.md 2026-10-06).

    Gates, in order — none of them optional:
      1. `providers.allow_vision_paid` (config.yaml, user approval) — only then
         does the router put this provider in the VISION chain (chat/tools/STT
         use `providers.chain` and never see it);
      2. `providers.allow_go_runtime` / `allow_paid_runtime` stay FALSE for
         everything else — `paid_selection_ok` exempts ONLY this provider;
      3. `providers.vision_paid_daily_cap_usd` — DailySpend hard stop in
         `Router.vision()` (exceed → E_OFFLINE + coord attention);
      4. selection is still by capability: roles.pick() returns a model only
         when live discovery shows a vision-hinted id — never a hardcoded id,
         and never a guess (score 0 → None → E_OFFLINE/no_model).

    Every Go call is assumed billed (MODEL_POLICY), so discovered models are
    marked paid for honest accounting.
    """

    def __init__(self, config: RouterConfig) -> None:
        # OpenCode Go requires a stable session id header for routing +
        # prompt caching (opencode.ai/docs/go — "Where can I use it?").
        # One stable id per provider instance (= per brain process) keeps
        # the header honest without inventing per-request ids.
        super().__init__(
            config,
            name="go_vision",
            base_url=config.providers.go_base_url,
            key_env=config.providers.zen_key_env,
            caps=frozenset({"vision"}),
            gated=False,
            assume_billed=True,
            extra_headers={
                "x-opencode-session": f"raphael-brain-{os.getpid()}",
            },
        )
        self.paid_selection_ok = True
