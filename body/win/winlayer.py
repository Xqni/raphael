"""Windows backend seam for the Body (pc-control lane).

Every OS call the `act_req` handlers need goes through ONE backend object:

* unit tests and the mock e2e bind a `FakeWin` — no Windows, no input ever
  injected (AGENT_RULES §5 / lane rule "never inject real input outside mocks");
* `WindowsBackend` implements the calls with stdlib `ctypes` where possible
  and lazy imports (pywinauto UIA, pywin32 clipboard, comtypes volume, mss
  capture) INSIDE methods — importing this module is side-effect free on any
  OS, including no pip installs;
* `NullBackend` answers loudly on non-Windows hosts so a mis-routed live call
  fails with a clear error instead of a half-executed action.

Nothing here is ever called with a held input lock unless the dispatcher
says so (PROTOCOL §7); the mouse/keyboard methods are the only input
injection points in the Body.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

# Key names accepted by `input{keys:[...]}` -> Windows virtual-key codes.
# Only this fixed vocabulary crosses the wire — no raw scan codes, no
# arbitrary SendInput payloads (PROTOCOL §7: structured args only).
KEYMAP: Dict[str, int] = {
    # VK_A..VK_Z are 0x41..0x5A for BOTH cases (not ASCII codes!).
    **{chr(ord('a') + i): 0x41 + i for i in range(26)},
    **{chr(ord('A') + i): 0x41 + i for i in range(26)},
    **{str(d): 0x30 + d for d in range(10)},
    **{'f%d' % i: 0x70 + i - 1 for i in range(1, 13)},
    'enter': 0x0D, 'tab': 0x09, 'esc': 0x1B, 'escape': 0x1B,
    'space': 0x20, 'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D,
    'home': 0x24, 'end': 0x23, 'pgup': 0x21, 'pgdn': 0x22,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12, 'win': 0x5B,
    'capslock': 0x14,
}
# Modifiers may only appear BEFORE the final key of a chord; they are always
# released (finally) so a failed unit can never leave Ctrl stuck down.
MODIFIERS: set = {'ctrl', 'shift', 'alt', 'win'}

# media{op} -> Windows virtual-key codes (synthesized keystrokes).
MEDIA_KEYS: Dict[str, int] = {
    'play_pause': 0xB3, 'stop': 0xB2, 'next': 0xB4, 'prev': 0xB1,
    'vol_up': 0xAF, 'vol_down': 0xAE, 'mute': 0xAD,
}


class BackendError(RuntimeError):
    """A backend call failed or is unavailable on this host."""


def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):
    """Import-or-install, PINNED (security: unpinned runtime pip = supply
    chain). Only ever reached from inside a WindowsBackend method."""
    try:
        __import__(import_name or pkg)
    except ImportError:
        import subprocess
        import sys
        subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                               '--quiet',
                               ('%s==%s' % (pkg, pin)) if pin else pkg])
        __import__(import_name or pkg)


def _sibling(name: str):
    """Import a body/win sibling module in package AND script mode."""
    import importlib
    if __package__:
        return importlib.import_module('.' + name, __package__)
    return importlib.import_module(name)


CREATE_NO_WINDOW = 0x08000000  # Win32 CREATE_NO_WINDOW (console suppression)


def hidden_popen_kwargs() -> dict:
    """subprocess kwargs that stop child processes from FLASHING a console
    window — the Wave-2 gate saw a blank cmd window during open_app
    (PowerShell child spawn; docs/BUGS-WAVE2.md Bug B). Pure + portable so
    tests can assert the flag on any OS."""
    import subprocess
    kwargs: dict = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW',
                                             CREATE_NO_WINDOW)}
    if os.name == 'nt':
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0          # SW_HIDE
            kwargs['startupinfo'] = si
        except (AttributeError, OSError):
            pass
    return kwargs


class WindowsBackend:
    """Real implementation. Constructed lazily on Windows only."""

    name = 'windows'

    # ---- keyboard / mouse (the ONLY input-injection points) -------------
    def type_text(self, text: str, pause: float = 0.0) -> None:
        """Unicode-safe typing via SendInput(KEYEVENTF_UNICODE) — no pywinauto
        brace-escaping hazards, works for any BMP character."""
        import ctypes
        from ctypes import wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', wintypes.WORD),
                        ('wScan', wintypes.WORD),
                        ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG),
                        ('dy', wintypes.LONG),
                        ('mouseData', wintypes.DWORD),
                        ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [('uMsg', wintypes.DWORD),
                        ('wParamL', wintypes.WORD),
                        ('wParamH', wintypes.WORD)]

        class _INPUTUNION(ctypes.Union):
            _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT),
                        ('hi', HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ('u',)
            _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]

        INPUT_KEYBOARDINPUT, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x0002, 0x0004
        user32 = ctypes.windll.user32
        for ch in text:
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                inp = INPUT(type=INPUT_KEYBOARDINPUT)
                inp.ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
            if pause:
                time.sleep(pause)

    def key_down(self, vk: int) -> None:
        import ctypes
        ctypes.windll.user32.keybd_event(int(vk), 0, 0, 0)

    def key_up(self, vk: int) -> None:
        import ctypes
        ctypes.windll.user32.keybd_event(int(vk), 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    def mouse_position(self) -> Tuple[int, int]:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    def mouse_move(self, x: int, y: int) -> None:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))

    def mouse_move_rel(self, dx: int, dy: int) -> None:
        x, y = self.mouse_position()
        self.mouse_move(x + int(dx), y + int(dy))

    _MB = {'left': 0x0002, 'right': 0x0008, 'middle': 0x0020}  # mouse_event flags

    def mouse_click(self, button: str = 'left', x: Optional[int] = None,
                    y: Optional[int] = None, clicks: int = 1) -> None:
        import ctypes
        if x is not None and y is not None:
            self.mouse_move(x, y)
        down, up = self._MB[button]
        for _ in range(max(1, int(clicks))):
            ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
            time.sleep(0.02)
            ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.02)

    def mouse_down(self, button: str = 'left') -> None:
        import ctypes
        ctypes.windll.user32.mouse_event(self._MB[button], 0, 0, 0, 0)

    def mouse_up(self, button: str = 'left') -> None:
        import ctypes
        flags = {'left': 0x0004, 'right': 0x0010, 'middle': 0x0040}[button]
        ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)

    def mouse_scroll(self, amount: int) -> None:
        """amount > 0 scrolls up, < 0 down (wheel clicks, like pyautogui)."""
        import ctypes
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(amount) * 120, 0)

    # ---- windows --------------------------------------------------------
    def _describe_window(self, hwnd: int) -> Optional[Dict[str, Any]]:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        if not hwnd or not user32.IsWindow(hwnd):
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, buf, len(buf))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = self.window_rect(hwnd)
        return {
            'hwnd': int(hwnd),
            'title': buf.value,
            'pid': int(pid.value),
            'process': self._process_name(int(pid.value)),
            'rect': rect,
            'visible': bool(user32.IsWindowVisible(hwnd)),
        }

    def _process_name(self, pid: int) -> Optional[str]:
        if not pid:
            return None
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, int(pid))
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                   ctypes.byref(size)):
                return buf.value.rsplit('\\', 1)[-1]
        finally:
            kernel32.CloseHandle(handle)
        return None

    def foreground(self) -> Optional[Dict[str, Any]]:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return self._describe_window(hwnd) if hwnd else None

    def list_windows(self) -> List[Dict[str, Any]]:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        out: List[Dict[str, Any]] = []
        WNDPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

        def cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                info = self._describe_window(hwnd)
                if info is not None:
                    out.append(info)
            return True

        user32.EnumWindows(WNDPROC(cb), 0)
        return out

    def focus_window(self, hwnd: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Foreground-lock bypass: attach our thread to the current foreground
        # thread first (documented SetForegroundWindow requirement).
        fg = user32.GetForegroundWindow()
        tid_cur = user32.GetCurrentThreadId()
        tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(tid_fg and tid_cur != tid_fg
                        and user32.AttachThreadInput(tid_fg, tid_cur, True))
        try:
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(tid_fg, tid_cur, False)

    def show_window(self, hwnd: int, mode: str) -> None:
        cmd = {'minimize': 6, 'maximize': 3, 'restore': 9}[mode]
        import ctypes
        ctypes.windll.user32.ShowWindow(hwnd, cmd)

    def window_rect(self, hwnd: int) -> Dict[str, int]:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        return {'left': int(r.left), 'top': int(r.top),
                'right': int(r.right), 'bottom': int(r.bottom),
                'width': int(r.right - r.left),
                'height': int(r.bottom - r.top)}

    def _work_area(self) -> Dict[str, int]:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        SPI_GETWORKAREA = 0x0030
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                                   ctypes.byref(r), 0)
        return {'left': int(r.left), 'top': int(r.top),
                'right': int(r.right), 'bottom': int(r.bottom)}

    def snap_window(self, hwnd: int, zone: str) -> Dict[str, int]:
        """Aero-style snapping to the monitor work area."""
        import ctypes
        wa = self._work_area()
        w = wa['right'] - wa['left']
        h = wa['bottom'] - wa['top']
        half_w, half_h = w // 2, h // 2
        rects = {
            'left':   (wa['left'], wa['top'], wa['left'] + half_w, wa['bottom']),
            'right':  (wa['left'] + half_w, wa['top'], wa['right'], wa['bottom']),
            'top':    (wa['left'], wa['top'], wa['right'], wa['top'] + half_h),
            'bottom': (wa['left'], wa['top'] + half_h, wa['right'], wa['bottom']),
            'max':    (wa['left'], wa['top'], wa['right'], wa['bottom']),
        }
        l, t, r, b = rects[zone]
        HWND_TOP = 0
        SWP_NOZORDER = 0x0004
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOP, l, t, r - l, b - t,
                                          SWP_NOZORDER)
        return {'left': l, 'top': t, 'right': r, 'bottom': b,
                'width': r - l, 'height': b - t}

    # ---- apps / processes ------------------------------------------------
    def start_menu_shortcuts(self) -> List[Dict[str, str]]:
        import pathlib
        roots = []
        appdata = os.environ.get('APPDATA')
        programdata = os.environ.get('ProgramData')
        if appdata:
            roots.append(pathlib.Path(appdata) / 'Microsoft' / 'Windows'
                         / 'Start Menu' / 'Programs')
        if programdata:
            roots.append(pathlib.Path(programdata) / 'Microsoft' / 'Windows'
                         / 'Start Menu' / 'Programs')
        out: List[Dict[str, str]] = []
        for root in roots:
            if not root.is_dir():
                continue
            for lnk in root.rglob('*.lnk'):
                out.append({'name': lnk.stem, 'path': str(lnk)})
        return out

    def resolve_lnk(self, path: str) -> Optional[str]:
        """Resolve a .lnk shortcut to its target path (pywin32 COM)."""
        try:
            import win32com.client  # type: ignore
        except ImportError:
            _ensure_pkg('pywin32', 'win32api', '312')
            import win32com.client  # type: ignore
        try:
            shell = win32com.client.Dispatch('WScript.Shell')
            return shell.CreateShortcut(path).TargetPath or None
        except Exception:  # noqa: BLE001 — corrupt/foreign lnk
            return None

    def path_commands(self) -> List[Dict[str, str]]:
        import pathlib
        out: List[Dict[str, str]] = []
        seen = set()
        for entry in (os.environ.get('PATH') or '').split(os.pathsep):
            d = pathlib.Path(entry)
            if not d.is_dir():
                continue
            try:
                for f in d.iterdir():
                    if f.suffix.lower() in ('.exe', '.com', '.bat', '.cmd', '.ps1'):
                        key = f.stem.lower()
                        if key not in seen:
                            seen.add(key)
                            out.append({'name': f.stem, 'path': str(f)})
            except OSError:
                continue
        return out

    def app_path_entries(self) -> List[Dict[str, str]]:
        """HKLM/HKCU `App Paths` registrations (chrome.exe -> full path)."""
        import winreg  # Windows-only stdlib
        out: List[Dict[str, str]] = []
        hives = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
        views = [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]
        for hive in hives:
            for view in views:
                key_path = (r'SOFTWARE\Microsoft\Windows\CurrentVersion'
                            r'\App Paths')
                try:
                    with winreg.OpenKey(hive, key_path, 0,
                                        winreg.KEY_READ | view) as base:
                        count = winreg.QueryInfoKey(base)[0]
                        for i in range(count):
                            sub = winreg.EnumKey(base, i)
                            try:
                                with winreg.OpenKey(base, sub) as leaf:
                                    target = winreg.QueryValueEx(leaf, '')[0]
                                out.append({'name': sub, 'path': str(target)})
                            except OSError:
                                continue
                except OSError:
                    continue
        return out

    def uwp_apps(self) -> List[Dict[str, str]]:
        """UWP/Start apps via the fixed `list_uwp_apps` PowerShell script."""
        act_powershell = _sibling('act_powershell')  # lazy — avoids import cycles
        res = act_powershell.run_script('list_uwp_apps', {}, self)
        apps = res.get('apps') if isinstance(res, dict) else None
        if not isinstance(apps, list):
            return []
        return [{'name': str(a.get('name') or ''),
                 'path': str(a.get('app_id') or '')}
                for a in apps if isinstance(a, dict)]

    def launch_path(self, path: str, args: Optional[List[str]] = None) -> None:
        import subprocess
        if args:
            subprocess.Popen([path, *args])
        else:
            os.startfile(path)  # noqa: S606 — shell-less default handler

    def launch_uwp(self, app_id: str) -> None:
        import subprocess
        subprocess.Popen(['explorer.exe', 'shell:AppsFolder\\%s' % app_id])

    def open_url(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def open_shell(self, target: str) -> None:
        """Open a file/folder/URL with its registered Windows handler."""
        os.startfile(target)

    def list_processes(self) -> List[Dict[str, Any]]:
        """Toolhelp32 snapshot — stdlib ctypes, no psutil dependency."""
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', wintypes.DWORD),
                ('szExeFile', ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap in (0, -1):
            raise BackendError('CreateToolhelp32Snapshot failed')
        out: List[Dict[str, Any]] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                out.append({'pid': int(entry.th32ProcessID),
                            'name': entry.szExeFile})
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return out

    # ---- system ---------------------------------------------------------
    def clipboard_get(self) -> str:
        clipboard = _sibling('clipboard')  # lazy: pywin32 (pinned pip fallback)
        return clipboard.get_clipboard_text()

    def clipboard_set(self, text: str) -> None:
        _sibling('clipboard').set_clipboard_text(text)

    def set_volume(self, level: int) -> None:
        _sibling('system').set_volume(int(level))  # lazy: comtypes

    def set_brightness(self, level: int) -> None:
        _sibling('system').set_brightness(int(level))

    def media_key(self, op: str) -> None:
        """Synthesized media keystroke (see MEDIA_KEYS). Input injection —
        the dispatcher only runs this while holding the input lock."""
        vk = MEDIA_KEYS[op]
        self.key_down(vk)
        time.sleep(0.02)
        self.key_up(vk)

    def notify(self, text: str) -> None:
        act_powershell = _sibling('act_powershell')  # fixed toast script
        act_powershell.run_script('notify_toast', {'text': text}, self)

    def powershell(self, argv: List[str], env: Dict[str, str],
                   timeout_s: float) -> Dict[str, Any]:
        """Run a FIXED argv (never user text) with args passed via env vars.
        Spawned HIDDEN (hidden_popen_kwargs) — no console flash (Bug B)."""
        import subprocess
        full_env = dict(os.environ)
        full_env.update(env)
        try:
            proc = subprocess.run(
                list(argv), env=full_env, capture_output=True, text=True,
                timeout=timeout_s, shell=False, **hidden_popen_kwargs())
        except subprocess.TimeoutExpired:
            return {'rc': -1, 'out': '', 'err': 'timeout after %.0fs' % timeout_s}
        return {'rc': int(proc.returncode),
                'out': (proc.stdout or '')[:65536],
                'err': (proc.stderr or '')[:8192]}

    # ---- UIA (pywinauto) -------------------------------------------------
    def _desktop(self):
        try:
            from pywinauto import Desktop  # type: ignore
        except ImportError:
            automation = _sibling('automation')
            automation._ensure_pkg('pywinauto', pin='0.6.9')
            from pywinauto import Desktop  # type: ignore
        return Desktop(backend='uia')

    @staticmethod
    def _matches(wrapper, sel: Dict[str, Any]) -> bool:
        ei = wrapper.element_info
        if 'name' in sel and (ei.name or '').lower() != sel['name'].lower():
            return False
        if 'control_type' in sel:
            ct = (ei.control_type or '')
            if ct.lower() != sel['control_type'].lower():
                return False
        if 'automation_id' in sel and (ei.automation_id or '') != sel['automation_id']:
            return False
        if 'class_name' in sel and (ei.class_name or '') != sel['class_name']:
            return False
        return True

    @staticmethod
    def _describe(wrapper) -> Dict[str, Any]:
        ei = wrapper.element_info
        try:
            rect = wrapper.rectangle()
            rect_d = {'left': int(rect.left), 'top': int(rect.top),
                      'right': int(rect.right), 'bottom': int(rect.bottom)}
        except Exception:  # noqa: BLE001 — detached element
            rect_d = None
        return {'name': ei.name or '', 'control_type': ei.control_type or '',
                'automation_id': ei.automation_id or '',
                'class_name': ei.class_name or '', 'rect': rect_d}

    def _iter_candidates(self, desktop):
        """Foreground window subtree first (fast path), then every window."""
        fg = desktop.window(active=True)
        try:
            yield fg.wrapper_object()
        except Exception:  # noqa: BLE001 — no active window
            pass
        for top in desktop.windows():
            try:
                yield top.wrapper_object()
            except Exception:  # noqa: BLE001
                continue

    def _find_wrapper(self, sel: Dict[str, Any], timeout_s: float):
        """Poll until the selector matches. `index` (0-based) selects the
        nth match so duplicate UI (two "OK" buttons) stays addressable."""
        raw_idx = sel.get('index', 0)
        idx = raw_idx if isinstance(raw_idx, int) and not isinstance(raw_idx, bool) else 0
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            hit = self._scan(sel, idx)
            if hit is not None:
                return hit
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.15)

    def _scan(self, sel: Dict[str, Any], idx: int):
        # Foreground window subtree first (fast, most-relevant), then the rest.
        for top in self._iter_candidates(self._desktop()):
            if self._matches(top, sel):
                if idx == 0:
                    return top
                idx -= 1
            for child in top.descendants():
                if self._matches(child, sel):
                    if idx == 0:
                        return child
                    idx -= 1
        return None

    def uia_find(self, selector: Dict[str, Any],
                 timeout_s: float) -> Optional[Dict[str, Any]]:
        w = self._find_wrapper(selector, timeout_s)
        return self._describe(w) if w is not None else None

    def uia_click(self, selector: Dict[str, Any], timeout_s: float,
                  button: str = 'left') -> Dict[str, Any]:
        w = self._find_wrapper(selector, timeout_s)
        if w is None:
            raise BackendError('element not found: %s' % selector)
        w.click_input(button=button)
        return self._describe(w)

    def uia_type(self, selector: Dict[str, Any], text: str, clear: bool,
                 timeout_s: float) -> Dict[str, Any]:
        w = self._find_wrapper(selector, timeout_s)
        if w is None:
            raise BackendError('element not found: %s' % selector)
        try:
            w.set_focus()
        except Exception:  # noqa: BLE001 — not focusable; click fallback
            w.click_input(button='left')
        if clear:
            self.key_down(KEYMAP['ctrl']); self.key_down(KEYMAP['a'])
            self.key_up(KEYMAP['a']); self.key_up(KEYMAP['ctrl'])
            time.sleep(0.05)
        self.type_text(text)
        return self._describe(w)

    def uia_read(self, selector: Dict[str, Any],
                 timeout_s: float) -> Dict[str, Any]:
        w = self._find_wrapper(selector, timeout_s)
        if w is None:
            raise BackendError('element not found: %s' % selector)
        out = self._describe(w)
        texts: List[str] = []
        try:
            own = (w.window_text() or '').strip()
            if own:
                texts.append(own)
            for child in w.descendants():
                if len(texts) >= 200:
                    break
                t = (child.window_text() or '').strip()
                if t and t not in texts:
                    texts.append(t)
        except Exception as e:  # noqa: BLE001 — tree went away mid-read
            raise BackendError('read failed: %s' % e)
        out['texts'] = [t[:500] for t in texts[:200]]
        return out

    def uia_tree(self, selector: Dict[str, Any], depth: int,
                 timeout_s: float) -> Dict[str, Any]:
        w = self._find_wrapper(selector, timeout_s)
        if w is None:
            raise BackendError('element not found: %s' % selector)
        budget = {'n': 500}

        def walk(node, d: int) -> Dict[str, Any]:
            info = self._describe(node)
            if d <= 0 or budget['n'] <= 0:
                info['children'] = []
                return info
            kids = []
            try:
                for child in node.children():
                    if budget['n'] <= 0:
                        break
                    budget['n'] -= 1
                    kids.append(walk(child, d - 1))
            except Exception:  # noqa: BLE001
                pass
            info['children'] = kids
            return info

        root = walk(w, max(1, int(depth)))
        root['truncated'] = budget['n'] <= 0
        return root

    # ---- capture ---------------------------------------------------------
    def capture(self, max_px: int, quality: int) -> bytes:
        capture = _sibling('capture')  # lazy: mss + Pillow installs
        return capture.capture_screenshot(int(max_px), int(quality))


class NullBackend:
    """Non-Windows guard: every call fails loudly (never half-executes)."""

    name = 'null'

    def __getattr__(self, item):
        if item.startswith('_'):
            raise AttributeError(item)

        def _fail(*_a, **_k):
            raise BackendError(
                'no Windows backend on this host (os.name=%r): %s' %
                (os.name, item))
        return _fail


_backend: Any = None


def get_backend():
    """WindowsBackend on Windows, NullBackend elsewhere (cached)."""
    global _backend
    if _backend is None:
        _backend = WindowsBackend() if os.name == 'nt' else NullBackend()
    return _backend


def set_backend(backend: Any) -> None:
    """Bind an explicit backend (FakeWin in tests / mock e2e)."""
    global _backend
    _backend = backend


def reset_backend() -> None:
    """Drop any override so the next get_backend() re-detects the OS."""
    global _backend
    _backend = None
