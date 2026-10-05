"""Tool registry for Brain.
Allows Body tools to register callable utilities.
Provides a simple shell execution tool.
"""
import subprocess
from typing import Callable, Dict

_registry: Dict[str, Callable] = {}

def register(name: str, func: Callable):
    _registry[name] = func

def get(name: str) -> Callable:
    return _registry.get(name)

# Built‑in shell tool (synchronous)
def shell_tool(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'Command failed: {result.stderr}')
    return result.stdout.strip()

# Register the built‑in tool
register('shell', shell_tool)
