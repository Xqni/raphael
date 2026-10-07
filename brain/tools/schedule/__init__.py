"""schedule tools — timers / reminders / recurring schedules (§3.5).

Storage: `schedules` table (brain/memory/schema.py) — survives restarts.
Fire path: a single lazily-started daemon thread pumps due rows and submits a
USER-FACING job through the existing engine seam (brain-core asked for
exactly this in my seam request: `engine.submit(text, priority='user_facing',
source='system')` — the normal loop then narrates/subtitles it; no new speak
API). Startup wiring: brain-core calls `arm_all(loop)` once at app start;
without it, tools still create/cancel/list, and fires RETRY (bounded by
`attempts`, then `status='error'` — visible via timer_list, never silent).

Safety: non-GUI, non-sensitive (risky=False); fire text is user-authored
data like any other tool output (untrusted per AGENT_RULES §9). Parsed
`at`/`pattern` values are validated loudly (ValueError -> model feedback).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import re
import threading
import time
from typing import Any, Callable, Dict, Optional

import brain.tools as _tool_reg

_MAX_ATTEMPTS = 5
_MAX_HORIZON_S = 31536000                 # 1y — absurd future dates rejected
_EVERY_RE = re.compile(r'^every\s+(\d+)\s*([mhd])$', re.I)
_DAILY_RE = re.compile(r'^daily\s+([01]?\d|2[0-3]):([0-5]\d)$')

_state: Dict[str, Any] = {'loop': None, 'submit_fn': None}
_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_arm_lock = threading.Lock()

SPECS = {
    'timer_set': {
        'type': 'object',
        'properties': {
            'seconds': {'type': 'integer',
                        'description': 'seconds from now (1..31536000)'},
            'label': {'type': 'string',
                      'description': 'short label announced when it fires'},
        },
        'required': ['seconds'],
        'additionalProperties': False,
    },
    'timer_list': {
        'type': 'object', 'properties': {}, 'required': [],
        'additionalProperties': False,
    },
    'timer_cancel': {
        'type': 'object',
        'properties': {
            'id': {'type': 'integer', 'description': 'schedule row id'},
        },
        'required': ['id'],
        'additionalProperties': False,
    },
    'reminder_set': {
        'type': 'object',
        'properties': {
            'at': {'type': 'string',
                   'description': 'ISO datetime, e.g. 2026-10-08T09:30 '
                                  '(local time when naive)'},
            'text': {'type': 'string', 'description': 'what to remind about'},
        },
        'required': ['at', 'text'],
        'additionalProperties': False,
    },
    'schedule_set': {
        'type': 'object',
        'properties': {
            'pattern': {'type': 'string',
                        'description': "recurrence: 'every 30m' | 'every 2h' "
                                       "| 'every 1d' | 'daily 08:00'"},
            'task_text': {'type': 'string',
                          'description': 'job text submitted each occurrence'},
        },
        'required': ['pattern', 'task_text'],
        'additionalProperties': False,
    },
    'schedule_list': {
        'type': 'object', 'properties': {}, 'required': [],
        'additionalProperties': False,
    },
    'schedule_cancel': {
        'type': 'object',
        'properties': {
            'id': {'type': 'integer', 'description': 'schedule row id'},
        },
        'required': ['id'],
        'additionalProperties': False,
    },
}


# ---- config / db helpers ----------------------------------------------------
def _cfg(dotted: str, default):
    try:
        from brain import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def _conn():
    from brain.memory import get_conn
    return get_conn()


def _now() -> int:
    return int(time.time())


def _iso(epoch: int) -> str:
    try:
        return _dt.datetime.fromtimestamp(int(epoch)).isoformat(timespec='seconds')
    except Exception:  # noqa: BLE001
        return str(epoch)


# ---- parsing / validation ---------------------------------------------------
def _due_in_seconds(seconds: Any) -> int:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        raise ValueError(f'seconds must be an integer, got {seconds!r}')
    if not 1 <= s <= _MAX_HORIZON_S:
        raise ValueError(f'seconds must be 1..{_MAX_HORIZON_S}, got {s}')
    return _now() + s


def _due_at_iso(at: Any) -> int:
    raw = str(at or '').strip()
    if not raw:
        raise ValueError('at must be an ISO datetime, e.g. 2026-10-08T09:30')
    try:
        dt = _dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'cannot parse {raw!r} as ISO datetime')
    if dt.tzinfo is None:
        dt = dt.astimezone()               # naive = user's LOCAL time
    epoch = int(dt.timestamp())
    if epoch < _now() - 5:
        raise ValueError(f'{raw} is in the past')
    if epoch > _now() + _MAX_HORIZON_S:
        raise ValueError('at is more than a year away')
    return epoch


def _next_recurring(pattern: str, after: Optional[int] = None) -> int:
    """Next due epoch for a validated recurring pattern (never in the past)."""
    now = after if after is not None else _now()
    m = _EVERY_RE.match(pattern)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        step = {'m': 60, 'h': 3600, 'd': 86400}[unit] * max(1, n)
        return max(_now(), now) + step
    m = _DAILY_RE.match(pattern)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        local = _dt.datetime.now().astimezone()
        cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= local:
            cand = cand + _dt.timedelta(days=1)
        return int(cand.timestamp())
    raise ValueError(f'unsupported pattern {pattern!r} '
                     f'(need "every N[m|h|d]" or "daily HH:MM")')


def _validate_pattern(pattern: Any) -> str:
    p = str(pattern or '').strip()
    if not (_EVERY_RE.match(p) or _DAILY_RE.match(p)):
        raise ValueError(f'unsupported pattern {pattern!r} '
                         f'(need "every N[m|h|d]" or "daily HH:MM")')
    _next_recurring(p)          # also proves it computes a next due
    return p


def _insert(kind: str, due_at: int, payload: str, *, label: str = '',
            pattern: Optional[str] = None) -> int:
    conn = _conn()
    try:
        cur = conn.execute(
            'INSERT INTO schedules (kind, due_at, label, pattern, payload, '
            'created_at) VALUES (?,?,?,?,?,?)',
            (kind, int(due_at), label, pattern, payload, _now()))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


# ---- tools ------------------------------------------------------------------
def timer_set(seconds: Any, label: str = '') -> str:
    due = _due_in_seconds(seconds)
    tid = _insert('timer', due,
                  f'Timer done: {label}' if str(label).strip() else 'Timer done.',
                  label=str(label or ''))
    return f'timer {tid} set for {_iso(due)} ({seconds}s)'


def reminder_set(at: Any, text: Any) -> str:
    body = str(text or '').strip()
    if not body:
        raise ValueError('reminder text must be non-empty')
    epoch = _due_at_iso(at)
    rid = _insert('reminder', epoch, f'Reminder: {body}')
    return f'reminder {rid} set for {_iso(epoch)}'


def schedule_set(pattern: Any, task_text: Any) -> str:
    p = _validate_pattern(pattern)
    task = str(task_text or '').strip()
    if not task:
        raise ValueError('task_text must be non-empty')
    sid = _insert('recurring', _next_recurring(p), task, pattern=p)
    return f'schedule {sid} set: {p} -> {_iso(_next_recurring(p))} (first run)'


def _list(kind_filter: tuple) -> str:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, due_at, label, pattern, payload, status, "
            f"last_error FROM schedules WHERE status IN ('pending', 'error') "
            f"AND kind IN ({','.join('?' * len(kind_filter))}) "
            'ORDER BY due_at',
            tuple(kind_filter)).fetchall()
    finally:
        conn.close()
    if not rows:
        return '(none pending)'
    out = []
    for r in rows:
        st = f' [{r["status"]}: {r["last_error"]}]' if r['status'] != 'pending' \
            else (f' [{r["last_error"]}]' if r['last_error'] else '')
        out.append(f'- #{r["id"]} {r["kind"]} at {_iso(r["due_at"])}: '
                   f'{r["pattern"] or r["payload"]}{st}')
    return '\n'.join(out)


def timer_list() -> str:
    """Pending timers + reminders (one-shot)."""
    return _list(('timer', 'reminder'))


def schedule_list() -> str:
    """Pending recurring schedules."""
    return _list(('recurring',))


def _cancel(row_id: Any, kinds: tuple, who: str) -> str:
    try:
        rid = int(row_id)
    except (TypeError, ValueError):
        raise ValueError(f'id must be an integer, got {row_id!r}')
    conn = _conn()
    try:
        cur = conn.execute(
            f"UPDATE schedules SET status = 'cancelled' WHERE id = ? "
            f"AND status = 'pending' AND kind IN ({','.join('?' * len(kinds))})",
            (rid, *kinds))
        conn.commit()
        return f'{who} {rid} cancelled' if cur.rowcount else \
            f'{who} {rid}: no such pending schedule'
    finally:
        conn.close()


def timer_cancel(id: Any) -> str:
    return _cancel(id, ('timer', 'reminder'), 'timer')


def schedule_cancel(id: Any) -> str:
    return _cancel(id, ('recurring',), 'schedule')


# ---- fire runtime -----------------------------------------------------------
def _fire_text(kind: str, row: Dict[str, Any]) -> str:
    return str(row.get('payload') or 'Schedule fired.')


def _default_submit(text: str) -> Any:
    """Production fire path: user-facing job on the engine, via the asyncio
    loop captured by arm(loop) (the seam brain-core asked for)."""
    loop = _state.get('loop')
    if loop is None or loop.is_closed():
        raise RuntimeError('schedule: no asyncio loop armed (call arm_all(loop) '
                           'at startup per the tools-memory seam request)')
    from brain.jobs.engine import get_engine
    fut = asyncio.run_coroutine_threadsafe(
        get_engine().submit(text=text, priority='user_facing', source='system'),
        loop)
    return fut.result(timeout=10)


def pump_once(submit_fn: Optional[Callable[[str], Any]] = None) -> int:
    """Process due rows NOW (synchronous; the thread calls this, tests inject
    their own submit_fn). Returns how many fires were accepted. Failed fires
    retry (attempts+1) up to _MAX_ATTEMPTS, then status='error' — visible,
    never silent."""
    fn = submit_fn or _state.get('submit_fn') or _default_submit
    accepted = 0
    now = _now()
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM schedules WHERE status = 'pending' AND due_at <= ? "
            'ORDER BY due_at LIMIT 50', (now,)).fetchall()]
    finally:
        conn.close()
    for row in rows:
        try:
            fn(_fire_text(row['kind'], row))
            accepted += 1
        except Exception as e:  # noqa: BLE001 — retryable, recorded
            _record_failure(row, str(e)[:200])
            continue
        _record_success(row)
    return accepted


def _record_success(row: Dict[str, Any]) -> None:
    conn = _conn()
    try:
        if row['kind'] == 'recurring':
            nxt = _next_recurring(row['pattern'], after=_now())
            conn.execute(
                'UPDATE schedules SET due_at = ?, attempts = 0, last_error = NULL '
                'WHERE id = ?', (nxt, row['id']))
        else:
            conn.execute(
                "UPDATE schedules SET status = 'fired', fired_at = ?, "
                'attempts = attempts + 1 WHERE id = ?',
                (_now(), row['id']))
        conn.commit()
    finally:
        conn.close()


def _record_failure(row: Dict[str, Any], error: str) -> None:
    conn = _conn()
    try:
        attempts = int(row.get('attempts') or 0) + 1
        status = 'error' if attempts >= _MAX_ATTEMPTS else 'pending'
        conn.execute(
            'UPDATE schedules SET attempts = ?, last_error = ?, status = ? '
            'WHERE id = ?', (attempts, error, status, row['id']))
        conn.commit()
    finally:
        conn.close()


def _thread_loop() -> None:
    while not _stop.is_set():
        try:
            tick = float(_cfg('schedule.tick_s', 1) or 1)
        except Exception:  # noqa: BLE001
            tick = 1.0
        _stop.wait(max(0.05, tick))
        try:
            pump_once()
        except Exception:  # noqa: BLE001 — the pump thread never dies
            pass


def arm(loop: Any = None, submit_fn: Optional[Callable[[str], Any]] = None) -> bool:
    """Start the fire thread (idempotent). `loop` = the brain's asyncio loop
    for the default engine-submit path; tests pass submit_fn instead.
    Safe to call without a loop: fires then retry/fail visibly."""
    global _thread
    if loop is not None:
        _state['loop'] = loop
    if submit_fn is not None:
        _state['submit_fn'] = submit_fn
    with _arm_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop.clear()
        _thread = threading.Thread(target=_thread_loop, name='schedule-pump',
                                   daemon=True)
        _thread.start()
    return True


def arm_all(loop: Any = None) -> bool:
    """Startup entry point brain-core calls (seam request): arm the pump with
    the live asyncio loop."""
    return arm(loop=loop)


def disarm(timeout: float = 2.0) -> None:
    """Stop the pump (Rule 14: tests leave zero orphans)."""
    global _thread
    _stop.set()
    t = _thread
    _thread = None
    if t is not None and t.is_alive():
        t.join(timeout)


def pump_pending_count() -> int:
    conn = _conn()
    try:
        return int(conn.execute(
            "SELECT COUNT(*) FROM schedules WHERE status = 'pending'"
        ).fetchone()[0])
    finally:
        conn.close()


def register(_reg=None) -> None:
    reg = _reg if _reg is not None and hasattr(_reg, 'register') else _tool_reg
    for name, fn, desc in (
            ('timer_set', timer_set, 'set a countdown timer (fires as a spoken job)'),
            ('timer_list', timer_list, 'list pending timers and reminders'),
            ('timer_cancel', timer_cancel, 'cancel a pending timer/reminder by id'),
            ('reminder_set', reminder_set, 'set a reminder at an ISO datetime'),
            ('schedule_set', schedule_set,
             'set a recurring schedule (every Nm|h|d / daily HH:MM)'),
            ('schedule_list', schedule_list, 'list pending recurring schedules'),
            ('schedule_cancel', schedule_cancel,
             'cancel a recurring schedule by id')):
        reg.register(name, fn, risky=False, category='local',
                     description=desc, schema=SPECS[name])


register()
