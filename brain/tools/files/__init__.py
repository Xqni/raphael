"""file tools — search / read / write + TRASH (never delete).

INTERFACES §(b) self-registration (discovery calls `register()`).

Safety rules (docs/lanes/tools-memory.md §3.2):
- **there is NO delete tool, ever** — `file_trash` MOVES a path into the
  instance trash dir (`<data-dir>/trash/<entry>/` + meta.json origin) and
  `file_restore` moves it back; nothing ever calls os.remove on user files;
- every path is `resolve()`d and must land inside `files.allowed_roots`
  (symlinks cannot escape);
- secret files (.env*, *.key, *.p12, id_rsa* …) are refused for BOTH read
  and write (AGENT_RULES §7 — the tools never touch key material);
- reads are capped (`files.read_max_bytes`), binaries refused (NUL sniff),
  decode uses errors='replace' (mojibake never crashes a job);
- output is plain text = untrusted data (the loop wraps it, AGENT_RULES §9).
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import List

import brain.tools as _tool_reg

_SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.cache',
              '.tox', '.mypy_cache', '.pytest_cache'}
# AUD-01: the sensitive DENY is resolved-path based and applies INSIDE every
# allowed root (widening roots must never reach these). Deny dirs are matched
# on ANY path component (case-insensitive); deny names on the basename.
_DENY_DIRS = {'.ssh', '.gnupg', '.aws', '.docker', '.kube', '.raphael',
              'dropbox', 'nextcloud', 'google drive', 'onedrive'}
_DENY_NAMES = {'.env', 'secrets.env', '.secrets', 'id_rsa', 'id_dsa',
               'id_ecdsa', 'id_ed25519', '.npmrc', '.netrc',
               'token', '.token', 'credentials', 'credentials.json',
               'authorized_keys'}
_SECRET_SUFFIXES = ('.key', '.pfx', '.p12', '.keystore', '.jks', '.pem', '.ppk')
_MAX_SCAN = 50000             # walk bound (correctness guard, not tuning)

SPECS = {
    'file_search': {
        'type': 'object',
        'properties': {
            'root': {'type': 'string', 'description':
                     'directory to search (must be inside allowed_roots)'},
            'pattern': {'type': 'string', 'description':
                        'glob matched against basename or full path, e.g. "*.pdf"'},
            'limit': {'type': 'integer', 'description':
                      'max matches to return (default 50)'},
        },
        'required': ['root', 'pattern'],
        'additionalProperties': False,
    },
    'file_read': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'description': 'file to read'},
            'offset': {'type': 'integer', 'description':
                       '0-based first line to return (default 0)'},
            'limit': {'type': 'integer', 'description':
                      'max lines to return (default 200)'},
        },
        'required': ['path'],
        'additionalProperties': False,
    },
    'file_write': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'description': 'file to write (parent dir must exist)'},
            'content': {'type': 'string', 'description': 'text to write'},
            'append': {'type': 'boolean', 'description':
                       'append instead of overwrite (default false)'},
        },
        'required': ['path', 'content'],
        'additionalProperties': False,
    },
    'file_trash': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'description':
                     'file or directory to MOVE to trash (recoverable, never deleted)'},
        },
        'required': ['path'],
        'additionalProperties': False,
    },
    'file_restore': {
        'type': 'object',
        'properties': {
            'trash_id': {'type': 'string', 'description':
                         'trash entry id returned by file_trash'},
        },
        'required': ['trash_id'],
        'additionalProperties': False,
    },
}


# ---- guards -----------------------------------------------------------------
def _cfg(dotted: str, default):
    try:
        from brain import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def _allowed_roots() -> List[Path]:
    # AUD-01: the default is the explicit app workspace — NEVER "~" (a
    # default of "~" put ~/.raphael/token inside reach).
    raw = _cfg('files.allowed_roots', ['~/raphael-wt', '~/raphael']) or \
        ['~/raphael-wt', '~/raphael']
    roots: List[Path] = []
    for r in raw:
        try:
            roots.append(Path(str(r)).expanduser().resolve())
        except Exception:  # noqa: BLE001 — bad config entry: skip it
            continue
    return roots


def _is_denied(p: Path) -> bool:
    """Sensitive-path deny (AUD-01): token/ssh/gnupg/cloud-store/secret —
    resolved-path based, applies inside ANY allowed root."""
    parts_l = {part.lower() for part in p.parts}
    if parts_l & _DENY_DIRS:
        return True
    name_l = p.name.lower()
    return (name_l in _DENY_NAMES or name_l.startswith('.env')
            or name_l.endswith(_SECRET_SUFFIXES))


def _resolve_in_roots(path: Any) -> Path:
    p = Path(str(path)).expanduser().resolve()      # symlinks resolved FIRST
    for root in _allowed_roots():
        if p == root or root in p.parents:
            if _is_denied(p):
                raise ValueError(
                    f'{p} is on the sensitive deny-list (AUD-01: tokens, '
                    f'ssh/gnupg/cloud stores, key material are never touched '
                    f'by the file tools)')
            return p
    allowed = ', '.join(str(r) for r in _allowed_roots()) or '(none)'
    raise ValueError(f'{p} is outside files.allowed_roots [{allowed}]')


def _is_secret(p: Path) -> bool:
    name = p.name
    return (name in _DENY_NAMES or name.startswith('.env')
            or name.endswith(_SECRET_SUFFIXES))


def _require_secret_free(p: Path) -> None:
    if _is_secret(p):
        raise ValueError(f'{name_of(p)} looks like secret material — '
                         f'the file tools never touch key/env files')


def name_of(p: Path) -> str:
    return p.name


def _trash_root() -> Path:
    from brain import config as appcfg
    return appcfg.data_dir() / 'trash'


# ---- tools ------------------------------------------------------------------
def file_search(root: str, pattern: str, limit: int = 50) -> str:
    """Glob-search under `root` (allowed roots only), skipping junk dirs."""
    base = _resolve_in_roots(root)
    if not base.is_dir():
        raise ValueError(f'{base} is not a directory')
    if not pattern:
        raise ValueError('pattern must be non-empty')
    limit = max(1, min(int(limit or 50), 500))
    hits: List[str] = []
    scanned = 0
    for dirpath, dirnames, filenames in base.walk() if hasattr(base, 'walk') else _walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            scanned += 1
            if scanned > _MAX_SCAN:
                hits.append(f'… scan cap {_MAX_SCAN} reached')
                return '\n'.join(hits)
            full_path = Path(dirpath) / fn
            if _is_denied(full_path):           # AUD-01: never even listed
                continue
            full = str(full_path)
            if fnmatch.fnmatch(fn, pattern) or fnmatch.fnmatch(full, pattern):
                hits.append(full)
                if len(hits) >= limit:
                    return '\n'.join(hits)
    return '\n'.join(hits) if hits else f'no matches for {pattern!r} under {base}'


def _walk(base: Path):
    import os
    for dirpath, dirnames, filenames in os.walk(base):
        yield Path(dirpath), dirnames, filenames


def file_read(path: str, offset: int = 0, limit: int = 200) -> str:
    p = _resolve_in_roots(path)
    _require_secret_free(p)
    if not p.is_file():
        raise ValueError(f'{p} is not a file')
    max_bytes = int(_cfg('files.read_max_bytes', 262144) or 262144)
    data = p.read_bytes()[:max_bytes]
    if b'\x00' in data[:8192]:
        raise ValueError(f'{p} is a binary file — refusing (use an image/vision tool)')
    text = data.decode('utf-8', errors='replace')
    lines = text.splitlines()
    start = max(0, int(offset or 0))
    count = max(1, int(limit or 200))
    chunk = lines[start:start + count]
    trunc = f', TRUNCATED at {max_bytes} bytes' if len(data) >= max_bytes else ''
    header = f'{p} (lines {start + 1}-{start + len(chunk)} of {len(lines)}{trunc})'
    if not chunk:
        return f'{p}: no lines at offset {start} (file has {len(lines)} lines)'
    return header + '\n' + '\n'.join(chunk)


def file_write(path: str, content: str, append: bool = False) -> str:
    p = _resolve_in_roots(path)
    _require_secret_free(p)
    if not p.parent.is_dir():
        raise ValueError(f'parent directory does not exist: {p.parent}')
    data = str(content)
    existed = p.exists()
    mode = 'a' if append else 'w'
    with p.open(mode, encoding='utf-8') as f:
        f.write(data)
    verb = 'appended' if append else ('overwrote' if existed else 'wrote')
    return f'{verb} {len(data)} chars to {p}'


def file_trash(path: str) -> str:
    """MOVE to the instance trash (recoverable). Confirm-gated via registry
    `risky=True` (maps to the delete_files confirm category)."""
    p = _resolve_in_roots(path)
    _require_secret_free(p)
    if not p.exists():
        raise ValueError(f'{p} does not exist')
    entry = _trash_root() / f'{int(time.time())}_{uuid.uuid4().hex[:8]}_{p.name}'
    entry.mkdir(parents=True, exist_ok=True)
    dest = entry / p.name
    shutil.move(str(p), str(dest))
    meta = {'origin': str(p), 'moved_at': int(time.time())}
    (entry / 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
    return f'trashed {p} -> {entry.name} (restore with file_restore)'


def file_restore(trash_id: str) -> str:
    tid = str(trash_id or '').strip()
    if not tid or '/' in tid or '\\' in tid or tid in ('.', '..'):
        raise ValueError(f'invalid trash_id {trash_id!r}')
    entry = _trash_root() / tid
    meta_path = entry / 'meta.json'
    if not meta_path.is_file():
        raise ValueError(f'no trash entry {tid!r}')
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    origin = Path(meta.get('origin', '')).resolve()
    _resolve_in_roots(str(origin))          # refuse restoring outside roots
    if origin.exists():
        raise ValueError(f'cannot restore: {origin} already exists again')
    origin.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(entry / origin.name), str(origin))
    shutil.rmtree(entry, ignore_errors=True)
    return f'restored {origin}'


def register(_reg=None) -> None:
    reg = _reg if _reg is not None and hasattr(_reg, 'register') else _tool_reg
    reg.register('file_search', file_search, risky=False, category='local',
                 description='glob-search files under an allowed directory',
                 schema=SPECS['file_search'])
    reg.register('file_read', file_read, risky=False, category='local',
                 description='read a text file (capped; secret files refused)',
                 schema=SPECS['file_read'])
    reg.register('file_write', file_write, risky=True, category='local',
                 description='write/append a text file inside allowed roots '
                             '(CONFIRM-gated per AUD-01; sensitive paths denied)',
                 schema=SPECS['file_write'])
    reg.register('file_trash', file_trash, risky=True, category='local',
                 description='MOVE a path to trash (recoverable; confirm-gated) '
                             '— there is no delete tool',
                 schema=SPECS['file_trash'])
    reg.register('file_restore', file_restore, risky=False, category='local',
                 description='restore a trashed path by its trash id',
                 schema=SPECS['file_restore'])


register()
