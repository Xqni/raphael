"""Input-lock arbitration + legacy UIA helpers for the Windows Body
(ARCHITECTURE: automation.py = UIA/input-lock).

The input lock is the Body's last-line enforcement of PROTOCOL §7
`lock:true` etiquette: only the holder of the lock may inject input or
take the foreground. The Brain arbitrates first (job-level FIFO); a busy
lock here surfaces as `act_res{error:"E_LOCK_BUSY"}`.

Import discipline: NO third-party imports at module level. pywinauto loads
lazily inside the legacy helpers, so `import body.win.automation` (and the
dispatcher that uses the lock) works on any OS without pip side effects —
required for unit tests (AGENT_RULES §5: prefer mocks).
"""
import asyncio
import threading
from typing import Any, Dict

# Global lock – only one coroutine may hold it at a time.
_input_lock = threading.Lock()


def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):
    """Import-or-install, PINNED (security: unpinned runtime pip = supply chain)."""
    try:
        __import__(import_name or pkg)
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet',
                               ('%s==%s' % (pkg, pin)) if pin else pkg])
        __import__(import_name or pkg)


def _pywinauto():
    """Lazy pywinauto import for the legacy helpers (Windows-only)."""
    _ensure_pkg('pywinauto', pin='0.6.9')
    from pywinauto import Application, mouse, keyboard  # noqa: F401
    return Application, mouse, keyboard


async def acquire_input_lock(timeout: float = 5.0) -> bool:
    # threading.Lock.acquire(blocking=True, timeout=...) accepts float
    # seconds. The old bug was passing the float POSITIONALLY into
    # `blocking` (found by e2e_phase3); keep blocking/timeout explicit.
    if timeout <= 0:
        return _input_lock.acquire(blocking=False)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _input_lock.acquire, True, float(timeout))


def release_input_lock():
    if _input_lock.locked():
        _input_lock.release()


def lock_held() -> bool:
    """True while any act_req holds the input lock (diagnostics/tests)."""
    return _input_lock.locked()


# ---- legacy helpers (kept for script-mode/manual use; the act_req path
# goes through body/win/actions.py + winlayer instead) -------------------

async def click(x: int, y: int, button: str = "left"):
    await acquire_input_lock()
    try:
        _Application, mouse, _kb = _pywinauto()
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: mouse.click(button, (x, y)))
    finally:
        release_input_lock()


async def type_keys(text: str, pause: float = 0.0):
    await acquire_input_lock()
    try:
        _App, _mouse, keyboard = _pywinauto()
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: keyboard.send_keys(text, {'pause': pause}))
    finally:
        release_input_lock()


async def launch_app(executable_path: str, args: str = ""):
    # Simple helper to start an application via pywinauto.
    Application, _m, _k = _pywinauto()
    await asyncio.get_running_loop().run_in_executor(
        None, Application().start, f'"{executable_path}" {args}'
    )


async def focus_window(title: str):
    """Bring a window with given title to foreground."""
    Application, _m, _k = _pywinauto()
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: Application().connect(title=title).top_window().set_focus())


async def minimize_window(title: str):
    """Minimize a window with given title."""
    Application, _m, _k = _pywinauto()
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: Application().connect(title=title).top_window().minimize())


async def close_window(title: str):
    """Close a window with given title."""
    Application, _m, _k = _pywinauto()
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: Application().connect(title=title).top_window().close())


async def perform_uia(op: str, target: Dict[str, Any], args: Dict[str, Any]):
    if op == "click":
        # Expect target to contain screen coordinates.
        x = target.get('x')
        y = target.get('y')
        if x is None or y is None:
            raise ValueError('click target must contain x and y')
        await click(x, y)
    elif op == "type":
        text = args.get('text', '')
        await type_keys(text)
    else:
        raise NotImplementedError(f'Unsupported UIA operation {op}')

# When executed directly, run a tiny demo (if a console is attached).
if __name__ == '__main__':
    import sys
    async def demo():
        await click(100, 100)
        await type_keys('Hello')
    asyncio.run(demo())
    print('Demo completed', file=sys.stderr)
