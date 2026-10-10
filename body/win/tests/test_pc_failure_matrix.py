"""Wave-4 partial-failure matrix (docs/lanes/pc-control.md, Wave 4):
for EVERY pc tool — happy (e2e), missing-denied, locked, backend crash —
plus timeout/kill recovery. The invariant under test: **act_res is always
truthful** (ok:false ⇒ no side effect happened; ok:true ⇒ it did) and the
body is fully usable after any failure.
"""
import asyncio
import json

import pytest

from body.win import actions, automation
from body.win.failure_cases import CRASH_CASES, INVALID_ARGS, crash_args

ALL = sorted(actions.action_names())


def test_failure_tables_cover_every_action():
    assert set(INVALID_ARGS) == set(ALL), set(ALL) - set(INVALID_ARGS)
    assert set(CRASH_CASES) == set(ALL), set(ALL) - set(CRASH_CASES)


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ALL)
async def test_invalid_args_refused_without_touching_os(action, actlog, fake):
    """missing/denied: E_BAD_MSG before the lock and before any OS call."""
    res = await actions.dispatch(action, INVALID_ARGS[action], lock=True,
                                 job='j_inv')
    assert res['ok'] is False and res['error'].startswith('E_BAD_MSG'), res
    assert fake.events == [], '%s touched the OS despite invalid args' % action
    assert not automation.lock_held()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ALL)
async def test_locked_dispatch_is_busy_and_side_effect_free(action, actlog,
                                                            fake, tmp_path):
    """denied/locked: E_LOCK_BUSY + queued, zero side effects, lock intact."""
    _, args = crash_args(action, tmp_path)     # VALID args — only the lock blocks
    assert await automation.acquire_input_lock(0.05)
    try:
        res = await actions.dispatch(action, args, lock=True, job='j_lock')
        assert res == {'ok': False, 'error': 'E_LOCK_BUSY', 'queued': True}, res
        assert fake.events == [], '%s acted while the lock was held' % action
    finally:
        automation.release_input_lock()
    assert not automation.lock_held()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ALL)
async def test_backend_crash_truthful_then_recovers(action, actlog, fake,
                                                    tmp_path):
    """crash: E_INTERNAL (never a hang, never a false ok), lock released,
    failing call observable, and the NEXT dispatch succeeds."""
    method, args = crash_args(action, tmp_path, fake)
    fake.fail_methods.add(method)
    needs_lock = actions.get_action(action).needs_lock
    try:
        res = await actions.dispatch(action, args, lock=needs_lock,
                                     job='j_crash')
        assert res['ok'] is False and res['error'].startswith('E_INTERNAL'), \
            '%s: %s' % (action, res)
        assert method in {name for name, _ in fake.events}, \
            'failing %s call must remain observable' % method
    finally:
        fake.fail_methods.discard(method)
    assert not automation.lock_held(), 'crash must not dangle the input lock'
    rec = await actions.dispatch('foreground_info', {}, job='j_recover')
    assert rec['ok'] is True, 'body unusable after %s crash: %s' % (action, rec)


@pytest.mark.asyncio
async def test_timeout_quarantines_lock_until_worker_ends(actlog, fake):
    """AUD-16: wait_for timeout cancels the AWAIT, not the worker thread —
    the input lock must stay quarantined until the blocked backend call
    truly returns, then a recovery dispatch must succeed."""
    fake.delays['clipboard_set'] = 0.6
    try:
        res = await actions.dispatch('clipboard',
                                     {'op': 'write', 'text': 'slow'},
                                     lock=True, job='j_slow', timeout_ms=100)
        assert res['ok'] is False and res['error'].startswith('E_TIMEOUT'), res
        assert automation.lock_held(), \
            'lock released while the worker is still running (AUD-16)'
        # quarantined: a competing locked act is refused, no input injected
        blocked = await actions.dispatch('input', {'keys': ['enter']},
                                         lock=True, job='j_blocked')
        assert blocked == {'ok': False, 'error': 'E_LOCK_BUSY',
                           'queued': True}, blocked
        await asyncio.sleep(0.7)              # worker drains
    finally:
        fake.delays.clear()
    assert not automation.lock_held(), 'lock never released after drain'
    rec = await actions.dispatch('foreground_info', {}, lock=True,
                                 job='j_after_timeout')
    assert rec['ok'] is True, rec


@pytest.mark.asyncio
async def test_cancel_quarantines_lock_until_worker_ends(actlog, fake):
    """AUD-16 kill/disconnect variant: cancel mid-worker keeps the lock
    quarantined (E_CANCELLED audited), released only when the thread ends."""
    fake.delays['media_key'] = 0.5
    task = asyncio.create_task(
        actions.dispatch('media', {'op': 'play_pause'}, lock=True,
                         job='j_cancel16'))
    try:
        for _ in range(200):                  # wait until the worker is live
            if fake.calls('media_key'):
                break
            await asyncio.sleep(0.01)
        assert fake.calls('media_key'), 'worker never started'
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert automation.lock_held(), \
            'cancel released the lock while the worker still runs (AUD-16)'
        blocked = await actions.dispatch('input', {'keys': ['enter']},
                                         lock=True, job='j_cancel16b')
        assert blocked.get('error') == 'E_LOCK_BUSY'
        await asyncio.sleep(0.6)              # worker drains
        assert not automation.lock_held(), \
            'lock must free once the worker truly ends (AUD-16)'
    finally:
        fake.delays.clear()
        if automation.lock_held():            # safety net: never leak across tests
            automation.release_input_lock()
    lines = [json.loads(l) for l in actlog.read_text().splitlines()]
    assert any(str(l.get('error') or '').startswith('E_CANCELLED')
               for l in lines), 'cancel must still be audited'
    rec = await actions.dispatch('foreground_info', {}, lock=True,
                                 job='j_cancel16c')
    assert rec['ok'] is True, rec


@pytest.mark.asyncio
async def test_cancel_mid_action_releases_lock_and_logs(actlog, fake):
    """kill/disconnect during a held-lock action (PROTOCOL §5): the
    dispatcher propagates the cancel, audits E_CANCELLED, releases the lock
    and stays usable."""
    orig = actions.ACTIONS['volume']
    started = asyncio.Event()

    async def slow(args, be):
        started.set()
        await asyncio.sleep(60)
        return {}

    actions.ACTIONS['volume'] = actions.Action(
        name='volume', handler=slow, validate=orig.validate, needs_lock=True,
        confirm=None, describe=orig.describe, atomic=False)
    try:
        task = asyncio.create_task(
            actions.dispatch('volume', {'level': 5}, lock=True, job='j_kill'))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not automation.lock_held(), 'cancel must release the lock'
        lines = [json.loads(l) for l in actlog.read_text().splitlines()]
        killed = [l for l in lines if l['job'] == 'j_kill']
        assert killed, 'cancelled dispatch must still be audited'
        assert killed[0]['error'].startswith('E_CANCELLED'), killed[0]
    finally:
        actions.ACTIONS['volume'] = orig
        if automation.lock_held():
            automation.release_input_lock()
    rec = await actions.dispatch('volume', {'level': 6}, lock=True,
                                 job='j_after_cancel')
    assert rec['ok'] is True, rec
