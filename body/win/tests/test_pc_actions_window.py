"""Window, system (clipboard/media/volume/brightness/notify), UIA and
screenshot actions against the fake backend."""
import base64

import pytest

from body.win import actions, automation

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------------ window
async def test_window_list_has_foreground_flag(actlog, fake):
    fake.foreground_window = fake.windows[1]
    res = await actions.dispatch('window', {'op': 'list'}, lock=True, job='j1')
    assert res['ok']
    assert res['result']['count'] == 2
    flags = {w['hwnd']: w['foreground'] for w in res['result']['windows']}
    assert flags == {1001: False, 1002: True}


async def test_window_focus_by_title_and_hwnd(actlog, fake):
    res = await actions.dispatch('window',
                                 {'op': 'focus', 'title': 'YouTube - Chromium'},
                                 lock=True, job='j2')
    assert res['ok'] and res['result']['focused'] == 1002
    assert fake.calls('focus_window') == [(1002,)]

    res = await actions.dispatch('window', {'op': 'focus', 'hwnd': 1001},
                                 lock=True, job='j3')
    assert res['ok'] and res['result']['focused'] == 1001


async def test_window_target_not_found(actlog, fake):
    res = await actions.dispatch('window',
                                 {'op': 'minimize', 'title': 'Ghost Window'},
                                 lock=True, job='j4')
    assert res['ok'] is False and 'window not found' in res['error']
    assert res['error'].startswith('E_INTERNAL')
    assert fake.calls('show_window') == []


async def test_window_snap_and_show_validation(actlog, fake):
    res = await actions.dispatch('window',
                                 {'op': 'snap', 'hwnd': 1001, 'zone': 'left'},
                                 lock=True, job='j5')
    assert res['ok'] and fake.calls('snap_window') == [(1001, 'left')]

    for args in ({'op': 'snap', 'hwnd': 1001},            # zone missing
                 {'op': 'snap', 'hwnd': 1001, 'zone': 'north'},
                 {'op': 'focus'},                          # no target
                 {'op': 'list', 'hwnd': 1001},             # list takes nothing
                 {'op': 'explode'},
                 {'op': 'minimize', 'hwnd': -5}):
        res = await actions.dispatch('window', args, lock=True, job='j6')
        assert res['ok'] is False and res['error'].startswith('E_BAD_MSG'), args
    assert fake.calls('snap_window') == [(1001, 'left')]
    assert fake.calls('show_window') == []


async def test_list_windows_and_foreground_info(actlog, fake):
    res = await actions.dispatch('list_windows', {}, job='j7')
    assert res['ok'] and res['result']['count'] == 2
    assert {'hwnd', 'title', 'process', 'pid', 'rect', 'foreground'} <= \
        set(res['result']['windows'][0])

    res = await actions.dispatch('foreground_info', {}, job='j8')
    assert res['ok']
    win = res['result']['window']
    assert win['hwnd'] == 1001 and win['process'] == 'notepad.exe'
    assert win['foreground'] is True

    res = await actions.dispatch('foreground_info', {'x': 1}, job='j9')
    assert res['ok'] is False and 'unknown field' in res['error']


# ------------------------------------------------------------------ system
async def test_clipboard_write_read_roundtrip(actlog, fake):
    res = await actions.dispatch('clipboard',
                                 {'op': 'write', 'text': 'hello world'},
                                 job='j10')
    assert res['ok'] and res['result'] == {'written': 11}
    res = await actions.dispatch('clipboard', {'op': 'read'}, job='j11')
    assert res['ok'] and res['result'] == 'hello world'   # legacy string shape


async def test_clipboard_validation(actlog, fake):
    assert (await actions.dispatch('clipboard', {'op': 'read'}, job='j12'))['ok']
    assert (await actions.dispatch('clipboard',
                                   {'op': 'write', 'text': ''},
                                   job='j13'))['ok']          # empty allowed
    for args in ({'op': 'write'}, {'op': 'read', 'text': 'x'},
                 {'op': 'delete'}, {'op': 'write', 'text': 5}):
        res = await actions.dispatch('clipboard', args, job='j14')
        assert res['ok'] is False, args


async def test_volume_brightness_ranges(actlog, fake):
    res = await actions.dispatch('volume', {'level': 42}, job='j15')
    assert res['ok'] and fake.volume == 42
    res = await actions.dispatch('brightness', {'level': 0}, job='j16')
    assert res['ok'] and fake.brightness == 0
    for args in ({'level': 101}, {'level': -1}, {'level': '50'},
                 {'level': True}, {}):
        assert (await actions.dispatch('volume', args, job='j17'))['ok'] is False


async def test_media_ops_and_lock(actlog, fake):
    res = await actions.dispatch('media', {'op': 'play_pause'}, lock=True,
                                 job='j18')
    assert res['ok'] and fake.calls('media_key') == [('play_pause',)]
    assert not automation.lock_held()
    res = await actions.dispatch('media', {'op': 'eject'}, lock=True, job='j19')
    assert res['ok'] is False and 'must be one of' in res['error']


async def test_notify_passes_text(actlog, fake):
    res = await actions.dispatch('notify', {'text': 'Timer done'}, job='j20')
    assert res['ok'] and fake.calls('notify') == [('Timer done',)]
    res = await actions.dispatch('notify', {'text': 'x' * 501}, job='j21')
    assert res['ok'] is False and 'exceeds' in res['error']


# ---------------------------------------------------------------------- uia
_UIA_OK = {'op': 'find', 'element': {'name': 'OK'}}


async def test_uia_find_and_read(actlog, fake):
    res = await actions.dispatch('uia', dict(_UIA_OK), lock=True, job='j22')
    assert res['ok'] and res['result'] == {'found': False}

    fake.uia_data['find'] = {'name': 'OK', 'control_type': 'Button'}
    res = await actions.dispatch('uia', dict(_UIA_OK), lock=True, job='j23')
    assert res['ok'] and res['result']['name'] == 'OK'

    res = await actions.dispatch('uia',
                                 {'op': 'read',
                                  'element': {'name': 'OK'}},
                                 lock=True, job='j24')
    assert res['ok'] and 'sample text' in res['result']['texts']


async def test_uia_validation(actlog, fake):
    bad = [
        {'op': 'hover', 'element': {'name': 'x'}},
        {'op': 'find'},                                       # no element
        {'op': 'find', 'element': {}},                        # no criteria
        {'op': 'find', 'element': {'index': 0}},              # index only
        {'op': 'find', 'element': {'name': 'x', 'bogus': 1}}, # extra key
        {'op': 'find', 'element': {'control_type': 'Lever'}}, # not a ControlType
        {'op': 'find', 'element': {'name': 'x'}, 'args': {'timeout_s': 60}},
        {'op': 'type', 'element': {'name': 'x'}},             # no text
        {'op': 'tree', 'element': {'name': 'x'}, 'args': {'depth': 9}},
        {'op': 'click', 'element': {'name': 'x'}, 'args': {'button': 'middle'}},
    ]
    for args in bad:
        res = await actions.dispatch('uia', args, lock=True, job='j25')
        assert res['ok'] is False and res['error'].startswith('E_BAD_MSG'), args
    assert fake.calls('uia_find') == []


async def test_uia_type_and_tree(actlog, fake):
    fake.uia_data['find'] = {'name': 'Field', 'control_type': 'Edit'}
    res = await actions.dispatch(
        'uia', {'op': 'type', 'element': {'control_type': 'edit'},
                'args': {'text': 'hi', 'clear': True}},
        lock=True, job='j26')
    assert res['ok']
    sel, text, clear, timeout = fake.calls('uia_type')[0]
    assert text == 'hi' and clear is True and timeout == 5.0
    assert sel == {'control_type': 'edit'}

    res = await actions.dispatch(
        'uia', {'op': 'tree', 'element': {'name': 'Field'},
                'args': {'depth': 2}}, lock=True, job='j27')
    assert res['ok'] and res['result']['truncated'] is False


# --------------------------------------------------------------- screenshot
async def test_screenshot_shape_and_passthrough(actlog, fake):
    res = await actions.dispatch('screenshot', {'max_px': 640, 'quality': 55},
                                 job='j28')
    assert res['ok']
    raw = base64.b64decode(res['result']['b64'])
    assert raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9')
    assert res['result']['bytes'] == len(raw)
    assert fake.calls('capture') == [(640, 55)]


async def test_screenshot_validation(actlog, fake):
    res = await actions.dispatch('screenshot', {'max_px': 10}, job='j29')
    assert res['ok'] is False and 'between 64 and 4096' in res['error']
    res = await actions.dispatch('screenshot', {'quality': 96}, job='j30')
    assert res['ok'] is False and 'between 10 and 95' in res['error']
    res = await actions.dispatch('screenshot', {'max_px': True}, job='j31')
    assert res['ok'] is False and 'integer' in res['error']
    assert fake.calls('capture') == []
