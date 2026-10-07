"""Launch actions (PROTOCOL §7): launch_url, search_youtube, open_app,
open_path, list_running_apps.

App resolution order (open_app): literal path -> PATH executables -> Start
Menu shortcuts (user + machine) -> App Paths registry -> UWP/Start apps ->
case-insensitive contains-match over all of the above. All lists come from
the winlayer backend, so tests drive resolution with a fake.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import quote_plus

try:
    from .actions import (ActionError, opt_str, register_action, req_str,
                          reject_extra)
except ImportError:  # script mode
    from actions import (ActionError, opt_str, register_action, req_str,
                         reject_extra)

_MAX_URL = 2048
_MAX_QUERY = 200
_MAX_NAME = 120
_MAX_PATH = 2048
_WS = re.compile(r'\s+')


def _normalize(name: str) -> str:
    n = _WS.sub(' ', (name or '').strip().lower())
    if n.endswith('.exe'):
        n = n[:-4]
    return n


# --------------------------------------------------------------- launch_url
def _validate_launch_url(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'url'})
    url = req_str(args, 'url', max_len=_MAX_URL)
    if any(ch.isspace() for ch in url):
        raise ValueError("field 'url' must not contain whitespace")
    scheme = url.split('://', 1)[0].lower() if '://' in url else ''
    if scheme not in ('http', 'https'):
        raise ValueError("field 'url' must be an http(s) URL")
    if not url[len(scheme) + 3:].strip('/'):
        raise ValueError("field 'url' is missing a host")
    return {'url': url}


async def _run_launch_url(args: Dict[str, Any], backend) -> Dict[str, Any]:
    await asyncio.to_thread(backend.open_url, args['url'])
    return {'opened': args['url']}


# ----------------------------------------------------------- search_youtube
def _validate_search_youtube(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'query'})
    query = req_str(args, 'query', max_len=_MAX_QUERY)
    return {'query': query}


async def _run_search_youtube(args: Dict[str, Any], backend) -> Dict[str, Any]:
    url = ('https://www.youtube.com/results?search_query='
           + quote_plus(args['query']))
    await asyncio.to_thread(backend.open_url, url)
    return {'opened': url, 'query': args['query']}


# ----------------------------------------------------------------- open_app
def _validate_open_app(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'name'})
    name = req_str(args, 'name', max_len=_MAX_NAME)
    return {'name': name}


def _resolve_source(name: str, backend):
    """(normalized, payload) lists per source — fetched lazily so an exact
    PATH hit never pays for a PowerShell UWP enumeration."""
    if name == 'path':
        return [(_normalize(c['name']), c['path'])
                for c in backend.path_commands()]
    if name == 'shortcut':
        return [(_normalize(c['name']), c['path'])
                for c in backend.start_menu_shortcuts()]
    if name == 'app_path':
        return [(_normalize(c['name']), c['path'])
                for c in backend.app_path_entries()]
    if name == 'uwp':
        return [(_normalize(c['name']), c['path'])
                for c in backend.uwp_apps()]
    raise KeyError(name)


_SOURCE_ORDER = ('path', 'shortcut', 'app_path', 'uwp')
_SOURCE_KIND = {'path': 'path', 'app_path': 'path',
                'shortcut': 'shortcut', 'uwp': 'uwp'}


def resolve_app(name: str, backend) -> Tuple[str, str]:
    """-> (kind, payload); raises ActionError('E_INTERNAL', ...) if unknown.
    kind: path | shortcut | uwp. Stages: literal path -> exact match per
    source in priority order -> prefix match -> contains match."""
    n = _normalize(name)
    # A literal filesystem path wins (relative/expansion resolved by caller).
    if os.path.sep in name or name.startswith('~'):
        expanded = os.path.expandvars(os.path.expanduser(name))
        if os.path.exists(expanded):
            return ('path', expanded)

    cache: Dict[str, List[Tuple[str, str]]] = {}

    def get(key: str) -> List[Tuple[str, str]]:
        if key not in cache:
            cache[key] = _resolve_source(key, backend)
        return cache[key]

    for key in _SOURCE_ORDER:                      # exact
        for cand_name, payload in get(key):
            if cand_name == n:
                return (_SOURCE_KIND[key], payload)
    if len(n) >= 2:
        for key in _SOURCE_ORDER:                  # prefix
            for cand_name, payload in get(key):
                if cand_name.startswith(n):
                    return (_SOURCE_KIND[key], payload)
    if len(n) >= 3:
        for key in _SOURCE_ORDER:                  # substring
            for cand_name, payload in get(key):
                if n in cand_name:
                    return (_SOURCE_KIND[key], payload)
    raise ActionError('E_INTERNAL',
                      "app not found: '%s' (tried PATH, Start Menu, "
                      "App Paths, UWP)" % _clean_name(name))


def _clean_name(name: str) -> str:
    return ''.join(ch if 32 <= ord(ch) < 127 else '?' for ch in name)[:60]


async def _run_open_app(args: Dict[str, Any], backend) -> Dict[str, Any]:
    kind, payload = await asyncio.to_thread(resolve_app, args['name'], backend)
    if kind == 'uwp':
        await asyncio.to_thread(backend.launch_uwp, payload)
    else:
        await asyncio.to_thread(backend.launch_path, payload)
    return {'launched': args['name'], 'kind': kind, 'resolved': payload}


# ---------------------------------------------------------------- open_path
def _validate_open_path(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'path'})
    path = req_str(args, 'path', max_len=_MAX_PATH)
    if path.startswith('\\\\') or path.startswith('//'):
        raise ValueError("field 'path' must be a local path (no UNC/network paths)")
    if path.lower().startswith('shell:'):
        raise ValueError("field 'path' must be a real filesystem path")
    expanded = os.path.expandvars(os.path.expanduser(path))
    if not os.path.exists(expanded):
        raise ValueError("field 'path' does not exist")
    return {'path': expanded}


async def _run_open_path(args: Dict[str, Any], backend) -> Dict[str, Any]:
    await asyncio.to_thread(backend.open_shell, args['path'])
    return {'opened': args['path']}


# ---------------------------------------------------------- list_running_apps
def _validate_list_running(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, set())
    return {}


async def _run_list_running(args: Dict[str, Any], backend) -> Dict[str, Any]:
    procs = await asyncio.to_thread(backend.list_processes)
    windows = await asyncio.to_thread(backend.list_windows)
    titles: Dict[int, List[str]] = {}
    for w in windows:
        if w.get('title'):
            titles.setdefault(int(w.get('pid') or 0), []).append(w['title'])
    grouped: Dict[str, Dict[str, Any]] = {}
    for p in procs:
        name = str(p.get('name') or '').strip()
        if not name:
            continue
        key = name.lower()
        g = grouped.setdefault(key, {'name': name, 'pids': [], 'windows': []})
        g['pids'].append(int(p.get('pid') or 0))
        for t in titles.get(int(p.get('pid') or 0), []):
            if t not in g['windows']:
                g['windows'].append(t)
    apps = sorted(grouped.values(),
                  key=lambda g: (0 if g['windows'] else 1, g['name'].lower()))
    total = len(apps)
    apps = apps[:150]
    for g in apps:
        g['processes'] = len(g['pids'])
        g['pids'] = g['pids'][:8]
        g['windows'] = g['windows'][:4]
    return {'count': total, 'apps': apps,
            **({'truncated': True} if total > len(apps) else {})}


register_action('launch_url', _run_launch_url, validate=_validate_launch_url,
                needs_lock=False, confirm=None,
                describe='Open an absolute http(s) URL in the default browser.')
register_action('search_youtube', _run_search_youtube,
                validate=_validate_search_youtube, needs_lock=False, confirm=None,
                describe='Open YouTube search results for a query string.')
register_action('open_app', _run_open_app, validate=_validate_open_app,
                needs_lock=False, confirm=None,
                describe="Launch a Windows app by name (Start Menu/PATH/"
                         "App Paths/UWP resolution).")
register_action('open_path', _run_open_path, validate=_validate_open_path,
                needs_lock=False, confirm=None,
                describe='Open an existing local file/folder with its default handler.')
register_action('list_running_apps', _run_list_running,
                validate=_validate_list_running, needs_lock=False, confirm=None,
                describe='List running applications with their window titles.')
