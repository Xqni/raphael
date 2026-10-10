"""Wave-5P P5 tests: named context slots scoping memory retrieval."""
import pytest

import brain.memory as mem
from brain.memory import profile, retrieval, slots, store


def test_default_slot_parity_with_previous_behavior():
    """Fresh state == today's behavior: everything in 'default', retrieval
    sees every row (including rows written before the slot column existed)."""
    assert slots.active_slot() == 'default'
    a = store.remember('pre-existing fact', category='fact')
    b = store.remember('another fact', category='fact')
    out = retrieval.retrieve('pre-existing another')
    assert {r['id'] for r in out} >= {a, b}
    assert all(r['slot'] == 'default' for r in out)


def test_switch_normalizes_and_reports():
    r = slots.switch_slot('  Travel  ')                 # voice says 'Travel'
    assert r == {'from': 'default', 'to': 'travel', 'changed': True}
    assert slots.switch_slot('travel')['changed'] is False   # idempotent


def test_slot_validation_is_loud():
    for bad in ('', '../evil', 'UPPER CASE!', 'a' * 40, None):
        with pytest.raises(ValueError):
            slots.switch_slot(bad)
    with pytest.raises(ValueError):
        store.remember('x', slot='BAD NAME')            # explicit param too


def test_retrieval_is_isolated_per_slot():
    slots.switch_slot('work')
    work_row = store.remember('quarterly report due friday', category='fact')
    work_pin = store.remember('work password rotation is monthly',
                              category='fact', pinned=True)
    slots.switch_slot('travel')
    travel_row = store.remember('flight lands at noon', category='fact')

    out = retrieval.retrieve('quarterly report flight')
    ids = {r['id'] for r in out}
    assert travel_row in ids and work_row not in ids     # slot isolation
    assert work_pin not in ids                           # pinned is scoped too

    slots.switch_slot('work')
    ids = {r['id'] for r in retrieval.retrieve('quarterly report flight')}
    assert work_row in ids and work_pin in ids and travel_row not in ids


def test_switch_mid_conversation_scopes_new_writes():
    before = store.remember('written in default', category='fact')
    slots.switch_slot('project-x')
    during = store.remember('written in project-x', category='fact')
    ids = {r['id'] for r in retrieval.retrieve('written')}
    assert during in ids and before not in ids
    slots.switch_slot('default')                        # and back...
    ids = {r['id'] for r in retrieval.retrieve('written')}
    assert before in ids and during not in ids


def test_active_slot_survives_restart():
    """Session-persistent: state table + cache re-read (restart simulation)."""
    slots.switch_slot('work')
    slots.reset_cache_for_tests()                       # what a process restart does
    assert slots.active_slot() == 'work'


def test_list_slots_counts_and_active_first():
    slots.switch_slot('work')
    store.remember('w1', category='fact')
    store.remember('w2', category='fact')
    slots.switch_slot('travel')
    slots.list_slots()                                  # active, empty slot visible
    out = slots.list_slots()
    assert out[0]['name'] == 'travel' and out[0]['active'] is True
    work = [s for s in out if s['name'] == 'work'][0]
    assert work['memories'] == 2 and work['active'] is False
    assert any(s['name'] == 'default' for s in out)


def test_profile_stays_global_across_slots():
    """User profile is about the USER, not the workstream (documented design)."""
    slots.switch_slot('travel')
    store.remember('lives in toronto', source='user', category='identity')
    slots.switch_slot('work')
    rows = profile.user_profile()
    assert any('toronto' in r['text'] for r in rows)    # global view


def test_fail_silent_broken_db_still_defaults(monkeypatch):
    def _raise():
        raise RuntimeError('db gone')
    monkeypatch.setattr(mem, 'get_conn', _raise)
    assert slots.active_slot() == 'default'             # default, never a crash
    assert slots.list_slots() == [{'name': 'default', 'memories': 0,
                                   'active': True}]
    assert retrieval.retrieve('anything') == []


def test_build_context_honors_active_slot():
    """The feeding seam P5 promises: context built only from active slot."""
    slots.switch_slot('work')
    store.remember('work item alpha', category='fact')
    ctx = retrieval.build_context('work item alpha')
    assert 'work item alpha' in ctx
    slots.switch_slot('travel')
    assert retrieval.build_context('work item alpha') == ''
