"""Unit tests for tests/ownership_check.py (the merge-loop checker) and the
Core Guard manifest tool — the checker's own contract, so a parser bug in
the tool can't silently bless ownership violations.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path.cwd()
sys.path.insert(0, str(REPO / 'tests'))

from ownership_check import check_file, load_lane_table  # noqa: E402

LANES = load_lane_table()


def test_lane_table_parses_all_lanes():
    expected = {'integrator', 'orb', 'brain-core', 'router', 'voice',
                'pc-control', 'computer-use', 'infra', 'qa-security',
                'tools-memory', 'evolution-persona'}
    assert set(LANES) == expected, sorted(LANES)
    assert 'tests/**' in LANES['qa-security']
    assert '.github/workflows/**' in LANES['qa-security']
    assert 'docs/reviews/**' in LANES['qa-security']
    assert 'brain/loop.py' in LANES['brain-core']
    assert 'docs/PROTOCOL.md' in LANES['integrator']


@pytest.mark.parametrize('path,lane', [
    ('tests/contract/test_auth.py', 'qa-security'),
    ('tests/harness/mock_body.py', 'qa-security'),
    ('tests/requirements.txt', 'qa-security'),
    ('.github/workflows/ci.yml', 'qa-security'),
    ('docs/reviews/2026-10-06-wave2.md', 'qa-security'),
    ('docs/lanes/qa-security.md', 'qa-security'),
    ('docs/status/qa-security.md', 'qa-security'),
    ('docs/requests/qa-security__to__router__fix.md', 'qa-security'),
    ('config.d/qa-security.yaml', 'qa-security'),
    ('brain/loop.py', 'brain-core'),
    ('brain/tests/test_ws.py', 'brain-core'),
    ('brain/jobs/engine.py', 'brain-core'),
    ('brain/router/core.py', 'router'),
    ('brain/router/tests/test_router.py', 'router'),
    ('brain/voice/tts.py', 'voice'),
    ('body/win/audio_in.py', 'voice'),
    ('body/win/main.py', 'pc-control'),
    ('body/orb/src/main.js', 'orb'),
    ('supervisor/main.py', 'infra'),
    ('scripts/setup.sh', 'infra'),
    ('docs/PROTOCOL.md', 'integrator'),
    ('config.yaml', 'integrator'),
    ('anything/unlisted/at_all.py', 'integrator'),
])
def test_lanes_can_edit_their_own_files(path, lane):
    assert check_file(path, lane, LANES) is None, \
        f'{lane} should own {path}: {check_file(path, lane, LANES)}'


@pytest.mark.parametrize('path,lane', [
    ('tests/contract/test_auth.py', 'brain-core'),
    ('tests/run_all', 'brain-core'),
    ('.github/workflows/ci.yml', 'infra'),
    ('docs/reviews/x.md', 'orb'),
    ('brain/loop.py', 'qa-security'),
    ('brain/router/core.py', 'qa-security'),
    ('docs/PROTOCOL.md', 'qa-security'),
    ('config.yaml', 'qa-security'),
    ('body/win/main.py', 'qa-security'),
    ('config.d/router.yaml', 'qa-security'),
    ('docs/lanes/brain-core.md', 'qa-security'),
    ('unlisted/new_file.py', 'qa-security'),
])
def test_lanes_cannot_edit_others_files(path, lane):
    reason = check_file(path, lane, LANES)
    assert reason is not None, f'{lane} must NOT be allowed to edit {path}'


def test_integrator_may_touch_anything():
    for path in ('tests/anything.py', 'brain/loop.py', 'body/win/main.py',
                 'docs/PROTOCOL.md'):
        assert check_file(path, 'integrator', LANES) is None


def test_manifest_verifies():
    r = subprocess.run([sys.executable, str(REPO / 'tests' / 'core_guard.py')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'Core Guard OK' in r.stdout


def test_manifest_lists_core_guard_files():
    import json
    manifest = json.loads((REPO / 'tests' / 'core_guard_manifest.json')
                          .read_text())
    assert set(manifest) == {'brain/confirm.py', 'brain/auth.py',
                             'brain/control.py', 'brain/mode.py'}
    assert all(len(v) == 64 for v in manifest.values())
