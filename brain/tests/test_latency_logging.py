"""ARCH-6 (CO-SHARE): uniform per-stage latency timestamps in /status +
value-blind structured JSON logging. No secrets, no transcripts in either."""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain import latency, logjson
from brain.app import app

TEST_TOKEN = 'latency-token-456'


@pytest.fixture(autouse=True)
def _clean_latency():
    latency.reset_for_tests()
    yield
    latency.reset_for_tests()


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-tok-lat-')
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


# ---- unit: stage anchors + honest omission ---------------------------------
def test_stage_chain_records_and_omits_honestly():
    # no anchors yet -> empty (never fabricated zeros)
    snap = latency.snapshot()
    assert snap['stages'] == {}
    # routing needs submit->running
    latency.note_running(1, 'j_20261007_0001')          # no submit anchor
    assert 'routing' not in latency.snapshot()['stages']
    latency.note_submit(2)
    latency.note_running(2, 'j_20261007_0002')
    assert 'routing' in latency.snapshot()['stages']
    # running-relative stages (one-shot per job)
    assert latency.note_llm_first_token(2) is True
    assert latency.note_llm_first_token(2) is False     # first token only
    assert latency.note_tool_start(2) is True
    assert 'llm_first_token' in latency.snapshot()['stages']
    assert 'tool_start' in latency.snapshot()['stages']
    # unknown rowid -> no number, no crash
    latency.note_llm_first_token(999)
    assert latency.snapshot()['job'] == 'j_20261007_0002'
    # stt + tts standalone
    latency.note_stt(42.5)
    latency.note_speak_start('j_1')
    latency.note_tts_first_audio('j_1')
    stages = latency.snapshot()['stages']
    assert stages['stt'] == 42.5 and 'tts_first_audio' in stages


def test_snapshot_is_value_blind():
    snap = latency.snapshot()
    # numbers/ids/timestamps only — no transcript/text fields exist
    for k, v in snap.get('stages', {}).items():
        assert isinstance(v, (int, float)), (k, v)
        assert k in latency.STAGES
    assert isinstance(snap, dict)


# ---- e2e: /status exposes the stages after a real job ----------------------
def test_status_exposes_latency_after_job(token_path):
    import brain.router as router

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        async def gen():
            yield {'delta': 'Stage report done.'}
            yield {'finish': 'stop', 'provider': 'fake', 'model': 'm'}
        return gen()

    old_chat = getattr(router, 'chat', None)
    router.chat = chat
    old_env = os.environ.get('RAPHAEL_DISABLE_ROUTER')
    os.environ.pop('RAPHAEL_DISABLE_ROUTER', None)
    h = {'X-Raphael-Token': TEST_TOKEN}
    try:
        with TestClient(app) as client:
            r = client.post('/jobs', json={'text': 'summarize the metrics'},
                            headers=h)
            job = r.json()['job_id']
            for _ in range(200):                 # wait for the job to finish
                st = client.get(f'/jobs/{job}', headers=h).json()
                if st['status'] in ('done', 'failed', 'cancelled'):
                    break
                import time as _t
                _t.sleep(0.02)
            lat = client.get('/status', headers=h).json()['latency']
            stages = lat['stages']
            assert 'routing' in stages, lat          # submit -> running
            assert 'llm_first_token' in stages, lat  # first streamed delta
            assert lat['job'].startswith('j_')
            assert isinstance(lat['updated_at'], int)
            # value-blind: stage values are numbers only
            for k, v in stages.items():
                assert isinstance(v, (int, float)) and k in latency.STAGES
    finally:
        if old_chat is None:
            delattr(router, 'chat')
        else:
            router.chat = old_chat
        if old_env is None:
            os.environ.pop('RAPHAEL_DISABLE_ROUTER', None)
        else:
            os.environ['RAPHAEL_DISABLE_ROUTER'] = old_env


# ---- structured logging: value-blind with redaction -------------------------
def test_slog_is_json_and_redacts_secret_values(capsys):
    logjson.slog('sec_probe',
                 detail='use sk-abcdef123456 now; password: hunter22; '
                        'mail me@secret.io; card 4111 1111 1111 1111',
                 count=3, flag=True)
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if '"event": "sec_probe"' in l][-1]
    obj = json.loads(line)                     # strict JSON, one line
    assert obj['event'] == 'sec_probe'
    assert obj['count'] == 3 and obj['flag'] is True   # non-str values intact
    blob = json.dumps(obj)
    assert 'sk-abcdef123456' not in blob
    assert 'hunter22' not in blob
    assert 'me@secret.io' not in blob
    assert '4111 1111 1111 1111' not in blob
    assert 'REDACTED' in blob


def test_slog_never_raises_and_drops_value_if_redactor_unavailable(monkeypatch,
                                                                  capsys):
    import brain.vision.redact as redact_mod

    def _boom(*_a, **_k):
        raise RuntimeError('broken')

    monkeypatch.setattr(redact_mod, 'redact_text', _boom)
    line = logjson.slog('fallback_probe', detail='super secret value')
    obj = json.loads(line)
    assert obj['event'] == 'fallback_probe'
    # value-blind default: the value is DROPPED, never printed raw
    assert obj['detail'] == '<redacted-unavailable>'
    assert 'super secret value' not in json.dumps(obj)


# ---- AUD-05: production foreground hook wired in lifespan --------------------
def test_foreground_hook_wired_and_freshness_bounded(token_path):
    from brain.router import privacy as rpriv
    from brain.vision import context as fgctx
    fgctx.reset_history()
    with TestClient(app) as client:
        # wired at boot: hook is callable now
        assert rpriv.foreground_window() is None          # nothing recorded yet
        fgctx.record_foreground('KeePass - Password Safe')
        assert rpriv.foreground_window() == 'KeePass - Password Safe'
        # stale observation => UNKNOWN (never served as 'current')
        import brain.app as app_mod
        hist = fgctx.recent_history(1)
        fgctx._history[-1] = (hist[-1][0] - 120.0, hist[-1][1])
        assert rpriv.foreground_window() is None
        # a broken hook source degrades to None (never raises)
        fgctx.reset_history()
        assert rpriv.foreground_window() is None
    fgctx.reset_history()


# ---- AUD-29: bounded histograms (distributions, not latest-sample) ---------
def test_histograms_bounded_with_percentiles():
    for v in range(150):                 # window keeps the LAST 120
        latency.note_stt(float(v))
    snap = latency.snapshot()
    h = snap['hist']['stt']
    assert h['count'] == 120, h          # bounded
    assert h['max'] == 149.0
    assert 80.0 <= h['p50'] <= 100.0, h
    assert h['p95'] >= h['p50'] and h['p95'] <= h['max']
    # value-blind: histogram values are numbers only
    for k, v in h.items():
        assert isinstance(v, (int, float)), (k, v)
    # hist absent when nothing recorded
    latency.reset_for_tests()
    assert 'hist' not in latency.snapshot()
