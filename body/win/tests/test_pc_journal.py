"""F-3 undoable-act journal: schema, inverse ops, truthfulness, undo API
(the pc-control half of the orb co-share — docs/audit-tasks/pc-control.md).
"""
import json

import pytest

from body.win import actions, journal

pytestmark = pytest.mark.asyncio

REQUIRED_KEYS = {'seq', 'ts', 'kind', 'act', 'job', 'summary', 'inverse',
                 'undone'}


def _schema_ok(entry: dict):
    missing = REQUIRED_KEYS - set(entry)
    assert not missing, missing
    assert isinstance(entry['seq'], int) and entry['seq'] >= 1
    assert isinstance(entry['ts'], int) and entry['ts'] > 0
    assert entry['kind'] in ('volume', 'brightness', 'window', 'media',
                             'recycle_move')
    assert isinstance(entry['summary'], str) and entry['summary']
    assert isinstance(entry['inverse'], dict) and entry['inverse']
    assert isinstance(entry['undone'], bool)


async def test_volume_change_records_and_undo_restores(actlog, fake):
    assert fake.volume == 50
    res = await actions.dispatch('volume', {'level': 42}, job='j_vol')
    assert res['ok'] and fake.volume == 42

    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_list')
    assert listed['ok']
    entry = listed['result']['entries'][0]
    _schema_ok(entry)
    assert entry['kind'] == 'volume' and entry['inverse'] == {'level': 50}
    assert entry['summary'] == 'volume 50 -> 42'
    assert entry['job'] == 'j_vol'

    undone = await actions.dispatch('activity', {'op': 'undo'}, job='j_undo')
    assert undone['ok'], undone
    assert undone['result']['undone']['seq'] == entry['seq']
    assert fake.volume == 50, 'undo must restore the previous level'

    after = await actions.dispatch('activity', {'op': 'list'}, job='j_l2')
    assert after['result']['entries'][0]['undone'] is True
    assert 'undo_seq' in after['result']['entries'][0]


async def test_brightness_roundtrip(actlog, fake):
    assert fake.brightness == 70
    assert (await actions.dispatch('brightness', {'level': 30},
                                   job='j_b'))['ok']
    assert fake.brightness == 30
    assert (await actions.dispatch('activity', {'op': 'undo'},
                                   job='j_bu'))['ok']
    assert fake.brightness == 70


async def test_window_snap_undo_restores_placement(actlog, fake):
    before = fake.window_placement(1001)
    res = await actions.dispatch('window',
                                 {'op': 'snap', 'hwnd': 1001, 'zone': 'left'},
                                 lock=True, job='j_snap')
    assert res['ok']
    assert fake.window_placement(1001)['rect'] != before['rect']

    undone = await actions.dispatch('activity', {'op': 'undo'},
                                    job='j_snap_undo')
    assert undone['ok'], undone
    assert undone['result']['undone']['kind'] == 'window'
    assert fake.window_placement(1001) == before, 'placement fully restored'


async def test_window_minimize_undo_restores_state(actlog, fake):
    assert (await actions.dispatch('window',
                                   {'op': 'minimize', 'hwnd': 1001},
                                   lock=True, job='j_min'))['ok']
    assert fake.window_placement(1001)['minimized'] is True
    assert (await actions.dispatch('activity', {'op': 'undo'},
                                   job='j_min_u'))['ok']
    assert fake.window_placement(1001)['minimized'] is False


async def test_failed_set_records_nothing(actlog, fake):
    """Truthfulness: a mutation that failed leaves no undoable trace."""
    fake.fail_methods.add('set_volume')
    res = await actions.dispatch('volume', {'level': 11}, job='j_fail')
    assert res['ok'] is False and res['error'].startswith('E_INTERNAL')
    fake.fail_methods.discard('set_volume')
    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_fl')
    assert listed['result']['entries'] == []


async def test_failed_undo_never_marks_undone(actlog, fake):
    assert (await actions.dispatch('volume', {'level': 20},
                                   job='j_u1'))['ok']
    fake.fail_methods.add('set_volume')
    res = await actions.dispatch('activity', {'op': 'undo'}, job='j_u2')
    assert res['ok'] is False and res['error'].startswith('E_INTERNAL')
    fake.fail_methods.discard('set_volume')
    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_u3')
    entry = listed['result']['entries'][0]
    assert entry['undone'] is False, 'failed undo must not mark undone'
    # and the journal still undoes it once the backend recovers
    assert (await actions.dispatch('activity', {'op': 'undo'},
                                   job='j_u4'))['ok']
    assert fake.volume == 50


async def test_undo_specific_seq_and_double_undo(actlog, fake):
    await actions.dispatch('volume', {'level': 31}, job='j_s1')
    await actions.dispatch('brightness', {'level': 32}, job='j_s2')
    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_s3')
    seqs = [e['seq'] for e in listed['result']['entries']]
    assert len(seqs) == 2 and seqs == sorted(seqs, reverse=True)

    vol_seq = [e for e in listed['result']['entries']
               if e['kind'] == 'volume'][0]['seq']
    undone = await actions.dispatch('activity', {'op': 'undo', 'seq': vol_seq},
                                    job='j_s4')
    assert undone['ok'] and fake.volume == 50
    again = await actions.dispatch('activity',
                                   {'op': 'undo', 'seq': vol_seq},
                                   job='j_s5')
    assert again['ok'] is False and 'already undone' in again['error']


async def test_undo_empty_journal_is_truthful_error(actlog, fake):
    res = await actions.dispatch('activity', {'op': 'undo'}, job='j_e')
    assert res['ok'] is False and 'nothing to undo' in res['error']
    assert fake.volume == 50, 'failed undo changed nothing'


async def test_invalid_activity_never_touches_journal(actlog, fake):
    res = await actions.dispatch('activity', {'op': 'fly'}, job='j_i')
    assert res['ok'] is False and res['error'].startswith('E_BAD_MSG')
    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_i2')
    assert listed['result']['entries'] == []
    assert fake.events == []


async def test_journal_survives_restart(actlog, fake):
    """Records persist in JSONL; a fresh in-memory view rehydrates them."""
    await actions.dispatch('volume', {'level': 66}, job='j_p1')
    path = actlog.parent / 'activity.jsonl'
    assert path.is_file() and path.read_text().count('\n') == 1

    journal.reset()                     # simulated body restart
    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_p2')
    assert listed['result']['count'] == 1
    entry = listed['result']['entries'][0]
    _schema_ok(entry)
    assert entry['summary'] == 'volume 50 -> 66'
    assert (await actions.dispatch('activity', {'op': 'undo'},
                                   job='j_p3'))['ok']
    assert fake.volume == 50
    # undo marker also persisted (append-only, 2 lines now)
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    assert any('undo_of' in l for l in lines)


async def test_journal_memory_cap(actlog, fake, monkeypatch):
    monkeypatch.setattr(journal, 'MAX_ENTRIES', 5)
    for i in range(8):
        journal.record('volume', 'volume', 'v%d' % i, {'level': i})
    listed = await actions.dispatch('activity', {'op': 'list', 'limit': 50},
                                    job='j_cap')
    assert listed['result']['count'] == 5
    assert listed['result']['entries'][0]['summary'] == 'v7'


async def test_same_value_change_is_not_journaled(actlog, fake):
    """No-op mutations create no undo noise."""
    await actions.dispatch('volume', {'level': 50}, job='j_no')  # already 50
    listed = await actions.dispatch('activity', {'op': 'list'}, job='j_no2')
    assert listed['result']['entries'] == []
