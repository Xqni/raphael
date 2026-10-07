"""Regression: instance isolation (INTERFACES §d).

1. The §d table itself is collision-free (ports/pidfiles/locks/mutexes/
   CDP/data-dirs unique across all 10 instances).
2. Tripwire: runtime code must derive values from RAPHAEL_INSTANCE
   (unimplemented — requests filed).
3. Two REAL brain processes, each with its own env, run side by side on
   127.0.0.1 with NO cross-talk: separate tokens, separate job stores.
"""
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path.cwd()
BOOT = REPO / 'tests' / 'harness' / 'brain_boot.py'


# ---- (1) table contract ---------------------------------------------------
def _interfaces_rows():
    text = (REPO / 'docs' / 'INTERFACES.md').read_text()
    rows = []
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip().strip('`') for c in line.strip('|').split('|')]
        if len(cells) == 8 and cells[0] != 'instance' \
                and not set(cells[0]) <= set('-: '):
            rows.append(cells)
    return rows


def test_interfaces_instance_table_is_collision_free():
    rows = _interfaces_rows()
    instances = [r[0].split()[0].strip('`') for r in rows]
    assert len(instances) == len(set(instances)), instances
    assert len(instances) == 11, instances   # main + 10 lane instances
    assert instances.count('main') == 1
    main = next(r for r in rows if r[0].startswith('main'))

    # full-value columns: unique as written
    for col, name in ((1, 'port'), (6, 'CDP port'), (7, 'data-dir')):
        values = [r[col] for r in rows]
        dupes = {v for v in values if values.count(v) > 1}
        assert not dupes, f'{name} collisions: {dupes} in {values}'
    ports = [int(r[1]) for r in rows]
    assert all(1024 < p < 65535 for p in ports), ports

    # derived columns: expand per the documented format rule and verify
    # uniqueness + that each cell names its instance.
    # pidfile contract (updated on main 2026-10-06): `<data-dir>/brain.pid`,
    # main keeps a legacy /tmp dual-write note — cells may also use `…` shorthand.
    expanded = {'pidfile': [], 'lock': [], 'mutex': []}
    for r, inst in zip(rows, instances):
        cell_pid, cell_lock, cell_mutex = r[2], r[3], r[4]
        if inst == 'main':
            assert cell_pid.startswith('~/.raphael/brain.pid'), cell_pid
            expanded['pidfile'].append('~/.raphael/brain.pid')
            expanded['lock'].append(main[3])
            expanded['mutex'].append(main[4])
            continue
        pid_exp = f'~/.raphael/{inst}/brain.pid'
        lock_exp = f'%TMP%\\raphael_body_{inst}.lock'
        mutex_exp = f'Raphael_Supervisor_{inst}'
        # cells must reference THEIR instance (doc self-consistency) —
        # full value (current table) or §d `…` shorthand
        assert cell_pid in (pid_exp, f'…_{inst}.pid',
                            f'…_{inst}.brain.pid'), (inst, cell_pid)
        assert cell_mutex in (mutex_exp, f'…_{inst}'), (inst, cell_mutex)
        assert cell_lock in (lock_exp, f'…_{inst}.lock',
                             f'…_body_{inst}.lock'), (inst, cell_lock)
        expanded['pidfile'].append(pid_exp)
        expanded['lock'].append(lock_exp)
        expanded['mutex'].append(mutex_exp)
    for name, values in expanded.items():
        dupes = {v for v in values if values.count(v) > 1}
        assert not dupes, f'{name} collisions: {dupes} in {values}'


# ---- (2) derivation tripwire ---------------------------------------------
@pytest.mark.xfail(strict=False,
                   reason='INTERFACES §d: no runtime code reads '
                          'RAPHAEL_INSTANCE — ports/locks/pidfiles/mutexes '
                          'are hardcoded, so two lane instances collide on '
                          '8765/raphael_body.lock/Raphael_Supervisor '
                          '(requests: qa-security -> brain-core/infra/'
                          'pc-control instance-derivation)')
def test_runtime_code_derives_from_raphael_instance():
    checked = [REPO / 'brain' / 'run.py', REPO / 'brain' / 'app.py',
               REPO / 'supervisor' / 'main.py', REPO / 'body' / 'win' / 'main.py',
               REPO / 'body' / 'win' / 'ws_client.py']
    missing = [str(p.relative_to(REPO)) for p in checked
               if p.exists() and 'RAPHAEL_INSTANCE' not in p.read_text()]
    assert not missing, f'RAPHAEL_INSTANCE not referenced in: {missing}'


# ---- (3) two real instances ----------------------------------------------
def _free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn(name: str, port: int) -> tuple[subprocess.Popen, dict]:
    db_fd, db_path = tempfile.mkstemp(prefix=f'qa-{name}-db-')
    os.close(db_fd)
    tok_fd, tok_path = tempfile.mkstemp(prefix=f'qa-{name}-tok-')
    os.close(tok_fd)
    log_fd, log_path = tempfile.mkstemp(prefix=f'qa-{name}-log-', suffix='.txt')
    token = f'{name}-token-{os.urandom(6).hex()}'
    with open(tok_path, 'w') as f:
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
    logf = open(log_fd, 'w')  # noqa: SIM115 — lives with the subprocess
    proc = subprocess.Popen(
        [sys.executable, str(BOOT)], cwd=str(REPO), env=env,
        stdout=logf, stderr=subprocess.STDOUT, text=True)
    meta = {'token': token, 'db': db_path, 'tok_path': tok_path,
            'log': log_path, 'logf': logf}
    return proc, meta


def _log_tail(meta: dict, limit: int = 2000) -> str:
    try:
        meta['logf'].flush()
        return Path(meta['log']).read_text(errors='replace')[-limit:]
    except OSError:
        return '<no log>'


def _health(port: int, token: str, meta: dict | None = None,
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
        f'log tail:\n{_log_tail(meta) if meta else "<no meta>"}')


def _rest(port: int, path: str, token: str, body: dict | None = None,
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
    with urllib.request.urlopen(req, timeout=5) as r:
        import json as _json
        return r.status, _json.loads(r.read() or b'{}')


def _stop(proc: subprocess.Popen):
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_two_instances_run_without_collision():
    """Two isolated instances (explicit per-instance env): independent
    health, tokens, and job stores — one instance's jobs never leak."""
    port_a, port_b = _free_port(), _free_port()
    proc_a = proc_b = None
    metas = []
    try:
        proc_a, meta_a = _spawn('qa-security-a', port_a)
        metas.append(meta_a)
        proc_b, meta_b = _spawn('qa-security-b', port_b)
        metas.append(meta_b)

        assert _health(port_a, meta_a['token'], meta_a) == 200
        assert _health(port_b, meta_b['token'], meta_b) == 200

        # cross-token must be rejected on each instance (separate secrets)
        import urllib.error
        for port, token in ((port_a, meta_b['token']),
                            (port_b, meta_a['token'])):
            req = urllib.request.Request(f'http://127.0.0.1:{port}/health',
                                         headers={'X-Raphael-Token': token})
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=3)
            assert exc.value.code == 401

        # a job on A must be invisible to B
        code, resp = _rest(port_a, '/jobs', meta_a['token'],
                           {'text': 'isolation probe job', 'source': 'text'})
        assert code == 200
        time.sleep(0.5)
        code, jobs_b = _rest(port_b, '/jobs', meta_b['token'])
        assert jobs_b == [], jobs_b
        code, jobs_a = _rest(port_a, '/jobs', meta_a['token'])
        assert any('isolation probe' in (j.get('text') or '')
                   for j in jobs_a), jobs_a

        # both processes still alive after interacting
        assert proc_a.poll() is None and proc_b.poll() is None
    finally:
        for p in (proc_a, proc_b):
            if p is not None:
                _stop(p)
        for m in metas:
            try:
                m['logf'].close()
            except Exception:  # noqa: BLE001
                pass
            for key in ('db', 'tok_path', 'log'):
                for suffix in ('', '-wal', '-shm'):
                    try:
                        os.remove(m[key] + suffix)
                    except OSError:
                        pass
