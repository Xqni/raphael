"""shell tool — the FIXED SCRIPT REGISTRY (docs/lanes/tools-memory.md §3.3).

There is NO arbitrary-command shell here (the wave-2 placeholder
`shell_tool(command, shell=True)` in the central registry gets REPLACED by
this registration — same tool name, `risky=True` metadata unchanged, i.e.
strengthening, never weakening):

- only scripts declared in `config.d/tools-memory.yaml → shell.scripts`
  can run: `{name: {cmd: [argv...], cwd?: str, desc?: str}}`;
- `args` are APPENDED as raw argv elements and executed with
  `subprocess.run(shell=False)` — no string interpolation, no metacharacter
  interpretation, so no injection surface exists;
- unknown script -> error listing what IS allowed (the allow-list is the
  point); timeout + output cap from config.

Registry shape check happens at CALL time (config is live), so a malformed
script definition fails loudly instead of silently running something else.
"""
from __future__ import annotations

import subprocess
from typing import Any, Dict, List

import brain.tools as _tool_reg

SPECS = {
    'shell': {
        'type': 'object',
        'properties': {
            'script': {'type': 'string',
                       'description': 'name of a registered script (see shell_list)'},
            'args': {'type': 'array', 'items': {'type': 'string'},
                     'description': 'extra argv entries appended verbatim'},
        },
        'required': ['script'],
        'additionalProperties': False,
    },
    'shell_list': {
        'type': 'object',
        'properties': {},
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


def _scripts() -> Dict[str, Any]:
    raw = _cfg('shell.scripts', {}) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def shell(script: str, args: List[str] = None) -> str:
    """Run one registered script (confirm-gated: risky=True)."""
    scripts = _scripts()
    name = str(script or '').strip()
    if name not in scripts:
        known = ', '.join(sorted(scripts)) or '(none configured)'
        raise ValueError(f'unknown script {name!r} — registered: {known}')
    entry = scripts[name] or {}
    if not isinstance(entry, dict):
        raise ValueError(f'script {name!r} config must be a mapping')
    cmd = entry.get('cmd')
    if not isinstance(cmd, (list, tuple)) or not cmd:
        raise ValueError(f'script {name!r} needs cmd as a NON-EMPTY argv list '
                         f'(strings are refused — no shell parsing, ever)')
    argv = [str(c) for c in cmd] + [str(a) for a in (args or [])]
    cwd = entry.get('cwd')
    timeout = float(_cfg('shell.timeout_s', 30) or 30)
    max_out = int(_cfg('shell.max_output_bytes', 65536) or 65536)
    try:
        proc = subprocess.run(
            argv, shell=False, cwd=str(cwd) if cwd else None,
            capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'script {name!r} timed out after {timeout:g}s')
    except FileNotFoundError as e:
        raise RuntimeError(f'script {name!r}: cannot execute {argv[0]!r} ({e})')
    out = (proc.stdout or b'') + (
        b'\n[stderr]\n' + proc.stderr if proc.stderr else b'')
    text = out.decode('utf-8', errors='replace').rstrip()
    if len(text) > max_out:
        half = max_out // 2
        text = (text[:half] + f'\n… [{len(text) - max_out} chars elided] …\n'
                + text[-half:])
    if proc.returncode != 0:
        raise RuntimeError(
            f'script {name!r} failed (rc={proc.returncode}): '
            f'{text[-500:] or "(no output)"}')
    return text or '(no output)'


def shell_list() -> str:
    """Names + descriptions of the registered scripts (what shell can run)."""
    scripts = _scripts()
    if not scripts:
        return ('(no scripts registered — add entries under shell.scripts in '
                'config.d/tools-memory.yaml)')
    lines = []
    for name in sorted(scripts):
        entry = scripts[name] or {}
        desc = entry.get('desc', '') if isinstance(entry, dict) else ''
        lines.append(f'- {name}{": " + desc if desc else ""}')
    return '\n'.join(lines)


def register(_reg=None) -> None:
    reg = _reg if _reg is not None and hasattr(_reg, 'register') else _tool_reg
    # Overwrites the wave-2 placeholder `shell` (shell=True) — metadata stays
    # risky=True; command surface narrows to the script allow-list.
    reg.register('shell', shell, risky=True, needs_lock=False,
                 category='local',
                 description='run a REGISTERED script by name (fixed script '
                             'registry, confirm-gated; no arbitrary commands)',
                 schema=SPECS['shell'])
    reg.register('shell_list', shell_list, risky=False, category='local',
                 description='list the registered shell scripts',
                 schema=SPECS['shell_list'])


register()
