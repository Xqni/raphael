"""Deterministic mock provider — the FIRST thing that landed (Wave 2 task 0).

Other lanes build against `brain.router` with the mock so no key and no
network is ever needed:

    RAPHAEL_ROUTER_MOCK=1          # config: providers.chain = ["mock"]
    result = await brain.router.chat([{"role": "user", "content": "hi"}])

Determinism contract (same input → same output, no randomness, no clock):
  - default:      text = "Mock reply to: <last user content>"
  - tool calls:   content `mock_call:<name>` or `mock_call:<name>{json}`
                  → one tool call with those (or {"echo": <content>}) args
  - scripted fail: content `mock_fail:E_CODE` → raises that RouterError code
  - vision:       "Mock vision answer to: <question>"
  - transcribe:   "Mock transcript (<N> bytes)"
  - stream:       words of the reply, then the final finish frame

Nothing here ever returns placeholder junk — `tests/test_router_contract.py`
fails the build if the old provider-name stub reply reappears in output or
anywhere in `brain/router/*.py`.
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from .config import RouterConfig
from .errors import RouterError
from .provider import ChatResult, Provider
from .roles import ModelInfo

_TOOL_RE = re.compile(r"mock_call:([A-Za-z0-9_]+)(\{.*\})?", re.DOTALL)
_FAIL_RE = re.compile(r"mock_fail:(E_[A-Z0-9_]+)")


class MockProvider(Provider):
    name = "mock"
    caps = frozenset({"chat", "tools", "vision", "stt"})
    key_env = None  # no key required — the point of the mock

    def __init__(self, config: RouterConfig | None = None,
                 script: list[ChatResult] | None = None) -> None:
        if config is None:
            from .config import load_config
            config = load_config()
        super().__init__(config)
        self._script = list(script or [])
        self._script_i = 0
        self.calls: list[dict[str, Any]] = []  # request audit for tests

    def has_key(self) -> bool:
        return True

    # ------------------------------------------------------------------ #
    # discovery — fixed, capability-tagged model set
    # ------------------------------------------------------------------ #
    async def _fetch_models(self) -> list[ModelInfo]:
        return [
            ModelInfo("mock-instant", self.name, capabilities=frozenset({"chat"})),
            ModelInfo("mock-large", self.name, capabilities=frozenset({"chat", "tools"})),
            ModelInfo("mock-vision", self.name, capabilities=frozenset({"chat", "vision"})),
            ModelInfo("mock-whisper", self.name, capabilities=frozenset({"audio"})),
        ]

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _last_user(messages: list[dict[str, Any]]) -> str:
        for msg in reversed(messages or []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return str(part.get("text") or "")
        return ""

    def _reply_for(self, messages: list[dict[str, Any]]) -> ChatResult:
        text = self._last_user(messages)
        fail = _FAIL_RE.search(text)
        if fail:
            code = fail.group(1)
            raise RouterError(f"scripted mock failure ({code})", code=code,
                              provider=self.name, reason="scripted")
        if self._script_i < len(self._script):
            scripted = self._script[self._script_i]
            self._script_i += 1
            return scripted
        tool = _TOOL_RE.search(text)
        if tool:
            name = tool.group(1)
            raw_args = tool.group(2)
            args: dict[str, Any]
            if raw_args:
                try:
                    parsed = json.loads(raw_args)
                    args = parsed if isinstance(parsed, dict) else {"value": parsed}
                except json.JSONDecodeError:
                    args = {"_raw": raw_args, "repaired": False}
            else:
                args = {"echo": text}
            return ChatResult(
                text="",
                tool_calls=[{
                    "id": "call_mock_0_" + name,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                    "arguments_raw": raw_args,
                    "repaired": False,
                }],
                finish="tool_calls",
                usage={"input": _tokens(messages), "output": 4},
            )
        reply = f"Mock reply to: {text}" if text else "Mock reply."
        return ChatResult(text=reply, finish="stop",
                          usage={"input": _tokens(messages), "output": _tokens(reply)})

    # ------------------------------------------------------------------ #
    # calls
    # ------------------------------------------------------------------ #
    async def chat(self, model: ModelInfo, messages: list[dict[str, Any]], *,
                   tools: list[dict[str, Any]] | None = None,
                   timeout: float) -> ChatResult:
        self.calls.append({"kind": "chat", "model": model.id,
                           "messages": messages, "tools": tools})
        return self._reply_for(messages)

    async def chat_stream(self, model: ModelInfo, messages: list[dict[str, Any]], *,
                          tools: list[dict[str, Any]] | None = None,
                          timeout: float) -> AsyncIterator[dict[str, Any]]:
        self.calls.append({"kind": "chat_stream", "model": model.id,
                           "messages": messages, "tools": tools})
        result = self._reply_for(messages)
        if result.tool_calls:
            yield {"finish": "tool_calls", "tool_calls": result.tool_calls,
                   "usage": dict(result.usage)}
            return
        for word in result.text.split(" "):
            yield {"delta": word + " "}
        yield {"finish": "stop", "tool_calls": [], "usage": dict(result.usage)}

    async def vision(self, model: ModelInfo, image_b64: str, mime: str,
                     question: str, *, timeout: float) -> ChatResult:
        self.calls.append({"kind": "vision", "model": model.id,
                           "mime": mime, "b64_len": len(image_b64)})
        fail = _FAIL_RE.search(question or "")
        if fail:
            raise RouterError("scripted mock failure", code=fail.group(1),
                              provider=self.name, reason="scripted")
        return ChatResult(text=f"Mock vision answer to: {question}",
                          finish="stop",
                          usage={"input": 8 + _tokens(question), "output": 8})

    async def transcribe(self, model: ModelInfo, audio: bytes, filename: str,
                         mime: str, language: str | None,
                         prompt: str | None = None, *,
                         timeout: float) -> dict[str, Any]:
        self.calls.append({"kind": "transcribe", "model": model.id,
                           "bytes": len(audio), "language": language,
                           "prompt": prompt})
        return {"text": f"Mock transcript ({len(audio)} bytes)", "model": model.id}


def _tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return max(1, len(text) // 4)
