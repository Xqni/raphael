"""schedule tools tests: validation, persistence, fire pump (injected
submit), recurring advance, failure visibility, thread lifecycle."""
import threading
import time

import pytest

from brain.tools import schedule as sc


def _insert_past(kind, payload, *, pattern=None, seconds_ago=10):
    return sc._insert(kind, int(time.time()) - seconds_ago, payload,
                      pattern=pattern)


def _insert_err(kind, payload, attempts=5):
    """Row that already exhausted its retries: status='error'."""
    conn = sc._conn()
    try:
        cur = conn.execute(
            'INSERT INTO schedules (kind, due_at, label, pattern, payload, '
            'status, attempts, created_at) VALUES (?,?,?,?,?,?,?,?)',
            (kind, int(time.time()) - 10, '', None, payload, 'error',
             attempts, int(time.time())))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_timer_set_list_cancel():
    import re
    out = sc.timer_set(60, 'tea')
    tid = int(re.search(r'timer (\d+)', out).group(1))
    assert '(60s)' in out
    listing = sc.timer_list()
    assert f'#{tid} timer' in listing and 'Timer done: tea' in listing
    assert 'cancelled' in sc.timer_cancel(tid)
    assert sc.timer_list() == '(none pending)'
    assert 'no such' in sc.timer_cancel(tid)


def test_timer_validation():
    with pytest.raises(ValueError):
        sc.timer_set(0)
    with pytest.raises(ValueError):
        sc.timer_set(-5)
    with pytest.raises(ValueError):
        sc.timer_set('soon')
    with pytest.raises(ValueError):
        sc.timer_set(10 ** 10)


def test_reminder_validation_and_firing_text():
    import datetime as dt
    soon = (dt.datetime.now() + dt.timedelta(days=1)).replace(
        hour=9, minute=30, second=0, microsecond=0).isoformat()
    with pytest.raises(ValueError):
        sc.reminder_set('2020-01-01T00:00', 'never')       # past
    with pytest.raises(ValueError):
        sc.reminder_set('tomorrow-ish', 'vague')
    with pytest.raises(ValueError):
        sc.reminder_set(soon, '   ')
    out = sc.reminder_set(soon, 'standup')
    assert out.startswith('reminder ') and 'T09:30' in out
    assert 'Reminder: standup' in sc.timer_list()


def test_schedule_patterns():
    import re
    ids = []
    for p in ('every 30m', 'every 2h', 'every 1d', 'daily 08:00'):
        out = sc.schedule_set(p, 'do the rounds')
        ids.append(int(re.search(r'schedule (\d+)', out).group(1)))
    with pytest.raises(ValueError):
        sc.schedule_set('weekly mondays', 'x')
    with pytest.raises(ValueError):
        sc.schedule_set('every 30m', '  ')
    listing = sc.schedule_list()
    assert all(f'#{i} recurring' in listing for i in ids)
    assert 'cancelled' in sc.schedule_cancel(ids[0])
    with pytest.raises(ValueError):
        sc.schedule_cancel('not-an-id')


def test_pump_fires_due_timer_once():
    tid = _insert_past('timer', 'Timer done: tea')
    calls = []
    assert sc.pump_once(submit_fn=calls.append) == 1
    assert calls == ['Timer done: tea']
    assert sc.pump_once(submit_fn=calls.append) == 0      # fired = no re-fire
    assert f'#{tid}' not in sc.timer_list()


def test_pump_advances_recurring_and_keeps_pending():
    _insert_past('recurring', 'check the build', pattern='every 1m')
    calls = []
    assert sc.pump_once(submit_fn=calls.append) == 1
    assert calls == ['check the build']
    # still pending with a FUTURE due_at (not in this pump's window)
    assert sc.pump_pending_count() == 1
    assert sc.pump_once(submit_fn=calls.append) == 0


def test_failed_fire_retries_then_becomes_visible_error():
    _insert_past('timer', 'Timer done: x')
    calls = []

    def flaky(text):
        calls.append(text)
        if len(calls) < 3:
            raise ConnectionError('engine busy')

    # failures 1-2: still pending (retry), attempts recorded
    sc.pump_once(submit_fn=flaky)
    sc.pump_once(submit_fn=flaky)
    assert sc.pump_pending_count() == 1
    # 3rd attempt succeeds -> fired
    assert sc.pump_once(submit_fn=flaky) == 1
    assert sc.timer_list() == '(none pending)'


def test_error_rows_are_visible_not_silent():
    _insert_err('timer', 'Timer done: hopeless')
    out = sc.timer_list()
    assert 'error' in out and 'hopeless' in out          # visible in listing
    assert sc.pump_once(submit_fn=lambda t: None) == 0   # errors never re-pump


def test_arm_thread_fires_and_disarm_leaves_no_orphans(monkeypatch):
    monkeypatch.setattr(sc, '_cfg', lambda k, d: 0.05 if k == 'schedule.tick_s'
                        else d)
    fired = threading.Event()
    _insert_past('timer', 'Timer done: bg')
    sc.arm(submit_fn=lambda t: fired.set())
    assert fired.wait(timeout=3.0)
    sc.disarm()
    t = sc._thread
    assert t is None or not t.is_alive()                 # Rule 14: no orphans


def test_arm_all_requires_loop_for_default_submit():
    # default submit without an armed loop fails VISIBLY (recorded, bounded)
    _insert_past('timer', 'Timer done: unlooped', seconds_ago=60)
    with pytest.raises(RuntimeError):
        sc._default_submit('x')
    # pump marks the attempt, then the row errors out after the cap
    for _ in range(5):
        sc.pump_once()                                    # default submit fails
    assert 'error' in sc.timer_list()


def test_registry_specs_are_strict():
    from brain import tools as reg
    for name in ('timer_set', 'timer_list', 'timer_cancel', 'reminder_set',
                 'schedule_set', 'schedule_list', 'schedule_cancel'):
        meta = reg.describe(name)
        assert meta['risky'] is False                     # non-GUI, non-sensitive
        s = meta['schema']
        assert s['type'] == 'object' and s['additionalProperties'] is False
    with pytest.raises(reg.BadToolArgs):
        reg.validate_args('timer_set', {'seconds': 5, 'extra': True})
