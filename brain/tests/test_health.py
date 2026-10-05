import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from brain.app import app

TEST_TOKEN = 'test-token-123'


@pytest.fixture(scope='module', autouse=True)
def token_path():
    # SAFETY: point the app at a TEMP token file — the real ~/.raphael/token
    # must never be written or deleted by tests.
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-')
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


client = TestClient(app)


def test_health_success():
    resp = client.get('/health', headers={'X-Raphael-Token': TEST_TOKEN})
    assert resp.status_code == 200
    assert resp.json()['status'] == 'ok'


def test_health_unauthorized():
    resp = client.get('/health')
    assert resp.status_code == 401


def test_job_crud():
    resp = client.post('/jobs', json={'task': 'do something', 'priority': 1},
                       headers={'X-Raphael-Token': TEST_TOKEN})
    assert resp.status_code == 200
    job_id = resp.json()['job_id']
    resp = client.get(f'/jobs/{job_id}', headers={'X-Raphael-Token': TEST_TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data['task'] == 'do something'
    assert data['status'] == 'queued'
    resp = client.post(f'/jobs/{job_id}/cancel', headers={'X-Raphael-Token': TEST_TOKEN})
    assert resp.status_code == 200
    assert resp.json()['cancelled'] is True
    resp = client.get(f'/jobs/{job_id}', headers={'X-Raphael-Token': TEST_TOKEN})
    assert resp.json()['status'] == 'cancelled'
