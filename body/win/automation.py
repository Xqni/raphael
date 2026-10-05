"""UI Automation helpers for the Windows Body.

Provides a thin wrapper around pywinauto for common actions required by the
protocol (click, type, read control text, etc.). The module also implements a
simple input‑lock arbitration primitive so that only one job holding the
lock can perform actions that manipulate the mouse/keyboard.
"""
import asyncio
import threading
from typing import Any, Dict

def _ensure_pkg(name: str):
    try:
        __import__(name)
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', name])
        __import__(name)

_ensure_pkg('pywinauto')
from pywinauto import Application, mouse, keyboard

# Global lock – only one coroutine may hold it at a time.
_input_lock = threading.Lock()

async def acquire_input_lock(timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _input_lock.acquire, timeout)

def release_input_lock():
    if _input_lock.locked():
        _input_lock.release()

async def click(x: int, y: int, button: str = "left"):
    await acquire_input_lock()
    try:
        await asyncio.get_running_loop().run_in_executor(None, mouse.click, button, (x, y))
    finally:
        release_input_lock()

async def type_keys(text: str, pause: float = 0.0):
    await acquire_input_lock()
    try:
        await asyncio.get_running_loop().run_in_executor(None, keyboard.send_keys, text, {'pause': pause})
    finally:
        release_input_lock()

async def launch_app(executable_path: str, args: str = ""):
    # Simple helper to start an application via pywinauto.
    await asyncio.get_running_loop().run_in_executor(
        None, Application().start, f'"{executable_path}" {args}'
    )

# Registry of UIA operations; the Brain will send structured ops like
# {"action": "click", "element": {...}, "args": {...}}
# For now we implement a very small subset.
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
