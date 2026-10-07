"""Minimal MCP (Model Context Protocol) stdio client — JSON-RPC 2.0.

Scope (tools-memory plan §3.6): `initialize` handshake, `tools/list`,
`tools/call`, notifications, and polite error responses to server-initiated
requests (method-not-supported — Raphael does not implement sampling/roots).

One `StdioClient` per configured server = one child process:
- argv list only (`shell=False` — MCP servers start ONLY from the
  user-authored `mcp.servers` config, never from a tool call / model);
- a reader thread decouples stdout lines from request/response matching;
  every request has a deadline (timeout -> McpError, child still alive);
- stderr is drained to a bounded tail (error context, never blocks the child);
- line size, result size and call timeouts are capped;
- `close()` terminates the child (terminate -> wait -> kill): tests and
  shutdown leave ZERO orphans (AGENT_RULES §14).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = '2024-11-05'
_MAX_LINE = 4_000_000          # single JSON-RPC line cap (bytes-ish)
_STDERR_TAIL = 4000


class McpError(RuntimeError):
    """Transport/protocol/timeout failure — carries a short message."""


class StdioClient:
    def __init__(self, argv: List[str], *, timeout: float = 10.0,
                 env: Optional[Dict[str, str]] = None,
                 cwd: Optional[str] = None):
        if not isinstance(argv, (list, tuple)) or not argv:
            raise McpError('command must be a non-empty argv list')
        self.argv = [str(a) for a in argv]
        self.timeout = float(timeout)
        self._id = 0
        self._q: 'queue.Queue[Optional[str]]' = queue.Queue()
        self._stderr_tail: List[str] = []
        try:
            self._proc = subprocess.Popen(
                self.argv, shell=False, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
                env={**os.environ, **(env or {})}, cwd=cwd)
        except (OSError, ValueError) as e:
            raise McpError(f'cannot spawn {self.argv[0]!r}: {e}')
        threading.Thread(target=self._read_stdout, name='mcp-out',
                         daemon=True).start()
        threading.Thread(target=self._read_stderr, name='mcp-err',
                         daemon=True).start()

    # ---- reader threads ----------------------------------------------------
    def _read_stdout(self):
        try:
            for line in self._proc.stdout:
                if len(line) > _MAX_LINE:
                    self._q.put(None)          # protocol abuse: fail all waiters
                    return
                self._q.put(line)
        except (ValueError, OSError):
            pass
        finally:
            self._q.put(None)                  # EOF sentinel

    def _read_stderr(self):
        try:
            for line in self._proc.stderr:
                self._stderr_tail.append(line)
                if len(self._stderr_tail) > 200:
                    del self._stderr_tail[:100]
        except (ValueError, OSError):
            pass

    def stderr_text(self) -> str:
        return ''.join(self._stderr_tail)[-_STDERR_TAIL:].strip()

    # ---- jsonrpc -----------------------------------------------------------
    def _send(self, obj: Dict[str, Any]) -> None:
        if self._proc.poll() is not None or self._proc.stdin is None:
            raise McpError(f'server exited (rc={self._proc.returncode}): '
                           f'{self.stderr_text()[-300:]}')
        try:
            self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + '\n')
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            raise McpError(f'write failed: {e} (rc={self._proc.returncode})')

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                timeout: Optional[float] = None) -> Dict[str, Any]:
        """Send a request, wait for ITS response. Returns the `result`
        object; raises McpError on server error / timeout / death."""
        self._id += 1
        rid = self._id
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method,
                    'params': params or {}})
        deadline = (timeout if timeout is not None else self.timeout)
        import time
        end = time.monotonic() + max(0.05, deadline)
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise McpError(f'timeout after {deadline:g}s waiting for '
                               f'{method!r} (stderr: {self.stderr_text()[-200:]})')
            try:
                line = self._q.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self._proc.poll() is not None and self._q.empty():
                    raise McpError(f'server exited (rc={self._proc.returncode}) '
                                   f'during {method!r}: '
                                   f'{self.stderr_text()[-300:]}')
                continue
            if line is None:
                if self._proc.poll() is not None:
                    raise McpError(f'server closed stdout (rc='
                                   f'{self._proc.returncode}) during '
                                   f'{method!r}: {self.stderr_text()[-300:]}')
                continue                          # transient EOF interleave
            try:
                msg = json.loads(line)
            except ValueError:
                continue                          # non-JSON noise: ignore
            if not isinstance(msg, dict):
                continue
            if msg.get('id') == rid and ('result' in msg or 'error' in msg):
                if 'error' in msg:
                    err = msg['error'] or {}
                    raise McpError(f"{method} -> error {err.get('code')}: "
                                   f"{err.get('message')}")
                result = msg.get('result')
                return result if isinstance(result, dict) else {}
            if 'method' in msg and 'id' in msg and 'result' not in msg:
                # server->client request: polite method-not-supported reply
                self._send({'jsonrpc': '2.0', 'id': msg['id'],
                            'error': {'code': -32601,
                                      'message': 'method not supported'}})
            # notifications and other ids: ignore

    # ---- lifecycle ---------------------------------------------------------
    def handshake(self) -> Dict[str, Any]:
        result = self.request('initialize', {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {},
            'clientInfo': {'name': 'raphael', 'version': '1.0'},
        })
        self.notify('notifications/initialized')
        return result

    def alive(self) -> bool:
        return self._proc.poll() is None

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:  # noqa: BLE001 — escalate to kill, never hang
            try:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._proc.stdout.close()
            self._proc.stderr.close()
        except (OSError, ValueError):
            pass
