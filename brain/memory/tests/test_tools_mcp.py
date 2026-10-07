"""MCP adapter tests: config validation, fail-closed allow-list, dynamic
registration with TIGHTENED schemas, confirm/risky, timeouts (fake stdio
server child — killed in teardown, zero orphans per Rule 14)."""
import sys
from pathlib import Path

import pytest

from brain.tools import mcp as m

_FAKE = Path(__file__).resolve().parent / 'fake_mcp_server.py'


def _srv(name='demo', allow=('echo', 'lax', 'weird'), mode=None,
         timeout_s=5.0, **over):
    cmd = [sys.executable, str(_FAKE)]
    if mode:
        cmd.append(mode)
    entry = {'name': name, 'transport': 'stdio', 'command': cmd,
             'allow': list(allow), 'timeout_s': timeout_s}
    entry.update(over)
    return entry


@pytest.fixture(autouse=True)
def _mcp_env(monkeypatch):
    from brain import tools as reg
    before = set(reg._registry)
    yield
    m.shutdown_clients()                      # Rule 14: kill every child
    m._inventory.clear()
    m._booted = False
    for name in set(reg._registry) - before:  # dynamic tools never leak
        reg._registry.pop(name, None)
        reg._META.pop(name, None)


def _patch_cfg(monkeypatch, servers, extra=None):
    extra = extra or {}
    def _cfg(k, d):
        if k == 'mcp.servers':
            return servers
        return extra.get(k, d)
    monkeypatch.setattr(m, '_cfg', _cfg)


# ---- config validation ------------------------------------------------------
def test_config_validation_rejects_bad_entries(monkeypatch):
    bad = [
        'not-a-mapping',
        {'name': 'BAD NAME', 'command': ['x']},
        {'name': 'http1', 'transport': 'http', 'command': ['x']},
        {'name': 'cmd1', 'command': 'single string'},
        {'name': 'cmd2', 'command': []},
        {'name': 'alw1', 'command': ['x'], 'allow': 'everything'},
        {'name': 'cfm1', 'command': ['x'], 'confirm': 'yes'},
    ]
    good = _srv('ok1')
    _patch_cfg(monkeypatch, bad + [good])
    valid, errors = m._servers()
    assert [c['name'] for c in valid] == ['ok1']
    assert len(errors) == len(bad)            # every bad entry reported


def test_empty_config_is_noop_and_list_explains(monkeypatch):
    _patch_cfg(monkeypatch, [])
    out = m.mcp_list()
    assert 'no MCP servers configured' in out
    assert 'model cannot' in out              # documents the security rule


# ---- e2e over the fake stdio server ----------------------------------------
def test_register_call_and_tightened_schemas(monkeypatch):
    from brain import tools as reg
    _patch_cfg(monkeypatch, [_srv('demo')])
    out = m.refresh(force=True)
    assert 'mcp_demo_echo' in out['registered']
    assert 'mcp_demo_lax' in out['registered']
    # weird (un-tightenable) tool: skipped LOUDLY, never registered
    assert not any(k.startswith('mcp_demo_weird') for k in reg.names())
    assert 'weird' in str(out['errors'])

    meta = reg.describe('mcp_demo_echo')
    assert meta['risky'] is True              # default: unknown behavior
    s = meta['schema']
    assert s['type'] == 'object' and s['additionalProperties'] is False
    assert s['properties']['text']['type'] == 'string'
    assert reg.describe('mcp_demo_lax')['schema']['required'] == []      # tightened
    assert reg.describe('mcp_demo_lax')['schema']['additionalProperties'] is False

    # live call through the child process
    assert reg.get('mcp_demo_echo')(text='hi') == 'echo: hi'
    assert reg.get('mcp_demo_lax')(x='1') == 'lax 1'
    # tightened schema is enforced at the registry level
    with pytest.raises(reg.BadToolArgs):
        reg.validate_args('mcp_demo_echo', {'text': 'x', 'extra': 1})
    with pytest.raises(reg.BadToolArgs):
        reg.validate_args('mcp_demo_echo', {'text': 42})


def test_allow_list_is_fail_closed(monkeypatch):
    from brain import tools as reg
    _patch_cfg(monkeypatch, [_srv('closed', allow=())])
    out = m.refresh(force=True)
    assert out['registered'] == []            # nothing callable
    assert not any(n.startswith('mcp_closed_') for n in reg.names())
    listing = m.mcp_list()
    assert 'allow-list is fail-closed' in listing
    assert '2 tool(s) hidden' in listing      # echo+lax valid but hidden (weird is schema-rejected)


def test_confirm_overrides_relax_risky(monkeypatch):
    from brain import tools as reg
    _patch_cfg(monkeypatch, [_srv('cfm', confirm={'echo': False})])
    m.refresh(force=True)
    assert reg.describe('mcp_cfm_echo')['risky'] is False   # USER config only
    assert reg.describe('mcp_cfm_lax')['risky'] is True     # default stays True


def test_timeout_is_recorded_and_other_servers_survive(monkeypatch):
    _patch_cfg(monkeypatch, [
        _srv('hangy', mode='hang', timeout_s=1.0),
        _srv('fine'),
    ])
    out = m.refresh(force=True)
    assert 'hangy' in out['errors']
    assert 'timeout' in out['errors']['hangy']           # recorded, not fatal
    assert 'mcp_fine_echo' in out['registered']          # per-server isolation
    listing = m.mcp_list()
    assert 'ERROR' in listing and 'mcp_fine_echo' in listing


def test_result_capping_and_iserror(monkeypatch):
    from brain import tools as reg
    _patch_cfg(monkeypatch, [_srv('cap', allow=('*', ))],
               extra={'mcp.max_result_chars': 40})
    m.refresh(force=True)
    out = reg.get('mcp_cap_echo')(text='y' * 500)
    assert '[truncated]' in out and len(out) < 80
    # server-reported error -> RuntimeError (job feedback, not silent text)
    with pytest.raises(RuntimeError) as e:
        m._call_tool('cap', 'nonexistent', {})
    assert 'reported an error' in str(e.value)


def test_call_rejects_unconfigured_and_disallowed(monkeypatch):
    _patch_cfg(monkeypatch, [_srv('one', allow=('echo',))])
    m.refresh(force=True)
    with pytest.raises(m.McpError):
        m._call_tool('ghost', 'echo', {})
    with pytest.raises(m.McpError) as e:
        m._call_tool('one', 'lax', {})         # exists but NOT allow-listed
    assert 'allow-list' in str(e.value)


def test_shutdown_kills_children(monkeypatch):
    _patch_cfg(monkeypatch, [_srv('killme')])
    m.refresh(force=True)
    cli = m._clients.get('killme')
    assert cli is not None and cli.alive()
    m.shutdown_clients()
    assert not cli.alive()                     # child terminated (Rule 14)
    assert m._clients == {}


def test_static_mcp_tools_have_no_config_surface():
    """The model can list/refresh — never add or configure a server."""
    from brain import tools as reg
    for name in ('mcp_list', 'mcp_refresh'):
        s = reg.describe(name)['schema']
        assert s['type'] == 'object'
        assert s['properties'] == {}          # ZERO parameters
        assert s['required'] == []
        assert s['additionalProperties'] is False
