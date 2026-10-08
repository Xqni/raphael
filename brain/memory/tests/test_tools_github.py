"""SEC-4 github tool tests: only status+push remain, creation/visibility/
deletion absent, push confirm-gated, token value-blind + scrubbed."""
import pytest

from brain.tools import github as gh


@pytest.fixture(autouse=True)
def _no_real_token(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.setattr(gh, 'shutil',
                        type('S', (), {'which': staticmethod(lambda n: '/usr/bin/' + n)})())


def test_sec4_removed_tools_are_gone_from_registry():
    from brain import tools as reg
    for gone in ('github_create_repo', 'github_create_repo_public',
                 'github_set_visibility'):
        assert reg.get(gone) is None, f'{gone} must be removed (SEC-4)'
        assert gone not in reg.names()
    assert not hasattr(gh, 'github_set_visibility')
    assert not hasattr(gh, 'github_create_repo')


def test_specs_stay_in_sync_with_registrations():
    """A stale SPECS entry without a registered tool = discovery load error."""
    from brain import tools as reg
    for name in gh.SPECS:
        assert reg.get(name) is not None, f'SPECS entry {name} has no tool'
        assert reg.describe(name)['schema'] == gh.SPECS[name]


def test_only_push_is_risky_and_it_is():
    from brain import tools as reg
    assert reg.describe('github_push')['risky'] is True      # confirm before push
    assert reg.describe('github_status')['risky'] is False
    assert gh.github_push.__doc__.startswith('Push the local build repo')


def test_status_is_presence_only_even_with_token_in_env(monkeypatch):
    token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'
    monkeypatch.setenv('GITHUB_TOKEN', token)
    out = gh.github_status()
    assert 'GITHUB_TOKEN/GH_TOKEN: set' in out
    assert token not in out                      # value NEVER surfaces
    assert 'default_visibility: private' in out
    assert 'HUMAN action (SEC-4)' in out


def test_status_missing_token_advisory():
    out = gh.github_status()
    assert 'MISSING' in out                       # fake which() -> gh path present
    assert '/usr/bin/gh' in out


def test_push_uses_argv_no_shell_and_validates(monkeypatch):
    calls = {}

    def _fake_run(argv, cwd=None, timeout=60.0):
        calls['argv'] = argv
        calls['cwd'] = cwd
        return 0, ''
    monkeypatch.setattr(gh, '_run', _fake_run)
    out = gh.github_push()
    assert calls['argv'] == ['git', 'push', 'origin']
    assert calls['cwd'].endswith('raphael-wt/tools-memory') or 'raphael' in calls['cwd']
    assert out.startswith('pushed to origin')
    gh.github_push(remote='upstream', branch='main')
    assert calls['argv'] == ['git', 'push', 'upstream', 'main']
    with pytest.raises(ValueError):
        gh.github_push(remote='origin; rm -rf /')
    with pytest.raises(ValueError):
        gh.github_push(branch='bad branch!')


def test_push_blocked_without_git(monkeypatch):
    monkeypatch.setattr(gh, 'shutil',
                        type('S', (), {'which': staticmethod(lambda n: None)})())
    assert gh.github_push().startswith('BLOCKED: git not found')


def test_scrub_masks_token_shapes():
    assert 'ghp_' not in gh._scrub('x ghp_abcdefghijklmnop12345678901234 y')
    assert gh._scrub('github_pat_abcdefghijklmno123456') == '***REDACTED***'
    assert gh._scrub('AKIA1234567890ABCDEF') == '***REDACTED***'
    assert gh._scrub('nothing secret here') == 'nothing secret here'


def test_run_uses_argv_and_scrubs(monkeypatch):
    import subprocess as sp

    def _fake_run(argv, shell=False, cwd=None, timeout=None,
                  capture_output=None, **kw):
        assert shell is False and capture_output is True
        return sp.CompletedProcess(
            argv, 0, b'ok ghp_abcdefghijklmnop12345678901234', b'')
    monkeypatch.setattr(gh.subprocess, 'run', _fake_run)
    rc, out = gh._run(['gh', 'version'])
    assert rc == 0 and 'ghp_' not in out and '***REDACTED***' in out
