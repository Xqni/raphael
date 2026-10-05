"""Ollama local fallback provider."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, request


class OllamaUnavailable(Exception):
    pass


class OllamaProvider:
    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")
        self._lock = asyncio.Lock()

    def _tags_url(self) -> str:
        return f"{self.base_url}/api/tags"

    async def _fetch_tags(self) -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            try:
                req = request.Request(self._tags_url(), headers={"Accept": "application/json"})
                with request.urlopen(req, timeout=3) as resp:
                    body = resp.read()
                data = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(data, dict) and isinstance(data.get("models"), list):
                    return [m for m in data["models"] if isinstance(m, dict)]
                return []
            except (error.URLError, error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
                raise OllamaUnavailable(str(e)) from e

        return await asyncio.to_thread(_do)

    async def health_check(self) -> bool:
        try:
            await self._fetch_tags()
            return True
        except OllamaUnavailable:
            return False

    async def list_models(self) -> list[str]:
        try:
            tags = await self._fetch_tags()
            return [str(t.get("name")) for t in tags if t.get("name")]
        except OllamaUnavailable:
            return []
