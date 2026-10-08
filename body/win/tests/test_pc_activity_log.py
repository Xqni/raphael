"""F-3 orb-viewer agreement (docs/requests/orb__to__pc-control__
act-journal-schema.md): stable ids, the op=log joined view with the EXACT
orb entry shape, reversibility classification, undo_ok semantics, and the
media-toggle roundtrip."""
import json

import pytest

from body.win import actions, automation, journal

pytestmark = pytest.mark.asyncio

ORB_KEYS = {'id', 'ts', 'job', 'action', 'args', 'ok', 'error', 'summary',
            'reversible', 'undo', 'undone', 'undo_ok'}
REVERSIBLE_ACTIONS = {'volume', 'brightness', 'window', 'media'}


async def _log_view(limit=50):
    res = await actions.dispatch('activity', {'op': 'log', 'limit': limit},
                                 job='j_view')
    assert res['ok'], res
    return res['result']['entries']


def _action_rows():
    raw = [json.loads(l) for l in actlog_lines()]
    return raw


def actlog_lines():
    from body.win import instance
    return instance.action_log_path().read_text().splitlines()


async def test_ids_are_stable_and_join_both_stores(actlog, fake):
    await actions.dispatch('volume', {'level': 44}, job='j_id')
    rows = _action_rows()
    vol_row = next(r for r in rows if r['action'] == 'volume')
    assert str(vol_row['id']).startswith('a_')
    # journal record carries the SAME id (the join key)
    jentries = journal.entries(10)
    assert jentries[0]['id'] == vol_row['id']
    # stable across restart: reset + rehydrate from files, id unchanged
    journal.reset()
    again = journal.entries(10)
    assert again[0]['id'] == vol_row['id']


async def test_log_view_has_exact_orb_shape_and_classification(actlog, fake):
    await actions.dispatch('volume', {'level': 41}, job='j1')   # reversible
    await actions.dispatch('screenshot', {'max_px': 320}, job='j2')  # n/a
    await actions.dispatch('launch_url', {'url': 'https://x.test'},
                           job='j3')                            # no
    entries = await _log_view()
    assert entries, 'log view must contain executed acts'
    for e in entries:
        assert ORB_KEYS <= set(e), ORB_KEYS - set(e)
        assert isinstance(e['reversible'], bool)
        assert e['undo'] is None or (
            e['undo']['action'] == 'activity'
            and e['undo']['args']['op'] == 'undo'
            and isinstance(e['undo']['args']['seq'], int))
        assert e['summary'] and len(e['summary']) <= 80
    by_action = {e['action']: e for e in entries}
    vol = by_action['volume']
    assert vol['reversible'] is True and vol['undo'] is not None
    assert vol['undone'] is False and vol['undo_ok'] is None
    for name in ('screenshot', 'launch_url'):
        e = by_action[name]
        assert e['reversible'] is False and e['undo'] is None, name
    # classification guard: reversible rows only ever name the 4 safe kinds
    rev_actions = {e['action'] for e in entries if e['reversible']}
    assert rev_actions <= REVERSIBLE_ACTIONS, rev_actions


async def test_log_view_reflects_successful_undo(actlog, fake):
    await actions.dispatch('volume', {'level': 33}, job='j_u')
    view = await _log_view()
    row = next(e for e in view if e['action'] == 'volume')
    seq = row['undo']['args']['seq']
    res = await actions.dispatch('activity',
                                 {'op': 'undo', 'seq': seq}, job='j_u2')
    assert res['ok'], res
    row2 = next(e for e in await _log_view() if e['action'] == 'volume')
    assert row2['undone'] is True and row2['undo'] is None
    assert row2['undo_ok'] is True
    assert fake.volume == 50


async def test_log_view_failed_undo_sets_undo_ok_false(actlog, fake):
    await actions.dispatch('volume', {'level': 22}, job='j_f')
    fake.fail_methods.add('set_volume')
    view = await _log_view()
    seq = next(e for e in view if e['action'] == 'volume')['undo']['args']['seq']
    res = await actions.dispatch('activity', {'op': 'undo', 'seq': seq},
                                 job='j_f2')
    assert res['ok'] is False
    fake.fail_methods.discard('set_volume')
    row = next(e for e in await _log_view() if e['action'] == 'volume')
    assert row['undo_ok'] is False and row['undone'] is False
    assert row['undo'] is not None, 'failed undo must keep the button offered'


async def test_undo_by_stable_id(actlog, fake):
    await actions.dispatch('brightness', {'level': 15}, job='j_id1')
    view = await _log_view()
    row = next(e for e in view if e['action'] == 'brightness')
    res = await actions.dispatch('activity',
                                 {'op': 'undo', 'id': row['id']}, job='j_id2')
    assert res['ok'], res
    assert res['result']['undone']['id'] == row['id']
    assert fake.brightness == 70
    again = await actions.dispatch('activity',
                                   {'op': 'undo', 'id': row['id']},
                                   job='j_id3')
    assert again['ok'] is False and 'already undone' in again['error']


async def test_media_toggle_is_journaled_and_undo_replays(actlog, fake):
    res = await actions.dispatch('media', {'op': 'play_pause'}, lock=True,
                                 job='j_m1')
    assert res['ok']
    view = await _log_view()
    row = next(e for e in view if e['action'] == 'media')
    assert row['reversible'] is True and row['undo'] is not None
    undone = await actions.dispatch('activity',
                                    {'op': 'undo', 'id': row['id']},
                                    job='j_m2')
    assert undone['ok'], undone
    assert fake.calls('media_key')[-1] == ('play_pause',)   # toggle replay

    before = journal.entries(50)
    await actions.dispatch('media', {'op': 'next'}, lock=True, job='j_m3')
    assert len(journal.entries(50)) == len(before), \
        'next/prev are not reversible — must not be journaled'
    next_row = next(e for e in await _log_view() if e['job'] == 'j_m3')
    assert next_row['reversible'] is False


async def test_activity_log_op_validation(actlog, fake):
    bad = [
        {'op': 'log', 'seq': 3},                       # seq not allowed
        {'op': 'log', 'id': 'a_1'},                    # id not allowed
        {'op': 'undo', 'seq': 1, 'id': 'a_1'},         # xor
        {'op': 'undo', 'id': 'not-an-id'},             # shape
        {'op': 'log', 'limit': 0},                     # range
    ]
    for args in bad:
        res = await actions.dispatch('activity', args, job='j_bad')
        assert res['ok'] is False and res['error'].startswith('E_BAD_MSG'), \
            (args, res)
    assert fake.events == []
