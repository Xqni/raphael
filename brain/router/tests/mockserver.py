"""Scripted OpenAI-compatible mock server for router contract tests.

Listens on 127.0.0.1:<ephemeral> only (AGENT_RULES §5: prefer mocks; no
external network, no keys). Every request is recorded so tests can assert
EXACTLY what left the process — e.g. "the GROQ key never appears in a body".

Scripting:
    srv = ScriptedServer()
    srv.start()
    srv.chat(script=[                 # consumed per POST /chat/completions
        {"choices": [...]},           # dict  -> 200 with this JSON body
        429,                          # int   -> that status (empty body)
        (429, {"Retry-After": "0.01"}, b"slow down"),
        ("sse", ["data: {...}", "data: [DONE]"]),
        b"not json at all",           # bytes -> 200 with raw body
    ])

`models` drives `GET /models` (discovery is never hardcoded upstream).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_MODELS = [
    {"id": "test-instant-8b"},
    {"id": "test-large-70b"},
    {"id": "test-whisper-large-v3"},
    {"id": "test-vision-scout"},
]


class ScriptedServer:
    def __init__(self, models: list[dict] | None = None,
                 free_suffix: bool = True,
                 whisper_field: str | None = None) -> None:
        self.models = models if models is not None else list(DEFAULT_MODELS)
        self.free_suffix = free_suffix       # append '-free' for Zen-style lists
        self.whisper_field = whisper_field   # optional multipart field name check
        self.requests: list[dict[str, Any]] = []
        self.chat_script: list[Any] = []
        self.transcribe_script: list[Any] = []
        self.ollama_script: list[Any] = []
        # per-model responses (model-capability learning tests): model id →
        # response, and model ids that 400 ONLY when the payload has tools
        self.model_script: dict[str, Any] = {}
        self.tool_fail_models: set[str] = set()
        self.status_by_path: dict[str, int] = {}
        self._lock = threading.Lock()
        self._http: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    # ------------------------------------------------------------------ #
    def start(self) -> str:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # silence stderr
                pass

            def _record(self, body: bytes) -> None:
                with server._lock:
                    server.requests.append({
                        "method": self.command,
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": body,
                        "ts": time.monotonic(),   # failover-ordering assertions
                    })

            def _send(self, status: int, body: bytes,
                      headers: dict[str, str] | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type",
                                 (headers or {}).get("Content-Type", "application/json"))
                for key, val in (headers or {}).items():
                    if key.lower() != "content-type":
                        self.send_header(key, val)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            # ---------------------------------------------------------- #
            def do_GET(self) -> None:  # noqa: N802
                self._record(b"")
                if self.path.endswith("/api/tags"):
                    self._handle_ollama_tags()
                    return
                if self.path.endswith("/models"):
                    status = server.status_by_path.get("models", 200)
                    if status != 200:
                        self._send(status, json.dumps(
                            {"error": {"message": "models down"}}).encode())
                        return
                    data = []
                    for model in server.models:
                        item = dict(model)
                        if server.free_suffix and "free" not in item["id"]:
                            item["id"] = item["id"] + "-free"
                        data.append(item)
                    self._send(200, json.dumps({"object": "list",
                                                "data": data}).encode())
                    return
                self._send(404, b'{"error":"not found"}')

            # ---------------------------------------------------------- #
            def do_POST(self) -> None:  # noqa: N802
                body = self._read_body()
                self._record(body)
                if self.path.endswith("/chat/completions"):
                    self._handle_chat(body)
                    return
                if self.path.endswith("/audio/transcriptions"):
                    self._handle_transcribe(body)
                    return
                if self.path.endswith("/api/chat"):
                    self._handle_ollama_chat(body)
                    return
                self._send(404, b'{"error":"not found"}')

            def _handle_chat(self, body: bytes) -> None:
                model, has_tools = _payload_model_tools(body)
                with server._lock:
                    if model in server.tool_fail_models and has_tools:
                        step = (400, {}, b'{"error":{"message":"tool calling '
                                b'is not supported with this model"}}')
                    elif model in server.model_script:
                        step = server.model_script[model]
                    else:
                        step = (server.chat_script.pop(0)
                                if server.chat_script else None)
                if step is None:
                    step = _default_reply(body)
                self._emit(step)

            def _handle_transcribe(self, body: bytes) -> None:
                with server._lock:
                    step = (server.transcribe_script.pop(0)
                            if server.transcribe_script else None)
                if step is None:
                    step = {"text": "mock whisper transcript"}
                self._emit(step)

            def _handle_ollama_tags(self) -> None:
                with server._lock:
                    models = [{"name": m["id"], "capabilities": ["chat", "tools"]}
                              for m in server.models]
                self._send(200, json.dumps({"models": models}).encode())

            def _handle_ollama_chat(self, body: bytes) -> None:
                with server._lock:
                    step = server.ollama_script.pop(0) if server.ollama_script else None
                if step is None:
                    model = "unknown"
                    try:
                        model = json.loads(body.decode("utf-8", errors="replace")).get(
                            "model", "unknown")
                    except json.JSONDecodeError:
                        pass
                    step = {"message": {"role": "assistant",
                                        "content": f"ollama reply from {model}"},
                            "done": True, "done_reason": "stop",
                            "usage": {"prompt_eval_count": 4, "eval_count": 6}}
                self._emit(step)

            def _emit(self, step: Any) -> None:
                if isinstance(step, tuple) and step and step[0] == "sse":
                    payload = "".join(
                        (line if line.endswith("\n") else line + "\n")
                        for line in step[1]).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if isinstance(step, tuple) and len(step) == 3:
                    status, headers, payload = step
                    self._send(status, payload, headers)
                    return
                if isinstance(step, int):
                    self._send(step, json.dumps(
                        {"error": {"message": f"scripted {step}"}}).encode(
                            ), {"Retry-After": "0.01"})
                    return
                if isinstance(step, bytes):
                    self._send(200, step)
                    return
                if isinstance(step, dict) and "status" in step:
                    status = int(step["status"])
                    headers = dict(step.get("headers") or {})
                    headers.setdefault("Retry-After", "0.01")
                    self._send(status, json.dumps(step.get("body") or {}).encode(),
                               headers)
                    return
                self._send(200, json.dumps(step).encode())

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = self._http.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._http.serve_forever,
                                        daemon=True, name="router-mock-http")
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._http is not None:
            self._http.shutdown()
            self._http.server_close()
            self._http = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------ #
    @property
    def chat_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.requests if r["path"].endswith("/chat/completions")]

    @property
    def model_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.requests if r["path"].endswith("/models")]

    @property
    def transcribe_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.requests
                    if r["path"].endswith("/audio/transcriptions")]

    def bodies(self) -> list[bytes]:
        with self._lock:
            return [r["body"] for r in self.requests]


def _payload_model_tools(body: bytes) -> tuple[str, bool]:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return "", False
    return str(payload.get("model") or ""), bool(payload.get("tools"))


def _default_reply(body: bytes) -> Any:
    """Deterministic 200 for unscripted chat calls (echoes the model asked for)."""
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        payload = {}
    model = payload.get("model", "unknown")
    return {
        "choices": [{
            "message": {"role": "assistant",
                        "content": f"scripted reply from {model}"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 7, "completion_tokens": 5},
    }


def tool_reply(name: str, arguments: str, *, finish: str = "tool_calls") -> dict:
    """OpenAI-shaped tool-call reply (arguments intentionally a raw string)."""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }],
            },
            "finish_reason": finish,
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 9},
    }


def sse_tool_stream(name: str, arguments: str) -> tuple:
    """SSE stream whose tool-call arguments arrive as fragments."""
    frags = [
        "data: " + json.dumps({"choices": [{"delta": {
            "tool_calls": [{"index": 0, "id": "call_sse_1",
                            "function": {"name": name, "arguments": ""}}],
        }, "finish_reason": None}]}),
        "data: " + json.dumps({"choices": [{"delta": {
            "tool_calls": [{"index": 0,
                            "function": {"arguments": arguments[:len(arguments)//2]}}],
        }, "finish_reason": None}]}),
        "data: " + json.dumps({"choices": [{"delta": {
            "tool_calls": [{"index": 0,
                            "function": {"arguments": arguments[len(arguments)//2:]}}],
        }, "finish_reason": None}]}),
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    return ("sse", frags)


def sse_text_stream(text: str) -> tuple:
    """SSE stream of plain text deltas."""
    words = text.split(" ")
    frags = []
    for i, word in enumerate(words):
        frags.append("data: " + json.dumps({"choices": [{
            "delta": {"content": word + (" " if i < len(words) - 1 else "")},
            "finish_reason": None}]}))
    frags.append("data: " + json.dumps(
        {"choices": [{"delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 5, "completion_tokens": 6}}))
    frags.append("data: [DONE]")
    return ("sse", frags)
