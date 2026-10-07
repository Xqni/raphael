"""github tools — authenticated `gh` CLI wrappers (addendum §2/§9).

Policy (config.yaml → github.* is READ-ONLY for this lane):
- `github.default_visibility: private`, `auto_public: false` — the SAFE
  creation tool physically CANNOT create a public repo (no `private` param;
  the public path is a separate tool, `risky=True`, on the
  `make_public_repo` confirm list; config `auto_public:true` is a USER edit,
  never a model lever);
- token presence is checked value-blind (AGENT_RULES §7): env names only,
  NEVER values; every subprocess output passes `_scrub()` so a token-shaped
  string can never reach logs/prompts;
- missing gh/token -> returns `BLOCKED: ...` (advisory for the model to
  report), invalid arguments -> ValueError (model feedback), network/CLI
  failure -> RuntimeError (job failure);
- argv lists only (`shell=False`) — descriptions/spaces need no quoting.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import List, Optional, Tuple

import brain.tools as _tool_reg

_REPO_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')
_REPO_REF_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$')
_TOKEN_RE = re.compile(
    r'gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|'
    r'AKIA[0-9A-Z]{16}')
_VISIBILITY = ('public', 'private')

SPECS = {
    'github_status': {
        'type': 'object', 'properties': {}, 'required': [],
        'additionalProperties': False,
    },
    'github_create_repo': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string',
                     'description': 'repository name (letters, digits, . _ -)'},
            'description': {'type': 'string', 'description': 'repo description'},
        },
        'required': ['name'],
        'additionalProperties': False,
    },
    'github_create_repo_public': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'description': 'repository name'},
            'description': {'type': 'string', 'description': 'repo description'},
        },
        'required': ['name'],
        'additionalProperties': False,
    },
    'github_push': {
        'type': 'object',
        'properties': {
            'remote': {'type': 'string', 'description': 'remote name (default origin)'},
            'branch': {'type': 'string', 'description': 'branch (default: current)'},
        },
        'required': [],
        'additionalProperties': False,
    },
    'github_set_visibility': {
        'type': 'object',
        'properties': {
            'repo': {'type': 'string',
                     'description': 'owner/name repository reference'},
            'visibility': {'type': 'string',
                           'description': 'public or private'},
        },
        'required': ['repo', 'visibility'],
        'additionalProperties': False,
    },
}


def _cfg(dotted: str, default):
    try:
        from brain import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def _scrub(text: str) -> str:
    """Token-shaped strings never leave this module un-masked."""
    return _TOKEN_RE.sub('***REDACTED***', str(text or ''))


def _have_token() -> bool:
    return bool(os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN'))


def _run(argv: List[str], *, cwd: Optional[str] = None,
         timeout: float = 60.0) -> Tuple[int, str]:
    proc = subprocess.run(argv, shell=False, cwd=cwd, capture_output=True,
                          timeout=timeout)
    out = (proc.stdout or b'').decode('utf-8', errors='replace')
    err = (proc.stderr or b'').decode('utf-8', errors='replace')
    return proc.returncode, _scrub((out + ('\n' + err if err else '')).strip())


def _validate_name(name=None) -> str:
    n = str(name or '').strip()
    if not _REPO_NAME_RE.match(n):
        raise ValueError(f'invalid repository name {name!r} '
                         f'(need [A-Za-z0-9._-], starting alphanumeric)')
    return n


def github_status() -> str:
    """Presence-only auth report (no values, ever)."""
    gh = shutil.which('gh')
    git = shutil.which('git')
    token = 'set' if _have_token() else 'MISSING'
    default_vis = _cfg('github.default_visibility', 'private')
    auto_public = _cfg('github.auto_public', False)
    return (f'gh: {gh or "NOT FOUND"} | git: {git or "NOT FOUND"} | '
            f'GITHUB_TOKEN/GH_TOKEN: {token} | '
            f'default_visibility: {default_vis} | auto_public: {auto_public}')


def _create(name: Any, description: Any, *, public: bool) -> str:
    n = _validate_name(name)
    if not shutil.which('gh'):
        return f'BLOCKED: gh CLI not found on PATH — cannot create {n!r}'
    if not _have_token():
        return (f'BLOCKED: no GITHUB_TOKEN/GH_TOKEN in the environment — '
                f'cannot create {n!r} (user must provide a token)')
    argv = ['gh', 'repo', 'create', n]
    if public:
        argv.append('--public')
    else:
        argv.append('--private')
    d = str(description or '').strip()
    if d:
        argv += ['--description', d]
    rc, out = _run(argv, timeout=60.0)
    if rc != 0:
        raise RuntimeError(f'gh repo create failed (rc={rc}): {out[-500:]}')
    vis = 'PUBLIC' if public else 'private'
    return out or f'created {n} ({vis})'


def github_create_repo(name: Any, description: Any = '') -> str:
    """Create a PRIVATE repository — always (the safe default cannot be
    overridden from a tool call)."""
    return _create(name, description, public=False)


def github_create_repo_public(name: Any, description: Any = '') -> str:
    """Create a PUBLIC repository — confirm-gated (risky=True; the
    `make_public_repo` confirm category fires before this ever runs)."""
    return _create(name, description, public=True)


def github_push(remote: Any = 'origin', branch: Any = '') -> str:
    """Push the local build repo (confirm-gated: risky=True, 'push' also
    matches the publish pattern in confirm.py)."""
    if not shutil.which('git'):
        return 'BLOCKED: git not found on PATH'
    rem = str(remote or 'origin').strip() or 'origin'
    if not re.match(r'^[A-Za-z0-9._/-]{1,100}$', rem):
        raise ValueError(f'invalid remote name {remote!r}')
    argv = ['git', 'push', rem]
    b = str(branch or '').strip()
    if b:
        if not re.match(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$', b):
            raise ValueError(f'invalid branch name {branch!r}')
        argv.append(b)
    from brain import config as appcfg
    rc, out = _run(argv, cwd=str(appcfg.REPO_ROOT), timeout=120.0)
    if rc != 0:
        raise RuntimeError(f'git push failed (rc={rc}): {out[-500:]}')
    return out or f'pushed to {rem}' + (f' {b}' if b else '')


def github_set_visibility(repo: Any, visibility: Any) -> str:
    """Visibility change — ALWAYS confirm-gated (risky=True)."""
    r = str(repo or '').strip()
    if not _REPO_REF_RE.match(r):
        raise ValueError(f'invalid repo reference {repo!r} (use owner/name)')
    v = str(visibility or '').strip().lower()
    if v not in _VISIBILITY:
        raise ValueError(f'visibility must be one of {_VISIBILITY}, got {visibility!r}')
    if not shutil.which('gh'):
        return f'BLOCKED: gh CLI not found on PATH — cannot change {r}'
    if not _have_token():
        return f'BLOCKED: no GITHUB_TOKEN/GH_TOKEN — cannot change {r}'
    rc, out = _run(['gh', 'repo', 'edit', r, f'--visibility', v], timeout=60.0)
    if rc != 0:
        raise RuntimeError(f'gh repo edit failed (rc={rc}): {out[-500:]}')
    return out or f'{r} is now {v}'


def register(_reg=None) -> None:
    reg = _reg if _reg is not None and hasattr(_reg, 'register') else _tool_reg
    reg.register('github_status', github_status, risky=False, category='local',
                 description='check gh/git/token presence (values never shown)',
                 schema=SPECS['github_status'])
    reg.register('github_create_repo', github_create_repo, risky=False,
                 category='local',
                 description='create a PRIVATE GitHub repository (always private)',
                 schema=SPECS['github_create_repo'])
    reg.register('github_create_repo_public', github_create_repo_public,
                 risky=True, category='local',
                 description='create a PUBLIC GitHub repository (confirm-gated)',
                 schema=SPECS['github_create_repo_public'])
    reg.register('github_push', github_push, risky=True, category='local',
                 description='git push the local repo (confirm-gated)',
                 schema=SPECS['github_push'])
    reg.register('github_set_visibility', github_set_visibility, risky=True,
                 category='local',
                 description='change a repo public/private (confirm-gated)',
                 schema=SPECS['github_set_visibility'])


register()
