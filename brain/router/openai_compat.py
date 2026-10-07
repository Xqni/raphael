"""OpenAI-compatible chat/vision/STT client (Groq, Zen free, Go).

One class serves every OpenAI-style endpoint — Groq
(`https://api.groq.com/openai/v1`), Zen free (`https://opencode.ai/zen/v1`)
and the gated Go endpoint differ only in base URL, key env and capabilities.

Implements (Wave 2 task 2):
- tool calls in OpenAI style, normalized to one shape across providers,
  with JSON repair for malformed `arguments` (jsonrepair.py);
- streaming (SSE) with tool-call fragment accumulation;
- vision via a base64 `image_url` part;
- Groq Whisper transcription via multipart upload;
- status→PROTOCOL §10 code mapping (errors.py) with Retry-After surfaced.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from . import httputil
from .config import RouterConfig
from .errors import RouterError, code_for_status
from .httputil import NetworkError, StreamHttpError, http_request, http_stream_lines
from .jsonrepair import repair_arguments
from .privacy import redact_secrets, secret
from .provider import ChatResult, Provider
from .roles import ModelInfo


def _join_content(content: Any) -> str:
    """Message content may be a string or a list of typed parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, dict):
                bits.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                bits.append(part)
        return "".join(bits)
    return "" if content is None else str(content)


def normalize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """One tool-call shape across providers:

        {"id": str, "type": "function",
         "function": {"name": str, "arguments": dict},   # ALWAYS a dict
         "arguments_raw": str|None}                      # original, for audit

    Handles: OpenAI `{"function": {...}}`, flat `{"name":..,"arguments":..}`,
    dict arguments, JSON-string arguments, `function_call`, and malformed
    JSON (repaired — see jsonrepair.repair_arguments).
    """
    out: list[dict[str, Any]] = []
    if not raw:
        return out
    if isinstance(raw, dict):          # legacy `function_call`
        raw = [raw]
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = item.get("name") or fn.get("name") or f"tool_{idx}"
        args = item.get("arguments", fn.get("arguments", item.get("args", {})))
        raw_args = args if isinstance(args, str) else None
        parsed, repaired = repair_arguments(args)
        out.append({
            "id": str(item.get("id") or f"call_{idx}_{name}"),
            "type": "function",
            "function": {"name": str(name), "arguments": parsed},
            "arguments_raw": raw_args,
            "repaired": repaired,
        })
    return out


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        config: RouterConfig,
        *,
        name: str,
        base_url: str,
        key_env: str | None,
        caps: frozenset[str] | None = None,
        gated: bool = False,
        free_only: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(config)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self.caps = caps or frozenset({"chat", "tools"})
        self.gated = gated
        self.free_only = free_only
        self.extra_headers = dict(extra_headers or {})

    # ------------------------------------------------------------------ #
    # request plumbing
    # ------------------------------------------------------------------ #
    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        headers.update(self.extra_headers)
        if self.key_env:
            key = secret(self.key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _error(self, resp: httputil.HttpResponse, model: str | None = None) -> RouterError:
        """HTTP status → RouterError with a PROTOCOL §10 code (secrets scrubbed)."""
        code = code_for_status(resp.status)
        reason = None
        if resp.status == 404:
            reason = "model_not_found"
        elif resp.status in (401, 403):
            reason = "auth"
        elif resp.status == 429:
            reason = "rate_limited"
        retry_after = httputil.parse_retry_after(resp.headers)
        snippet = redact_secrets(resp.text[:300]).replace("\n", " ").strip()
        return RouterError(
            f"HTTP {resp.status}: {snippet}",
            code=code,
            provider=self.name,
            model=model,
            reason=reason,
            status=resp.status,
            retry_after=retry_after,
        )

    async def _post_json(self, path: str, payload: dict[str, Any], *, timeout: float,
                         model: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        try:
            resp = await http_request(
                self._url(path), method="POST", headers=self._headers(),
                body=body, timeout=timeout,
            )
        except NetworkError as e:
            raise RouterError(redact_secrets(str(e)), code="E_OFFLINE",
                              provider=self.name, model=model, reason="network") from e
        if not resp.ok:
            raise self._error(resp, model)
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise RouterError("non-JSON response body", code="E_PROVIDER_5XX",
                              provider=self.name, model=model, reason="bad_body") from e
        if not isinstance(data, dict):
            raise RouterError("unexpected response shape", code="E_PROVIDER_5XX",
                              provider=self.name, model=model, reason="bad_body")
        return data, resp.headers

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    async def _fetch_models(self) -> list[ModelInfo]:
        try:
            resp = await http_request(
                self._url("/models"), method="GET", headers=self._headers(),
                timeout=self.config.providers.discovery_timeout_s,
            )
        except NetworkError as e:
            raise RouterError(redact_secrets(str(e)), code="E_OFFLINE",
                              provider=self.name, reason="network") from e
        if not resp.ok:
            raise self._error(resp)
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise RouterError("non-JSON /models body", code="E_PROVIDER_5XX",
                              provider=self.name, reason="bad_body") from e
        items: Any = []
        if isinstance(data, dict):
            items = data.get("data") or data.get("models") or []
        models: list[ModelInfo] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            mid = item.get("id") or item.get("model") or item.get("name")
            if not mid:
                continue
            free = item.get("free", True)
            if isinstance(free, str):
                free = free.lower() == "true"
            paid = bool(item.get("paid") or item.get("premium") or False)
            models.append(ModelInfo(
                id=str(mid),
                provider=self.name,
                free=bool(free),
                paid=paid,
                capabilities=frozenset(_capabilities_from(item)),
                meta={k: item[k] for k in ("owned_by", "context_window")
                      if isinstance(item.get(k), (str, int))},
            ))
        if self.free_only:
            models = [m for m in models if m.free and not m.paid]
        return models

    # ------------------------------------------------------------------ #
    # chat
    # ------------------------------------------------------------------ #
    def _payload(self, model: ModelInfo, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model.id,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def chat(self, model: ModelInfo, messages: list[dict[str, Any]], *,
                   tools: list[dict[str, Any]] | None = None,
                   timeout: float) -> ChatResult:
        data, headers = await self._post_json(
            "/chat/completions", self._payload(model, messages, tools, False),
            timeout=timeout, model=model.id,
        )
        return _parse_chat_response(data, headers)

    async def chat_stream(self, model: ModelInfo, messages: list[dict[str, Any]], *,
                          tools: list[dict[str, Any]] | None = None,
                          timeout: float) -> AsyncIterator[dict[str, Any]]:
        body = json.dumps(self._payload(model, messages, tools, True)).encode("utf-8")
        pieces: dict[int, dict[str, str]] = {}
        finish = "stop"
        usage = {"input": 0, "output": 0}
        try:
            async for line in http_stream_lines(
                self._url("/chat/completions"), headers=self._headers(), body=body,
                timeout=timeout,
            ):
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                payload = text[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue  # tolerate keep-alives / partial junk
                last = _consume_stream_chunk(chunk, pieces, usage)
                if last:
                    finish = last
                delta = _chunk_text(chunk)
                if delta:
                    yield {"delta": delta}
        except StreamHttpError as e:
            raise self._error(httputil.HttpResponse(e.status, e.headers, e.body),
                              model.id) from e
        except NetworkError as e:
            raise RouterError(redact_secrets(str(e)), code="E_OFFLINE",
                              provider=self.name, model=model.id,
                              reason="network") from e

        tool_calls = _assemble_tool_calls(pieces)
        if tool_calls:
            finish = "tool_calls"
        yield {
            "finish": finish,
            "tool_calls": tool_calls,
            "usage": dict(usage),
        }

    # ------------------------------------------------------------------ #
    # vision / STT
    # ------------------------------------------------------------------ #
    async def vision(self, model: ModelInfo, image_b64: str, mime: str,
                     question: str, *, timeout: float) -> ChatResult:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }]
        data, headers = await self._post_json(
            "/chat/completions", self._payload(model, messages, None, False),
            timeout=timeout, model=model.id,
        )
        return _parse_chat_response(data, headers)

    async def transcribe(self, model: ModelInfo, audio: bytes, filename: str,
                         mime: str, language: str | None, *, timeout: float) -> dict[str, Any]:
        fields: dict[str, str] = {
            "model": model.id,
            "response_format": "json",
        }
        if language:
            fields["language"] = language
        body, ctype = httputil.encode_multipart(
            fields, {"file": (filename, audio, mime)}
        )
        try:
            resp = await http_request(
                self._url("/audio/transcriptions"), method="POST",
                headers=self._headers(ctype), body=body, timeout=timeout,
            )
        except NetworkError as e:
            raise RouterError(redact_secrets(str(e)), code="E_OFFLINE",
                              provider=self.name, model=model.id,
                              reason="network") from e
        if not resp.ok:
            raise self._error(resp, model.id)
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise RouterError("non-JSON transcription body", code="E_PROVIDER_5XX",
                              provider=self.name, model=model.id,
                              reason="bad_body") from e
        text = str((data or {}).get("text") or "")
        return {"text": text.strip(), "model": model.id}


# --------------------------------------------------------------------------- #
# response parsing / normalization
# --------------------------------------------------------------------------- #
def _capabilities_from(item: dict[str, Any]) -> set[str]:
    """Best-effort capability extraction from /models metadata."""
    caps: set[str] = set()
    caps_list = item.get("capabilities")
    if isinstance(caps_list, list):
        caps.update(str(c).lower() for c in caps_list)
    if item.get("vision") is True:
        caps.add("vision")
    if item.get("tools") is True:
        caps.add("tools")
    if item.get("audio") is True or item.get("audio_input") is True:
        caps.add("audio")
    supported = item.get("supported_parameters") or item.get("supported_params")
    if isinstance(supported, list):
        if "tools" in supported:
            caps.add("tools")
    modalities = item.get("modalities") or item.get("output_modalities")
    if isinstance(modalities, list) and "image" in modalities:
        caps.add("vision")
    arch = item.get("architecture") or {}
    if isinstance(arch, dict):
        inp = arch.get("input_modalities") or []
        if isinstance(inp, list) and "image" in inp:
            caps.add("vision")
        out = arch.get("output_modalities") or []
        if isinstance(out, list) and "text" in out:
            caps.add("chat")
    if "whisper" in str(item.get("id", "")).lower() or item.get("type") == "audio":
        caps.add("audio")
    return caps


def _parse_chat_response(data: dict[str, Any],
                         headers: dict[str, str]) -> ChatResult:
    choices = data.get("choices") or []
    if not choices:
        raise RouterError("response had no choices", code="E_PROVIDER_5XX",
                          reason="empty_choices")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    text = _join_content(message.get("content")).strip()
    tool_calls = normalize_tool_calls(
        message.get("tool_calls") or message.get("function_call")
    )
    finish = choice.get("finish_reason") or ("tool_calls" if tool_calls else "stop")
    usage = data.get("usage") or {}
    usage_out = {
        "input": int(usage.get("prompt_tokens") or 0),
        "output": int(usage.get("completion_tokens") or 0),
    }
    return ChatResult(
        text=text,
        tool_calls=tool_calls,
        finish=str(finish),
        usage=usage_out,
        rate_limit=httputil.parse_rate_limit(headers),
    )


def _chunk_text(chunk: dict[str, Any]) -> str:
    choices = chunk.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta") or {}
    if isinstance(delta, dict):
        return _join_content(delta.get("content"))
    return ""


def _consume_stream_chunk(chunk: dict[str, Any],
                          pieces: dict[int, dict[str, str]],
                          usage: dict[str, int]) -> str | None:
    """Fold one SSE chunk into the accumulators; return finish_reason if set."""
    finish: str | None = None
    choices = chunk.get("choices") or []
    if choices and isinstance(choices[0], dict):
        choice = choices[0]
        if choice.get("finish_reason"):
            finish = str(choice["finish_reason"])
        delta = choice.get("delta") or {}
        if isinstance(delta, dict):
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                idx = int(tc.get("index") or 0)
                slot = pieces.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = tc.get("name") or fn.get("name")
                if name:
                    slot["name"] += str(name)
                args = tc.get("arguments", fn.get("arguments"))
                if args:
                    slot["arguments"] += args if isinstance(args, str) else json.dumps(args)
            fc = delta.get("function_call")
            if isinstance(fc, dict):
                slot = pieces.setdefault(0, {"id": "", "name": "", "arguments": ""})
                if fc.get("name"):
                    slot["name"] += str(fc["name"])
                if fc.get("arguments"):
                    slot["arguments"] += str(fc["arguments"])
    u = chunk.get("usage")
    if isinstance(u, dict):
        usage["input"] = int(u.get("prompt_tokens") or usage["input"])
        usage["output"] = int(u.get("completion_tokens") or usage["output"])
    return finish


def _assemble_tool_calls(pieces: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx in sorted(pieces):
        slot = pieces[idx]
        raw = slot["arguments"] or "{}"
        parsed, repaired = repair_arguments(raw)
        out.append({
            "id": slot["id"] or f"call_{idx}_{slot['name'] or 'tool'}",
            "type": "function",
            "function": {"name": slot["name"] or f"tool_{idx}", "arguments": parsed},
            "arguments_raw": slot["arguments"] or None,
            "repaired": repaired,
        })
    return out

