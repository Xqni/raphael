"""Hermetic brain-instance processes for resilience drills (qa-security).

Spawns `tests/harness/brain_boot.py` on an EPHEMERAL 127.0.0.1 port with a
private token + DB — never the live stack (Rule 12/14 + the wave-4 note:
the live stack stays up; these processes never touch its port, pidfile, or
data). Every spawned process MUST be stopped via _stop() (RAM rule).
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
REPO = TESTS.parent
BOOT = TESTS / 'harness' / 'brain_boot.py'


def free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def spawn(name: str, port: int, db_path: str | None = None) -> tuple:
    """Start one isolated brain. `db_path` pre-seeds an EXISTING DB (crash-
    recovery drills); otherwise a fresh temp DB is created."""
    if db_path is None:
        db_fd, db_path = tempfile.mkstemp(prefix=f'qa-{name}-db-')
        os.close(db_fd)
    tok_fd, tok_path = tempfile.mkstemp(prefix=f'qa-{name}-tok-')
    os.close(tok_fd)
    log_fd, log_path = tempfile.mkstemp(prefix=f'qa-{name}-log-',
                                        suffix='.txt')
    token = f'{name}-token-{os.urandom(6).hex()}'
    with open(tok_path, 'w', encoding='utf-8') as f:
        f.write(token)
    env = dict(os.environ)
    env.update({
        'RAPHAEL_INSTANCE': name,
        'RAPHAEL_PORT': str(port),
        'RAPHAEL_BIND': '127.0.0.1',
        'RAPHAEL_DB_PATH': db_path,
        'RAPHAEL_TOKEN_PATH': tok_path,
        'RAPHAEL_DISABLE_ROUTER': '1',
        'RAPHAEL_DISABLE_BINARY_TTS': '1',
        'RAPHAEL_FISH_PORT': '1',
        'RAPHAEL_CONFIRM_TIMEOUT_S': '2',
        'RAPHAEL_JOBS_MAX_CONCURRENT': '4',
        'PYTHONPATH': str(REPO),
    })
    logf = open(log_fd, 'w', encoding='utf-8')  # noqa: SIM115 — with subprocess
    proc = subprocess.Popen(
        [sys.executable, str(BOOT)], cwd=str(REPO), env=env,
        stdout=logf, stderr=subprocess.STDOUT, text=True)
    meta = {'token': token, 'db': db_path, 'tok_path': tok_path,
            'log': log_path, 'logf': logf, 'port': port, 'proc': proc}
    return proc, meta


def log_tail(meta: dict, limit: int = 2000) -> str:
    try:
        meta['logf'].flush()
        return Path(meta['log']).read_text(encoding='utf-8',
                                           errors='replace')[-limit:]
    except OSError:
        return '<no log>'


def health(port: int, token: str, meta: dict | None = None,
           timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}/health',
            headers={'X-Raphael-Token': token})
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.status
        except Exception as e:  # noqa: BLE001 — boot polling
            last = e
            time.sleep(0.25)
    raise AssertionError(
        f'instance on :{port} never became healthy: {last}\n'
        f'log tail:\n{log_tail(meta) if meta else "<no meta>"}')


def rest(port: int, path: str, token: str, body: dict | None = None,
         method: str = 'GET'):
    data = None
    headers = {'X-Raphael-Token': token}
    if body is not None:
        import json as _json
        data = _json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
        method = 'POST'
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                                 data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            import json as _json
            raw = r.read() or b'{}'
            try:
                return r.status, _json.loads(raw)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        import json as _json
        try:
            return e.code, _json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}


def stop(proc: subprocess.Popen):
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def cleanup_meta(meta: dict):
    try:
        meta['logf'].close()
    except Exception:  # noqa: BLE001
        pass
    for key in ('db', 'tok_path', 'log'):
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(meta[key] + suffix)
            except OSError:
                pass
