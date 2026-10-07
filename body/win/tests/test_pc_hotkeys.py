"""Hotkey contract tests (lane rule: NEVER register real hotkeys).

`build_bindings` is pure config->binding mapping; `register_hotkeys` is
exercised against a STUB `keyboard` module injected into sys.modules, so no
OS hook is ever installed, and every emitted frame is checked against the
PROTOCOL §3 control-action enum parsed from the doc.
"""
import json
import pathlib
import re
import sys
import types

import pytest

from body.win import hotkeys

REPO = pathlib.Path(__file__).resolve().parents[3]

CONFIG = {
    'safety': {
        'kill_switch_hotkey': 'ctrl+alt+shift+k',
        'pause_hotkey': 'ctrl+alt+p',
        'private_hotkey': 'ctrl+alt+shift+p',
    },
    'voice': {'ptt_hotkey': 'ctrl+alt+space'},
}


def protocol_control_actions():
    text = (REPO / 'docs' / 'PROTOCOL.md').read_text()
    row = re.search(r'\|\s*`control`\s*\|[^\n]+', text).group(0)
    raw = re.search(r'action:\s*([^\`]+)', row).group(1)
    actions = raw.split(',')[0].replace('\\', '').strip()
    return set(actions.split('|'))


class StubKeyboard:
    """Drop-in for the `keyboard` module: records bindings, hooks nothing."""

    def __init__(self):
        self.hotkeys = []
        self.unhooked = False

    def add_hotkey(self, chord, callback, **kwargs):
        self.hotkeys.append((chord, callback, kwargs))

    def unhook_all_hotkeys(self):
        self.unhooked = True


@pytest.fixture
def stub_keyboard(monkeypatch):
    stub = StubKeyboard()
    mod = types.ModuleType('keyboard')
    mod.add_hotkey = stub.add_hotkey
    mod.unhook_all_hotkeys = stub.unhook_all_hotkeys
    monkeypatch.setitem(sys.modules, 'keyboard', mod)
    monkeypatch.setattr(hotkeys, '_registered', False)
    return stub


def test_build_bindings_is_pure_and_covers_config():
    bindings = hotkeys.build_bindings(CONFIG)
    assert [(b['chord'], b['kind']) for b in bindings] == [
        ('ctrl+alt+shift+k', 'once'),
        ('ctrl+alt+p', 'toggle'),
        ('ctrl+alt+shift+p', 'toggle'),
    ]
    kill = bindings[0]
    assert kill['action'] == 'kill_gui' and kill['persist'] is False
    pause, priv = bindings[1], bindings[2]
    assert pause['actions'] == ['pause', 'resume'] and pause['persist'] is True
    assert priv['actions'] == ['private_on', 'private_off']
    # PTT is deliberately NOT a control frame (PROTOCOL §3 has no PTT action).
    assert all('space' not in b['chord'] for b in bindings)


def test_build_bindings_empty_config_is_safe():
    assert hotkeys.build_bindings({}) == []
    assert hotkeys.build_bindings({'safety': {}}) == []


def test_register_never_touches_os_with_stub(stub_keyboard, monkeypatch):
    frames = []
    monkeypatch.setattr(hotkeys, '_post',
                        lambda action, persist: frames.append((action, persist)))
    hotkeys.register_hotkeys(CONFIG)
    hotkeys.register_hotkeys(CONFIG)          # idempotent
    assert [c for c, _, _ in stub_keyboard.hotkeys] == [
        'ctrl+alt+shift+k', 'ctrl+alt+p', 'ctrl+alt+shift+p']

    # Fire each stub callback: momentary once, toggles alternate.
    for _, cb, _ in stub_keyboard.hotkeys:
        cb()
    for _, cb, _ in stub_keyboard.hotkeys[1:]:
        cb()
    assert frames == [
        ('kill_gui', False),
        ('pause', True), ('private_on', True),
        ('resume', True), ('private_off', True),
    ]


def test_every_frame_action_is_in_protocol_enum(stub_keyboard, monkeypatch):
    allowed = protocol_control_actions()
    assert {'pause', 'resume', 'private_on', 'private_off',
            'kill_gui'} <= allowed
    frames = []
    monkeypatch.setattr(hotkeys, '_post',
                        lambda a, p: frames.append(a))
    hotkeys.register_hotkeys(CONFIG)
    for _, cb, _ in stub_keyboard.hotkeys:
        cb()
    assert set(frames) <= allowed, set(frames) - allowed


def test_toggle_frame_envelope_via_queue(monkeypatch):
    async def run():
        import asyncio
        hotkeys.set_loop(asyncio.get_running_loop())
        while not hotkeys._control_queue.empty():
            hotkeys._control_queue.get_nowait()
        toggler = hotkeys._toggler(['pause', 'resume'], True)
        toggler(); toggler(); toggler()
        out = []
        for _ in range(3):
            out.append(await asyncio.wait_for(hotkeys._control_queue.get(),
                                              timeout=1))
        return out

    frames = asyncio_run(run())
    assert frames == [
        {'type': 'control', 'v': 1, 'action': 'pause', 'persist': True},
        {'type': 'control', 'v': 1, 'action': 'resume', 'persist': True},
        {'type': 'control', 'v': 1, 'action': 'pause', 'persist': True},
    ]
    # Machine-checkable envelope for the conformance suite.
    assert json.dumps(frames[0]).startswith('{')


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
