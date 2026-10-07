"""shell tool tests: fixed script registry, argv-only (no shell parsing),
timeout/caps, registry replacement of the wave-2 placeholder."""
import sys

import pytest

from brain.tools import shell as sh


@pytest.fixture(autouse=True)
def _scripts(monkeypatch):
    scripts = {
        'hello': {'cmd': ['/bin/echo', 'hi'], 'desc': 'say hi'},
        'fail': {'cmd': [sys.executable, '-c',
                         'import sys; sys.stderr.write("boom"); sys.exit(3)']},
        'slow': {'cmd': [sys.executable, '-c', 'import time; time.sleep(5)']},
        'loud': {'cmd': [sys.executable, '-c', "print('x' * 100000)"]},
        'bad_string': {'cmd': 'rm -rf /'},               # FORBIDDEN shape
    }
    cfg = {'shell.scripts': scripts, 'shell.timeout_s': 1.0,
           'shell.max_output_bytes': 200}
    monkeypatch.setattr(sh, '_cfg', lambda k, d: cfg.get(k, d))
    return scripts


def test_registered_script_runs_argv_only():
    assert sh.shell('hello') == 'hi'
    # args are appended VERBATIM — metacharacters are literal data (shell=False)
    out = sh.shell('hello', args=['; rm -rf /', '$(whoami)', '`id`'])
    assert '; rm -rf /' in out and '$(whoami)' in out and '`id`' in out


def test_unknown_script_lists_allowlist():
    with pytest.raises(ValueError) as e:
        sh.shell('rm_everything')
    assert 'hello' in str(e.value) and 'registered' in str(e.value)


def test_string_cmd_is_refused():
    with pytest.raises(ValueError) as e:
        sh.shell('bad_string')
    assert 'argv list' in str(e.value)


def test_nonzero_exit_raises_with_output():
    with pytest.raises(RuntimeError) as e:
        sh.shell('fail')
    assert 'rc=3' in str(e.value) and 'boom' in str(e.value)


def test_timeout_is_enforced():
    with pytest.raises(RuntimeError) as e:
        sh.shell('slow')
    assert 'timed out' in str(e.value)


def test_output_capped_with_elision_marker():
    out = sh.shell('loud')
    assert len(out) < 500 and 'elided' in out


def test_shell_list_and_empty_registry(monkeypatch):
    listing = sh.shell_list()
    assert '- hello: say hi' in listing
    monkeypatch.setattr(sh, '_cfg', lambda k, d: {} if k == 'shell.scripts' else d)
    assert 'no scripts registered' in sh.shell_list()


def test_registry_replaced_placeholder_with_keeping_risk():
    from brain import tools as reg
    # the wave-2 shell=True placeholder is GONE: this module's impl owns 'shell'
    assert reg.get('shell') is sh.shell
    meta = reg.describe('shell')
    assert meta['risky'] is True                     # never weakened (§8)
    s = meta['schema']
    assert s['type'] == 'object'
    assert s['additionalProperties'] is False
    assert 'command' not in s['properties']          # arbitrary cmd surface gone
    # shell_list is model-facing too (zero-arg conforming spec)
    assert reg.describe('shell_list')['schema']['required'] == []
    with pytest.raises(reg.BadToolArgs):
        reg.validate_args('shell', {'script': 'x', 'command': 'rm -rf /'})
