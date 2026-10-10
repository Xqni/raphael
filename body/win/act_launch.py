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
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

try:
    from .actions import (offload, ActionError, opt_str, register_action,
                          req_str, reject_extra)
    from .act_input import _chord
except ImportError:  # script mode
    from actions import (offload, ActionError, opt_str, register_action, req_str,
                         reject_extra)
    from act_input import _chord

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
    await offload(backend.open_url, args['url'])
    return {'opened': args['url']}


# ----------------------------------------------------------- search_youtube
def _validate_search_youtube(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'query'})
    query = req_str(args, 'query', max_len=_MAX_QUERY)
    return {'query': query}


async def _run_search_youtube(args: Dict[str, Any], backend) -> Dict[str, Any]:
    url = ('https://www.youtube.com/results?search_query='
           + quote_plus(args['query']))
    await offload(backend.open_url, url)
    return {'opened': url, 'query': args['query']}


# ----------------------------------------------------------------- open_app
_SENSITIVE_CACHE: Optional[List[str]] = None


def sensitive_apps() -> List[str]:
    """`privacy.blocklist_apps` from config.yaml (AUD-11 sensitive boundary).

    yaml is optional → empty list in minimal test envs (no false refusals);
    tests inject via `monkeypatch.setattr(act_launch, '_SENSITIVE_CACHE', [...])`."""
    global _SENSITIVE_CACHE
    if _SENSITIVE_CACHE is None:
        apps: List[str] = []
        try:
            import pathlib
            import yaml
            cfg_path = pathlib.Path(__file__).resolve().parents[2] / 'config.yaml'
            if cfg_path.is_file():
                cfg = yaml.safe_load(cfg_path.read_text()) or {}
                apps = [str(a) for a in
                        ((cfg.get('privacy') or {}).get('blocklist_apps') or [])]
        except Exception:  # noqa: BLE001 — no yaml/no config → no refusals
            apps = []
        _SENSITIVE_CACHE = apps
    return _SENSITIVE_CACHE


def _validate_open_app(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'name'})
    name = req_str(args, 'name', max_len=_MAX_NAME)
    # AUD-11 sensitive boundary: refuses BEFORE any resolution/backend call;
    # the confirm-gated open_path is the sanctioned route for these.
    low = name.lower()
    for entry in sensitive_apps():
        if entry.lower() and entry.lower() in low:
            raise ValueError(
                "app matches sensitive entry '%s' (privacy.blocklist_apps) — "
                "launch it via open_path, which requires confirmation"
                % entry)
    return {'name': name}


# Console-script suffixes are excluded from launch candidates: running them
# flashes a cmd window (BUGS-WAVE2 Bug B "blank Windows terminal"). Users
# can still open such a file explicitly via open_path (default handler).
_CONSOLE_SCRIPTS = ('.bat', '.cmd', '.ps1', '.vbs', '.wsf')


def _resolve_source(name: str, backend):
    """(normalized, payload) lists per source — fetched lazily so an exact
    PATH hit never pays for a PowerShell UWP enumeration."""
    if name == 'path':
        return [(_normalize(c['name']), c['path'])
                for c in backend.path_commands()
                if not str(c.get('path', '')).lower().endswith(_CONSOLE_SCRIPTS)]
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
    kind: path | shortcut | uwp. Stages: exact match per source in priority
    order -> prefix match -> contains match.

    AUD-11: TRUSTED launches only — curated sources (PATH, Start Menu,
    App Paths, UWP). Literal filesystem paths are deliberately NOT resolved
    here; they go through open_path, which is confirmation-gated
    (confirm='open_arbitrary_file')."""
    n = _normalize(name)
    if os.path.sep in name or name.startswith('~') or ':' in name.split(os.path.sep)[0]:
        # path-like input: refuse at the trusted boundary (arbitrary
        # exe/document execution must clear the open_path confirmation).
        raise ActionError(
            'E_INTERNAL',
            "open_app only launches curated apps — literal paths are not "
            "resolved here; use open_path (confirmation-gated) for "
            "arbitrary files/executables")

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
    # Precise, stage-counted failure (Bug B: the gate saw an opaque
    # "open_app failed" — the error now says exactly what was searched).
    raise ActionError(
        'E_INTERNAL',
        "app not found: '%s' (tried %d PATH, %d Start Menu, %d App Paths, "
        "%d UWP candidates; console scripts excluded)"
        % (_clean_name(name), len(get('path')), len(get('shortcut')),
           len(get('app_path')), len(get('uwp'))))


def _clean_name(name: str) -> str:
    return ''.join(ch if 32 <= ord(ch) < 127 else '?' for ch in name)[:60]


async def _run_open_app(args: Dict[str, Any], backend) -> Dict[str, Any]:
    kind, payload = await offload(resolve_app, args['name'], backend)
    if kind == 'uwp':
        await offload(backend.launch_uwp, payload)
    else:
        await offload(backend.launch_path, payload)
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
    await offload(backend.open_shell, args['path'])
    return {'opened': args['path']}


# ---------------------------------------------------------- list_running_apps
def _validate_list_running(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, set())
    return {}


async def _run_list_running(args: Dict[str, Any], backend) -> Dict[str, Any]:
    procs = await offload(backend.list_processes)
    windows = await offload(backend.list_windows)
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


# ---------------------------------------------------------- navigate_url ---
# P0 UX (coord inbox [42], user-reported): "open youtube" + "search X" must
# NAVIGATE IN PLACE, not spawn a second tab. Browsers are identified by
# process basename; the FOREGROUND browser wins, else the topmost (z-order)
# window from EnumWindows. First-ever open (no browser anywhere) still
# launches via the default handler — no confirmation needed (the URL is
# scheme-validated http/https only).
_BROWSERS = frozenset({
    'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe',
    'opera gx.exe', 'vivaldi.exe', 'waterfox.exe', 'floorp.exe',
})
_SETTLE_S = 0.12            # activation settle before Ctrl+L
_POST_TYPE_S = 0.05         # address bar catches up before Enter


def _browser_of(win: Any) -> bool:
    proc = str((win or {}).get('process') or '').lower()
    return proc in _BROWSERS and bool(str((win or {}).get('title') or '').strip())


def _validate_navigate_url(args: Dict[str, Any]) -> Dict[str, Any]:
    return _validate_launch_url(args)      # same http(s)-only guard


async def _run_navigate_url(args: Dict[str, Any], backend) -> Any:
    url = args['url']
    windows = await offload(backend.list_windows)
    fg = await offload(backend.foreground)
    fg_hwnd = (fg or {}).get('hwnd')
    if _browser_of(fg):
        target = fg                        # the visible foreground tab
    else:
        # z-order first candidate (EnumWindows order) — deterministic pick,
        # so the target is always identifiable (no confirm needed per spec)
        target = next((w for w in windows if _browser_of(w)), None)
    if target is None:
        await offload(backend.open_url, url)   # first-ever open: launch
        return {'mode': 'launch', 'opened': url}
    hwnd = target.get('hwnd')
    if hwnd != fg_hwnd:
        await offload(backend.focus_window, hwnd)
        await asyncio.sleep(_SETTLE_S)
    # Input-lock path (needs_lock=True): Ctrl+L -> type URL -> Enter.
    # Inline on purpose: ordered input must run under the held lock exactly
    # like act_input's atomic units.
    try:
        _chord(backend, 'ctrl+l')
        backend.type_text(url)
        await asyncio.sleep(_POST_TYPE_S)
        _chord(backend, 'enter')
    except Exception as e:
        raise ActionError('E_INTERNAL',
                          'navigate-in-place failed (%s) — URL not opened'
                          % type(e).__name__)
    return {'mode': 'reuse', 'hwnd': hwnd, 'process': target.get('process')}


register_action('launch_url', _run_launch_url, validate=_validate_launch_url,
                needs_lock=False, confirm=None,
                describe='Open an absolute http(s) URL in the default browser.')
register_action('navigate_url', _run_navigate_url,
                validate=_validate_navigate_url, needs_lock=True, confirm=None,
                describe='Open a URL NAVIGATING IN PLACE (P0 UX [42]): '
                         'reuses the foreground/visible browser tab via '
                         'Ctrl+L + type + Enter under the input lock; '
                         'first-ever open (no browser window) launches the '
                         'default handler. Prefer over launch_url for any '
                         'browser navigation.')
register_action('search_youtube', _run_search_youtube,
                validate=_validate_search_youtube, needs_lock=False, confirm=None,
                describe='Open YouTube search results for a query string.')
register_action('open_app', _run_open_app, validate=_validate_open_app,
                needs_lock=False, confirm=None,
                describe="Launch a CURATED Windows app by name (Start Menu/"
                         "PATH/App Paths/UWP only — literal paths and "
                         "privacy.blocklist_apps entries are refused and go "
                         "through the confirmation-gated open_path).")
register_action('open_path', _run_open_path, validate=_validate_open_path,
                needs_lock=False, confirm='open_arbitrary_file',
                describe='Open an existing local file/folder with its default '
                         'handler (arbitrary exe/document/handler-open — '
                         'AUD-11 confirm-gated).')
register_action('list_running_apps', _run_list_running,
                validate=_validate_list_running, needs_lock=False, confirm=None,
                describe='List running applications with their window titles.')
