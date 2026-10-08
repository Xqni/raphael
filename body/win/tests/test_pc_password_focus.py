"""computer-use focused-password-flag (docs/requests/computer-use__
to__pc-control__focused-password-flag.md): foreground_info carries
`focused_is_password` (False when unknown) and uia descriptors carry
true-only `is_password`/`focused` flags."""
from types import SimpleNamespace

import pytest

from body.win import actions, automation, winlayer

pytestmark = pytest.mark.asyncio


async def test_foreground_info_reports_password_focus(actlog, fake):
    res = await actions.dispatch('foreground_info', {}, job='j1')
    assert res['ok']
    assert set(res['result']) == {'window', 'focused_is_password'}
    assert res['result']['focused_is_password'] is False   # default
    assert res['result']['window']['title'] == 'Untitled - Notepad'

    fake.focused_is_password_value = True
    res = await actions.dispatch('foreground_info', {}, job='j2')
    assert res['result']['focused_is_password'] is True

    fake.focused_is_password_value = None          # unknown -> False
    res = await actions.dispatch('foreground_info', {}, job='j3')
    assert res['result']['focused_is_password'] is False
    assert not automation.lock_held()


async def test_password_focus_backend_failure_is_truthful(actlog, fake):
    fake.fail_methods.add('focused_is_password')
    res = await actions.dispatch('foreground_info', {}, job='j4')
    assert res['ok'] is False and res['error'].startswith('E_INTERNAL')
    fake.fail_methods.discard('focused_is_password')
    ok = await actions.dispatch('foreground_info', {}, job='j5')
    assert ok['ok'], ok


async def test_uia_flags_true_only_and_unknown_safe():
    both = winlayer.uia_flags(SimpleNamespace(_element=SimpleNamespace(
        CurrentIsPassword=True, CurrentHasKeyboardFocus=True)))
    assert both == {'is_password': True, 'focused': True}

    clean = winlayer.uia_flags(SimpleNamespace(_element=SimpleNamespace(
        CurrentIsPassword=False, CurrentHasKeyboardFocus=False)))
    assert clean == {}, 'false values must be ABSENT (consumer default)'

    no_el = winlayer.uia_flags(SimpleNamespace(name='x'))
    assert no_el == {}

    class Boom:
        @property
        def CurrentIsPassword(self):
            raise RuntimeError('detached')

    assert winlayer.uia_flags(SimpleNamespace(_element=Boom())) == {}


async def test_uia_descriptors_carry_password_flag(actlog, fake):
    fake.uia_data['find'] = {'name': 'Password', 'control_type': 'Edit',
                             'is_password': True, 'focused': True}
    res = await actions.dispatch('uia',
                                 {'op': 'tree', 'element': {'name': 'Field'},
                                  'args': {'depth': 1}},
                                 lock=True, job='j6')
    assert res['ok'] and res['result']['is_password'] is True
    assert res['result']['focused'] is True

    read = await actions.dispatch('uia',
                                  {'op': 'read', 'element': {'name': 'Field'}},
                                  lock=True, job='j7')
    assert read['ok'] and read['result']['is_password'] is True
    # clean nodes simply lack the keys (backward compatible both ways)
    fake.uia_data['find'] = {'name': 'Plain', 'control_type': 'Text'}
    clean = await actions.dispatch(
        'uia', {'op': 'read', 'element': {'name': 'Plain'}},
        lock=True, job='j8')
    assert 'is_password' not in clean['result']
    assert 'focused' not in clean['result']
