"""Fake Windows backend for tests and the mock e2e harness.

Binds over `winlayer.set_backend()` so every act_req handler runs to
completion WITHOUT touching a real OS: no input injection, no subprocess, no
network. Records every call in `events` as `(method, args_tuple)` so tests
can assert ordering/atomicity.

This module is test support that ships in body/win (documented in
docs/lanes/pc-control.md); the live Body never binds it — `winlayer.
get_backend()` only auto-selects WindowsBackend on `os.name == 'nt'`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    from .winlayer import BackendError
except ImportError:  # script mode
    from winlayer import BackendError


class FakeWin:
    """Configurable in-memory stand-in for WindowsBackend."""

    name = 'fake'

    def __init__(self, **overrides: Any):
        self.events: List[Tuple[str, tuple]] = []
        # --- configurable state -----------------------------------------
        self.windows: List[Dict[str, Any]] = overrides.pop('windows', [
            {'hwnd': 1001, 'title': 'Untitled - Notepad', 'pid': 10,
             'process': 'notepad.exe',
             'rect': {'left': 0, 'top': 0, 'right': 800, 'bottom': 600,
                      'width': 800, 'height': 600},
             'visible': True},
            {'hwnd': 1002, 'title': 'YouTube - Chromium', 'pid': 20,
             'process': 'chrome.exe',
             'rect': {'left': 100, 'top': 100, 'right': 1500, 'bottom': 900,
                      'width': 1400, 'height': 800},
             'visible': True},
        ])
        self.foreground_window = overrides.pop('foreground_window',
                                               self.windows[0])
        self.processes = overrides.pop('processes', [
            {'pid': 10, 'name': 'notepad.exe'},
            {'pid': 20, 'name': 'chrome.exe'},
            {'pid': 30, 'name': 'Spotify.exe'},
        ])
        self.paths = overrides.pop('paths', [
            {'name': 'notepad', 'path': 'C:\\Windows\\System32\\notepad.exe'},
            {'name': 'pwsh', 'path': 'C:\\Program Files\\PowerShell\\pwsh.exe'},
        ])
        self.shortcuts = overrides.pop('shortcuts', [
            {'name': 'Notepad', 'path': 'C:\\StartMenu\\Notepad.lnk'},
            {'name': 'Spotify', 'path': 'C:\\StartMenu\\Spotify.lnk'},
        ])
        self.app_paths = overrides.pop('app_paths', [
            {'name': 'chrome.exe', 'path': 'C:\\Chrome\\chrome.exe'},
        ])
        self.uwp = overrides.pop('uwp', [
            {'name': 'Calculator',
             'path': 'Microsoft.WindowsCalculator_8wekyb3d8bbwe!App'},
        ])
        self.clipboard_value: str = overrides.pop('clipboard', '')
        self.volume: Optional[int] = None
        self.brightness: Optional[int] = None
        self.cursor: Tuple[int, int] = overrides.pop('cursor', (100, 100))
        self.powershell_result: Dict[str, Any] = overrides.pop(
            'powershell_result', {'rc': 0, 'out': '[]', 'err': ''})
        self.uia_data: Dict[str, Any] = overrides.pop('uia_data', {})
        # --- failure injection ------------------------------------------
        self.fail_methods: set = set()          # BackendError on these calls
        self.fail_key_down_vk: Optional[int] = None
        self.delays: Dict[str, float] = {}      # method -> seconds (timeout drills)
        if overrides:
            raise TypeError('unknown FakeWin overrides: %s'
                            % ', '.join(sorted(overrides)))

    # -- recording helper -------------------------------------------------
    def _rec(self, method: str, *args: Any) -> None:
        # Record FIRST (the call happened), then apply delay/failure
        # injection — a crashed call stays observable in the audit trail.
        self.events.append((method, args))
        self._maybe_fail(method)

    def calls(self, method: str) -> List[tuple]:
        return [args for name, args in self.events if name == method]

    def _maybe_fail(self, method: str) -> None:
        delay = self.delays.get(method)
        if delay:
            import time
            time.sleep(delay)
        if method in self.fail_methods:
            raise BackendError('injected failure in %s' % method)

    # -- keyboard / mouse -------------------------------------------------
    def type_text(self, text: str, pause: float = 0.0) -> None:
        self._rec('type_text', text)

    def key_down(self, vk: int) -> None:
        self._rec('key_down', vk)
        if self.fail_key_down_vk is not None and vk == self.fail_key_down_vk:
            raise BackendError('injected key_down failure')

    def key_up(self, vk: int) -> None:
        self._rec('key_up', vk)

    def mouse_position(self) -> Tuple[int, int]:
        self._rec('mouse_position')
        return self.cursor

    def mouse_move(self, x: int, y: int) -> None:
        self._rec('mouse_move', x, y)
        self.cursor = (x, y)

    def mouse_move_rel(self, dx: int, dy: int) -> None:
        self._rec('mouse_move_rel', dx, dy)
        self.cursor = (self.cursor[0] + dx, self.cursor[1] + dy)

    def mouse_click(self, button: str = 'left', x: Optional[int] = None,
                    y: Optional[int] = None, clicks: int = 1) -> None:
        self._rec('mouse_click', button, x, y, clicks)
        if x is not None and y is not None:
            self.cursor = (x, y)

    def mouse_down(self, button: str = 'left') -> None:
        self._rec('mouse_down', button)

    def mouse_up(self, button: str = 'left') -> None:
        self._rec('mouse_up', button)

    def mouse_scroll(self, amount: int) -> None:
        self._rec('mouse_scroll', amount)

    # -- windows ----------------------------------------------------------
    def foreground(self) -> Optional[Dict[str, Any]]:
        self._rec('foreground')
        return self.foreground_window

    def list_windows(self) -> List[Dict[str, Any]]:
        self._rec('list_windows')
        return list(self.windows)

    def focus_window(self, hwnd: int) -> None:
        self._rec('focus_window', hwnd)
        for w in self.windows:
            if w['hwnd'] == hwnd:
                self.foreground_window = w
                break

    def show_window(self, hwnd: int, mode: str) -> None:
        self._rec('show_window', hwnd, mode)

    def window_rect(self, hwnd: int) -> Dict[str, int]:
        self._rec('window_rect', hwnd)
        return {'left': 0, 'top': 0, 'right': 100, 'bottom': 100,
                'width': 100, 'height': 100}

    def snap_window(self, hwnd: int, zone: str) -> Dict[str, int]:
        self._rec('snap_window', hwnd, zone)
        return {'left': 0, 'top': 0, 'right': 960, 'bottom': 1080,
                'width': 960, 'height': 1080}

    # -- apps / processes -------------------------------------------------
    def start_menu_shortcuts(self) -> List[Dict[str, str]]:
        self._rec('start_menu_shortcuts')
        return list(self.shortcuts)

    def resolve_lnk(self, path: str) -> Optional[str]:
        self._rec('resolve_lnk', path)
        return path[:-4] + '.exe' if path.endswith('.lnk') else path

    def path_commands(self) -> List[Dict[str, str]]:
        self._rec('path_commands')
        return list(self.paths)

    def app_path_entries(self) -> List[Dict[str, str]]:
        self._rec('app_path_entries')
        return list(self.app_paths)

    def uwp_apps(self) -> List[Dict[str, str]]:
        self._rec('uwp_apps')
        return list(self.uwp)

    def launch_path(self, path: str, args: Optional[List[str]] = None) -> None:
        self._rec('launch_path', path, args)

    def launch_uwp(self, app_id: str) -> None:
        self._rec('launch_uwp', app_id)

    def open_url(self, url: str) -> None:
        self._rec('open_url', url)

    def open_shell(self, target: str) -> None:
        self._rec('open_shell', target)

    def list_processes(self) -> List[Dict[str, Any]]:
        self._rec('list_processes')
        return list(self.processes)

    # -- system -----------------------------------------------------------
    def clipboard_get(self) -> str:
        self._rec('clipboard_get')
        return self.clipboard_value

    def clipboard_set(self, text: str) -> None:
        self._rec('clipboard_set', text)
        self.clipboard_value = text

    def set_volume(self, level: int) -> None:
        self._rec('set_volume', level)
        self.volume = level

    def set_brightness(self, level: int) -> None:
        self._rec('set_brightness', level)
        self.brightness = level

    def media_key(self, op: str) -> None:
        self._rec('media_key', op)

    def notify(self, text: str) -> None:
        self._rec('notify', text)

    def powershell(self, argv: List[str], env: Dict[str, str],
                   timeout_s: float) -> Dict[str, Any]:
        self._rec('powershell', list(argv), dict(env), timeout_s)
        return dict(self.powershell_result)

    # -- UIA --------------------------------------------------------------
    def uia_find(self, selector: Dict[str, Any],
                 timeout_s: float) -> Optional[Dict[str, Any]]:
        self._rec('uia_find', dict(selector), timeout_s)
        return self.uia_data.get('find')

    def uia_click(self, selector: Dict[str, Any], timeout_s: float,
                  button: str = 'left') -> Dict[str, Any]:
        self._rec('uia_click', dict(selector), timeout_s, button)
        if self.uia_data.get('find') is None:
            raise BackendError('element not found: %s' % selector)
        return self.uia_data['find']

    def uia_type(self, selector: Dict[str, Any], text: str, clear: bool,
                 timeout_s: float) -> Dict[str, Any]:
        self._rec('uia_type', dict(selector), text, clear, timeout_s)
        if self.uia_data.get('find') is None:
            raise BackendError('element not found: %s' % selector)
        return self.uia_data['find']

    def uia_read(self, selector: Dict[str, Any],
                 timeout_s: float) -> Dict[str, Any]:
        self._rec('uia_read', dict(selector), timeout_s)
        if self.uia_data.get('find') is None:
            raise BackendError('element not found: %s' % selector)
        return dict(self.uia_data['find'],
                    texts=self.uia_data.get('texts', ['sample text']))

    def uia_tree(self, selector: Dict[str, Any], depth: int,
                 timeout_s: float) -> Dict[str, Any]:
        self._rec('uia_tree', dict(selector), depth, timeout_s)
        if self.uia_data.get('find') is None:
            raise BackendError('element not found: %s' % selector)
        return dict(self.uia_data['find'],
                    children=self.uia_data.get('children', []),
                    truncated=False)

    # -- capture ----------------------------------------------------------
    def capture(self, max_px: int, quality: int) -> bytes:
        self._rec('capture', max_px, quality)
        return b'\xff\xd8' + b'FAKEJPEG' * 32 + b'\xff\xd9'
