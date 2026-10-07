"""Scripted mock OpenAI-compatible provider (INTERFACES §a shape) for the
router seam — runs on an ephemeral 127.0.0.1 port, never a real provider.

Endpoints (the ones brain/router uses):
- GET  {base}/models            -> {"data": [{"id": "mock-model-1", ...}]}
- POST {base}/chat/completions  -> next scripted step
- POST {base}/...anything...    -> also recorded (used as an ollama/counter mock)

Script steps (queue; when empty, `default_step` applies):
  {"content": "text"}                        -> 200, normal assistant text
  {"tool": {"name": "launch_url", "args": {}}} -> 200, content = JSON tool call
                                                 (loop._extract_tool_call path)
  {"status": 429}                            -> 429 rate limit
  {"status": 500}                            -> provider 5xx
  {"raw": "{malformed"}                      -> 200 with malformed JSON body
  {"delay": 0.5, "content": "x"}             -> slow reply (seconds)

Every request is recorded in `.requests` (method, path, parsed body if JSON,
authorization header presence — tests only ever use FAKE keys).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


class MockOpenAI:
    def __init__(self, name: str = 'mock-openai'):
        self.name = name
        self.requests: List[Dict[str, Any]] = []
        self.script: List[Dict[str, Any]] = []
        self.default_step: Dict[str, Any] = {'content': 'mock default reply'}
        self.models: List[str] = ['mock-model-1']
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port: int = 0
        self._lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> 'MockOpenAI':
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name=f'{self.name}-{self._port}',
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> 'MockOpenAI':
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- addressing ---------------------------------------------------------
    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        """OpenAI-style base (…/v1) — router appends /chat/completions."""
        return f'http://127.0.0.1:{self._port}/v1'

    @property
    def plain_url(self) -> str:
        """Bare origin — e.g. as an ollama_url counter target."""
        return f'http://127.0.0.1:{self._port}'

    # -- introspection ------------------------------------------------------
    @property
    def count(self) -> int:
        with self._lock:
            return len(self.requests)

    @property
    def completions_count(self) -> int:
        with self._lock:
            return len([r for r in self.requests
                        if 'chat/completions' in r['path']])

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()
        self.script.clear()

    def push(self, *steps: Dict[str, Any]) -> None:
        self.script.extend(steps)

    # -- serving ------------------------------------------------------------
    def _record(self, method: str, path: str, body: bytes,
                headers: Dict[str, str]) -> None:
        entry: Dict[str, Any] = {
            'method': method, 'path': path,
            'auth': bool(headers.get('Authorization')
                         or headers.get('authorization')),
            # case-insensitive copy — header assertions (e.g. Bug A's
            # x-opencode-session) must not depend on casing
            'headers': {str(k).lower(): v for k, v in headers.items()},
            'ts': time.time(),
        }
        try:
            entry['json'] = json.loads(body.decode('utf-8')) if body else None
        except (ValueError, UnicodeDecodeError):
            entry['json'] = None
            entry['body_len'] = len(body)
        with self._lock:
            self.requests.append(entry)

    def _next_chat_response(self, stream: bool) -> tuple[int, str, str]:
        """-> (status, content_type, body). Honors `stream: true` with real
        SSE (the merged router parses `data:` lines + [DONE] — a plain JSON
        reply to a streaming request yields zero deltas)."""
        step = self.script.pop(0) if self.script else self.default_step
        delay = float(step.get('delay') or 0)
        if delay:
            time.sleep(delay)
        status = int(step.get('status') or 200)
        if status != 200:
            body = json.dumps({'error': {'message': f'mock status {status}',
                                         'type': 'mock_error'}})
            return status, 'application/json', body
        if stream:
            return 200, 'text/event-stream; charset=utf-8', \
                self._sse_body(step)
        if 'raw' in step:
            return 200, 'application/json', str(step['raw'])
        if 'tool' in step:
            tool = step['tool']
            content = json.dumps({'tool': tool.get('name'),
                                  'args': tool.get('args') or {}})
        else:
            content = str(step.get('content', ''))
        body = json.dumps({
            'id': 'chatcmpl-mock', 'object': 'chat.completion',
            'model': 'mock-model-1',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5,
                      'total_tokens': 15},
        })
        return 200, 'application/json', body

    def _sse_body(self, step: dict) -> str:
        """SSE transcript for one scripted step (content OR tool call)."""
        def ev(obj) -> str:
            return 'data: ' + json.dumps(obj) + '\n\n'

        head = {'id': 'chatcmpl-mock', 'object': 'chat.completion.chunk',
                'model': 'mock-model-1', 'choices': [{'index': 0}]}
        out = [ev({**head, 'choices': [{'index': 0,
                                        'delta': {'role': 'assistant'}}]})]
        if 'tool' in step:
            tool = step['tool']
            args = json.dumps(tool.get('args') or {})
            out.append(ev({**head, 'choices': [{'index': 0, 'delta': {
                'tool_calls': [{'index': 0, 'id': 'call_mock_0',
                                'type': 'function',
                                'function': {'name': tool.get('name'),
                                             'arguments': args}}]}}]}))
            out.append(ev({**head, 'choices': [{'index': 0, 'delta': {},
                                                'finish_reason': 'tool_calls'}]}))
        else:
            content = str(step.get('content', ''))
            words = content.split(' ')
            if words:
                n = max(1, len(words) // 3)
                pieces = [' '.join(words[i:i + n])
                          for i in range(0, len(words), n)]
            else:
                pieces = []
            for piece in pieces:
                out.append(ev({**head, 'choices': [{'index': 0, 'delta': {
                    'content': piece + ' '}}]}))
            out.append(ev({**head, 'choices': [{'index': 0, 'delta': {},
                                                'finish_reason': 'stop'}]}))
        out.append('data: [DONE]\n\n')
        return ''.join(out)


def _make_handler(mock: MockOpenAI):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):  # silence access logs
            return

        def _read_body(self) -> bytes:
            length = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(length) if length else b''

        def _respond(self, status: int, ctype: str, body: str) -> None:
            data = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            mock._record('GET', self.path, b'', dict(self.headers))
            if self.path.rstrip('/').endswith('/models'):
                data = json.dumps({'data': [{'id': m, 'free': True}
                                            for m in mock.models]})
                self._respond(200, 'application/json', data)
                return
            self._respond(404, 'application/json',
                          json.dumps({'error': 'not found'}))

        def do_POST(self):  # noqa: N802
            body = self._read_body()
            mock._record('POST', self.path, body, dict(self.headers))
            if 'chat/completions' in self.path:
                stream = False
                try:
                    stream = bool(json.loads(body.decode('utf-8')).get('stream'))
                except (ValueError, UnicodeDecodeError):
                    stream = False
                status, ctype, resp = mock._next_chat_response(stream)
                self._respond(status, ctype, resp)
                return
            # unknown POST (e.g. ollama /api/chat when used as a counter) —
            # recorded; a well-formed JSON error so nothing crashes.
            self._respond(404, 'application/json',
                          json.dumps({'error': 'mock: no handler'}))

    return Handler


def make_mock_openai(name: str = 'mock-openai') -> MockOpenAI:
    return MockOpenAI(name=name).start()
