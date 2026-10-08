"""Launch actions: URL scheme guard, YouTube query encoding, staged app
resolution, open_path safety, running-app grouping."""
import pathlib

import pytest

from body.win import actions

pytestmark = pytest.mark.asyncio


async def test_launch_url_accepts_http_https(actlog, fake):
    res = await actions.dispatch('launch_url',
                                 {'url': 'https://example.com/x'}, job='j1')
    assert res['ok'] and res['result'] == {'opened': 'https://example.com/x'}
    assert fake.calls('open_url') == [('https://example.com/x',)]


async def test_launch_url_rejects_dangerous_schemes(actlog, fake):
    for url in ('javascript:alert(1)', 'file:///etc/passwd',
                'data:text/html,x', 'ftp://host/x', 'not-a-url'):
        res = await actions.dispatch('launch_url', {'url': url}, job='j2')
        assert res['ok'] is False and res['error'].startswith('E_BAD_MSG'), url
    assert fake.calls('open_url') == [], 'no dangerous scheme may open'


async def test_search_youtube_encodes_query(actlog, fake):
    res = await actions.dispatch('search_youtube',
                                 {'query': 'lo-fi & chill music'}, job='j3')
    assert res['ok']
    [(url,)] = fake.calls('open_url')
    assert url == ('https://www.youtube.com/results?search_query='
                   'lo-fi+%26+chill+music')
    assert res['result']['query'] == 'lo-fi & chill music'


async def test_search_youtube_rejects_empty(actlog, fake):
    res = await actions.dispatch('search_youtube', {'query': '   '}, job='j4')
    assert res['ok'] is False and 'empty' in res['error']


async def test_open_app_resolution_priority(actlog, fake):
    # exact PATH hit (cheapest source, no UWP enumeration)
    res = await actions.dispatch('open_app', {'name': 'notepad'}, job='j5')
    assert res['ok'] and res['result']['kind'] == 'path'
    assert res['result']['resolved'].endswith('notepad.exe')
    assert fake.calls('uwp_apps') == [], 'exact PATH hit must not scan UWP'

    # exact Start Menu shortcut when not on PATH
    res = await actions.dispatch('open_app', {'name': 'Spotify'}, job='j6')
    assert res['ok'] and res['result']['kind'] == 'shortcut'
    assert fake.calls('launch_path')[-1][0].endswith('.lnk')

    # exact App Paths (registry) name with .exe spelling
    res = await actions.dispatch('open_app', {'name': 'chrome'}, job='j7')
    assert res['ok'] and res['result']['resolved'].endswith('chrome.exe')

    # UWP app (only reached when the other sources miss)
    res = await actions.dispatch('open_app', {'name': 'Calculator'}, job='j8')
    assert res['ok'] and res['result']['kind'] == 'uwp'
    assert fake.calls('launch_uwp')


async def test_open_app_prefix_match_and_not_found(actlog, fake):
    # prefix match: 'spot' -> Start Menu 'Spotify' (short-circuits before UWP)
    res = await actions.dispatch('open_app', {'name': 'spot'}, job='j9')
    assert res['ok'] and res['result']['kind'] == 'shortcut'
    assert res['result']['resolved'].endswith('.lnk')

    res = await actions.dispatch('open_app', {'name': 'definitely-not-real'},
                                 job='j10')
    assert res['ok'] is False
    assert 'app not found' in res['error']
    assert fake.calls('launch_uwp') == [], 'failed resolution must not launch'


async def test_open_path_guards(actlog, fake, tmp_path):
    target = tmp_path / 'note.txt'
    target.write_text('hi')
    res = await actions.dispatch('open_path', {'path': str(target)}, job='j11')
    assert res['ok'] and fake.calls('open_shell') == [(str(target),)]

    res = await actions.dispatch('open_path',
                                 {'path': str(tmp_path / 'missing.txt')},
                                 job='j12')
    assert res['ok'] is False and 'does not exist' in res['error']

    res = await actions.dispatch('open_path',
                                 {'path': '\\\\evil-server\\share\\x.exe'},
                                 job='j13')
    assert res['ok'] is False and 'UNC' in res['error']

    res = await actions.dispatch('open_path', {'path': 'shell:AppsFolder\\x'},
                                 job='j14')
    assert res['ok'] is False and 'real filesystem path' in res['error']


async def test_list_running_apps_groups_and_sorts(actlog, fake):
    res = await actions.dispatch('list_running_apps', {}, job='j15')
    assert res['ok']
    out = res['result']
    assert out['count'] == 3
    names = [a['name'] for a in out['apps']]
    # windowed apps sort first (notepad.exe has a window, Spotify does not)
    assert names[0] in ('notepad.exe', 'chrome.exe')
    assert 'truncated' not in out
    by_name = {a['name']: a for a in out['apps']}
    assert by_name['notepad.exe']['windows'] == ['Untitled - Notepad']
    assert by_name['notepad.exe']['processes'] == 1


async def test_open_app_skips_console_scripts(actlog):
    """Bug B: .bat/.cmd/.ps1 launch candidates are excluded — spawning them
    flashes the blank Windows terminal the gate saw."""
    from body.win import winlayer
    from body.win.fakewin import FakeWin
    bat_only = FakeWin(paths=[{'name': 'youtube', 'path': 'C:\\tools\\youtube.bat'}],
                       shortcuts=[], app_paths=[], uwp=[])
    winlayer.set_backend(bat_only)
    try:
        res = await actions.dispatch('open_app', {'name': 'youtube'}, job='j1')
        assert res['ok'] is False
        assert 'console scripts excluded' in res['error']
        assert bat_only.calls('launch_path') == []
        assert bat_only.calls('launch_uwp') == []
    finally:
        winlayer.reset_backend()


async def test_open_app_prefers_exe_over_bat(actlog):
    from body.win import winlayer
    from body.win.fakewin import FakeWin
    both = FakeWin(paths=[
        {'name': 'youtube', 'path': 'C:\\tools\\youtube.bat'},
        {'name': 'youtube', 'path': 'C:\\tools\\youtube.exe'},
    ], shortcuts=[], app_paths=[], uwp=[])
    winlayer.set_backend(both)
    try:
        res = await actions.dispatch('open_app', {'name': 'youtube'}, job='j2')
        assert res['ok'] is True, res
        assert res['result']['resolved'].endswith('youtube.exe')
    finally:
        winlayer.reset_backend()


async def test_not_found_error_reports_stage_counts(actlog, fake):
    res = await actions.dispatch('open_app', {'name': 'definitely-not-real'},
                                 job='j3')
    assert res['ok'] is False
    err = res['error']
    assert 'app not found' in err
    assert 'PATH' in err and 'Start Menu' in err and 'UWP' in err
    assert 'candidates' in err


# --------------------------------------------------------------- AUD-11 ----
async def test_open_app_refuses_literal_paths(actlog, fake):
    """Trusted boundary: literal exe/document paths are NOT resolved by
    open_app — they must go through the confirm-gated open_path."""
    for name in ('C:\\Tools\\tool.exe', '/usr/local/bin/tool', '~/bin/x'):
        res = await actions.dispatch('open_app', {'name': name}, job='j_lit')
        assert res['ok'] is False, (name, res)
        assert 'open_path (confirmation-gated)' in res['error'], res
    assert fake.calls('launch_path') == [], 'literal path must not launch'
    assert fake.calls('launch_uwp') == []


async def test_open_app_refuses_sensitive_blocklist_entries(actlog, fake,
                                                            monkeypatch):
    """Sensitive apps (privacy.blocklist_apps) refuse BEFORE any resolution
    and steer to the confirm-gated open_path."""
    import body.win.act_launch as act_launch
    monkeypatch.setattr(act_launch, '_SENSITIVE_CACHE',
                        ['1Password', 'KeePass', 'Bitwarden', 'Banking'])
    res = await actions.dispatch('open_app', {'name': '1Password'},
                                 job='j_sens')
    assert res['ok'] is False
    assert 'open_path' in res['error'] and 'confirmation' in res['error']
    assert fake.calls('path_commands') == [], 'refused before resolution'
    # non-sensitive curated launches still work
    ok = await actions.dispatch('open_app', {'name': 'notepad'}, job='j_ok')
    assert ok['ok'], ok


async def test_confirm_metadata_on_boundary_acts(actlog, fake):
    """open_path/uia carry their confirm categories (risky gate pairs with
    registry metadata brain-core enforces at dispatch)."""
    from body.win import actions as acts
    assert acts.get_action('open_path').confirm == 'open_arbitrary_file'
    assert acts.get_action('uia').confirm == 'gui_submission'
    assert acts.get_action('open_app').confirm is None   # curated stays free
    assert acts.get_action('launch_url').confirm is None
