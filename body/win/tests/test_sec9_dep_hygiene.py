"""SEC-9 (audit 2026-10-07): the Body never installs or fetches at runtime.

AST-level scan of pc-control's body paths (body/win minus audio_*, which is
voice-owned, + brain/tools/pc/**) plus checks that the hash-pinned
environment file is complete and that the fail-loud helper works WITHOUT
touching the network.
"""
import ast
import importlib.util
import pathlib
import re

import pytest

from body.win import depfail

REPO = pathlib.Path(__file__).resolve().parents[3]


def scope_files():
    files = [p for p in sorted((REPO / 'body' / 'win').glob('*.py'))
             if not p.name.startswith('audio_')]
    files += sorted((REPO / 'brain' / 'tools' / 'pc').glob('*.py'))
    return files


BANNED_IMPORTS = {'requests', 'httpx', 'aiohttp', 'urllib.request', 'urllib3'}
SUBPROCESS_FUNCS = {'run', 'call', 'check_call', 'check_output', 'Popen'}


def violations(path: pathlib.Path):
    """(line, reason) for every runtime installer/network construct."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in BANNED_IMPORTS:
                    out.append((node.lineno, 'imports %s' % alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if mod in BANNED_IMPORTS or mod.startswith('urllib.request'):
                out.append((node.lineno, 'imports from %s' % mod))
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = getattr(fn, 'attr', None) or getattr(fn, 'id', None)
            if fname == '_ensure_pkg':
                out.append((node.lineno, 'calls _ensure_pkg'))
                continue
            if fname == 'system':
                owner = fn.value if isinstance(fn, ast.Attribute) else None
                is_os = ((isinstance(owner, ast.Name) and owner.id == 'os')
                         or (isinstance(owner, ast.Attribute)
                             and owner.attr == 'os'))
                if is_os:
                    out.append((node.lineno, 'os.system call'))
                    continue
            if fname not in SUBPROCESS_FUNCS:
                continue
            # subprocess/popen call carrying a 'pip' / 'ensurepip' constant
            consts = {c.value for c in ast.walk(node) if isinstance(c, ast.Constant)
                      and isinstance(c.value, str)}
            for bad in ('pip', 'ensurepip'):
                if bad in consts:
                    out.append((node.lineno, 'subprocess invokes %r' % bad))
    return out


def test_no_runtime_installs_or_network_fetches():
    assert scope_files(), 'scope glob found nothing — check test paths'
    found = {}
    for path in scope_files():
        v = violations(path)
        if v:
            found[str(path.relative_to(REPO))] = v
    assert not found, 'SEC-9 violations (file:line -> reason): %s' % found


def test_depfail_has_no_subprocess_and_no_network():
    src = (REPO / 'body' / 'win' / 'depfail.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or '').split('.')[0])
    assert not imports & {'subprocess', 'requests', 'httpx', 'urllib'}, imports
    assert 'find_spec' in src  # probe-only, never executes the module


def test_requirements_file_is_hash_pinned_and_complete():
    req = REPO / 'body' / 'win' / 'requirements.txt'
    assert req.is_file(), 'SEC-9 requires body/win/requirements.txt'
    text = req.read_text(encoding='utf-8')
    assert re.search(r'^--require-hashes\s*$', text, re.M), \
        'requirements must enable --require-hashes'
    pins = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)\s*\\?\s*$',
                           text, re.M))
    required = {'pywinauto', 'pillow', 'pywin32', 'mss', 'comtypes',
                'keyboard', 'websockets', 'pyyaml', 'six',
                'sounddevice', 'numpy'}   # last two = audio_in (voice) pins
    assert required <= set(pins), sorted(required - set(pins))
    # every pin carries >=1 sha256 hash, all hashes well-formed
    blocks = re.split(r'(?=^[A-Za-z0-9_.-]+==)', text, flags=re.M)
    for block in blocks:
        head = block.split('\n', 1)[0]
        m = re.match(r'([A-Za-z0-9_.-]+)==', head)
        if not m:
            continue
        hashes = re.findall(r'--hash=sha256:([0-9a-f]+)', block)
        assert hashes, 'no hash for %s' % m.group(1)
        assert all(len(h) == 64 for h in hashes), m.group(1)


def test_require_fails_loud_without_touching_the_network(capsys):
    with pytest.raises(RuntimeError) as ei:
        depfail.require('definitely-not-a-real-package-xyz')
    msg = str(ei.value)
    assert 'requirements.txt' in msg and 'never pip-installs' in msg
    # nothing was printed to the child-process streams (no pip chatter)
    assert capsys.readouterr().out == ''


@pytest.mark.skipif(importlib.util.find_spec('mss') is not None,
                    reason='mss present: module import succeeds by design')
def test_capture_module_fails_loud_when_deps_missing():
    import importlib
    with pytest.raises(RuntimeError, match='requirements.txt'):
        importlib.import_module('body.win.capture')
    # failed import must not linger half-initialized
    assert 'body.win.capture' not in __import__('sys').modules
