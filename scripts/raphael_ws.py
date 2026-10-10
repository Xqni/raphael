# -*- coding: utf-8 -*-
"""Minimal stdlib WebSocket client for the Raphael Brain (role=cli).

Implements exactly what docs/PROTOCOL.md §2/§3 requires of a CLI client —
handshake + auth frame, masked client frames (RFC 6455), automatic pong
(the server pings every 10 s; a silent client is dropped after 3 misses),
text frames = JSON control frames with `v: 1` + per-connection `seq`.

Stdlib only, synchronous, value-blind (tokens are never printed; auth
failures surface codes only). Used by scripts/raphael_cli.py for
`confirm` and `chat` — those two are WS-only surfaces (confirm_resp /
command / answer frames have no REST twin).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct

_WS_GUID = "258EAFA5-E914-47DA-95CA-5AB0DC85B11F"


class WSError(Exception):
    """Handshake/auth/framing failure. Message never contains the token."""


def _mask_frame(opcode: int, payload: bytes) -> bytes:
    """Client->server frame: FIN|opcode, MASK+len, 4-byte key, masked body."""
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        head = bytes([0x80 | opcode, 0x80 | length])
    elif length < 65536:
        head = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack("!H", length)
    else:
        head = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack("!Q", length)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + mask + masked


class WSSession:
    def __init__(self, sock):
        self.sock = sock
        self._rfile = sock.makefile("rb")
        self.seq = 0
        self.closed = False

    @classmethod
    def connect(cls, host, port, token, timeout=10.0, role="cli",
                client="raphael-cli", client_v="1.0", path="/ws"):
        """TCP + HTTP upgrade + auth handshake (PROTOCOL §2). Raises
        WSError on any failure — codes only, token never in messages."""
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        try:
            sock = socket.create_connection((host, int(port)), timeout=timeout)
        except OSError as exc:
            raise WSError("connect failed: %s" % exc)
        try:
            sock.sendall((
                "GET %s HTTP/1.1\r\n"
                "Host: %s:%s\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Key: %s\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
                % (path, host, port, key)).encode("ascii"))
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise WSError("connection closed during handshake")
                buf += chunk
                if len(buf) > 16384:
                    raise WSError("handshake response too large")
            head = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace")
            lines = head.split("\r\n")
            if " 101" not in lines[0]:
                raise WSError("handshake rejected: %s" % lines[0])
            expect = base64.b64encode(
                hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
            ).decode("ascii")
            got = None
            for line in lines[1:]:
                if line.lower().startswith("sec-websocket-accept:"):
                    got = line.split(":", 1)[1].strip()
            if got != expect:
                raise WSError("bad Sec-WebSocket-Accept")
        except OSError as exc:
            sock.close()
            raise WSError("handshake failed: %s" % exc)
        sock.settimeout(timeout)
        sess = cls(sock)
        try:
            sess.send_json({"type": "auth", "token": token, "role": role,
                            "client": client, "client_v": client_v})
            frame = sess.recv_json(timeout=timeout)
        except Exception:
            sess.close()
            raise
        if not frame or frame.get("type") == "auth_fail":
            code = (frame or {}).get("code", "no-response")
            sess.close()
            raise WSError("auth failed: %s" % code)
        if frame.get("type") != "auth_ok":
            sess.close()
            raise WSError("unexpected handshake frame: %s"
                          % frame.get("type"))
        sock.settimeout(None)
        return sess

    # -- sending -----------------------------------------------------------
    def send_json(self, obj):
        obj.setdefault("v", 1)
        obj["seq"] = self.seq
        self.seq += 1
        payload = json.dumps(obj).encode("utf-8")
        self.sock.sendall(_mask_frame(0x1, payload))

    def _send_control(self, opcode, payload=b""):
        try:
            self.sock.sendall(_mask_frame(opcode, payload))
        except OSError:
            pass

    def _read_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self._rfile.read(n - len(out))
            if not chunk:
                raise WSError("connection closed mid-frame")
            out += chunk
        return out

    # -- receiving ---------------------------------------------------------
    def recv_frame(self, timeout=None):
        """-> (opcode, payload-bytes). Transparently answers server pings;
        returns (8, reason) on close; raises WSError on EOF, TimeoutError
        on idle."""
        if self.closed:
            return 8, b""
        self.sock.settimeout(timeout)
        try:
            b0, b1 = self._read_exact(2)
        except socket.timeout:
            raise TimeoutError("no frame within %ss" % timeout)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else None
        payload = self._read_exact(length) if length else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x9:                       # ping -> pong (masked, empty)
            self._send_control(0xA)
            return self.recv_frame(timeout=timeout)
        if opcode == 0x8:
            self.closed = True
            return 8, payload
        return opcode, payload

    def recv_json(self, timeout=None, skip_binary=True):
        """Next text frame as a dict (JSON); None on close. Binary frames
        (e.g. stray speak chunks) are skipped by default."""
        while True:
            opcode, payload = self.recv_frame(timeout=timeout)
            if opcode == 0x8:
                return None
            if opcode == 0x1:
                try:
                    data = json.loads(payload.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue                   # tolerate junk, keep reading
                return data if isinstance(data, dict) else None
            if opcode == 0x2 and skip_binary:
                continue

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.sendall(_mask_frame(0x8, b""))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
