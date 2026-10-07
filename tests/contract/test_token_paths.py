"""brain.auth.default_token_path — instance-derived token paths
(INTERFACES §d; approved change pc-control → integrator
`instance-token-path.md`, landed on main 2026-10-06).

Rules under test:
- RAPHAEL_TOKEN_PATH always wins (the fixture pattern the whole suite uses —
  the REAL ~/.raphael/token is never read/written here);
- unset instance (`main`) → ~/.raphael/token, BYTE-IDENTICAL to the
  pre-derivation behavior;
- lane instance → ~/.raphael/<instance>/token so two stacks never share one
  credential;
- get_token()/check_token() consume the derived path (with the env override
  they stay on temp files).

Derivation tests assert PATHS ONLY — they never open a real token file.
"""
import os

import pytest

from brain import auth as auth_mod

REAL_MAIN_PATH = os.path.expanduser('~/.raphael/token')


def _derive(monkeypatch, *, token_path=None, instance=None):
    """Control both env inputs explicitly (conftest forces both by default)."""
    if token_path is None:
        monkeypatch.delenv('RAPHAEL_TOKEN_PATH', raising=False)
    else:
        monkeypatch.setenv('RAPHAEL_TOKEN_PATH', token_path)
    if instance is None:
        monkeypatch.delenv('RAPHAEL_INSTANCE', raising=False)
    else:
        monkeypatch.setenv('RAPHAEL_INSTANCE', instance)


def test_main_instance_path_is_byte_identical(monkeypatch):
    """Unset RAPHAEL_INSTANCE must resolve to the EXACT legacy path —
    zero change for the real stack (INTERFACES §d guarantee)."""
    _derive(monkeypatch, instance=None)
    assert auth_mod.default_token_path() == REAL_MAIN_PATH
    assert auth_mod.default_token_path() == os.path.join(
        os.path.expanduser('~/.raphael'), 'token')


def test_explicit_main_instance_is_the_same_path(monkeypatch):
    _derive(monkeypatch, instance='main')
    assert auth_mod.default_token_path() == REAL_MAIN_PATH


def test_lane_instance_derives_own_token_path(monkeypatch):
    _derive(monkeypatch, instance='qa-security')
    lane_path = auth_mod.default_token_path()
    assert lane_path == os.path.join(os.path.expanduser('~/.raphael'),
                                     'qa-security', 'token')
    assert lane_path != REAL_MAIN_PATH, \
        'lane instances must never share the main credential file'


@pytest.mark.parametrize('instance', ['router', 'brain-core', 'pc-control',
                                      'voice', 'computer-use', 'orb', 'infra',
                                      'tools-memory', 'evolution-persona'])
def test_every_lane_instance_gets_a_distinct_path(monkeypatch, instance):
    _derive(monkeypatch, instance=instance)
    assert auth_mod.default_token_path() == os.path.join(
        os.path.expanduser('~/.raphael'), instance, 'token')


def test_blank_instance_falls_back_to_main(monkeypatch):
    _derive(monkeypatch, instance='   ')
    assert auth_mod.default_token_path() == REAL_MAIN_PATH


def test_env_token_path_wins_over_everything(monkeypatch, tmp_path):
    """RAPHAEL_TOKEN_PATH precedence — the pattern every test fixture in
    this suite depends on (never the real file)."""
    fake = tmp_path / 'token'
    fake.write_text('temp-token-value')
    _derive(monkeypatch, token_path=str(fake), instance='qa-security')
    assert auth_mod.default_token_path() == str(fake)
    assert auth_mod.get_token() == 'temp-token-value'


def test_get_token_reads_derived_path_via_override(monkeypatch, tmp_path):
    fake = tmp_path / 'lane-token'
    fake.write_text('  padded-token  \n')
    _derive(monkeypatch, token_path=str(fake), instance='voice')
    # get_token must consume default_token_path() and strip whitespace
    assert auth_mod.get_token() == 'padded-token'


def test_get_token_denies_when_path_missing(monkeypatch, tmp_path):
    _derive(monkeypatch, token_path=str(tmp_path / 'does-not-exist'))
    assert auth_mod.get_token() is None
    assert auth_mod.check_token('anything') is False
    assert auth_mod.check_token(None) is False


def test_check_token_roundtrip_and_wrong_value(monkeypatch, tmp_path):
    fake = tmp_path / 'token'
    fake.write_text('tok-abc-123')
    _derive(monkeypatch, token_path=str(fake))
    assert auth_mod.check_token('tok-abc-123') is True
    assert auth_mod.check_token('tok-abc-124') is False
    assert auth_mod.check_token('') is False


def test_bearer_parsing_variants():
    assert auth_mod.bearer_from_header('Bearer  abc ') == 'abc'
    assert auth_mod.bearer_from_header('bearer abc') == 'abc'
    assert auth_mod.bearer_from_header('Token abc') is None
    assert auth_mod.bearer_from_header(None) is None
