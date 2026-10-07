"""Retrieval tests: pinned-always, BM25/keyword ordering, boosts, recency,
use counters, owner isolation, fail-silent. Plus block.py framing tests."""
import brain.memory as mem
from brain.memory import block, fts, retrieval, store


def _age(mid: int, days: float):
    """Set a memory's ts to N days ago (UTC), controlling recency precisely."""
    import calendar
    import time as _t
    then = _t.strftime('%Y-%m-%d %H:%M:%S',
                        _t.gmtime(_t.time() - days * 86400))
    conn = mem.get_conn()
    try:
        conn.execute('UPDATE memories SET ts = ? WHERE id = ?', (then, mid))
        conn.commit()
    finally:
        conn.close()


def test_pinned_always_included_even_when_query_misses():
    pinned_id = store.remember('raphael speaks with a japanese voice',
                               source='user', category='preference', pinned=True)
    store.remember('lofi hip hop radio stream exists', category='fact')
    out = retrieval.retrieve('unrelated query about weather')
    assert out[0]['id'] == pinned_id          # pinned ALWAYS first
    assert out[0]['pinned'] == 1
    assert out[0]['score'] == float('inf')


def test_topk_and_best_match_first():
    fox = store.remember('the quick brown fox jumps over the lazy dog',
                         category='fact')
    store.remember('a fox in the garden', category='fact')
    store.remember('coffee brewing temperature matters', category='fact')
    out = retrieval.retrieve('brown fox', k=2)
    assert out[0]['id'] == fox                 # best match (2 terms) first
    assert len(out) == 2                       # k respected (no pinned present)
    assert 'score' in out[0] and out[0]['score'] > 0


def test_uses_counter_bumps_on_every_retrieval():
    mid = store.remember('repeatedly useful fact about backups', category='fact')
    retrieval.retrieve('backups')
    retrieval.retrieve('backups')
    row = [r for r in store.list_memories() if r['id'] == mid][0]
    assert row['uses'] == 2
    assert row['last_used'] is not None


def test_owner_isolation_in_retrieval():
    store.remember('alice private note about banking', source='user',
                   category='fact', owner='alice')
    assert retrieval.retrieve('banking note', owner='bob') == []
    assert retrieval.retrieve('banking note') == []        # default != alice


def test_category_boost_breaks_a_tie():
    # identical text -> identical base score; preference must win the boost
    a = store.remember('meeting at nine tomorrow', category='fact')
    b = store.remember('meeting at nine tomorrow', category='preference')
    now = '2026-10-07 12:00:00'
    conn = mem.get_conn()
    try:
        conn.execute("UPDATE memories SET ts = ? WHERE id IN (?, ?)", (now, a, b))
        conn.commit()
    finally:
        conn.close()
    out = retrieval.retrieve('meeting nine', k=5)
    ids = [r['id'] for r in out]
    assert ids.index(b) < ids.index(a)         # preference outranks fact


def test_recency_breaks_a_tie():
    old = store.remember('deploy the service on fridays', category='fact')
    new = store.remember('deploy the service on fridays', category='fact')
    _age(old, days=25)
    _age(new, days=0)
    out = retrieval.retrieve('deploy service fridays', k=5)
    ids = [r['id'] for r in out]
    assert ids.index(new) < ids.index(old)     # newer first


def test_keyword_fallback_when_no_fts(monkeypatch):
    monkeypatch.setattr(fts, 'available', lambda: False)
    a = store.remember('kubernetes pods restart policy', category='fact')
    store.remember('gardening tips for tomatoes', category='fact')
    out = retrieval.retrieve('pods restart', k=3)
    assert out and out[0]['id'] == a           # same API, overlap scoring
    assert out[0]['score'] > 0


def test_fts_sanitization_and_punctuation_only_query():
    store.remember('sane memory exists', category='fact')
    # FTS operators in user text must not blow up (quoted tokens only)
    assert isinstance(retrieval.retrieve('a NEAR/0 OR * "quoted"'), list)
    # no tokens at all -> only pinned (none here) -> empty
    assert retrieval.retrieve('!!! ??? ***') == []


def test_retrieve_fail_silent_on_db_error(monkeypatch):
    def _raise():
        raise RuntimeError('db gone')
    monkeypatch.setattr(mem, 'get_conn', _raise)
    assert retrieval.retrieve('anything') == []


# ---- block.py ---------------------------------------------------------------
def test_block_framing_and_contents():
    rows = [{'id': 1, 'text': '  user   likes\nshort answers ',
             'category': 'preference', 'ts': '2026-10-06 10:00:00'}]
    out = block.build_untrusted_block(rows)
    assert out.startswith('[UNTRUSTED memory')
    assert 'never instructions' in out.splitlines()[0]
    assert '- (preference, 2026-10-06): user likes short answers' in out
    assert out.endswith('[/UNTRUSTED memory]')


def test_block_excludes_personal_when_asked():
    rows = [
        {'text': 'lives in toronto', 'category': 'identity', 'ts': 'x'},
        {'text': 'prefers tea', 'category': 'preference', 'ts': 'x'},
        {'text': 'call mom sundays', 'category': 'contact', 'ts': 'x'},
    ]
    assert block.has_personal(rows) is True
    out = block.build_untrusted_block(rows, include_personal=False)
    assert 'lives in toronto' not in out and 'call mom' not in out
    assert 'prefers tea' in out
    assert block.has_personal([{'category': 'preference'}]) is False


def test_block_empty_and_truncation():
    assert block.build_untrusted_block([]) == ''
    assert block.build_untrusted_block(None) == ''
    rows = [{'text': 'x' * 500, 'category': 'fact', 'ts': '2026-01-01'} for _ in range(20)]
    out = block.build_untrusted_block(rows, max_chars=600)
    assert len(out) <= 620                     # header/footer + truncation marker
    assert out.endswith('[/UNTRUSTED memory]')  # footer always closes
    assert '(truncated)' in out
