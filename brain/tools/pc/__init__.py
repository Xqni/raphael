"""pc tools — LLM-facing Windows control tools (pc-control lane).

Self-registration per INTERFACES §b: importing this package registers every
pc tool into `brain.tools` with `category='gui'` (the agent loop routes those
to the Body over `act_req`, PROTOCOL §7 — never executes them locally) plus
the `risky` / `needs_lock` metadata that confirm gating and input-lock
arbitration read in code.

One module per tool group:
  launch.py     launch_url, search_youtube, open_app, open_path, list_running_apps
  system.py     volume, brightness, media, notify, clipboard
  window.py     window, list_windows, foreground_info
  automation.py uia, input, screenshot
  powershell.py powershell (risky -> system_settings_change)

Exports for the Brain:
  SPECS           name -> ToolSpec (all validated at import, loud on error)
  openai_tools()  OpenAI function-tool list for providers with native
                  tool-calling (brain-core passes these to router.chat)
  prompt_block()  plain-text tool list for the {"tool":..., "args":...}
                  protocol loop._extract_tool_call understands
  confirm_category(name) / meta(name)  — confirm + lock metadata lookup

Every tool name equals its act_req action name (loop.py forwards
`action: tool_name`), and needs_lock mirrors the body action exactly —
tests/pc_tool_specs.py asserts both invariants.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._spec import SpecError, ToolSpec
from .activity import SPECS as _ACTIVITY
from .automation import SPECS as _AUTOMATION
from .launch import SPECS as _LAUNCH
from .powershell import SPECS as _POWERSHELL
from .report import SPECS as _REPORT
from .system import SPECS as _SYSTEM
from .window import SPECS as _WINDOW

_GROUPS = {
    'launch': _LAUNCH,
    'system': _SYSTEM,
    'window': _WINDOW,
    'automation': _AUTOMATION,
    'powershell': _POWERSHELL,
    'report': _REPORT,
    'activity': _ACTIVITY,
}

SPECS: Dict[str, ToolSpec] = {}
for _group, _specs in _GROUPS.items():
    for _s in _specs:
        if _s.name in SPECS:
            raise SpecError('duplicate pc tool: %s' % _s.name)
        SPECS[_s.name] = _s
for _s in SPECS.values():
    _s.validate()   # loud at import (INTERFACES §b)


def _gui_stub(**_kwargs: Any):
    raise RuntimeError('gui tool must run on the body (act pipeline)')


def _register_all() -> None:
    from .. import register as _register  # brain.tools registry (brain-core)
    for s in SPECS.values():
        # Pass schema= so brain.tools tool_specs() OFFERS the tool to the
        # model (registry skips schema-less tools; guarded by
        # brain-core's test_tool_specs_only_offers_conforming_schemas and my
        # parity test). Zero-arg tools included: brain-core merged the
        # empty-properties relaxation (request allow-empty-properties-schema,
        # ACCEPTED 2026-10-06), so `properties: {}` + `required: []` passes.
        _register(s.name, _gui_stub, risky=s.risky, needs_lock=s.needs_lock,
                  description=s.description, category='gui',
                  schema=s.schema())


_register_all()


# ------------------------------------------------------------------ exports
def names() -> List[str]:
    return sorted(SPECS)


def meta(name: str) -> Dict[str, Any]:
    """Registry metadata for one pc tool (risky/needs_lock/confirm/group)."""
    s = SPECS[name]
    return {'name': s.name, 'group': s.group, 'risky': s.risky,
            'needs_lock': s.needs_lock, 'confirm': s.confirm,
            'description': s.description}


def confirm_category(name: str) -> Optional[str]:
    """Confirm category a tool declares (None = no confirmation needed)."""
    return SPECS[name].confirm


def openai_tools() -> List[Dict[str, Any]]:
    """OpenAI function-tool list (strict JSON Schema parameters)."""
    return [SPECS[n].openai() for n in sorted(SPECS)]


def prompt_block() -> str:
    """Plain-text tool list for providers without native tool-calling.
    The format matches loop._extract_tool_call: one JSON object
    {"tool": name, "args": {...}} as the reply."""
    lines = ['Available tools (call at most one per reply; reply with ONLY '
             'a JSON object {"tool": "<name>", "args": {...}}):']
    for name in sorted(SPECS):
        s = SPECS[name]
        params = []
        for key, prop in s.properties.items():
            hint = prop.get('type', 'any')
            if 'enum' in prop:
                hint = '|'.join(str(v) for v in prop['enum'])
            mark = '' if key in s.required else '?'
            params.append('%s%s: %s' % (key, mark, hint))
        args = (' args[' + ', '.join(params) + ']') if params else ' (no args)'
        lines.append('- %s%s: %s' % (name, args, s.description))
    return '\n'.join(lines)
