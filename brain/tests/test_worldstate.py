"""Wave 5U task 6 — world state + fastpath browser follow-ups.
Acceptance: open youtube (tab pushed by a fake body) -> 'search pewdiepie'
dispatches navigate to the SAME tab context; follow-up intents resolve in
the fast path with registry-probe fallbacks (honest refusal, never fake).
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from brain import fastpath
from brain import foreground
from brain import worldstate
from brain.app import app
from brain.ws import Session, get_hub

TEST_TOKEN = 'worldstate-token-9'


import os  # noqa: E402
import tempfile  # noqa: E402


@pytest.fixture(scope='module', autouse=True)
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-ws-')
    with os.fdopen(fd, 'w') as f:
        f.write(TEST_TOKEN)
    old = os.environ.get('RAPHAEL_TOKEN_PATH')
    os.environ['RAPHAEL_TOKEN_PATH'] = path
    yield path
    if old is None:
        os.environ.pop('RAPHAEL_TOKEN_PATH', None)
    else:
        os.environ['RAPHAEL_TOKEN_PATH'] = old
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clean():
    worldstate.reset_for_tests()
    foreground.reset_for_tests()
    fastpath.register_builtin_intents()
    yield
    worldstate.reset_for_tests()
    foreground.reset_for_tests()


def _ctx():
    return fastpath.IntentCtx()


def _recv(ws, timeout=5.0):
    for _ in range(20):
        msg = json.loads(ws.receive_text())
        if msg.get('type') not in ('ping', 'orb_state'):
            return msg
    raise AssertionError('no non-push frame')


# ---- worldstate units ------------------------------------------------------
def test_tab_record_clear_and_site():
    t = worldstate.record_browser_tab('https://www.YouTube.com/watch?v=x',
                                      title='Vid - YouTube', tab_id='t1')
    assert t['site'] == 'youtube.com' and t['tab_id'] == 't1'
    assert worldstate.active_tab()['url'].startswith('https://www.YouTube')
    assert worldstate.record_browser_tab(None) is None       # cleared
    assert worldstate.active_tab() is None


def test_tab_goes_stale():
    worldstate.record_browser_tab('https://example.com', tab_id='t')
    worldstate._tab['ts'] = time.time() - 1000.0            # >15 min
    assert worldstate.active_tab() is None


def test_action_and_search_records_value_blind_capped():
    worldstate.record_action('shell', False, {'cmd': 'x' * 500},
                             detail='Boom ' * 100)
    a = worldstate.snapshot()['last_action']
    assert a['tool'] == 'shell' and a['ok'] is False
    assert len(a['detail']) <= 200
    worldstate.record_search('pewdiepie', 'youtube',
                             'https://youtube.com/results?q=p', tab_id='t1')
    s = worldstate.snapshot()['last_search']
    assert s['query'] == 'pewdiepie' and s['tab_id'] == 't1'
    snap = worldstate.snapshot()
    assert set(snap) == {'focused', 'tab', 'last_action', 'last_search'}


# ---- ws consumer -----------------------------------------------------------
def test_ws_browser_tab_body_only_and_updates_state():
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'auth', 'v': 1,
                                     'token': TEST_TOKEN, 'role': 'body',
                                     'client': 't', 'client_v': '1'}))
            assert _recv(ws)['type'] == 'auth_ok'
            ws.send_text(json.dumps({'type': 'browser_tab', 'v': 1,
                                     'url': 'https://youtube.com/results',
                                     'title': 'x - YouTube', 'tab_id': 't9'}))
            msg = _recv(ws)
            assert msg['type'] == 'ack' and msg['kind'] == 'browser_tab', msg
            assert worldstate.active_tab()['tab_id'] == 't9'
        with client.websocket_connect('/ws') as ws2:
            ws2.send_text(json.dumps({'type': 'auth', 'v': 1,
                                      'token': TEST_TOKEN, 'role': 'ui',
                                      'client': 't', 'client_v': '1'}))
            assert _recv(ws2)['type'] == 'auth_ok'
            ws2.send_text(json.dumps({'type': 'browser_tab', 'v': 1,
                                      'url': 'https://evil.example'}))
            msg = _recv(ws2)
            assert msg['type'] == 'error' and msg['code'] == 'E_UNSUPPORTED'
            assert worldstate.active_tab()['tab_id'] == 't9'   # unchanged


# ---- follow-up intents (fallbacks first: no tools registered) -------------
def test_followups_fall_back_honestly_without_tools(monkeypatch):
    monkeypatch.setattr(fastpath, '_have_tool', lambda n: False)
    for phrase, name in (('scroll down', 'browser_scroll'),
                         ('scroll up', 'browser_scroll'),
                         ('go back', 'browser_back'),
                         ('go forward', 'browser_forward'),
                         ('read this page', 'browser_read'),
                         ('open the second result', 'browser_click')):
        res = fastpath.run_intent(phrase, _ctx())
        assert res is not None, phrase
        assert res.tool is None and name in res.text, (phrase, res.text)
        assert 'not connected' in res.text


@pytest.fixture
def browser_tools(monkeypatch):
    names = ('browser_scroll', 'browser_back', 'browser_forward',
             'browser_click', 'browser_read')
    monkeypatch.setattr(fastpath, '_have_tool', lambda n: n in names)
    return names


def test_followups_dispatch_registered_tools(browser_tools):
    r = fastpath.run_intent('scroll down', _ctx())
    assert (r.tool, r.tool_args, r.needs_lock) == \
        ('browser_scroll', {'direction': 'down'}, True)
    r = fastpath.run_intent('scroll up', _ctx())
    assert r.tool_args == {'direction': 'up'}
    assert fastpath.run_intent('go back', _ctx()).tool == 'browser_back'
    assert fastpath.run_intent('go forward', _ctx()).tool == 'browser_forward'
    assert fastpath.run_intent('read this page', _ctx()).tool == 'browser_read'
    r = fastpath.run_intent('open the second result', _ctx())
    assert (r.tool, r.tool_args) == ('browser_click', {'n': 2})
    r = fastpath.run_intent('open result 3', _ctx())
    assert r.tool_args == {'n': 3}


def test_open_result_prefix_beats_generic_open(browser_tools):
    # 'open the second result' must NOT fall into the app-launch intent
    res = fastpath.run_intent('open the second result', _ctx())
    assert res.tool == 'browser_click'
    # ...while a real app open is untouched
    res2 = fastpath.run_intent('open notepad', _ctx())
    assert res2.tool == 'open_app'


# ---- acceptance: tab context + search on the same tab ----------------------
def test_acceptance_search_dispatches_on_same_tab_context(monkeypatch):
    # fake body pushed a YouTube tab; browser is foreground
    worldstate.record_browser_tab('https://www.youtube.com/',
                                  title='YouTube', tab_id='t42')
    foreground.set_foreground('YouTube - Google Chrome | chrome.exe')
    monkeypatch.setattr(fastpath, '_have_tool',
                        lambda n: n in ('navigate_url', 'browser_scroll'))
    res = fastpath.run_intent('search pewdiepie', _ctx())
    assert res.tool == 'navigate_url'
    assert res.tool_args['url'] == \
        'https://www.youtube.com/results?search_query=pewdiepie'
    s = worldstate.snapshot()['last_search']
    assert s['tab_id'] == 't42', s        # SAME tab context followed the search
    assert s['site'] == 'youtube'
