"""Wave-5P P6 tests: spoken memory privacy (recall / forget / report)."""
import pytest

import brain.memory as mem
from brain.memory import privacy, retrieval, slots, store


def test_recall_is_scoped_by_owner_and_slot():
    slots.switch_slot('work')
    store.remember('project deadline is tuesday', category='fact')
    store.remember('sensitive alice fact', category='fact', owner='alice')
    slots.switch_slot('travel')
    store.remember('flight is on time', category='fact')

    r = privacy.recall('deadline flight')
    assert r['slot'] == 'travel'
    assert 'flight is on time' in r['text']
    assert 'project deadline' not in r['text']        # slot scoping
    assert 'alice' not in r['text']                   # owner scoping (PR #2404)
    assert r['count'] == 1 and 'Nothing' not in r['text']

    empty = privacy.recall('completely unrelated zzz')
    assert empty['text'] == 'Nothing remembered.' and empty['count'] == 0


def test_recall_explicit_slot_does_not_switch_context():
    slots.switch_slot('travel')
    store.remember('travel fact', category='fact')
    slots.switch_slot('work')
    r = privacy.recall('travel fact', slot='travel')
    assert r['count'] == 1 and 'travel fact' in r['text']
    assert slots.active_slot() == 'work'              # read-only override!
    with pytest.raises(ValueError):
        privacy.recall('x', slot='../evil')


def test_forget_requires_confirm_then_deletes_idempotently():
    a = store.remember('forget me about cakes', category='fact')
    slots.switch_slot('travel')                                  # other slot
    b = store.remember('forget me about cars', category='fact')
    slots.switch_slot('default')

    # 1) no confirmed=True -> preview ONLY, nothing deleted
    r = privacy.forget_fact('forget me about')
    assert r['status'] == 'needs_confirm' and r['matches'] == 2
    assert 'forget me about cakes' in r['preview']
    assert len(store.list_memories(limit=99)) == 2              # untouched

    # 2) confirmed -> deletes owner-wide (across slots, P6 semantics)
    r = privacy.forget_fact('forget me about', confirmed=True)
    assert r['status'] == 'done' and r['deleted'] == 2
    remaining = [m['id'] for m in store.list_memories(limit=99)]
    assert a not in remaining and b not in remaining

    # 3) idempotent: second run = 0, no error
    r = privacy.forget_fact('forget me about', confirmed=True)
    assert r['status'] == 'done' and r['deleted'] == 0

    # 4) nothing to forget without confirm -> done 0 (no pointless question)
    assert privacy.forget_fact('nonexistent thing')['status'] == 'done'


def test_forget_never_crosses_owners():
    store.remember('shared words here', category='fact', owner='alice')
    mine = store.remember('shared words here too', category='fact')
    r = privacy.forget_fact('shared words', confirmed=True)
    assert r['deleted'] == 1                          # ONLY mine
    survivors = store.list_memories(owner='alice', limit=99)
    assert len(survivors) == 1                        # alice's row untouched
    assert survivors[0]['text'] == 'shared words here'
    assert mine not in [m['id'] for m in survivors]


def test_memory_report_shape_and_fail_silence():
    store.remember('one fact', category='fact')
    store.remember('pinned pref', category='preference', pinned=True)
    out = privacy.memory_report()
    assert out.startswith('Memory report')
    assert 'memories (' in out and 'fact: 1' in out and 'pinned' in out
    assert 'active slot: default' in out
    assert 'export' in out and 'wipe' in out         # wave-4 pointers

    def _raise():
        raise RuntimeError('db gone')
    orig = mem.get_conn
    mem.get_conn = _raise
    try:
        assert privacy.memory_report() == 'Memory report is unavailable right now.'
    finally:
        mem.get_conn = orig


def test_all_surfaces_are_router_free_private_mode_safe(monkeypatch):
    """Private mode / RAPHAEL_DISABLE_ROUTER: recall, forget, report and
    export are LOCAL sqlite/file paths — none may touch the cloud."""
    import brain.router as router

    def _boom(*a, **k):
        raise AssertionError('router must not be called')
    monkeypatch.setattr(router, 'chat', _boom)
    store.remember('local only memory', category='fact')
    assert 'local only memory' in privacy.recall('local only')['text']
    assert privacy.forget_fact('local only', confirmed=True)['deleted'] == 1
    assert privacy.memory_report().startswith('Memory report')
    from brain.memory import export
    assert export.wipe('memories')['memories'] == 0    # already gone -> 0
