"""Zen free-model discovery and selection."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from .policy import is_excluded

DEFAULT_ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"


@dataclass(frozen=True)
class ZenModel:
    id: str
    free: bool


class ZenDiscoveryError(Exception):
    pass


class ZenDiscovery:
    def __init__(self, base_url: str, ttl_s: int = 3600) -> None:
        self.base_url = base_url.rstrip("/")
        self.models_url = f"{self.base_url}/models"
        self.ttl_s = ttl_s
        self._models: list[ZenModel] = []
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _parse_models(data: Any) -> list[ZenModel]:
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
            free = item.get("free", True)
            if isinstance(free, str):
                free = free.lower() == "true"
            models.append(ZenModel(id=str(mid), free=bool(free)))
        return models

    async def _fetch_sync(self) -> list[ZenModel]:
        def _do() -> list[ZenModel]:
            try:
                req = request.Request(self.models_url, headers={"Accept": "application/json"})
                with request.urlopen(req, timeout=5) as resp:
                    body = resp.read()
                data = json.loads(body.decode("utf-8", errors="replace"))
                return self._parse_models(data)
            except (error.URLError, error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
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
        ids = [m.id for m in models if m.free and not is_excluded(m.id)]
        return ids

    async def select_free_model(self, candidates: list[str] | None = None) -> str | None:
        free_ids = set(await self.get_free_model_ids())
        if candidates:
            for c in candidates:
                if c in free_ids:
                    return c
            return next((c for c in candidates if not is_excluded(c)), None)
        # prefer known free names if present in live list? return first free id
        ids = await self.get_free_model_ids()
        return ids[0] if ids else None
