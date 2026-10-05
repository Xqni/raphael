"""Tool registry for Brain (ARCHITECTURE §4).
Body/tools register callables here; the agent loop dispatches plan → tool.
Metadata (risky / needs_lock) feeds confirmation enforcement (brain/confirm.py)
and input-lock arbitration — risky tools are confirm-gated in code, never
left to a model's judgment.
"""
import subprocess
from typing import Any, Callable, Dict

_registry: Dict[str, Callable] = {}
_META: Dict[str, Dict[str, Any]] = {}


def register(name: str, func: Callable, *, risky: bool = False,
             needs_lock: bool = False, description: str = '',
             category: str = 'local'):
    # category='gui' -> loop.py routes the call to the BODY over act_req
    # (PROTOCOL §7) instead of executing locally in WSL.
    _registry[name] = func
    _META[name] = {'risky': risky, 'needs_lock': needs_lock,
                   'description': description, 'category': category}


def get(name: str) -> Callable:
    return _registry.get(name)


def describe(name: str) -> Dict[str, Any]:
    return dict(_META.get(name, {'risky': False, 'needs_lock': False,
                                 'description': ''}))


def names():
    return sorted(_registry)


# Built-in shell tool (synchronous; run via asyncio.to_thread by the loop)
def shell_tool(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'Command failed: {result.stderr}')
    return result.stdout.strip()


register('shell', shell_tool, risky=True, needs_lock=False,
         description='run a shell command locally (confirm-gated)')


# ---- gui-class tools (PROTOCOL §7): the fns below must NEVER run locally.
# loop.py intercepts category='gui' and routes to the body via act_req; the
# stub exists only so tool_reg.get(name) passes the existence check.
def _gui_only(**_kwargs):
    raise RuntimeError('gui tool must run on the body (act pipeline)')


for _name, _desc, _lock in (
        ('launch_url', 'open a URL in the default browser (body)', False),
        ('open_app', 'launch an application (body)', False),
        ('screenshot', 'capture the screen (body)', False),
        ('uia', 'drive UI Automation (body)', True),
        ('clipboard', 'read/write the clipboard (body)', False)):
    register(_name, _gui_only, category='gui', needs_lock=_lock,
             description=_desc)
