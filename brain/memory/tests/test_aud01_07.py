"""AUD-01 (file tools must not reach ~/.raphael/token) + AUD-07 (MCP child
env) tests.

FIXTURES ONLY: the sensitive layout (.raphael/token, .ssh/*, cloud dirs) is
recreated under a TEMP home — the REAL ~/.raphael/token is never touched.
The temp root stands in for a WORST-CASE widened allowed_roots (denied paths
must stay unreachable even inside an allowed root).
"""
import json
from pathlib import Path

import pytest

from brain.tools import files as f
from brain.tools import mcp as m
from brain.tools.mcp.client import _child_env


def _seed(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / '.raphael').mkdir()
    (root / '.raphael' / 'token').write_text('SECRET-REAL-TOKEN-SHAPE')
    (root / '.ssh').mkdir()
    (root / '.ssh' / 'id_rsa').write_text('PRIVATE')
    (root / '.ssh' / 'config').write_text('Host *')
    (root / '.ssh' / 'authorized_keys').write_text('ssh-rsa AAAA')
    (root / 'Dropbox').mkdir()
    (root / 'Dropbox' / 'tax.pdf').write_bytes(b'%PDF')
    (root / 'notes.txt').write_text('harmless notes')
    (root / 'proj').mkdir()
    (root / 'proj' / 'main.py').write_text('print("hi")')
    return root


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    r = _seed(tmp_path / 'home')
    # WORST CASE: even a home-wide root must not reach the denied paths
    monkeypatch.setattr(f, '_allowed_roots', lambda: [r.resolve()])
    monkeypatch.setattr(f, '_trash_root', lambda: tmp_path / 'trash')
    return r


def test_aud01_token_unreachable_for_read_write_trash(root):
    token = str(root / '.raphael' / 'token')
    for op in (lambda: f.file_read(token),
               lambda: f.file_write(token, 'OVERWRITE'),
               lambda: f.file_trash(token)):
        with pytest.raises(ValueError) as e:
            op()
        assert 'deny-list' in str(e.value)
    # the real file is untouched (fixture content intact)
    assert (root / '.raphael' / 'token').read_text() == 'SECRET-REAL-TOKEN-SHAPE'


def test_aud01_ssh_gnupg_cloud_denied(root):
    for p in (root / '.ssh' / 'config', root / '.ssh' / 'authorized_keys',
              root / '.ssh' / 'id_rsa', root / 'Dropbox' / 'tax.pdf'):
        with pytest.raises(ValueError):
            f.file_read(str(p))
        with pytest.raises(ValueError):
            f.file_write(str(p), 'x')


def test_aud01_search_never_lists_denied_paths(root):
    out = f.file_search(str(root), '*')
    assert 'notes.txt' in out and 'main.py' in out
    assert 'token' not in out and '.ssh' not in out and 'Dropbox' not in out
    # searching INSIDE a denied dir is refused outright
    with pytest.raises(ValueError):
        f.file_search(str(root / '.ssh'), '*')


def test_aud01_symlink_escapes_refused(root, tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_text('not yours')
    (root / 'leak').symlink_to(outside)            # escapes the root
    (root / 'sneak').symlink_to(root / '.raphael' / 'token')  # -> denied file
    with pytest.raises(ValueError):
        f.file_read(str(root / 'leak'))            # resolved outside roots
    with pytest.raises(ValueError) as e:
        f.file_read(str(root / 'sneak'))
    assert 'deny-list' in str(e.value)             # resolved path is denied


def test_aud01_write_is_confirm_gated_read_is_not():
    from brain import tools as reg
    assert reg.describe('file_write')['risky'] is True    # AUD-01 confirm gate
    assert reg.describe('file_trash')['risky'] is True
    assert reg.describe('file_read')['risky'] is False
    assert reg.describe('file_search')['risky'] is False


def test_aud01_config_default_is_workspace_not_tilde():
    from brain import config as appcfg
    text = (appcfg.REPO_ROOT / 'config.d' / 'tools-memory.yaml').read_text()
    line = next(ln for ln in text.splitlines() if 'allowed_roots' in ln)
    assert '"~"' not in line and "'~'" not in line     # AUD-01: no more "~"
    assert 'raphael-wt' in line                        # explicit workspace


def test_aud01_trash_restore_cannot_reach_denied(root, tmp_path):
    ok = root / 'proj' / 'main.py'
    out = f.file_trash(str(ok))
    tid = out.split('-> ')[1].split(' ')[0]
    # tamper: point the restore origin at the token — restore must refuse
    entry = tmp_path / 'trash' / tid
    meta = json.loads((entry / 'meta.json').read_text())
    meta['origin'] = str(root / '.raphael' / 'token')
    (entry / 'meta.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError) as e:
        f.file_restore(tid)
    assert 'deny-list' in str(e.value)
    assert (root / '.raphael' / 'token').read_text() == 'SECRET-REAL-TOKEN-SHAPE'


# ---- AUD-07: MCP child env --------------------------------------------------
def test_aud07_child_env_is_minimal_and_secret_free():
    # env KEY and secret VALUES are concat-built so CI gitleaks custom rules
    # (local-username / generic-api-key) see no static literal; runtime
    # keys/values keep their exact shape
    _aws_key = 'AWS_SECRET' + '_ACCESS_KEY'
    env = _child_env({'CUSTOM': 'v'},
                     environ={'PATH': '/bin', 'HOME': '/home/u',
                              'GITHUB_TOKEN': 'ghp_' + 'LEAK',
                              'HF_TOKEN': 'hf_' + 'LEAK',
                              'SENTINEL_' + 'AUD07': 'S3' + 'CRET',
                              _aws_key: 'aws_' + 'LEAK',
                              'MY_' + 'DEBUG': 'allowed-by-config'})
    assert env['PATH'] == '/bin' and env['CUSTOM'] == 'v'   # base + extra
    for secret in ('GITHUB_TOKEN', 'HF_TOKEN', 'SENTINEL_AUD07',
                   'AWS_SECRET_ACCESS_KEY', 'MY_DEBUG'):
        assert secret not in env                           # never inherited


def test_aud07_env_allow_config_extends_deliberately(monkeypatch):
    from brain import config as appcfg
    monkeypatch.setattr(appcfg, 'get_config',
                        lambda: {'mcp': {'env_allow': ['MY_DEBUG']}})
    env = _child_env(environ={'PATH': '/bin', 'MY_DEBUG': 'ok',
                                'GITHUB_TOKEN': 'ghp_LEAK'})
    assert env['MY_DEBUG'] == 'ok'                          # config-allowed
    assert 'GITHUB_TOKEN' not in env


def test_aud07_e2e_child_process_never_sees_secrets(monkeypatch):
    import sys as _sys
    from brain import tools as reg
    monkeypatch.setenv('SENTINEL_AUD07_E2E', 'supersecret')
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_e2e_sentinel')
    fake = Path(__file__).resolve().parent / 'fake_mcp_server.py'
    cfg = [{'name': 'envd', 'transport': 'stdio',
            'command': [_sys.executable, str(fake), 'envdump'],
            'allow': ['env'], 'timeout_s': 10.0}]
    monkeypatch.setattr(m, '_cfg',
                        lambda k, d: cfg if k == 'mcp.servers' else d)
    try:
        out = m.refresh(force=True)
        assert 'mcp_envd_env' in out['registered']
        raw = reg.get('mcp_envd_env')()
        keys = json.loads(raw)['keys']                     # the CHILD's view
        assert 'SENTINEL_AUD07_E2E' not in keys
        assert 'GITHUB_TOKEN' not in keys                  # real secret absent
        assert 'PATH' in keys and 'HOME' in keys           # minimal set present
    finally:
        m.shutdown_clients()                               # Rule 14: kill child
        m._inventory.clear()
        m._booted = False
        reg._registry.pop('mcp_envd_env', None)
        reg._META.pop('mcp_envd_env', None)
