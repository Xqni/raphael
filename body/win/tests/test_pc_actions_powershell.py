"""Fixed PowerShell registry: script_id allow-list, declared-args-only,
injection-free argv, JSON parsing, failure mapping."""
import pytest

from body.win import actions, act_powershell

pytestmark = pytest.mark.asyncio


async def test_registry_self_check():
    assert set(act_powershell.SCRIPTS) >= {
        'list_uwp_apps', 'disk_usage', 'network_info', 'sysinfo',
        'recycle_bin_status', 'notify_toast'}
    for sid, spec in act_powershell.SCRIPTS.items():
        assert 'confirm' in spec, sid          # explicit category, no implicit
        assert isinstance(spec['argv'], list) and spec['argv']
        assert spec['argv'][:1] == ['powershell']


async def test_unknown_script_id_rejected(actlog, fake):
    res = await actions.dispatch('powershell',
                                 {'script_id': 'rm_rf'}, job='j1')
    assert res['ok'] is False and 'unknown script_id' in res['error']


async def test_undeclared_argument_rejected(actlog, fake):
    res = await actions.dispatch('powershell',
                                 {'script_id': 'disk_usage',
                                  'args': {'path': 'C:\\'}}, job='j2')
    assert res['ok'] is False and 'does not declare' in res['error']


async def test_argv_is_fixed_and_text_travels_via_env_only(actlog, fake):
    evil = '"; Remove-Item -Recurse C:\\ ; "'
    fake.powershell_result = {'rc': 0, 'out': '{"ok": true}', 'err': ''}
    res = await actions.dispatch('powershell',
                                 {'script_id': 'notify_toast',
                                  'args': {'text': evil}}, job='j3')
    assert res['ok'] is True
    (argv, env, timeout) = fake.calls('powershell')[0]
    assert evil not in argv, 'user text leaked into argv'
    assert '-NoProfile' in argv and argv[:2] == ['powershell', '-NoProfile']
    assert env == {'RAPHAEL_ARG_TEXT': evil}
    assert timeout == act_powershell.SCRIPTS['notify_toast']['timeout_s']


async def test_json_script_result_parsed(actlog, fake):
    fake.powershell_result = {'rc': 0, 'out': '{"items": 3}', 'err': ''}
    res = await actions.dispatch('powershell',
                                 {'script_id': 'recycle_bin_status'}, job='j4')
    assert res['ok'] and res['result'] == {'items': 3}


async def test_json_single_object_normalized_to_list_for_array_scripts(actlog, fake):
    # ConvertTo-Json emits a bare object when only one row matches.
    fake.powershell_result = {'rc': 0, 'out': '{"name": "x", "app_id": "y"}',
                              'err': ''}
    res = await actions.dispatch('powershell',
                                 {'script_id': 'list_uwp_apps'}, job='j5')
    assert res['ok'] and res['result'] == [{'name': 'x', 'app_id': 'y'}]


async def test_nonzero_rc_and_bad_json_fail_loudly(actlog, fake):
    fake.powershell_result = {'rc': 1, 'out': '',
                              'err': 'boom: access denied'}
    res = await actions.dispatch('powershell',
                                 {'script_id': 'sysinfo'}, job='j6')
    assert res['ok'] is False and res['error'].startswith('E_INTERNAL')
    assert 'rc=1' in res['error']

    fake.powershell_result = {'rc': 0, 'out': 'not json', 'err': ''}
    res = await actions.dispatch('powershell',
                                 {'script_id': 'sysinfo'}, job='j7')
    assert res['ok'] is False and 'non-JSON' in res['error']


async def test_notify_toast_arg_validation(actlog, fake):
    fake.powershell_result = {'rc': 0, 'out': '', 'err': ''}
    res = await actions.dispatch('powershell',
                                 {'script_id': 'notify_toast',
                                  'args': {'text': 'x' * 501}}, job='j8')
    assert res['ok'] is False and 'exceeds' in res['error']

    res = await actions.dispatch('powershell',
                                 {'script_id': 'notify_toast',
                                  'args': {'text': ''}}, job='j9')
    assert res['ok'] is False and 'too short' in res['error']
    assert fake.calls('powershell') == [], 'invalid args must fail pre-lock'
