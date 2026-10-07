"""`input` action: atomic ordering, modifier release on failure, mouse
failsafe, strict key vocabulary."""
import pytest

from body.win import actions, act_input, automation
from body.win.winlayer import KEYMAP

pytestmark = pytest.mark.asyncio


async def test_atomic_order_mouse_then_text_then_keys(actlog, fake):
    res = await actions.dispatch(
        'input',
        {'mouse': {'action': 'click', 'x': 500, 'y': 400},
         'text': 'hello', 'clear_first': True,
         'keys': ['enter']},
        lock=True, job='j1')
    assert res['ok'], res
    names = [e[0] for e in fake.events]
    # mouse first, then the clear chord, then typing, then the final chord
    assert names.index('mouse_click') < names.index('type_text') < \
        names.index('key_down', names.index('type_text'))
    assert fake.calls('type_text') == [('hello',)]
    assert res['result'] == {'units': 3, 'keys': 1, 'typed_chars': 5}
    assert not automation.lock_held()


async def test_chord_presses_modifiers_then_final_and_releases(actlog, fake):
    res = await actions.dispatch('input', {'keys': ['ctrl+shift+s']},
                                 lock=True, job='j2')
    assert res['ok']
    downs = [a[0] for a in fake.calls('key_down')]
    ups = [a[0] for a in fake.calls('key_up')]
    assert downs == [KEYMAP['ctrl'], KEYMAP['shift'], KEYMAP['s']]
    # final key released first, then modifiers in reverse order
    assert ups == [KEYMAP['s'], KEYMAP['shift'], KEYMAP['ctrl']]


async def test_modifier_never_stuck_when_final_key_fails(actlog, fake):
    fake.fail_key_down_vk = KEYMAP['s']
    res = await actions.dispatch('input', {'keys': ['ctrl+shift+s']},
                                 lock=True, job='j3')
    assert res['ok'] is False and res['error'].startswith('E_INTERNAL')
    downs = [a[0] for a in fake.calls('key_down')]
    ups = [a[0] for a in fake.calls('key_up')]
    assert downs == [KEYMAP['ctrl'], KEYMAP['shift'], KEYMAP['s']]
    # both modifiers were released despite the failure
    assert ups == [KEYMAP['shift'], KEYMAP['ctrl']]
    assert not automation.lock_held()


async def test_failsafe_corner_aborts_before_injecting(actlog, fake, monkeypatch):
    monkeypatch.setattr(act_input, '_FAILSAFE', True)
    fake.cursor = (2, 2)
    res = await actions.dispatch('input', {'keys': ['enter']}, lock=True,
                                 job='j4')
    assert res['ok'] is False and 'failsafe' in res['error']
    assert fake.calls('key_down') == [], 'no input may be injected'


async def test_failsafe_disabled_allows_corner(actlog, fake, monkeypatch):
    monkeypatch.setattr(act_input, '_FAILSAFE', False)
    fake.cursor = (2, 2)
    res = await actions.dispatch('input', {'keys': ['enter']}, lock=True,
                                 job='j5')
    assert res['ok'] is True


async def test_unknown_key_rejected_before_lock(actlog, fake):
    res = await actions.dispatch('input', {'keys': ['ctrl+notakey']},
                                 lock=True, job='j6')
    assert res['ok'] is False and 'unknown key' in res['error']
    assert fake.calls('key_down') == []


async def test_modifier_only_chord_rejected(actlog, fake):
    res = await actions.dispatch('input', {'keys': ['ctrl']}, lock=True,
                                 job='j7')
    assert res['ok'] is False and 'non-modifier' in res['error']


async def test_input_requires_one_payload(actlog, fake):
    res = await actions.dispatch('input', {}, lock=True, job='j8')
    assert res['ok'] is False and 'one of' in res['error']


async def test_mouse_drag_releases_button_even_if_move_fails(actlog, fake):
    # Cursor starts away from the corner, then parks IN the corner once the
    # button is down -> the mid-drag failsafe must abort AND release.
    real_position = fake.mouse_position

    def tricky_position():
        fake.events.append(('mouse_position', ()))
        if any(name == 'mouse_down' for name, _ in fake.events):
            return (5, 5)
        return (100, 100)

    fake.mouse_position = tricky_position
    try:
        res = await actions.dispatch(
            'input', {'mouse': {'action': 'drag', 'x': 300, 'y': 300,
                                'steps': 5}},
            lock=True, job='j9')
        assert res['ok'] is False and 'failsafe' in res['error']
        assert fake.calls('mouse_down') == [('left',)]
        assert fake.calls('mouse_up') == [('left',)], 'button must always release'
        assert fake.calls('mouse_move') == [], 'aborted before moving'
    finally:
        fake.mouse_position = real_position


async def test_mouse_validation_ranges(actlog, fake):
    bad = [
        {'mouse': {'action': 'fly'}},
        {'mouse': {'action': 'move', 'x': 1}},           # y missing
        {'mouse': {'action': 'drag'}},                   # no target
        {'mouse': {'action': 'scroll', 'amount': 999}},  # out of range
        {'mouse': {'action': 'click', 'button': 'side'}},
        {'mouse': {'action': 'move', 'x': 1, 'y': 2, 'z': 3}},  # extra key
    ]
    for args in bad:
        res = await actions.dispatch('input', args, lock=True, job='j10')
        assert res['ok'] is False and res['error'].startswith('E_BAD_MSG'), args
    assert fake.calls('mouse_move') == []
    assert fake.calls('mouse_click') == []


async def test_text_control_chars_rejected(actlog, fake):
    res = await actions.dispatch('input', {'text': 'a\x07b'}, lock=True,
                                 job='j11')
    assert res['ok'] is False and 'control characters' in res['error']
    assert fake.calls('type_text') == []
