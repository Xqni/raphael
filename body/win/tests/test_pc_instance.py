"""Instance isolation (INTERFACES §d / AGENT_RULES §5): every per-instance
resource derives from RAPHAEL_INSTANCE; main defaults are byte-for-byte the
original behavior."""
import importlib
import os
import pathlib

import pytest

from body.win import instance


def test_main_defaults(main_instance):
    assert instance.instance_name() == 'main'
    assert instance.is_main() is True
    assert instance.port() == 8765
    assert instance.ws_url() == 'ws://127.0.0.1:8765/ws'
    tmp = os.getenv('TMP', '/tmp')
    assert instance.body_lock_path() == pathlib.Path(tmp) / 'raphael_body.lock'
    assert instance.supervisor_mutex() == 'Raphael_Supervisor'
    assert instance.data_dir() == pathlib.Path.home() / '.raphael'
    assert instance.action_log_path().name == 'actions.log'
    assert instance.activity_log_path().name == 'activity.jsonl'   # F-3


def test_main_token_candidates_use_main_paths(main_instance, monkeypatch):
    monkeypatch.setenv('APPDATA', 'C:\\FakeAppData')
    paths = instance.token_candidates()
    # main: APPDATA\Raphael\token then ~/.raphael/token — no lane segment.
    assert paths[0] == pathlib.Path('C:\\FakeAppData') / 'Raphael' / 'token'
    assert paths[1] == pathlib.Path.home() / '.raphael' / 'token'
    assert all('pc-control' not in str(p) for p in paths)


def test_lane_derivation(lane_instance):
    assert instance.instance_name() == 'pc-control'
    assert instance.is_main() is False
    assert instance.port() == 8903                      # INTERFACES §d table
    assert instance.ws_url() == 'ws://127.0.0.1:8903/ws'
    tmp = os.getenv('TMP', '/tmp')
    assert instance.body_lock_path() == \
        pathlib.Path(tmp) / 'raphael_body_pc-control.lock'
    assert instance.supervisor_mutex() == 'Raphael_Supervisor_pc-control'
    assert instance.data_dir() == pathlib.Path.home() / '.raphael' / 'pc-control'
    assert instance.action_log_path().name == 'actions_pc-control.log'
    assert instance.activity_log_path().name == 'activity_pc-control.jsonl'  # F-3
    # Lane lock/log never collide with main's.
    assert instance.action_log_path().name != 'actions.log'


def test_lane_token_candidates_are_isolated(lane_instance, monkeypatch):
    monkeypatch.setenv('APPDATA', 'C:\\FakeAppData')
    paths = instance.token_candidates()
    assert paths[0] == pathlib.Path('C:\\FakeAppData') / 'Raphael' / 'pc-control' / 'token'
    assert paths[1] == pathlib.Path.home() / '.raphael' / 'pc-control' / 'token'
    # Never falls back to the main token (or vice versa).
    assert pathlib.Path.home() / '.raphael' / 'token' not in paths


def test_token_path_env_override(lane_instance, monkeypatch, tmp_path):
    monkeypatch.setenv('RAPHAEL_TOKEN_PATH', str(tmp_path / 'tok'))
    assert instance.token_candidates()[0] == tmp_path / 'tok'


def test_port_env_override_wins(lane_instance, monkeypatch):
    monkeypatch.setenv('RAPHAEL_PORT', '8999')
    assert instance.port() == 8999


def test_all_lane_ports_from_interfaces_table(main_instance, monkeypatch):
    expected = {'router': 8901, 'brain-core': 8902, 'pc-control': 8903,
                'voice': 8904, 'computer-use': 8905, 'orb': 8906,
                'infra': 8907, 'qa-security': 8908, 'tools-memory': 8909,
                'evolution-persona': 8910}
    for lane, port in expected.items():
        monkeypatch.setenv('RAPHAEL_INSTANCE', lane)
        assert instance.port() == port, lane


def test_unknown_instance_never_defaults_a_port(main_instance, monkeypatch):
    monkeypatch.setenv('RAPHAEL_INSTANCE', 'no-such-lane')
    with pytest.raises(ValueError):
        instance.port()          # AGENT_RULES §5: never guess a port


def test_invalid_instance_name_rejected(main_instance, monkeypatch):
    monkeypatch.setenv('RAPHAEL_INSTANCE', '../evil/..')
    with pytest.raises(ValueError):
        instance.instance_name()


def test_cdp_port_derivation(lane_instance, monkeypatch):
    """INTERFACES Wave-5U addendum: browser CDP main 9500, lanes 9500+idx;
    nothing hard-codes a port."""
    assert instance.cdp_port() == 9503            # pc-control = index 3
    monkeypatch.delenv('RAPHAEL_INSTANCE', raising=False)
    assert instance.cdp_port() == 9500            # main
    monkeypatch.setenv('RAPHAEL_INSTANCE', 'router')
    assert instance.cdp_port() == 9501
    monkeypatch.setenv('RAPHAEL_CDP_PORT', '9777')
    assert instance.cdp_port() == 9777
    monkeypatch.delenv('RAPHAEL_INSTANCE', raising=False)
    monkeypatch.delenv('RAPHAEL_CDP_PORT', raising=False)
    assert instance.browser_profile_dir().name == 'browser-profile'
    assert str(instance.browser_profile_dir()).endswith('browser-profile')


def test_action_log_env_override(main_instance, monkeypatch, tmp_path):
    monkeypatch.setenv('RAPHAEL_ACTION_LOG', str(tmp_path / 'x.jsonl'))
    assert instance.action_log_path() == tmp_path / 'x.jsonl'


def test_main_lock_path_unchanged_after_import(main_instance):
    # body.win.main computes LOCK_PATH at import; reload under main env to
    # prove the shipped default is the original raphael_body.lock.
    import body.win.main as main_mod
    try:
        os.environ.pop('RAPHAEL_INSTANCE', None)
        reloaded = importlib.reload(main_mod)
        tmp = os.getenv('TMP', '/tmp')
        assert reloaded.LOCK_PATH == pathlib.Path(tmp) / 'raphael_body.lock'
    finally:
        importlib.reload(main_mod)   # restore for the rest of the suite
