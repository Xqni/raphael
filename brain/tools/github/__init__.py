"""github tools — authenticated `gh` CLI wrappers (SEC-4 hardened, 2026-10-07).

SEC-4 policy (docs/security/pat-scope.md + audit packet docs/audit-tasks/tools-memory.md):

- **THERE ARE ONLY TWO TOOLS: `github_status` + `github_push`.**
  - repo creation (incl. public) REMOVED: `POST/user/repos` requires
    `Administration: write` (GitHub docs, permissions-required-for-fine-grained-
    personal-access-tokens) and the packet PAT grants NO Administration — a
    token-created repo is impossible by design, so **creation is a HUMAN user
    action** (create it private in the UI; it lands in Selected repositories);
  - `github_set_visibility` REMOVED: `gh repo edit --visibility` also requires
    Administration: write — visibility changes are REFUSED entirely (as are
    repo deletion and settings changes: no such tool exists, grep-verified);
  - `github_push` stays `risky=True` — every push is confirm-gated in code
    (brain/confirm.py), never left to a model's judgment.
- Tokens: presence-checked value-blind ONLY (`github_status` prints
  `set`/`MISSING`, never a value) and every subprocess output passes `_scrub()`
  so token-shaped strings can never reach logs or tool output (AGENT_RULES §7).
- argv lists only (`shell=False`).

Registry note: `SPECS` must stay in exact sync with registrations — the
discovery walker rejects SPECS entries without a registered tool (loudly).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, List, Optional, Tuple

import brain.tools as _tool_reg

_TOKEN_RE = re.compile(
    r'gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|'
    r'AKIA[0-9A-Z]{16}')

SPECS = {
    'github_status': {
        'type': 'object', 'properties': {}, 'required': [],
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


def github_status() -> str:
    """Presence-only auth report (value-blind — never prints the token)."""
    gh = shutil.which('gh')
    git = shutil.which('git')
    token = 'set' if _have_token() else 'MISSING'
    default_vis = _cfg('github.default_visibility', 'private')
    auto_public = _cfg('github.auto_public', False)
    return (f'gh: {gh or "NOT FOUND"} | git: {git or "NOT FOUND"} | '
            f'GITHUB_TOKEN/GH_TOKEN: {token} | '
            f'default_visibility: {default_vis} | auto_public: {auto_public} | '
            f'repo creation/visibility: HUMAN action (SEC-4)')


def github_push(remote: Any = 'origin', branch: Any = '') -> str:
    """Push the local build repo — CONFIRM-GATED (risky=True in the registry;
    confirm.py also pattern-matches 'push' as publish)."""
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


def register(_reg=None) -> None:
    reg = _reg if _reg is not None and hasattr(_reg, 'register') else _tool_reg
    reg.register('github_status', github_status, risky=False, category='local',
                 confirm='read_only',
                 description='check gh/git/token presence (values never shown); '
                             'repo creation/visibility is a human action',
                 schema=SPECS['github_status'])
    reg.register('github_push', github_push, risky=True, category='local',
                 confirm='web_publish',
                 description='git push the local repo (confirm-gated)',
                 schema=SPECS['github_push'])


register()
