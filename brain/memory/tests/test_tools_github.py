"""github tool tests: private-by-default, confirm metadata, BLOCKED paths,
token value-blindness, scrubbing. gh/git never actually invoked."""
import pytest

from brain.tools import github as gh


@pytest.fixture(autouse=True)
def _no_real_token(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.setattr(gh, 'shutil',
                        type('S', (), {'which': staticmethod(lambda n: '/usr/bin/' + n)})())


def test_status_is_presence_only():
    out = gh.github_status()
    assert 'GITHUB_TOKEN/GH_TOKEN: MISSING' in out
    assert 'default_visibility: private' in out
    assert 'auto_public: False' in out


def test_create_private_is_blocked_without_token():
    out = gh.github_create_repo('myrepo')
    assert out.startswith('BLOCKED:') and 'GITHUB_TOKEN' in out


def test_create_private_blocked_without_gh(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.setenv('GITHUB_TOKEN', 'dummy-not-a-real-key-for-test')
    monkeypatch.setattr(gh, 'shutil',
                        type('S', (), {'which': staticmethod(lambda n: None)})())
    out = gh.github_create_repo('myrepo')
    assert out.startswith('BLOCKED:') and 'gh CLI' in out


def test_create_public_is_risky_and_never_default():
    from brain import tools as reg
    assert reg.describe('github_create_repo')['risky'] is False   # private path
    assert reg.describe('github_create_repo_public')['risky'] is True
    assert reg.describe('github_push')['risky'] is True
    assert reg.describe('github_set_visibility')['risky'] is True
    # the safe tool's schema has NO visibility/private switch to abuse
    props = reg.describe('github_create_repo')['schema']['properties']
    assert set(props) == {'name', 'description'}


def test_name_and_visibility_validation():
    with pytest.raises(ValueError):
        gh.github_create_repo('../evil')
    with pytest.raises(ValueError):
        gh.github_create_repo('bad name!')
    with pytest.raises(ValueError):
        gh.github_set_visibility('owner/repo', 'secret')
    with pytest.raises(ValueError):
        gh.github_set_visibility('not a ref', 'public')
    with pytest.raises(ValueError):
        gh.github_push(remote='origin; rm -rf /')


def test_scrub_masks_token_shapes():
    sample = 'created https://api.github.com ghp_abcdefghijklmnop12345678901234 done'
    out = gh._scrub(sample)
    assert 'ghp_' not in out and '***REDACTED***' in out
    assert gh._scrub('github_pat_abcdefghijklmno123456') == '***REDACTED***'
    assert gh._scrub('nothing secret here') == 'nothing secret here'


def test_run_uses_argv_and_scrubs(monkeypatch):
    class _P:
        returncode = 0
        stdout = b'ok ghp_abcdefghijklmnop12345678901234'
        stderr = b''

    def _fake_run(argv, shell=False, cwd=None, timeout=None,
                  capture_output=None, **kw):
        assert shell is False and capture_output is True
        import subprocess as sp
        return sp.CompletedProcess(argv, 0, _P.stdout, b'')

    monkeypatch.setattr(gh.subprocess, 'run', _fake_run)
    rc, out = gh._run(['gh', 'version'])
    assert rc == 0 and 'ghp_' not in out and '***REDACTED***' in out
