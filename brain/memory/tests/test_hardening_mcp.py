"""MCP stdio orphan/failure-mode tests (wave-4 hardening).

Proves: dead-handshake and post-handshake-death leave NO cached client and NO
alive child; a wedged (timeout) child is evicted+closed; a KILLED child is
transparently respawned on the next call; per-server failures stay isolated.
Rule 14: every recorded child is killed in teardown.
"""
import sys
from pathlib import Path

import pytest

from brain.tools import mcp as m

_FAKE = Path(__file__).resolve().parent / 'fake_mcp_server.py'


def _srv(name, mode=None, timeout_s=5.0, allow=('echo',)):
    cmd = [sys.executable, str(_FAKE)]
    if mode:
        cmd.append(mode)
    return {'name': name, 'transport': 'stdio', 'command': cmd,
            'allow': list(allow), 'timeout_s': timeout_s}


@pytest.fixture(autouse=True)
def _mcp_env(monkeypatch):
    from brain import tools as reg
    before = set(reg._registry)
    instances = []
    real = m.StdioClient

    class _Recording(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            instances.append(self)

    monkeypatch.setattr(m, 'StdioClient', _Recording)
    yield instances
    m.shutdown_clients()
    m._inventory.clear()
    m._booted = False
    for inst in instances:                  # belt+braces: never leave one alive
        try:
            if inst.alive():
                inst.close()
        except Exception:  # noqa: BLE001
            pass
    for name in set(reg._registry) - before:
        reg._registry.pop(name, None)
        reg._META.pop(name, None)


def _patch_cfg(monkeypatch, servers):
    monkeypatch.setattr(m, '_cfg',
                        lambda k, d: servers if k == 'mcp.servers' else d)


def test_dead_handshake_reaps_child(monkeypatch, _mcp_env):
    _patch_cfg(monkeypatch, [_srv('dead', mode='diefast')])
    out = m.refresh(force=True)
    assert 'dead' in out['errors']          # recorded, not fatal
    assert 'dead' not in m._clients         # never cached
    assert _mcp_env, 'client object was created'
    assert _mcp_env[0]._proc.poll() is not None   # dead + reaped (no zombie)


def test_death_after_initialize_recorded(monkeypatch, _mcp_env):
    _patch_cfg(monkeypatch, [_srv('flaky', mode='dieafterinit')])
    out = m.refresh(force=True)
    assert 'flaky' in out['errors']
    assert 'flaky' not in m._clients
    assert _mcp_env[0]._proc.poll() is not None


def test_timeout_evicts_and_kills_wedged_child(monkeypatch, _mcp_env):
    _patch_cfg(monkeypatch, [
        _srv('hangy', mode='hang', timeout_s=1.0),
        _srv('fine'),
    ])
    out = m.refresh(force=True)
    assert 'timeout' in out['errors'].get('hangy', '')
    assert 'mcp_fine_echo' in out['registered']    # isolation
    assert 'hangy' not in m._clients               # wedged child EVICTED...
    hang = next(c for c in _mcp_env if c.argv[-1] == 'hang')
    assert hang._proc.poll() is not None           # ...and KILLED (no orphan)


def test_killed_child_respawns_on_next_call(monkeypatch, _mcp_env):
    from brain import tools as reg
    _patch_cfg(monkeypatch, [_srv('live')])
    out = m.refresh(force=True)
    assert 'mcp_live_echo' in out['registered']
    first = m._clients['live']
    first._proc.kill()
    first._proc.wait(timeout=5)
    # the next call must transparently respawn instead of failing forever
    assert reg.get('mcp_live_echo')(text='again') == 'echo: again'
    second = m._clients['live']
    assert second is not first and second.alive()


def test_failure_modes_never_leak_dynamic_tools(monkeypatch, _mcp_env):
    from brain import tools as reg
    _patch_cfg(monkeypatch, [_srv('dead', mode='diefast')])
    m.refresh(force=True)
    assert not any(n.startswith('mcp_dead_') for n in reg.names())
