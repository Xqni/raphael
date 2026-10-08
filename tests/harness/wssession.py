"""Shared WebSocket session helpers over starlette's TestClient.

Timed receive pattern copied from brain/tests/test_ws.py (starlette 1.7's
WebSocketTestSession.receive_json() has no timeout — wrap the underlying
anyio stream receive with fail_after inside the portal so a hung server fails
the test instead of hanging pytest forever).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import anyio
from starlette.websockets import WebSocketDisconnect

Frame = Union[Dict[str, Any], bytes]


class SessionTimeout(AssertionError):
    """No matching frame arrived within the timeout."""


def recv_frame(ws, timeout: float = 5.0) -> Frame:
    """Timed raw receive from a starlette WebSocketTestSession: dict (JSON)
    or bytes (binary). Raises SessionTimeout / WebSocketDisconnect."""
    async def _inner():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    try:
        message = ws.portal.call(_inner)
    except TimeoutError:
        raise SessionTimeout(f'no frame within {timeout}s') from None
    if message['type'] == 'websocket.close':
        raise WebSocketDisconnect(code=message.get('code', 1000),
                                  reason=message.get('reason', ''))
    if message['type'] == 'websocket.http.response.start':
        raise AssertionError(f'WS denial response: {message["status"]}')
    if message.get('text') is not None:
        return json.loads(message['text'])
    return message.get('bytes', b'')


def ws_send(ws, obj: Dict[str, Any]) -> None:
    ws.send_text(json.dumps(obj, ensure_ascii=False))


def ws_send_raw(ws, raw: str) -> None:
    ws.send_text(raw)


def ws_auth(ws, token: str, role: str = 'cli', client: str = 'qa-test',
            v: int = 1, timeout: float = 5.0) -> Dict[str, Any]:
    """Send an auth frame and return the reply (auth_ok or auth_fail)."""
    ws_send(ws, {'type': 'auth', 'v': v, 'token': token, 'role': role,
                 'client': client, 'client_v': '1.0'})
    return wait_frame(ws, lambda m: m.get('type') in ('auth_ok', 'auth_fail'),
                      timeout=timeout)


def wait_frame(ws, pred: Callable[[Dict[str, Any]], bool], timeout: float = 5.0,
               skip: Tuple[str, ...] = ('ping',), limit: int = 200) -> Dict[str, Any]:
    """Read JSON frames until pred(frame). Pings (and `skip` types) are
    dropped. Non-matching frames are simply skipped over."""
    for _ in range(limit):
        frame = recv_frame(ws, timeout=timeout)
        if isinstance(frame, bytes):
            continue
        if frame.get('type') in skip:
            continue
        if pred(frame):
            return frame
    raise SessionTimeout(f'predicate not met within {limit} frames')


class WSSession:
    """One authenticated WS connection against a TestClient app."""

    role = 'cli'
    client_name = 'qa-test'

    def __init__(self, client, token: str, role: Optional[str] = None,
                 client_name: Optional[str] = None):
        self.client = client
        self.token = token
        self.role = role or self.role
        self.client_name = client_name or self.client_name
        self._ws = None
        self.frames: List[Dict[str, Any]] = []   # every JSON frame read (excl. ping)
        self.sent: List[Dict[str, Any]] = []     # every JSON frame we sent (golden recorder)
        self.binary: List[bytes] = []            # every binary frame read
        self.pings: List[Dict[str, Any]] = []
        self.session_id: Optional[str] = None

    # -- lifecycle ----------------------------------------------------------
    def open(self, timeout: float = 5.0) -> 'WSSession':
        self._ws = self.client.websocket_connect('/ws').__enter__()
        self.send({'type': 'auth', 'v': 1, 'token': self.token,
                   'role': self.role, 'client': self.client_name,
                   'client_v': '1.0'})
        reply = self.wait(lambda m: m.get('type') in ('auth_ok', 'auth_fail'),
                          timeout=timeout, record=False)
        if reply.get('type') != 'auth_ok':
            raise AssertionError(f'auth rejected: {reply}')
        self.session_id = reply.get('session')
        return self

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 — closing twice must not explode
                pass
            self._ws = None

    def __enter__(self) -> 'WSSession':
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- send ---------------------------------------------------------------
    def send(self, obj: Dict[str, Any]) -> None:
        self.sent.append(obj)
        self._ws.send_text(json.dumps(obj, ensure_ascii=False))

    def send_raw_text(self, raw: str) -> None:
        self._ws.send_text(raw)

    def send_bytes(self, data: bytes) -> None:
        self._ws.send_bytes(data)

    # -- receive ------------------------------------------------------------
    def _recv_raw(self, timeout: float) -> Frame:
        return recv_frame(self._ws, timeout=timeout)

    def recv(self, timeout: float = 5.0, record: bool = True) -> Frame:
        """One raw frame: dict (JSON) or bytes (binary). Pings recorded but
        NOT returned — call recv_json(include_ping=True) style via wait(never)."""
        while True:
            frame = self._recv_raw(timeout)
            if isinstance(frame, bytes):
                self.binary.append(frame)
                if record:
                    return frame          # binary is a real answer for callers
                continue
            if frame.get('type') == 'ping':
                self.pings.append(frame)
                if record:
                    return frame          # only surfaces when caller asked
                continue
            if record:
                self.frames.append(frame)
            return frame

    def wait(self, pred: Callable[[Dict[str, Any]], bool], timeout: float = 5.0,
             skip: Tuple[str, ...] = ('ping',), limit: int = 200,
             record: bool = True) -> Dict[str, Any]:
        """Read until pred(frame) — JSON frames only; returns the frame.
        Non-matching JSON frames are recorded (unless record=False)."""
        for _ in range(limit):
            frame = self._recv_raw(timeout)
            if isinstance(frame, bytes):
                self.binary.append(frame)
                continue
            if frame.get('type') in skip:
                self.pings.append(frame)
                continue
            if record:
                self.frames.append(frame)
            if pred(frame):
                return frame
            # non-matching frames stay recorded; keep waiting
        raise SessionTimeout(f'predicate not met within {limit} frames '
                             f'(role={self.role}, last={self.frames[-1] if self.frames else None})')

    def drain(self, quiet: float = 0.35, cap: float = 4.0) -> List[Dict[str, Any]]:
        """Read frames until `quiet` seconds of silence (max `cap`).
        Returns the JSON frames collected (binary goes to self.binary)."""
        collected: List[Dict[str, Any]] = []
        import time as _t
        deadline = _t.monotonic() + cap
        while _t.monotonic() < deadline:
            try:
                frame = self._recv_raw(timeout=quiet)
            except SessionTimeout:
                break
            if isinstance(frame, bytes):
                self.binary.append(frame)
                continue
            if frame.get('type') == 'ping':
                self.pings.append(frame)
                continue
            self.frames.append(frame)
            collected.append(frame)
        return collected

    # -- convenience --------------------------------------------------------
    def authed_session_id(self) -> Optional[str]:
        return self.session_id
