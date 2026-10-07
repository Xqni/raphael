"""Ollama local provider — kept in the repo, disabled by profile (Wave 6 prep).

Two classes:
- `OllamaProvider` — the original lightweight tags/health client (API kept
  for older callers/tests);
- `OllamaLocalProvider` — the full `Provider` implementation (chat with tool
  calls, streaming, vision via `/api/chat` images) used when the active
  profile puts `ollama` in `providers.chain` (profile `local`).

Under profile `cloud_temp` the chain is `[groq, zen_free]`, so NOTHING here
runs (WAVES.md global constraint: no local models, Ollama is never started).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator
from urllib import error, request

from .config import RouterConfig
from .errors import RouterError, code_for_status
from .httputil import NetworkError, StreamHttpError, http_request, http_stream_lines
from .jsonrepair import repair_arguments
from .policy import is_excluded
from .privacy import redact_secrets
from .provider import ChatResult, Provider
from .roles import ModelInfo


class OllamaUnavailable(Exception):
    pass


class OllamaProvider:
    """Original minimal client (tags + health), API preserved."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")
        self._lock = None  # legacy attribute kept for API parity

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
            except (error.URLError, error.HTTPError,
                    json.JSONDecodeError, TimeoutError) as e:
                raise OllamaUnavailable(str(e)) from e

        import asyncio
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
            return [str(t.get("name")) for t in tags
                    if t.get("name") and not is_excluded(str(t.get("name")))]
        except OllamaUnavailable:
            return []


class OllamaLocalProvider(Provider):
    """Full provider over Ollama's native API (profile `local`)."""

    name = "ollama"
    caps = frozenset({"chat", "tools", "vision"})
    key_env = None  # local — no key

    def __init__(self, config: RouterConfig) -> None:
        super().__init__(config)
        self.base_url = config.local_model.ollama_url.rstrip("/")

    def has_key(self) -> bool:
        return True

    # ------------------------------------------------------------------ #
    # discovery (tags carry capabilities: ["vision","tools",…])
    # ------------------------------------------------------------------ #
    async def _fetch_models(self) -> list[ModelInfo]:
        try:
            resp = await http_request(f"{self.base_url}/api/tags", timeout=4.0)
        except NetworkError as e:
            raise RouterError(str(e), code="E_LOCAL_DOWN", provider=self.name,
                              reason="network") from e
        if not resp.ok:
            raise RouterError(f"HTTP {resp.status}", code="E_LOCAL_DOWN",
                              provider=self.name, reason="status")
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise RouterError("bad /api/tags body", code="E_LOCAL_DOWN",
                              provider=self.name, reason="bad_body") from e
        models: list[ModelInfo] = []
        for item in (data.get("models") or []):
            if not isinstance(item, dict):
                continue
            mid = item.get("name") or item.get("model")
            if not mid or is_excluded(str(mid)):
                continue
            raw_caps = item.get("capabilities") or []
            caps = set()
            if isinstance(raw_caps, list):
                for cap in raw_caps:
                    cap = str(cap).lower()
                    if cap in ("vision", "tools"):
                        caps.add(cap)
                    if cap in ("chat", "generate", "completion"):
                        caps.add("chat")
            models.append(ModelInfo(id=str(mid), provider=self.name,
                                    capabilities=frozenset(caps)))
        return models

    # ------------------------------------------------------------------ #
    # calls
    # ------------------------------------------------------------------ #
    def _payload(self, model: ModelInfo, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model.id,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": 0.7},
        }
        if tools:
            payload["tools"] = list(tools)
        return payload

    async def _post(self, path: str, payload: dict[str, Any], *, timeout: float,
                    stream: bool = False):
        body = json.dumps(payload).encode("utf-8")
        try:
            if stream:
                return http_stream_lines(f"{self.base_url}{path}",
                                         headers={"Content-Type": "application/json"},
                                         body=body, timeout=timeout)
            resp = await http_request(f"{self.base_url}{path}", method="POST",
                                      headers={"Content-Type": "application/json"},
                                      body=body, timeout=timeout)
        except NetworkError as e:
            raise RouterError(str(e), code="E_LOCAL_DOWN", provider=self.name,
                              reason="network") from e
        if not resp.ok:
            raise RouterError(f"HTTP {resp.status}: {redact_secrets(resp.text[:200])}",
                              code=code_for_status(resp.status) if resp.status != 404
                              else "E_LOCAL_DOWN",
                              provider=self.name, status=resp.status)
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise RouterError("non-JSON response", code="E_LOCAL_DOWN",
                              provider=self.name, reason="bad_body") from e
        return data

    async def chat(self, model: ModelInfo, messages: list[dict[str, Any]], *,
                   tools: list[dict[str, Any]] | None = None,
                   timeout: float) -> ChatResult:
        data = await self._post("/api/chat",
                                self._payload(model, messages, tools, False),
                                timeout=timeout)
        message = data.get("message") or {}
        text = str(message.get("content") or "").strip()
        tool_calls = []
        for tc in message.get("tools") or message.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
            name = fn.get("name") or "tool"
            args, repaired = repair_arguments(fn.get("arguments", {}))
            tool_calls.append({
                "id": str(tc.get("id") or f"call_{len(tool_calls)}_{name}"),
                "type": "function",
                "function": {"name": str(name), "arguments": args},
                "arguments_raw": fn.get("arguments") if isinstance(
                    fn.get("arguments"), str) else None,
                "repaired": repaired,
            })
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            tool_calls=tool_calls,
            finish="tool_calls" if tool_calls else "stop",
            usage={
                "input": int(usage.get("prompt_eval_count") or 0),
                "output": int(usage.get("eval_count") or 0),
            },
        )

    async def chat_stream(self, model: ModelInfo, messages: list[dict[str, Any]], *,
                          tools: list[dict[str, Any]] | None = None,
                          timeout: float) -> AsyncIterator[dict[str, Any]]:
        try:
            lines = await self._post("/api/chat",
                                     self._payload(model, messages, tools, True),
                                     timeout=timeout, stream=True)
        except RouterError:
            raise
        usage = {"input": 0, "output": 0}
        finish = "stop"
        try:
            async for line in lines:
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    chunk = json.loads(text)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message") or {}
                delta = str(msg.get("content") or "")
                if delta:
                    yield {"delta": delta}
                if chunk.get("done"):
                    finish = str(chunk.get("done_reason") or "stop")
                    u = chunk.get("usage") or {}
                    usage["input"] = int(u.get("prompt_eval_count") or usage["input"])
                    usage["output"] = int(u.get("eval_count") or usage["output"])
        except StreamHttpError as e:
            raise RouterError(f"HTTP {e.status}", code=code_for_status(e.status),
                              provider=self.name, status=e.status) from e
        except NetworkError as e:
            raise RouterError(str(e), code="E_LOCAL_DOWN", provider=self.name,
                              reason="network") from e
        yield {"finish": finish, "tool_calls": [], "usage": usage}

    async def vision(self, model: ModelInfo, image_b64: str, mime: str,
                     question: str, *, timeout: float) -> ChatResult:
        messages = [{
            "role": "user",
            "content": question,
            "images": [image_b64],
        }]
        data = await self._post("/api/chat", self._payload(model, messages, None, False),
                                timeout=timeout)
        text = str(((data.get("message") or {}).get("content")) or "").strip()
        usage = data.get("usage") or {}
        return ChatResult(text=text, finish="stop", usage={
            "input": int(usage.get("prompt_eval_count") or 0),
            "output": int(usage.get("eval_count") or 0),
        })

    async def transcribe(self, model: ModelInfo, audio: bytes, filename: str,
                         mime: str, language: str | None, *,
                         timeout: float) -> dict[str, Any]:
        # Local STT is faster-whisper — the voice lane registers it behind
        # Router.set_local_transcriber() (INTERFACES §a). Ollama has no STT
        # slot in this design.
        raise RouterError("Ollama has no STT slot; use the local transcriber",
                          code="E_LOCAL_DOWN", provider=self.name,
                          reason="stt_not_available")
