"""Config loader + instance isolation tests (INTERFACES §c/§d).

No network, no providers, no real ~/.raphael writes (RAPHAEL_HOME points the
data-dir derivation at tmp_path).
"""
import os

import pytest

from brain import config as cfg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in ('RAPHAEL_PROFILE', 'RAPHAEL_INSTANCE', 'RAPHAEL_PORT',
                'RAPHAEL_BIND', 'RAPHAEL_LOG_LEVEL'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('RAPHAEL_HOME', str(tmp_path))
    cfg.reset_config_for_tests()
    yield
    cfg.reset_config_for_tests()


# ---- §c: load order + deep merge ------------------------------------------
def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_deep_merge_maps_merge_lists_and_scalars_replace():
    base = {'a': {'x': 1, 'y': 2}, 'lst': [1, 2], 's': 'base'}
    over = {'a': {'y': 9, 'z': 3}, 'lst': [3], 's': 'over'}
    out = cfg.deep_merge(base, over)
    assert out == {'a': {'x': 1, 'y': 9, 'z': 3}, 'lst': [3], 's': 'over'}
    # inputs untouched
    assert base['a']['y'] == 2 and base['lst'] == [1, 2]


def test_config_d_fragments_sorted_deep_merged_then_profile(tmp_path):
    _write(tmp_path / 'config.yaml',
           'profile: cloud_temp\njobs:\n  a: 1\n  b: 2\njobs_list: [base]\n')
    # fragments apply in filename order (00 before 10); non-.yaml ignored
    _write(tmp_path / 'config.d' / '00-first.yaml', 'jobs:\n  b: 20\n  c: 30\n')
    _write(tmp_path / 'config.d' / '10-second.yaml', 'jobs:\n  c: 300\n')
    _write(tmp_path / 'config.d' / 'notes.md', 'jobs:\n  nope: 999\n')
    c = cfg.load_config(tmp_path / 'config.yaml', force=True)
    assert c['jobs'] == {'a': 1, 'b': 20, 'c': 300}, c['jobs']
    assert c['jobs_list'] == ['base']
    assert c['profile'] == 'cloud_temp'
    assert 'nope' not in c['jobs']


def test_profile_overlay_wins_and_env_profile_beats_key(tmp_path, monkeypatch):
    _write(tmp_path / 'config.yaml',
           'profile: cloud_temp\nproviders:\n  chain: [groq, zen_free]\n'
           'profiles:\n  cloud_temp: {}\n'
           '  local:\n    profile: local\n    providers: {chain: [zen_free, go]}\n')
    # default: base profile key
    c = cfg.load_config(tmp_path / 'config.yaml', force=True)
    assert c['profile'] == 'cloud_temp' and c['providers']['chain'] == ['groq', 'zen_free']
    # RAPHAEL_PROFILE wins over the file's profile key
    # (monkeypatch, NOT os.environ directly: _clean_env's delenv(raising=False)
    #  on an ABSENT var records nothing to restore, so a raw set leaks into
    #  other suites' tests in the same process — voice's load_voice_config
    #  then reads profile=local. Seen in the merged-main combined run.)
    monkeypatch.setenv('RAPHAEL_PROFILE', 'local')
    c = cfg.load_config(tmp_path / 'config.yaml', force=True)
    assert c['profile'] == 'local'
    assert c['providers']['chain'] == ['zen_free', 'go'], c['providers']


def test_profile_defaults_to_cloud_temp(tmp_path):
    _write(tmp_path / 'config.yaml', 'jobs: {a: 1}\n')
    c = cfg.load_config(tmp_path / 'config.yaml', force=True)
    assert c['profile'] == 'cloud_temp'


def test_env_overrides_for_instance_values(tmp_path, monkeypatch):
    _write(tmp_path / 'config.yaml', 'server: {host: 0.0.0.0, port: 8765}\n')
    # monkeypatch (not raw os.environ) so the _clean_env teardown can restore —
    # same absent-var delenv gap as the profile test above.
    monkeypatch.setenv('RAPHAEL_PORT', '8999')
    monkeypatch.setenv('RAPHAEL_BIND', '127.0.0.1')
    c = cfg.load_config(tmp_path / 'config.yaml', force=True)
    assert c['server']['port'] == 8999 and c['server']['host'] == '127.0.0.1'


def test_repo_config_loads_and_has_profile():
    """The REAL repo tree must load (config.yaml + config.d + overlay)."""
    c = cfg.get_config()
    assert c['profile'] in ('cloud_temp', 'local')
    assert c.get('providers', {}).get('chain'), 'providers.chain missing'


# ---- §d: instance derivation ----------------------------------------------
def test_main_instance_zero_change(monkeypatch):
    monkeypatch.delenv('RAPHAEL_INSTANCE', raising=False)
    monkeypatch.delenv('RAPHAEL_PORT', raising=False)
    assert cfg.instance() == 'main'
    assert cfg.port() == 8765
    assert cfg.cdp_port() == 9333
    assert cfg.data_dir().name == '.raphael'
    # pidfile moved OUT of the shared /tmp root (data-dir), legacy kept for main
    from pathlib import Path as _P
    assert cfg.pidfile().parent != _P('/tmp')
    assert cfg.pidfile().name == 'brain.pid'
    assert str(cfg.legacy_pidfile()) == '/tmp/raphael-brain.pid'
    assert cfg.body_lock_name() == 'raphael_body.lock'
    assert cfg.supervisor_mutex_name() == 'Raphael_Supervisor'


@pytest.mark.parametrize('name,port,cdp', [
    ('router', 8901, 9401),
    ('brain-core', 8902, 9402),
    ('pc-control', 8903, 9403),
    ('voice', 8904, 9404),
    ('computer-use', 8905, 9405),
    ('orb', 8906, 9406),
    ('infra', 8907, 9407),
    ('qa-security', 8908, 9408),
    ('tools-memory', 8909, 9409),
    ('evolution-persona', 8910, 9410),
    ('shadow', 8911, 9411),   # evolution verification instance (approved row)
])
def test_lane_instances_derive(monkeypatch, tmp_path, name, port, cdp):
    monkeypatch.setenv('RAPHAEL_INSTANCE', name)
    monkeypatch.delenv('RAPHAEL_PORT', raising=False)
    assert cfg.port() == port
    assert cfg.cdp_port() == cdp
    assert cfg.data_dir() == tmp_path / '.raphael' / name
    assert cfg.pidfile() == tmp_path / '.raphael' / name / 'brain.pid'
    from pathlib import Path as _P
    assert cfg.pidfile().parent != _P('/tmp')
    # lanes NEVER write the shared legacy pidfile
    assert cfg.legacy_pidfile() is None
    assert cfg.body_lock_name() == f'raphael_body_{name}.lock'
    assert cfg.supervisor_mutex_name() == f'Raphael_Supervisor_{name}'


def test_raphael_port_env_wins_over_table(monkeypatch):
    monkeypatch.setenv('RAPHAEL_INSTANCE', 'router')
    monkeypatch.setenv('RAPHAEL_PORT', '8990')
    assert cfg.port() == 8990


def test_unknown_instance_is_loud_not_guessed(monkeypatch):
    monkeypatch.setenv('RAPHAEL_INSTANCE', 'not-a-lane')
    monkeypatch.delenv('RAPHAEL_PORT', raising=False)
    with pytest.raises(RuntimeError):
        cfg.port()


def test_snapshot_shape():
    snap = cfg.snapshot()
    for key in ('instance', 'profile', 'port', 'cdp_port', 'data_dir',
                'pidfile', 'body_lock', 'supervisor_mutex'):
        assert key in snap
