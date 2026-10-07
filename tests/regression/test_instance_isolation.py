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
    text = (REPO / 'docs' / 'INTERFACES.md').read_text(encoding='utf-8')
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
    assert len(instances) >= 11, instances   # main + every lane + sanctioned extras
    assert instances.count('main') == 1
    main = next(r for r in rows if r[0].startswith('main'))

    # CROSS-SOURCE EQUALITY (approved brain-core request
    # brain-core__to__qa-security__shadow-row-count, decision 2026-10-07):
    # the §d doc table must list EXACTLY the instances the code derives from
    # brain/config.py::_INSTANCES — sturdier than a count bump: any approved
    # new row (e.g. `shadow`, port 8911) must land in BOTH or this goes red,
    # and it is green across the merge boundary either way.
    from brain.config import _INSTANCES
    code_instances = {name for name, _port, _idx in _INSTANCES}
    assert set(instances) == code_instances, (
        f'doc/code instance mismatch: doc-only='
        f'{sorted(set(instances) - code_instances)} code-only='
        f'{sorted(code_instances - set(instances))}')

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
        code_port = dict((n, p) for n, p, _i in _INSTANCES).get(inst)
        assert code_port is not None and int(r[1]) == code_port, \
            (inst, r[1], code_port)   # table port == code-derived port
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
               if p.exists() and 'RAPHAEL_INSTANCE' not in p.read_text(encoding='utf-8')]
    assert not missing, f'RAPHAEL_INSTANCE not referenced in: {missing}'


# ---- (3) two real instances ----------------------------------------------
# Shared spawn/health/rest/stop helpers live in the harness (used by the
# crash-recovery resilience drill too).
from harness.instance_proc import (free_port as _free_port,  # noqa: F401
                                   spawn as _spawn,
                                   log_tail as _log_tail,
                                   health as _health,
                                   rest as _rest,
                                   stop as _stop)


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
