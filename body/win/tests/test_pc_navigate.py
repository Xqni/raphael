"""P0 UX [42] navigate-in-place: reuse the existing browser tab via the
input-lock path (Ctrl+L + type + Enter); first-ever open launches.
Fixtures drive FakeWin (no real input, no sockets)."""
import pytest

from body.win import actions, automation
from body.win.winlayer import KEYMAP

pytestmark = pytest.mark.asyncio

URL = 'https://www.youtube.com/results?search_query=pewdiepie'
CHROME = {'hwnd': 2001, 'title': 'New Tab', 'pid': 30, 'process': 'chrome.exe',
          'rect': {'left': 0, 'top': 0, 'right': 900, 'bottom': 700,
                   'width': 900, 'height': 700},
          'visible': True}
NOTEPAD = {'hwnd': 1001, 'title': 'Untitled - Notepad', 'pid': 10,
           'process': 'notepad.exe',
           'rect': {'left': 0, 'top': 0, 'right': 800, 'bottom': 600,
                    'width': 800, 'height': 600},
           'visible': True}


async def test_reuse_foreground_browser_in_place(actlog, fake):
    fake.windows = [NOTEPAD, CHROME]
    fake.foreground_window = CHROME          # browser already focused
    res = await actions.dispatch('navigate_url', {'url': URL}, lock=True,
                                 job='j1')
    assert res['ok'] and res['result'] == {'mode': 'reuse', 'hwnd': 2001,
                                           'process': 'chrome.exe'}
    # in-place: Ctrl+L, typed URL, Enter — no new tab spawned
    assert fake.calls('open_url') == [], 'reuse must never shell-open'
    assert fake.calls('focus_window') == [], 'foreground browser needs no refocus'
    downs = [a[0] for a in fake.calls('key_down')]
    assert downs[:2] == [KEYMAP['ctrl'], KEYMAP['l']]
    assert downs[-1] == KEYMAP['enter']
    assert fake.calls('type_text') == [(URL,)]
    assert not automation.lock_held()


async def test_reuse_focuses_visible_browser_first(actlog, fake):
    fake.windows = [NOTEPAD, CHROME]
    fake.foreground_window = NOTEPAD        # browser exists but not focused
    res = await actions.dispatch('navigate_url', {'url': URL}, lock=True,
                                 job='j2')
    assert res['ok'] and res['result']['mode'] == 'reuse'
    assert fake.calls('focus_window') == [(2001,)]
    assert fake.calls('open_url') == []
    assert fake.calls('type_text') == [(URL,)]


async def test_launch_first_when_no_browser_exists(actlog, fake):
    fake.windows = [NOTEPAD]                 # no browser anywhere
    fake.foreground_window = NOTEPAD
    res = await actions.dispatch('navigate_url', {'url': URL}, lock=True,
                                 job='j3')
    assert res['ok'] and res['result'] == {'mode': 'launch', 'opened': URL}
    assert fake.calls('open_url') == [(URL,)]
    assert fake.calls('key_down') == [], 'launch path must not inject input'


async def test_scheme_guard_shares_launch_url_rules(actlog, fake):
    res = await actions.dispatch('navigate_url',
                                 {'url': 'javascript:alert(1)'}, lock=True,
                                 job='j4')
    assert res['ok'] is False and res['error'].startswith('E_BAD_MSG')
    assert fake.events == []


async def test_needs_lock_metadata_and_busy(actlog, fake):
    assert actions.get_action('navigate_url').needs_lock is True
    assert await automation.acquire_input_lock(0.05)
    try:
        res = await actions.dispatch('navigate_url', {'url': URL}, lock=True,
                                     job='j5')
        assert res == {'ok': False, 'error': 'E_LOCK_BUSY', 'queued': True}
        assert fake.calls('key_down') == [], 'busy body must not inject'
    finally:
        automation.release_input_lock()


async def test_injection_failure_is_truthful_no_fallback(actlog, fake):
    fake.windows = [CHROME]
    fake.foreground_window = CHROME
    fake.fail_methods.add('key_down')
    res = await actions.dispatch('navigate_url', {'url': URL}, lock=True,
                                 job='j6')
    assert res['ok'] is False and 'URL not opened' in res['error']
    assert fake.calls('open_url') == [], 'failed reuse must not double-open'
    assert not automation.lock_held()


async def test_ctrl_released_when_navigation_fails(actlog, fake):
    fake.windows = [CHROME]
    fake.foreground_window = CHROME
    fake.fail_key_down_vk = KEYMAP['l']      # fails mid Ctrl+L chord
    res = await actions.dispatch('navigate_url', {'url': URL}, lock=True,
                                 job='j7')
    assert res['ok'] is False
    ups = [a[0] for a in fake.calls('key_up')]
    assert KEYMAP['ctrl'] in ups, 'Ctrl must never stay stuck'
    assert not automation.lock_held()
