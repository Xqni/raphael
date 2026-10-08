"""SEC-7 (Wave-5H): Core Guard manifest check -> safe mode + visible Notice.
Format: {<repo-relative path>: sha256} (qa's tests/core_guard.py writer)."""
import hashlib
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain import coreguard
from brain.app import app

TEST_TOKEN = 'coreguard-token-999'


@pytest.fixture(autouse=True)
def _clean_state():
    coreguard.reset_for_tests()
    yield
    coreguard.reset_for_tests()


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-tok-cg-')
    with os.fdopen(fd, 'w') as f:
        f.write(TEST_TOKEN)
    old = os.environ.get('RAPHAEL_TOKEN_PATH')
    os.environ['RAPHAEL_TOKEN_PATH'] = path
    yield path
    if old is None:
        os.environ.pop('RAPHAEL_TOKEN_PATH', None)
    else:
        os.environ['RAPHAEL_TOKEN_PATH'] = old
    try:
        os.remove(path)
    except OSError:
        pass


def _recv_json(ws, timeout=8.0):
    import anyio

    async def _inner():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    m = ws.portal.call(_inner)
    t = m.get('text')
    if t is None:
        t = m.get('bytes', b'').decode()
    return json.loads(t)


def _recv_until(ws, pred, skip=('ping',), limit=60, timeout=8):
    for _ in range(limit):
        msg = _recv_json(ws, timeout=timeout)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg
    raise AssertionError('predicate not met')


def test_worktree_manifest_verifies_clean():
    res = coreguard.verify()
    assert res['ok'] is True, res
    assert res['mismatched'] == [] and res['missing'] == []


def test_verify_detects_mismatch_missing_and_bad_manifest(tmp_path):
    # mismatch: wrong hash for a real file
    good = hashlib.sha256(b'anything').hexdigest()
    bad = tmp_path / 'm1.json'
    bad.write_text(json.dumps({'brain/mode.py': good}))
    res = coreguard.verify(bad)
    assert res['ok'] is False and res['reason'] == 'hash_mismatch'
    assert res['mismatched'] == ['brain/mode.py']
    # file listed but absent
    m2 = tmp_path / 'm2.json'
    m2.write_text(json.dumps({'brain/does_not_exist.py': good}))
    res = coreguard.verify(m2)
    assert res['ok'] is False and res['missing'] == ['brain/does_not_exist.py']
    # missing manifest
    res = coreguard.verify(tmp_path / 'nope.json')
    assert res['ok'] is False and res['reason'] == 'manifest_missing'
    # unreadable manifest -> not verified (fail-safe, never raises)
    m3 = tmp_path / 'm3.json'
    m3.write_text('not json {{{')
    res = coreguard.verify(m3)
    assert res['ok'] is False and 'unreadable' in res['reason']


def test_glob_keys_hash_like_the_writer(tmp_path):
    """Manifest glob entries ('dir/**') use qa's aggregate algorithm —
    runtime verification must agree with tests/core_guard.py (format
    coordination: see brain-core__to__evolution-persona request)."""
    good = coreguard._digest('brain/jobs/**')
    assert good and len(good) == 64           # aggregate computes
    m = tmp_path / 'glob.json'
    m.write_text(json.dumps({'brain/jobs/**': good}))
    assert coreguard.verify(m)['ok'] is True
    m.write_text(json.dumps({'brain/jobs/**': '0' * 64}))
    res = coreguard.verify(m)
    assert res['ok'] is False and res['mismatched'] == ['brain/jobs/**']


def test_status_block_is_value_blind():
    st = coreguard.status()
    assert set(st.keys()) <= {'active', 'ok', 'manifest', 'reason',
                              'mismatched', 'missing'}
    assert isinstance(st['active'], bool)


def test_boot_drift_refuses_to_serve(token_path, monkeypatch, tmp_path):
    """[56] FAIL-CLOSED BEFORE SERVING: manifest drift (or guard-tool failure)
    aborts startup with a loud refusal — uvicorn/TestClient never come up."""
    coreguard.reset_for_tests()
    bad = tmp_path / 'drifted.json'
    bad.write_text(json.dumps({'brain/mode.py': '0' * 64}))
    monkeypatch.setattr(coreguard, 'DEFAULT_MANIFEST', bad)
    try:
        with pytest.raises(RuntimeError, match='REFUSING TO SERVE'):
            with TestClient(app):
                pass
        # bookkeeping still records WHY (value-blind)
        assert coreguard.SAFE_MODE.get('active') is True
    finally:
        coreguard.reset_for_tests()


def test_guard_tool_failure_also_refuses(token_path, monkeypatch):
    """If qa's guard tool itself cannot run -> not verified -> refuse."""
    coreguard.reset_for_tests()
    monkeypatch.setattr(coreguard, 'run_guard_tool',
                        lambda timeout_s=60.0: {'ok': False, 'rc': None,
                                                'detail': 'tool exploded'})
    try:
        with pytest.raises(RuntimeError, match='REFUSING TO SERVE'):
            with TestClient(app):
                pass
    finally:
        coreguard.reset_for_tests()


def test_midrun_drift_flips_safe_mode_and_blocks_dispatch(token_path,
                                                          monkeypatch):
    """AUD-21 enforcement: a mid-run manifest flip (throttled reverify) marks
    SAFE MODE — /status shows it and tool dispatch is blocked."""
    coreguard.reset_for_tests()
    with TestClient(app) as client:
        # healthy at boot
        cg = client.get('/status', headers={'X-Raphael-Token': TEST_TOKEN}
                        ).json()['core_guard']
        assert cg['active'] is False and cg['ok'] is True
        # simulate drift discovered by the next reverify
        monkeypatch.setattr(coreguard, 'verify',
                            lambda manifest_path=None: {
                                'ok': False, 'reason': 'hash_mismatch',
                                'mismatched': ['brain/confirm.py'],
                                'missing': [], 'manifest': 'x'})
        monkeypatch.setattr(coreguard, '_VERIFY_INTERVAL_S', 0.0)
        coreguard._last_verify = -1e9
        cg = client.get('/status', headers={'X-Raphael-Token': TEST_TOKEN}
                        ).json()['core_guard']
        assert cg['active'] is True and cg['ok'] is False
        assert coreguard.SAFE_MODE['active'] is True
    coreguard.reset_for_tests()
