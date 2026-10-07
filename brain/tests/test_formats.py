"""Answer/Report format emitters (APPROVED 2026-10-07) — exact shapes, the
server-side caps, REST kind/parent validation. Roles ui+cli only (see the
e2e role assertions in test_agent_loop)."""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain import formats
from brain.app import app

TEST_TOKEN = 'formats-token-654'


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-tok-fmt-')
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


# ---- answer shape -----------------------------------------------------------
def test_answer_shape_exact_and_provider_optional():
    f = formats.build_answer('j_20261007_0001', 'Two plus two is four.',
                             provider='groq', model='llama-x')
    assert set(f.keys()) == {'type', 'v', 'job', 'text', 'format',
                             'provider', 'model'}
    assert f == {'type': 'answer', 'v': 1, 'job': 'j_20261007_0001',
                 'text': 'Two plus two is four.', 'format': 'answer',
                 'provider': 'groq', 'model': 'llama-x'}
    # Private Mode / fastpath: no router hop -> keys OMITTED (decision cond 3)
    f2 = formats.build_answer(None, 'Private mode is on — cloud models are '
                                    'disabled. Fast path only.')
    assert set(f2.keys()) == {'type', 'v', 'job', 'text', 'format'}
    assert 'provider' not in f2 and 'model' not in f2


# ---- report caps (decision cond 1: enforced BEFORE emit) --------------------
def test_report_caps_sections_summary_and_text():
    body = '\n\n'.join(f'paragraph number {i} ' + ('x' * 500) for i in range(30))
    f = formats.build_report('j_1', body, title='Analysis — disk')
    assert f['type'] == 'report' and f['format'] == 'report'
    assert f['title'] == 'Analysis — disk'
    assert len(f['summary']) <= 500
    assert len(f['sections']) <= 10, len(f['sections'])
    for sec in f['sections']:
        assert set(sec.keys()) == {'heading', 'text'}
        assert len(sec['text']) <= 2000
    assert f['sections'][0]['heading'] == 'Part 1'   # multi-paragraph


def test_report_single_paragraph_and_empty_body():
    f = formats.build_report('j_1', 'one finding only')
    assert f['sections'] == [{'heading': 'Findings', 'text': 'one finding only'}]
    assert f['summary'] == 'one finding only'
    # long single paragraph hard-capped at 2000
    f2 = formats.build_report('j_1', 'y' * 9000)
    assert len(f2['sections'][0]['text']) == 2000
    # default title when none given
    assert f2['title'] == 'Report'
    # empty body never produces a malformed frame
    f3 = formats.build_report(None, '')
    assert f3['sections'] and f3['summary'] == ''


def test_emitters_are_noop_without_hub():
    assert formats.answer(None, 'j_1', 'hi') is False
    assert formats.report(None, 'j_1', 'hi') is False
    assert formats.answer(object(), None, None) is False   # text None guard


# ---- REST kind/parent validation (APPROVED wire fields) ---------------------
def test_rest_jobs_kind_parent_validation(token_path):
    h = {'X-Raphael-Token': TEST_TOKEN}
    with TestClient(app) as client:
        # invalid kind -> 422, loud
        r = client.post('/jobs', json={'text': 'x', 'kind': 'simluation'},
                        headers=h)
        assert r.status_code == 422 and 'kind' in r.json()['detail']
        # valid kind + parent -> echoed on the accepted snapshot
        r = client.post('/jobs', json={'text': 'queued kind job',
                                       'kind': 'analysis',
                                       'parent': 'j_20261007_0001'},
                        headers=h)
        assert r.status_code == 200
        job = r.json()['job']
        assert job['kind'] == 'analysis' and job['parent'] == 'j_20261007_0001'
        # default: kind/parent stay None (additive — zero change when absent)
        r = client.post('/jobs', json={'text': 'plain job'}, headers=h)
        assert r.json()['job']['kind'] is None
        assert r.json()['job']['parent'] is None
        # cancel the queued rows (jobs API hygiene)
        for j in (job, r.json()['job']):
            client.post(f"/jobs/{j['job']}/cancel", json={'scope': 'full'},
                        headers=h)
