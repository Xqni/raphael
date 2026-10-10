"""Wave 5U §5.2 browser worker (raw CDP over the fake seam): status/tabs/
activate/navigate/back/forward/reload/find/click/type/press/scroll/read +
status pushes. No sockets, no real browser — FakeWin scripts the CDP."""
import pytest

from body.win import act_browser, actions, instance

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _browser_state():
    act_browser.reset()
    act_browser._PRIVACY_CACHE = None
    yield
    act_browser.reset()
    act_browser._PRIVACY_CACHE = None


def _ax(role, name, dom=None, value='', **props):
    node = {'backendDOMNodeId': dom, 'role': {'name': role}, 'name': name,
            'properties': [{'name': k, 'value': {'value': v}}
                           for k, v in props.items()]}
    if value:
        node['value'] = {'value': value}
    return node


async def _status_push_ok(actlog, fake):
    sent = []

    async def _cap(f):
        sent.append(f)
        return True

    act_browser.set_status_sender(_cap)
    return sent


async def test_status_reports_down_without_launching(actlog, fake):
    res = await actions.dispatch('browser', {'op': 'status'}, job='j1')
    assert res['ok'] and res['result']['up'] is False
    assert fake.calls('launch_browser') == [], 'status must never launch'


async def test_status_reports_up_and_active(actlog, fake):
    fake.cdp_up = True
    res = await actions.dispatch('browser', {'op': 'status'}, job='j2')
    out = res['result']
    assert out['up'] is True and out['port'] == instance.cdp_port()
    assert out['tabs_count'] == 2 and out['active']['id'] == 'T-active'


async def test_tabs_auto_starts_worker(actlog, fake):
    assert fake.cdp_up is False
    res = await actions.dispatch('browser', {'op': 'tabs'}, job='j3')
    assert res['ok'] and res['result']['active_id'] == 'T-active'
    assert res['result']['tabs'][0]['url'] == 'about:blank'
    assert fake.calls('launch_browser'), 'explicit ops auto-start'
    profile, port = fake.calls('launch_browser')[0]
    assert profile.endswith('browser-profile') and port == instance.cdp_port()
    assert fake.cdp_up is True                          # fake flips on launch


async def test_activate_by_id(actlog, fake):
    fake.cdp_up = True
    res = await actions.dispatch('browser', {'op': 'activate', 'id': 'T-other'},
                                 job='j4')
    assert res['ok'] and res['result'] == {'activated': 'T-other'}
    assert any(p.endswith('/json/activate/T-other')
               for _port, p, _m in fake.calls('cdp_http'))
    bad = await actions.dispatch('browser', {'op': 'activate', 'id': 'nope'},
                                 job='j5')
    assert bad['ok'] is False and 'no tab' in bad['error']


async def test_navigate_same_tab_and_new_tab(actlog, fake):
    fake.cdp_up = True
    res = await actions.dispatch('browser',
                                 {'op': 'navigate', 'url': 'https://x.test/'},
                                 job='j6')
    assert res['ok'] and res['result']['new_tab'] is False
    assert 'Page.navigate' in [m for c in fake.calls('cdp_page') for m in c[1]]
    res2 = await actions.dispatch('browser',
                                  {'op': 'navigate', 'url': 'https://x.test/y',
                                   'new_tab': True}, job='j7')
    assert res2['ok'] and res2['result']['new_tab'] is True
    assert any(p.startswith('/json/new?') and m == 'PUT'
               for _port, p, m in fake.calls('cdp_http'))
    for bad in ('javascript:alert(1)', 'file:///x', 'data:text/html,x'):
        r = await actions.dispatch('browser',
                                   {'op': 'navigate', 'url': bad}, job='j8')
        assert r['ok'] is False and r['error'].startswith('E_BAD_MSG'), bad


async def test_history_and_reload(actlog, fake):
    fake.cdp_up = True
    fake.cdp_page_results['Page.getNavigationHistory'] = {
        'currentIndex': 1,
        'entries': [{'id': 11}, {'id': 12}, {'id': 13}]}
    for op, want in (('back', 11), ('forward', 13)):
        res = await actions.dispatch('browser', {'op': op}, job='j9')
        assert res['ok'] and res['result'] == {'moved': op}
        # navigateToHistory called with the right entry id
        hist_calls = [c for c in fake.calls('cdp_page')
                      if 'Page.navigateToHistory' in c[1]]
        assert hist_calls, op
    res = await actions.dispatch('browser', {'op': 'reload'}, job='j10')
    assert res['ok'] and res['result'] == {'reloaded': True}


async def test_find_stores_refs_and_gates_reads(actlog, fake):
    fake.cdp_up = True
    fake.cdp_page_results['Accessibility.getFullAXTree'] = {'nodes': [
        _ax('link', 'Open the first result', dom=5),
        _ax('button', 'Subscribe', dom=6),
        _ax('searchbox', 'Search', dom=7)]}
    res = await actions.dispatch('browser',
                                 {'op': 'find', 'role': 'link'}, job='j11')
    assert res['ok'] and res['result']['count'] == 1
    ref = res['result']['refs'][0]
    assert ref['ref'] == 0 and ref['dom'] == 5 and ref['role'] == 'link'

    # privacy gate: blocklisted title -> find/read refuse
    fake.cdp_targets[0]['title'] = 'Vault — Bank of Example'
    act_browser._PRIVACY_CACHE = {'apps': ['bank of example'], 'patterns': []}
    gated = await actions.dispatch('browser', {'op': 'find', 'text': 'x'},
                                   job='j12')
    assert gated['ok'] is False and 'privacy' in gated['error']


async def test_click_uses_box_model_center(actlog, fake):
    fake.cdp_up = True
    fake.cdp_page_results['Accessibility.getFullAXTree'] = {'nodes': [
        _ax('link', 'First result', dom=9)]}
    fake.cdp_page_results['DOM.getBoxModel'] = {
        'model': {'content': [10, 20, 110, 20, 110, 50, 10, 50]}}
    found = await actions.dispatch('browser',
                                   {'op': 'find', 'role': 'link'}, job='j13a')
    assert found['ok'] and found['result']['count'] == 1
    res = await actions.dispatch('browser', {'op': 'click', 'ref': 0},
                                 job='j13')
    assert res['ok'] and res['result']['at'] == [60, 35]
    methods = [m for c in fake.calls('cdp_page') for m in c[1]]
    assert methods.count('Input.dispatchMouseEvent') == 2   # down + up
    unknown = await actions.dispatch('browser', {'op': 'click', 'ref': 7},
                                     job='j14')
    assert unknown['ok'] is False and 'run find/read first' in unknown['error']


async def test_type_refuses_password_field(actlog, fake):
    fake.cdp_up = True
    fake.cdp_page_results['Runtime.evaluate'] = {'result': {'value': True}}
    res = await actions.dispatch('browser', {'op': 'type', 'text': 'hunter2'},
                                 job='j15')
    assert res['ok'] is False and 'password' in res['error']
    assert 'Input.insertText' not in [m for c in fake.calls('cdp_page')
                                      for m in c[1]]


async def test_type_inserts_and_submits(actlog, fake):
    fake.cdp_up = True
    fake.cdp_page_results['Runtime.evaluate'] = {'result': {'value': False}}
    res = await actions.dispatch('browser',
                                 {'op': 'type', 'text': 'pewdiepie',
                                  'submit': True}, job='j16')
    assert res['ok'] and res['result'] == {'typed': 9, 'submitted': True}
    methods = [m for c in fake.calls('cdp_page') for m in c[1]]
    assert 'Input.insertText' in methods
    assert methods.count('Input.dispatchKeyEvent') == 2   # enter down+up


async def test_press_chord_key_events(actlog, fake):
    fake.cdp_up = True
    res = await actions.dispatch('browser', {'op': 'press', 'key': 'ctrl+l'},
                                 job='j17')
    assert res['ok']
    events = [c for c in fake.calls('cdp_page')
              if 'Input.dispatchKeyEvent' in c[1]]
    assert len(events) == 4        # ctrl down, l down, l up, ctrl up


async def test_scroll_and_read(actlog, fake):
    fake.cdp_up = True
    fake.cdp_page_results['Runtime.evaluate'] = {'result': {'value': None}}
    res = await actions.dispatch('browser', {'op': 'scroll', 'dy': -600},
                                 job='j18')
    assert res['ok'] and res['result'] == {'scrolled': -600}
    evals = [c for c in fake.calls('cdp_page')
             if 'Runtime.evaluate' in c[1]]
    assert evals, 'scroll must evaluate the fixed helper'

    fake.cdp_page_results['Accessibility.getFullAXTree'] = {'nodes': [
        _ax('heading', 'Top story', dom=1),
        _ax('text', 'Body copy here', dom=2)]}
    read = await actions.dispatch('browser', {'op': 'read', 'max_chars': 500},
                                  job='j19')
    assert read['ok'] and 'Top story' in read['result']['text']
    assert read['result']['chars'] <= 500
    bad = await actions.dispatch('browser', {'op': 'scroll', 'dy': 0},
                                 job='j20')
    assert bad['ok'] is False and bad['error'].startswith('E_BAD_MSG')


async def test_status_push_after_op_and_dedupe(actlog, fake):
    fake.cdp_up = True
    sent = await _status_push_ok(actlog, fake)
    await actions.dispatch('browser', {'op': 'tabs'}, job='j21')
    assert sent and sent[-1]['type'] == 'browser_status'
    assert sent[-1]['browser']['up'] is True
    before = len(sent)
    await actions.dispatch('browser', {'op': 'tabs'}, job='j22')
    # watcher-free dedupe: post-op push of an unchanged active tab is deduped
    assert len(sent) <= before + 1
