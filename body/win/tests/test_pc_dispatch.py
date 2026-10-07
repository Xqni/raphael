"""Dispatcher contract (PROTOCOL §7): allow-list conformance, input-lock
etiquette (E_LOCK_BUSY/queued), timeouts, strict validation, and the
redacted action log."""
import asyncio
import json
import pathlib
import re

import pytest

from body.win import actions, automation

REPO = pathlib.Path(__file__).resolve().parents[3]


def protocol_seven_actions():
    """Parse the §7 action enum straight out of docs/PROTOCOL.md (the line
    that carries the enum, guarded by its first member)."""
    text = (REPO / 'docs' / 'PROTOCOL.md').read_text()
    section = text.split('## 7. Body action API', 1)[1].split('## 8.', 1)[0]
    enum_line = next(l for l in section.splitlines() if '`launch_url{' in l)
    return set(re.findall(r'`([a-z_]+)\{', enum_line))


def test_registry_matches_protocol_enum_plus_requested_additions():
    doc = protocol_seven_actions()
    reg = set(actions.action_names())
    # Every §7 action is implemented...
    missing = doc - reg
    assert not missing, 'PROTOCOL §7 actions not implemented: %s' % sorted(missing)
    # ...and the ONLY extras are the three documented additions.
    extra = reg - doc
    assert extra == set(actions.PENDING_PROTO_ADDITIONS), sorted(extra)
    # Every pending name must be covered by an open request file (the
    # integrator applies it to §7 — protocol-report-act.md for `report`).
    requests = sorted((REPO / 'docs' / 'requests').glob('pc-control__to__*.md'))
    assert requests, 'missing pc-control request files'
    covered = '\n'.join(p.read_text() for p in requests)
    for name in actions.PENDING_PROTO_ADDITIONS:
        assert name in covered, \
            'pending action %s not covered by any pc-control request' % name


def test_every_action_declares_metadata():
    for name in actions.action_names():
        a = actions.get_action(name)
        assert a.describe and len(a.describe) > 10, name
        assert isinstance(a.needs_lock, bool)
        assert a.confirm is None or isinstance(a.confirm, str)
        assert callable(a.validate) and callable(a.handler)


@pytest.mark.asyncio
async def test_unknown_action_rejected(actlog):
    res = await actions.dispatch('teleport', {}, job='j1')
    assert res['ok'] is False
    assert res['error'].startswith('E_UNSUPPORTED')
    assert 'queued' not in res


@pytest.mark.asyncio
async def test_args_must_be_object(actlog):
    res = await actions.dispatch('volume', ['nope'], job='j2')
    assert res['ok'] is False and res['error'].startswith('E_BAD_MSG')


@pytest.mark.asyncio
async def test_validation_rejects_extra_and_bad_values(actlog):
    res = await actions.dispatch('volume', {'level': 50, 'junk': 1}, job='j3')
    assert res['ok'] is False and 'unknown field' in res['error']
    res = await actions.dispatch('volume', {'level': True}, job='j4')
    assert res['ok'] is False and 'integer' in res['error']
    res = await actions.dispatch('volume', {'level': 101}, job='j5')
    assert res['ok'] is False and 'between 0 and 100' in res['error']


@pytest.mark.asyncio
async def test_validation_never_echoes_values(actlog, tmp_path):
    secret = 'TOPSECRETVALUE123'
    res = await actions.dispatch('clipboard',
                                 {'op': 'write', 'text': {'x': secret}},
                                 job='j6')
    assert res['ok'] is False
    assert secret not in res['error']
    logged = actlog.read_text()
    assert secret not in logged, 'secret leaked into the action log'


@pytest.mark.asyncio
async def test_lock_busy_returns_exact_e_lock_busy(actlog, fake):
    assert await automation.acquire_input_lock(0.05)
    try:
        res = await actions.dispatch('input', {'keys': ['enter']},
                                     lock=True, job='j7')
        assert res == {'ok': False, 'error': 'E_LOCK_BUSY', 'queued': True}
        assert fake.calls('key_down') == [], 'busy body must not inject input'
    finally:
        automation.release_input_lock()
    assert not automation.lock_held()


@pytest.mark.asyncio
async def test_lock_released_after_handler(actlog, fake):
    res = await actions.dispatch('media', {'op': 'next'}, lock=True, job='j8')
    assert res['ok'] is True
    assert not automation.lock_held()


@pytest.mark.asyncio
async def test_needs_lock_action_acquires_lock_even_if_sender_forgets(actlog, fake):
    # Defense in depth: input never runs without the lock held.
    seen = {}
    original = actions.ACTIONS['input']

    async def probe(args, be):
        seen['held'] = automation.lock_held()
        return {'ok': True}

    monkeyed = actions.Action(name=original.name, handler=probe,
                              validate=original.validate, needs_lock=True,
                              confirm=original.confirm,
                              describe=original.describe, atomic=True)
    actions.ACTIONS['input'] = monkeyed
    try:
        res = await actions.dispatch('input', {'keys': ['enter']},
                                     lock=False, job='j9')
        assert res['ok'] is True
        assert seen['held'] is True
    finally:
        actions.ACTIONS['input'] = original
        if automation.lock_held():
            automation.release_input_lock()


@pytest.mark.asyncio
async def test_timeout_maps_to_e_timeout_and_releases_lock(actlog, fake):
    async def slow(args, be):
        await asyncio.sleep(1.0)
        return {}

    original = actions.ACTIONS['volume']
    actions.ACTIONS['volume'] = actions.Action(
        name='volume', handler=slow, validate=original.validate,
        needs_lock=True, confirm=None, describe=original.describe, atomic=False)
    try:
        res = await actions.dispatch('volume', {'level': 1}, lock=True,
                                     job='j10', timeout_ms=100)
        assert res['ok'] is False and res['error'].startswith('E_TIMEOUT')
        assert not automation.lock_held()
    finally:
        actions.ACTIONS['volume'] = original


@pytest.mark.asyncio
async def test_action_log_is_redacted_and_structural(actlog, fake):
    secret = 'hunter2-TOPSECRET'
    await actions.dispatch('clipboard', {'op': 'write', 'text': secret},
                           job='jlog1')
    await actions.dispatch('screenshot', {'max_px': 640}, job='jlog2')
    await actions.dispatch('search_youtube', {'query': 'lofi'}, lock=False,
                           job='jlog3')
    lines = [json.loads(l) for l in actlog.read_text().splitlines()]
    assert len(lines) == 3
    by_job = {l['job']: l for l in lines}

    clip = by_job['jlog1']
    assert clip['action'] == 'clipboard' and clip['ok'] is True
    assert clip['args']['text'] == '[len=%d]' % len(secret)
    assert clip['result']['result'] == {'written': len(secret)}

    shot = by_job['jlog2']
    assert shot['result']['result']['b64'].startswith('[chars=')
    assert 'FAKEJPEG' not in actlog.read_text()

    yt = by_job['jlog3']
    assert yt['args']['query'] == 'lofi'
    assert yt['lock'] is False
    for l in lines:
        assert l['instance'] and isinstance(l['ms'], int)
        assert isinstance(l['lock'], bool)
    assert secret not in actlog.read_text()


@pytest.mark.asyncio
async def test_backend_error_maps_to_e_internal(actlog, fake):
    fake.fail_methods.add('capture')
    res = await actions.dispatch('screenshot', {}, job='j11')
    assert res['ok'] is False and res['error'].startswith('E_INTERNAL')


@pytest.mark.asyncio
async def test_lock_busy_is_not_action_logged_as_executed(actlog, fake):
    # §7: the log records executed actions; a busy refusal never ran.
    assert await automation.acquire_input_lock(0.05)
    try:
        res = await actions.dispatch('input', {'keys': ['enter']},
                                     lock=True, job='jbusy')
        assert res['error'] == 'E_LOCK_BUSY'
    finally:
        automation.release_input_lock()
    assert not actlog.exists(), 'busy refusal must not appear as an execution'
