"""Wave 5U §5.4 P0: every tools-memory tool carries an explicit confirm
class (P0.2 fail-closed: no class -> confirm).

Coverage is DERIVED from each package's SPECS dict — a future tool added
without a tag fails this test by construction.
"""
import pytest

from brain import tools as reg

# name -> class (charter docs/USEFUL-NOW-PLAN.md §5.4 + request
# tools-memory__to__integrator__wave5u-confirm-classes.md for new names)
EXPECTED = {
    # web_* -> web_fetch (existing auto class)
    'web_fetch': 'web_fetch', 'web_search': 'web_fetch',
    'web_summarize': 'web_fetch',
    # files
    'file_search': 'read_only', 'file_read': 'read_only',
    'file_write': 'files_write', 'file_trash': 'delete_files',
    'file_restore': 'files_write',
    # shell
    'shell': 'system_command', 'shell_list': 'read_only',
    # github (per existing risk: status=read, push=publish)
    'github_status': 'read_only', 'github_push': 'web_publish',
    # schedule (writers=reversible auto, readers=read_only)
    'timer_set': 'schedule', 'timer_cancel': 'schedule',
    'reminder_set': 'schedule', 'schedule_set': 'schedule',
    'schedule_cancel': 'schedule',
    'timer_list': 'read_only', 'schedule_list': 'read_only',
    # mcp static
    'mcp_list': 'read_only', 'mcp_refresh': 'mcp_tool',
}

# every class name this lane may use (existing config classes + the 5 new
# ones requested from the integrator) — drift guard vs the request file
KNOWN_CLASSES = {
    'web_fetch', 'files_write', 'delete_files',        # config (existing)
    'read_only', 'schedule', 'system_command',         # requested new (auto/confirm)
    'web_publish', 'mcp_tool',                          # requested new (confirm)
}


def _my_tools() -> set:
    """Derive my lane's tool names from the package SPECS dicts."""
    import importlib
    names = set()
    for ns in ('web', 'files', 'shell', 'github', 'schedule', 'mcp'):
        mod = importlib.import_module(f'brain.tools.{ns}')
        names |= set(getattr(mod, 'SPECS', {}))
    return names


def test_every_lane_tool_has_an_explicit_confirm_class():
    """P0.2: no class -> fail-closed confirm. Reads must be tagged too."""
    missing = [n for n in sorted(_my_tools())
               if not reg.describe(n).get('confirm')]
    assert missing == [], f'untagged tools (would fail closed): {missing}'


def test_charter_class_mapping_exact():
    for name, cls in EXPECTED.items():
        meta = reg.describe(name)
        assert meta.get('confirm') == cls, \
            f'{name}: expected {cls!r}, got {meta.get("confirm")!r}'


def test_class_vocabulary_matches_the_request_file():
    used = {reg.describe(n).get('confirm') for n in _my_tools()}
    assert used <= KNOWN_CLASSES, used - KNOWN_CLASSES


def test_risky_tools_always_carry_a_class():
    """pc-control's guard: a risky tool without a confirm category would
    silently bypass the gate — refuse (test) to load such a registration."""
    for name in sorted(_my_tools()):
        if reg.describe(name).get('risky'):
            assert reg.describe(name).get('confirm'), f'risky untagged: {name}'
    # and the charter's risky trio maps to the HIGH classes
    assert reg.describe('file_trash')['confirm'] == 'delete_files'
    assert reg.describe('shell')['confirm'] == 'system_command'
    assert reg.describe('github_push')['confirm'] == 'web_publish'


def test_mcp_wrapped_tools_default_to_confirm(monkeypatch):
    """Charter: MCP wrapped tools default confirm unless config marks a
    read-only class (mapping = Wave-C task 5; default NOW = mcp_tool)."""
    import sys as _sys
    from pathlib import Path
    from brain.tools import mcp as m
    fake = Path(__file__).resolve().parent / 'fake_mcp_server.py'
    cfg = [{'name': 'demo', 'transport': 'stdio',
            'command': [_sys.executable, str(fake)],
            'allow': ['echo', 'lax'], 'timeout_s': 10.0}]
    monkeypatch.setattr(m, '_cfg',
                        lambda k, d: cfg if k == 'mcp.servers' else d)
    try:
        out = m.refresh(force=True)
        assert 'mcp_demo_echo' in out['registered']
        assert reg.describe('mcp_demo_echo')['confirm'] == 'mcp_tool'
        assert reg.describe('mcp_demo_lax')['confirm'] == 'mcp_tool'
    finally:
        m.shutdown_clients()
        m._inventory.clear()
        m._booted = False
        for n in ('mcp_demo_echo', 'mcp_demo_lax'):
            reg._registry.pop(n, None)
            reg._META.pop(n, None)
